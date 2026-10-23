"""Test memory/manager.py (ch.9): MEMORY.md 索引、主题文件、四种类型、生命周期。"""
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from openharness.memory import MEMORY_TYPES, MemoryError, MemoryManager

# 工作区内的临时目录：沙箱只允许写 session workspace
TMP_ROOT = Path(__file__).resolve().parents[2] / "_tmp_tests"


def _fresh_dir(name: str) -> Path:
    d = TMP_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


class TestMemoryManager(unittest.TestCase):
    """第 9 章：MEMORY.md 索引 + memory/ 主题文件 + 四种类型 + 生命周期。"""

    def setUp(self):
        self.dir = _fresh_dir("memory")
        self.mm = MemoryManager(self.dir)

    # ---------- 创建 + 索引 ----------

    def test_save_writes_typed_file_with_frontmatter(self):
        p = self.mm.save("测试偏好", "用户对测试方式的偏好", "feedback",
                         "集成测试必须使用真实数据库，不要 Mock。\n\n**Why:** 上季度 Mock 全部通过但生产迁移失败。")
        self.assertTrue(p.exists())
        self.assertEqual(p.name, "feedback_测试偏好.md")
        text = p.read_text(encoding="utf-8")
        self.assertIn("name: 测试偏好", text)
        self.assertIn("description: 用户对测试方式的偏好", text)
        self.assertIn("type: feedback", text)
        self.assertIn("**Why:**", text)

    def test_save_rejects_unknown_type(self):
        with self.assertRaises(MemoryError):
            self.mm.save("x", "d", "note", "body")

    def test_save_all_four_types(self):
        for t in ("user", "feedback", "project", "reference"):
            self.mm.save(f"记忆{t}", f"{t} 描述", t, f"{t} 正文")
        types = {m["type"] for m in self.mm.list_memories()}
        self.assertEqual(types, set(MEMORY_TYPES))

    def test_save_is_idempotent_per_name(self):
        self.mm.save("用户画像", "高级 Go 开发者", "user", "旧内容")
        p2 = self.mm.save("用户画像", "刚接触 React", "user", "新内容")
        self.assertEqual(p2.name, "user_用户画像.md")
        self.assertIn("新内容", p2.read_text(encoding="utf-8"))
        self.assertNotIn("旧内容", p2.read_text(encoding="utf-8"))
        index = self.mm.index.read_text(encoding="utf-8")
        entry_lines = [line for line in index.splitlines() if line.startswith("- [")]
        self.assertEqual(len(entry_lines), 1)  # 索引只留一行

    def test_index_lists_entries_with_resolvable_links(self):
        self.mm.save("代码冻结", "3 月 5 日后有代码冻结期", "project", "冻结期内只修 bug")
        self.mm.save("Bug 追踪", "Bug 追踪在 Linear 的 INGEST 项目中", "reference", "链接见 Linear")
        index = self.mm.index.read_text(encoding="utf-8")
        self.assertIn("# MEMORY", index)
        for name in ("代码冻结", "Bug 追踪"):
            self.assertRegex(index, rf"- \[{name}\]\((.+?)\) — .+")
        # 索引里的每个链接都指向真实存在的文件
        for link in re.findall(r"\]\((.+?)\)", index):
            self.assertTrue((self.dir / link).exists(), f"索引链接失效：{link}")

    # ---------- 加载 ----------

    def test_list_memories_scans_directory_not_index(self):
        self.mm.save("孤儿记忆", "索引丢失也能找到", "user", "正文")
        self.mm.index.unlink()  # 模拟索引损坏
        names = [m["name"] for m in self.mm.list_memories()]
        self.assertIn("孤儿记忆", names)

    def test_get_returns_full_text_and_none_for_missing(self):
        self.mm.save("反馈示例", "不要在回复末尾做总结", "feedback", "直接给结论。")
        text = self.mm.get("反馈示例")
        self.assertIsNotNone(text)
        self.assertIn("type: feedback", text)
        self.assertIn("直接给结论。", text)
        self.assertIsNone(self.mm.get("不存在"))

    def test_load_all_concatenates_bodies(self):
        self.mm.save("A", "da", "user", "甲正文")
        self.mm.save("B", "db", "project", "乙正文")
        all_text = self.mm.load_all()
        self.assertIn("甲正文", all_text)
        self.assertIn("乙正文", all_text)

    def test_snapshot_empty_before_any_memory(self):
        self.assertEqual(self.mm.snapshot(), "")

    def test_snapshot_injectable_into_system_prompt(self):
        self.mm.save("反馈", "不要在回复末尾做总结", "feedback", "直接给结论。")
        snap = self.mm.snapshot()
        self.assertTrue(snap.startswith("## 长期记忆"))
        self.assertIn("反馈", snap)
        self.assertIn("memory/feedback_反馈.md", snap)  # 索引含相对链接

    def test_snapshot_truncates_very_long_index(self):
        for i in range(60):
            self.mm.save(f"超长{i}", "y" * 200, "user", "z" * 100)
        self.assertLessEqual(len(self.mm.snapshot()), 4200)

    # ---------- 更新 / 删除（生命周期） ----------

    def test_update_changes_body_and_description(self):
        self.mm.save("项目约定", "旧约定", "project", "旧内容")
        self.mm.update("项目约定", description="新约定", body="新内容")
        text = self.mm.get("项目约定")
        self.assertIn("description: 新约定", text)
        self.assertIn("新内容", text)
        self.assertNotIn("旧内容", text)
        self.assertIn("新约定", self.mm.index.read_text(encoding="utf-8"))

    def test_update_missing_raises(self):
        with self.assertRaises(MemoryError):
            self.mm.update("没有这条")

    def test_delete_removes_file_and_index_line(self):
        self.mm.save("待删", "临时信息", "reference", "过时的链接")
        self.mm.save("保留", "长期有效", "user", "留下")
        self.assertTrue(self.mm.delete("待删"))
        self.assertFalse(any(p.name.startswith("reference_") for p in self.mm.dir.glob("*.md")))
        index = self.mm.index.read_text(encoding="utf-8")
        self.assertNotIn("待删", index)
        self.assertIn("保留", index)

    def test_delete_missing_returns_false(self):
        self.assertFalse(self.mm.delete("幽灵"))


if __name__ == "__main__":
    unittest.main()
