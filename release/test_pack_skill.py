"""Exercise release assembly with isolated fixtures, never the real runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pack_skill


class ReleaseAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix=".pack-skill-fixture-", dir=Path(__file__).resolve().parent))
        (self.root / ".fixture-owner.json").write_text('{"owner":"pack-skill-fixture"}', encoding="utf-8")
        for directory in pack_skill.DIRECTORIES:
            self.put(f"{directory}/fixture.py", b"# fixture source\n")
        for name in pack_skill.EXAMPLES:
            self.put(f"examples/{name}/plugin.json", b'{"fixture":true}\n')
        self.put("runtime/1.1.4/ZwPluginHub.dll", b"synthetic hub, not an executable")
        self.put("runtime/1.1.4/HubManager.exe", b"synthetic manager, not an executable")
        runtime = self.root / "runtime" / "1.1.4"
        checksums = {name: pack_skill.digest((runtime / name).read_bytes())
                     for name in ("ZwPluginHub.dll", "HubManager.exe")}
        self.put("runtime/1.1.4/checksums.json", pack_skill.json_bytes(checksums))
        self.put("installer-runtime/1.0.0/SetupTemplate.exe", b"synthetic installer template")
        self.put("installer-runtime/1.0.0/checksums.json", pack_skill.json_bytes({
            "SetupTemplate.exe": pack_skill.digest(b"synthetic installer template")}))
        skill = f"skills/{pack_skill.SKILL_NAME}"
        self.put(f"{skill}/SKILL.md", b"---\nname: zw3d-plugin-dev\ndescription: fixture\n---\n")
        self.put(f"{skill}/references/contract.md", b"fixture contract\n")
        self.put(f"{skill}/agents/openai.yaml", b'interface:\n  display_name: "fixture"\n')

    def put(self, relative: str, data: bytes):
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    @property
    def kit(self):
        return self.root / "skills" / pack_skill.SKILL_NAME / "assets" / "kit"

    def tearDown(self):
        # This exact fixture was created by this test. Never remove a computed outside path.
        absolute = self.root.resolve()
        self.assertTrue(absolute.is_relative_to(Path(__file__).resolve().parent))
        self.assertTrue(absolute.name.startswith(".pack-skill-fixture-"))
        self.assertEqual(json.loads((absolute / ".fixture-owner.json").read_text(encoding="utf-8")),
                         {"owner": "pack-skill-fixture"})
        shutil.rmtree(absolute)

    def test_first_build_is_self_contained_and_reproducible(self):
        self.put("tools/.env", b"fixture secret\n")
        self.put("tools/__pycache__/fixture.pyc", b"fixture cache\n")
        self.put("tools/logs/run.log", b"fixture log\n")
        first = pack_skill.assemble(self.root)
        artifact = Path(first["artifact"])
        original = artifact.read_bytes()
        pack_skill.verify_owned(self.root, self.kit)
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
            self.assertIn("zw3d-plugin-dev/SKILL.md", names)
            self.assertIn("zw3d-plugin-dev/assets/kit/runtime/1.1.4/HubManager.exe", names)
            self.assertFalse(any(".env" in name or "__pycache__" in name or "/logs/" in name for name in names))
            self.assertTrue(all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist()))
            self.assertEqual(len(names), len(set(name.casefold() for name in names)))
        self.assertEqual(pack_skill.assemble(self.root)["sha256"], first["sha256"])
        self.assertEqual(artifact.read_bytes(), original)

    def test_development_candidate_preserves_historical_release(self):
        old = self.root / "release/zw3d-plugin-dev-0.2.4.zip"
        self.put("release/zw3d-plugin-dev-0.2.4.zip", b"historical release")
        result = pack_skill.assemble(self.root)
        self.assertEqual(old.read_bytes(), b"historical release")
        self.assertTrue(result["artifact"].endswith("0.2.5-dev.zip"))
        with self.assertRaisesRegex(ValueError, "release tag"):
            pack_skill.assemble(self.root, version="0.2.4")

    def test_corrupt_installer_template_changes_nothing(self):
        first = pack_skill.assemble(self.root)
        original = Path(first["artifact"]).read_bytes()
        self.put("installer-runtime/1.0.0/SetupTemplate.exe", b"modified")
        with self.assertRaisesRegex(ValueError, "installer template was modified"):
            pack_skill.assemble(self.root)
        self.assertEqual(Path(first["artifact"]).read_bytes(), original)

    def test_crlf_text_is_normalized_before_hashes_and_zip(self):
        # Binary CRLF bytes deliberately remain raw. Only UTF-8 text gets Git's LF representation.
        raw_hub = b"fixture DLL\r\n\x00binary bytes\r\n"
        raw_manager = b"fixture EXE\r\n\x00binary bytes\r\n"
        self.put("runtime/1.1.4/ZwPluginHub.dll", raw_hub)
        self.put("runtime/1.1.4/HubManager.exe", raw_manager)
        self.put("runtime/1.1.4/checksums.json", pack_skill.json_bytes({
            "ZwPluginHub.dll": pack_skill.digest(raw_hub),
            "HubManager.exe": pack_skill.digest(raw_manager),
        }))
        for item in self.root.rglob("*"):
            if item.is_file() and item.suffix in (".py", ".md", ".json", ".yaml"):
                item.write_bytes(item.read_bytes().replace(b"\n", b"\r\n"))
        original_source = (self.root / "framework" / "fixture.py").read_bytes()
        first = pack_skill.assemble(self.root)
        actual = pack_skill.files_in(self.root, self.kit)
        hashes = pack_skill.read_json(actual[pack_skill.HASHES])["files"]
        self.assertTrue(all(pack_skill.digest(actual[name]) == digest for name, digest in hashes.items()))
        self.assertEqual(actual["runtime/1.1.4/ZwPluginHub.dll"], raw_hub)
        self.assertEqual(actual["runtime/1.1.4/HubManager.exe"], raw_manager)
        for name, data in actual.items():
            if not name.endswith((".dll", ".exe")):
                self.assertNotIn(b"\r\n", data, name)
        artifact = Path(first["artifact"])
        with zipfile.ZipFile(artifact) as archive:
            for name in archive.namelist():
                data = archive.read(name)
                if not name.endswith((".dll", ".exe")):
                    self.assertNotIn(b"\r\n", data, name)
                if name.startswith("zw3d-plugin-dev/assets/kit/"):
                    relative = name.removeprefix("zw3d-plugin-dev/assets/kit/")
                    self.assertEqual(data, actual[relative], name)
        self.assertEqual((self.root / "framework" / "fixture.py").read_bytes(), original_source)
        self.assertEqual(pack_skill.assemble(self.root)["sha256"], first["sha256"])

    def test_unknown_existing_kit_is_preserved(self):
        self.put(f"skills/{pack_skill.SKILL_NAME}/assets/kit/user.md", b"keep this\n")
        with self.assertRaisesRegex(ValueError, "unknown directory"):
            pack_skill.assemble(self.root)
        self.assertEqual((self.kit / "user.md").read_bytes(), b"keep this\n")

    def test_edited_generated_file_is_preserved(self):
        first = pack_skill.assemble(self.root)
        source = self.kit / "framework" / "fixture.py"
        source.write_bytes(b"author changes\n")
        with self.assertRaisesRegex(ValueError, "was edited"):
            pack_skill.assemble(self.root)
        self.assertEqual(source.read_bytes(), b"author changes\n")
        self.assertEqual(pack_skill.digest(Path(first["artifact"]).read_bytes()), first["sha256"])

    def test_unrecorded_file_or_empty_folder_is_preserved(self):
        pack_skill.assemble(self.root)
        extra = self.kit / "personal.md"
        extra.write_bytes(b"keep\n")
        with self.assertRaisesRegex(ValueError, "Unknown files"):
            pack_skill.assemble(self.root)
        extra.unlink()
        empty = self.kit / "personal-empty-folder"
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, "Unknown empty directory"):
            pack_skill.assemble(self.root)
        self.assertTrue(empty.is_dir())

    def test_corrupt_runtime_changes_nothing(self):
        first = pack_skill.assemble(self.root)
        snapshot = pack_skill.files_in(self.root, self.kit)
        self.put("runtime/1.1.4/HubManager.exe", b"unexpected bytes\n")
        with self.assertRaisesRegex(ValueError, "runtime was modified"):
            pack_skill.assemble(self.root)
        self.assertEqual(pack_skill.files_in(self.root, self.kit), snapshot)
        self.assertEqual(pack_skill.digest(Path(first["artifact"]).read_bytes()), first["sha256"])

    def test_sdk_binary_is_not_an_allowed_runtime_artifact(self):
        self.put("runtime/1.1.4/ZW3D.dll", b"synthetic SDK stand-in\n")
        with self.assertRaisesRegex(ValueError, "only the two framework binaries"):
            pack_skill.assemble(self.root)
        self.assertFalse(self.kit.exists())

    def test_personal_machine_path_is_rejected(self):
        self.put("framework/fixture.py", b"SDK = 'C:/Users/maintainer/Desktop/sdk'\n")
        with self.assertRaisesRegex(ValueError, "Personal machine path"):
            pack_skill.assemble(self.root)

    def test_unknown_zip_is_preserved(self):
        artifact = self.root / "release" / f"{pack_skill.SKILL_NAME}-{pack_skill.DEVELOPMENT_VERSION}.zip"
        self.put(artifact.relative_to(self.root).as_posix(), b"user archive\n")
        with self.assertRaisesRegex(ValueError, "Unknown or incomplete prior release"):
            pack_skill.assemble(self.root)
        self.assertEqual(artifact.read_bytes(), b"user archive\n")
        self.assertFalse(self.kit.exists())

    def test_failed_record_publish_rolls_back_kit_and_zip(self):
        first = pack_skill.assemble(self.root)
        original_kit = pack_skill.files_in(self.root, self.kit)
        original_zip = Path(first["artifact"]).read_bytes()
        self.put("framework/fixture.py", b"# updated source\n")
        real_write = pack_skill.atomic_write
        failed = False

        def failing_write(root, path, data):
            nonlocal failed
            if path.name.endswith(".release.json") and not failed:
                failed = True
                raise OSError("fixture publication failure")
            real_write(root, path, data)

        with patch.object(pack_skill, "atomic_write", failing_write):
            with self.assertRaisesRegex(OSError, "fixture publication failure"):
                pack_skill.assemble(self.root)
        self.assertEqual(pack_skill.files_in(self.root, self.kit), original_kit)
        self.assertEqual(Path(first["artifact"]).read_bytes(), original_zip)

    def test_link_outside_fixture_is_rejected_before_copy(self):
        link = self.root / "tools" / "external"
        outside = pack_skill.PROJECT / "release"
        if os.name == "nt":
            # Directory junctions exercise the same reparse guard without symlink privilege.
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            command = ("New-Item -ItemType Junction -ErrorAction Stop -Path " + quote(link)
                       + " -Target " + quote(outside) + " | Out-Null")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "leaves the project|Linked paths"):
                pack_skill.assemble(self.root)
        finally:
            # Remove only the explicitly created link, never recursively its target.
            self.assertTrue(link.absolute().is_relative_to(self.root))
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()


if __name__ == "__main__":
    unittest.main()
