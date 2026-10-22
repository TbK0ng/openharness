"""Test 长期记忆工具：MemorySave / MemorySearch / MemoryDelete 真正落盘。"""
import asyncio
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openharness.engine.query_engine as qe
from openharness.engine.query_engine import Engine
from openharness.hooks.executor import execute_tool_with_hooks

TMP_ROOT = Path(__file__).resolve().parents[1] / "_tmp_tests"


def _fresh_dir(name: str) -> Path:
    d = TMP_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _call(ctx, name, args, call_id="c1"):
    return asyncio.run(execute_tool_with_hooks(
        ctx, {"name": name, "arguments": args, "id": call_id}))


class TestMemoryTools(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(qe, "build_llm", return_value=object())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = Engine(cwd=str(_fresh_dir("memory_tools")))
        self.ctx = self.engine.create_context()
        self.ctx.permissions.set_mode("full-auto")

    def test_tools_are_registered(self):
        for name in ("MemorySave", "MemorySearch", "MemoryDelete"):
            self.assertIsNotNone(self.engine.registry.get_tool(name), name)

    def test_save_persists_file_and_index(self):
        result = _call(self.ctx, "MemorySave", {
            "name": "测试偏好", "description": "集成测试用真实数据库",
            "type": "feedback", "body": "不要 Mock 数据库。",
        })
        self.assertFalse(result.is_error, result.error)
        path = self.engine.memory.dir / "feedback_测试偏好.md"
        self.assertTrue(path.exists())
        self.assertIn("不要 Mock 数据库", path.read_text(encoding="utf-8"))
        self.assertIn("测试偏好", (self.engine.oh_dir / "MEMORY.md")
                      .read_text(encoding="utf-8"))
        # 下一轮 system prompt 能看到索引
        self.assertIn("测试偏好", self.engine._build_system_prompt())

    def test_search_finds_by_name_and_body(self):
        _call(self.ctx, "MemorySave", {
            "name": "构建命令", "description": "项目构建方式",
            "type": "project", "body": "使用 uv run pytest。",
        })
        result = _call(self.ctx, "MemorySearch", {"query": "uv"})
        self.assertFalse(result.is_error)
        self.assertIn("构建命令", result.output)
        self.assertIn("uv run pytest", result.output)

    def test_delete_removes_file_and_index_line(self):
        _call(self.ctx, "MemorySave", {
            "name": "临时", "description": "过期", "type": "reference", "body": "x",
        })
        result = _call(self.ctx, "MemoryDelete", {"name": "临时"})
        self.assertFalse(result.is_error)
        self.assertFalse((self.engine.memory.dir / "reference_临时.md").exists())
        self.assertNotIn("临时", (self.engine.oh_dir / "MEMORY.md")
                         .read_text(encoding="utf-8"))

    def test_save_rejects_unknown_type(self):
        result = _call(self.ctx, "MemorySave", {
            "name": "x", "description": "d", "type": "note", "body": "b",
        })
        self.assertTrue(result.is_error)
        self.assertIn("未知记忆类型", result.error)


if __name__ == "__main__":
    unittest.main()
