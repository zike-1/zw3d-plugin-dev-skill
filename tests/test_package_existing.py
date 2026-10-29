"""Regression checks for prebuilt package creation without SDK or compiler."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import shutil
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from package_existing import package_existing
from package_lib import PE, PackageError, sha256, validate_package
from package_validation import binary, manifest
import prebuilt_installer
from inspect_installer import inspect
from build_plugin import DEFAULT_RUNTIME


class PrebuiltPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zwplug_prebuilt_")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "payload").mkdir(parents=True)
        self.out = self.root / "dist"
        self.m = manifest()
        self.write_manifest()
        (self.project / "payload" / "ArtHello.dll").write_bytes(binary())

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        (self.project / "plugin.json").write_text(
            json.dumps(self.m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_prebuilt_dll_requires_neither_sdk_nor_compiler(self):
        with patch.dict(os.environ, {"PATH": ""}):
            report = package_existing(self.project, self.out)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["installerGenerated"])
        self.assertFalse(report["hostApisChecked"])
        self.assertEqual(validate_package(Path(report["package"]))["files"], 1)
        self.assertEqual(package_existing(self.project, self.out)["sha256"], report["sha256"])

    def test_prebuilt_exe_with_multiple_hub_entries(self):
        self.m.update(type="exe", entry="ArtHello.exe")
        self.m["commands"].append({
            "id": "ArtHelloSettings", "label": "设置",
            "environments": ["top", "part", "assembly", "drawing"],
            "arguments": "/settings"
        })
        self.write_manifest()
        (self.project / "payload" / "ArtHello.dll").unlink()
        (self.project / "payload" / "ArtHello.exe").write_bytes(binary(dll=False))
        report = package_existing(self.project, self.out)
        self.assertEqual(validate_package(Path(report["package"]))["files"], 1)

    def test_changed_content_with_same_version_refuses_overwrite(self):
        path = Path(package_existing(self.project, self.out)["package"])
        original = path.read_bytes()
        (self.project / "payload" / "readme.txt").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(PackageError, "increase version"):
            package_existing(self.project, self.out)
        self.assertEqual(path.read_bytes(), original)

    def test_missing_or_invalid_binary_has_no_published_artifact(self):
        (self.project / "payload" / "ArtHello.dll").write_bytes(b"invalid")
        with self.assertRaises(PackageError):
            package_existing(self.project, self.out)
        self.assertFalse(list(self.out.glob("*.zwplug")))

    def test_output_inside_payload_is_rejected(self):
        with self.assertRaisesRegex(PackageError, "inside project/payload"):
            package_existing(self.project, self.project / "payload" / "dist")

    def test_optional_sdk_verification_fails_closed(self):
        with self.assertRaises((PackageError, OSError)):
            package_existing(self.project, self.out, self.root / "not-a-host")
        self.assertFalse(list(self.out.glob("*.zwplug")))

    def test_cli_emits_machine_readable_report(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "package_existing.py"),
             str(self.project), "--out", str(self.out)],
            capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertFalse(report["installerGenerated"])
        self.assertTrue(Path(report["package"]).is_file())


@unittest.skipUnless(os.name == "nt", "Windows resource writer required")
class PrebuiltInstallerTests(unittest.TestCase):
    setUp = PrebuiltPackageTests.setUp
    tearDown = PrebuiltPackageTests.tearDown
    write_manifest = PrebuiltPackageTests.write_manifest

    def build(self):
        return package_existing(self.project, self.out, installer=True)

    def test_dll_installer_without_sdk_path_or_subprocesses_is_reproducible(self):
        self.out = self.root / "中文 安装包"
        original = (self.project / "payload/ArtHello.dll").read_bytes()
        with patch.dict(os.environ, {"PATH": ""}), patch(
                "subprocess.run", side_effect=AssertionError("compiler/process was invoked")):
            first = self.build()
            second = self.build()
        self.assertTrue(first["installerGenerated"])
        self.assertFalse(first["compilerInvoked"])
        self.assertFalse(first["hostApisChecked"])
        self.assertEqual(first["installerSha256"], second["installerSha256"])
        self.assertEqual((self.project / "payload/ArtHello.dll").read_bytes(), original)
        self.assertEqual(inspect(Path(first["installer"]), Path(first["package"]),
                                 DEFAULT_RUNTIME)["status"], "PASS")

    def test_exe_installer_uses_custom_icon_and_fixed_arguments(self):
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        icon = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress((b"\0" + b"\x10\x80\xd0" * 16) * 16)) + chunk(b"IEND", b""))
        self.m.update(type="exe", entry="ArtHello.exe")
        self.m["commands"][0].update(icon="icons/custom.png", arguments="/settings")
        self.write_manifest()
        (self.project / "payload/ArtHello.dll").unlink()
        (self.project / "payload/ArtHello.exe").write_bytes(binary(dll=False))
        (self.project / "payload/icons").mkdir()
        (self.project / "payload/icons/custom.png").write_bytes(icon)
        result = self.build()
        resources = PE(Path(result["installer"]).read_bytes()).resources()
        self.assertEqual(resources[(3, 1, 1033)], icon)
        self.assertIn(b"/settings", resources[(10, 2000, 1033)])

    def test_frozen_template_corruption_is_rejected_without_publication(self):
        template = self.root / "template"
        shutil.copytree(prebuilt_installer.DEFAULT_TEMPLATE, template)
        with (template / "SetupTemplate.exe").open("ab") as stream:
            stream.write(b"tampered")
        with patch.object(prebuilt_installer, "DEFAULT_TEMPLATE", template):
            with self.assertRaisesRegex(PackageError, "template was modified"):
                self.build()
        self.assertFalse(list(self.out.glob("*.zwplug")))
        self.assertFalse(list(self.out.glob("*.exe")))

    def test_frozen_framework_corruption_is_rejected_without_publication(self):
        runtime = self.root / "runtime"
        shutil.copytree(DEFAULT_RUNTIME, runtime)
        (runtime / "HubManager.exe").write_bytes(b"tampered")
        with patch.object(prebuilt_installer, "DEFAULT_RUNTIME", runtime):
            with self.assertRaisesRegex(PackageError, "runtime was modified"):
                self.build()
        self.assertFalse(list(self.out.glob("*.zwplug")))

    def test_signed_template_is_rejected_even_with_matching_checksum(self):
        template = self.root / "template"
        shutil.copytree(prebuilt_installer.DEFAULT_TEMPLATE, template)
        exe = template / "SetupTemplate.exe"
        data = bytearray(exe.read_bytes())
        optional = struct.unpack_from("<I", data, 60)[0] + 24
        struct.pack_into("<II", data, optional + 112 + 4 * 8, len(data), 8)
        exe.write_bytes(data)
        (template / "checksums.json").write_text(json.dumps({"SetupTemplate.exe": sha256(data)}))
        with patch.object(prebuilt_installer, "DEFAULT_TEMPLATE", template):
            with self.assertRaisesRegex(PackageError, "unsigned"):
                self.build()

    def test_resource_write_failure_keeps_existing_package(self):
        prior = Path(package_existing(self.project, self.out)["package"])
        original = prior.read_bytes()
        with patch.object(prebuilt_installer, "update_resources", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                self.build()
        self.assertEqual(prior.read_bytes(), original)
        self.assertFalse(list(self.out.glob("*.exe")))

    def test_existing_installer_is_not_overwritten_with_different_bytes(self):
        result = self.build()
        exe, package = Path(result["installer"]), Path(result["package"])
        original = package.read_bytes()
        exe.write_bytes(b"externally changed")
        with self.assertRaisesRegex(PackageError, "increase version"):
            self.build()
        self.assertEqual(package.read_bytes(), original)
        self.assertEqual(exe.read_bytes(), b"externally changed")

    def test_invalid_payload_publishes_neither_artifact(self):
        (self.project / "payload/ArtHello.dll").write_bytes(b"not a PE")
        with self.assertRaises(PackageError):
            self.build()
        self.assertFalse(list(self.out.glob("*.zwplug")))
        self.assertFalse(list(self.out.glob("*.exe")))

    def test_publication_failure_rolls_back_the_artifact_set(self):
        prior = Path(package_existing(self.project, self.out)["package"])
        original = prior.read_bytes()
        replace = os.replace
        def fail_installer(source, destination):
            if Path(destination).name.endswith("-setup.exe"):
                raise OSError("installer publication failed")
            return replace(source, destination)
        with patch("build_plugin.os.replace", side_effect=fail_installer):
            with self.assertRaisesRegex(OSError, "publication failed"):
                self.build()
        self.assertEqual(prior.read_bytes(), original)
        self.assertFalse(list(self.out.glob("*.exe")))
        self.assertFalse(list(self.out.glob(".zwplug-*")))

    def test_code_mutation_is_detected(self):
        data = prebuilt_installer.checked_template()
        changed = bytearray(data)
        changed[PE(data).sections[0][3]] ^= 1
        with self.assertRaisesRegex(PackageError, "code or non-resource data changed"):
            prebuilt_installer.verify_code(data, changed)

    def test_cli_installer_with_empty_path_runs_and_rejects_invalid_target(self):
        env = dict(os.environ, PATH="")
        proc = subprocess.run([sys.executable, str(ROOT / "tools/package_existing.py"),
            str(self.project), "--out", str(self.out), "--installer"],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        log = self.root / "invalid-target.log"
        proc = subprocess.run([result["installer"], "/quiet", "/install",
            "/target=" + str(self.root / "not-a-host"), "/log=" + str(log)],
            env=env, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Not a ZW3D installation", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
