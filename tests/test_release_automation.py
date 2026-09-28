import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseAutomationTests(unittest.TestCase):
    def test_automation_creates_version_tag_and_release(self) -> None:
        text = (ROOT / ".cursor/automations/release-on-merge.md").read_text(encoding="utf-8")
        self.assertIn("Pull request merged", text)
        self.assertIn("次のタグ番号を決める", text)
        self.assertIn("pyproject.toml", text)
        self.assertIn("release:minor", text)
        self.assertIn("release:major", text)
        self.assertIn("gh release create", text)
        self.assertIn("--target", text)
        self.assertIn("40桁", text)
        self.assertIn("固定参照", text)
        self.assertNotIn("create_release.py", text)
        self.assertFalse((ROOT / "create_release.py").exists())
