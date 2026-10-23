"""Test skills/loader.py (ch.8): frontmatter 技能发现与按需加载。"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from openharness.skills.loader import SkillLoader

# 工作区内的临时目录：沙箱只允许写 session workspace
TMP_ROOT = Path(__file__).resolve().parents[2] / "_tmp_tests"


def _fresh_dir(name: str) -> Path:
    d = TMP_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


class TestSkillLoader(unittest.TestCase):
    """第 8 章：技能 = 带 frontmatter 的 Markdown，按需加载。"""

    def setUp(self):
        self.dir = _fresh_dir("skills")
        (self.dir / "commit.md").write_text(
            "---\nname: commit\ndescription: 帮助用户创建规范的 Git 提交\n---\n\n"
            "# Git 提交规范\n\n1. git status\n2. git diff\n",
            encoding="utf-8",
        )
        # 主题子目录形式
        sub = self.dir / "review"
        sub.mkdir()
        (sub / "SKILL.md").write_text(
            "---\nname: review-pr\ndescription: 评审 PR\n---\n\n# PR 评审\n",
            encoding="utf-8",
        )
        self.loader = SkillLoader([self.dir])

    def test_discovers_flat_and_nested_skills(self):
        names = {s["name"] for s in self.loader.list_skills()}
        self.assertIn("commit", names)
        self.assertIn("review-pr", names)

    def test_frontmatter_description_parsed(self):
        by_name = {s["name"]: s for s in self.loader.list_skills()}
        self.assertEqual(by_name["commit"]["description"], "帮助用户创建规范的 Git 提交")

    def test_get_returns_full_content(self):
        content = self.loader.get("commit")
        self.assertIsNotNone(content)
        self.assertIn("git status", content)
        self.assertIn("name: commit", content)  # 原始 frontmatter 一并保留

    def test_missing_skill_returns_none(self):
        self.assertIsNone(self.loader.get("nope"))

    def test_summary_lists_skills_for_prompt(self):
        s = self.loader.summary()          # Engine 调用的是 summary()
        self.assertIn("commit", s)
        self.assertIn("review-pr", s)
        # 摘要只放索引，不包含正文
        self.assertNotIn("git status", s)

    def test_summary_empty_when_no_skills(self):
        self.assertEqual(SkillLoader([_fresh_dir("empty_skills")]).summary(), "")


if __name__ == "__main__":
    unittest.main()
