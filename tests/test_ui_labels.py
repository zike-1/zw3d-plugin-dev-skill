"""Check display-only labels while preserving stable host registry identifiers."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PluginHubDisplayNames(unittest.TestCase):
    def test_ribbon_and_manager_labels(self):
        setup = (ROOT / "framework/setup.cpp").read_text(encoding="utf-8")
        self.assertIn(r'text=\\\"扩展工具\\\"', setup)
        self.assertIn("<Ribbon>插件管理</Ribbon><Menu>插件管理</Menu>", setup)
        self.assertIn('L"扩展工具管理器"', setup)
        self.assertIn('在“扩展工具”功能区使用', setup)
        self.assertIn('name=\\\"ZwPluginHubPage\\\"', setup)
        self.assertIn('name=\\\"ID_ZpHub_ZwPluginHubManage\\\"', setup)

    def test_launch_feedback_labels(self):
        hub = (ROOT / "framework/ZwPluginHub.cpp").read_text(encoding="utf-8")
        self.assertNotIn('L"小插件工具箱"', hub)
        self.assertIn('L"扩展工具"', hub)
        self.assertIn("ZwPluginHubManage", hub)

    def test_released_version_is_not_rewritten(self):
        import json
        checksum = json.loads((ROOT / "runtime/1.1.3/checksums.json").read_text("utf-8"))
        self.assertEqual(set(checksum), {"HubManager.exe", "ZwPluginHub.dll"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
