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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from package_existing import package_existing
from package_lib import PackageError, validate_package
from package_validation import binary, manifest


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


if __name__ == "__main__":
    unittest.main()
