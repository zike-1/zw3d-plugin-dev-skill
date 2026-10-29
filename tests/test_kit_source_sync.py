"""Guard source/skill-kit parity and generated kit hash ownership."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "release"))
import pack_skill


class KitSourceSyncTests(unittest.TestCase):
    def test_source_matches_bundled_kit(self):
        kit = ROOT / "skills" / "zw3d-plugin-dev" / "assets" / "kit"
        for relative in ("tools/build_plugin.py", "tools/package_existing.py", "tools/prebuilt_installer.py",
                         "installer-runtime/1.0.0/SetupTemplate.exe", "installer-runtime/1.0.0/checksums.json",
                         "framework/setup.cpp", "framework/ZwPluginHub.cpp"):
            with self.subTest(file=relative):
                self.assertEqual((ROOT / relative).read_bytes(), (kit / relative).read_bytes())

    def test_generated_kit_has_valid_checksums(self):
        pack_skill.verify_owned(ROOT, ROOT / "skills" / "zw3d-plugin-dev" / "assets" / "kit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
