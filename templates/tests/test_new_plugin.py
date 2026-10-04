"""Generator contracts: valid projects, preserved work, rejected identities."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


TEMPLATES = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("new_plugin", TEMPLATES / "new_plugin.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class GeneratorContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="generator-test-", dir=TEMPLATES)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_dll_manifest_and_names_agree(self):
        target = self.root / "hello"
        generator.create_plugin("dll", "org.example.hello", "Hello", "中文问候", target)
        manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        source = (target / "src" / "Hello.cpp").read_text(encoding="utf-8")
        self.assertEqual(manifest["entry"], "Hello.dll")
        self.assertEqual(manifest["commands"][0]["id"], "HelloShow")
        self.assertEqual(manifest["host"], {"product": "ZW3D", "versions": [2027], "architecture": "x64"})
        self.assertIn('constexpr char commandName[] = "HelloShow";', source)
        self.assertIn('int HelloInit()', source)
        self.assertIn('int HelloExit()', source)
        self.assertNotIn("@PREFIX@", source)
        self.assertEqual(generator.validate_manifest(manifest), manifest)

    def test_exe_uses_one_entry_and_fixed_arguments(self):
        target = self.root / "notes"
        generator.create_plugin("exe", "org.example.notes", "Notes", '引号"与\\路径', target)
        manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
        source = (target / "src" / "Notes.cpp").read_text(encoding="utf-8")
        self.assertEqual(manifest["entry"], "Notes.exe")
        self.assertEqual(manifest["commands"][0]["arguments"], "")
        self.assertNotIn("arguments", manifest)
        self.assertNotIn("entry", manifest["commands"][0])
        self.assertIn('L"引号\\"与\\\\路径"', source)
        self.assertNotIn("zwapi", source)
        self.assertEqual(generator.validate_manifest(manifest), manifest)

    def test_existing_work_is_preserved(self):
        target = self.root / "existing"
        target.mkdir()
        sentinel = target / "notes.txt"
        sentinel.write_text("my work", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            generator.create_plugin("dll", "org.example.hello", "Hello", "问候", target)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "my work")
        self.assertEqual(list(target.iterdir()), [sentinel])

    def test_invalid_identity_does_not_create_a_project(self):
        target = self.root / "invalid"
        for plugin_id, prefix in [("../escape", "Hello"), ("org.example.good", "Bad;Command"),
                                  ("org.example.good", "H" * 33), ("org.example.good", "HubDemo"),
                                  ("org.example.good", "CON"), ("org.example.good", "lowercase"),
                                  ("org.123.invalid", "Hello")]:
            with self.subTest(plugin_id=plugin_id, prefix=prefix):
                with self.assertRaises(ValueError):
                    generator.create_plugin("dll", plugin_id, prefix, "示例", target)
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
