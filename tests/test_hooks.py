"""Test hooks/executor.py (ch.7: 4 events, 4 hook types, execute_tool_with_hooks flow)."""
import asyncio
import sys
import unittest
from pathlib import Path

from tests.util import make_context
from openharness.hooks.executor import (
    PRE_TOOL_USE, POST_TOOL_USE, SESSION_START,
    execute_tool_with_hooks,
)

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable


class TestHookFlow(unittest.TestCase):
    """教程第 7 章的顺序：PreHook → 权限检查 → 执行 → PostHook。"""

    def test_happy_path_in_default_mode(self):
        ctx, state = make_context(_tmp(), mode="default")
        tc = {"name": "Echo", "arguments": {"text": "hello"}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertFalse(result.is_error)
        self.assertEqual(result.output, "hello")

    def test_hook_can_block_pre_tool_use(self):
        hook_config = {
            "pre_tool_use": [
                {"type": "command", "command": "echo BLOCK: dangerous tool call", "match_tools": ["Echo"]},
            ]
        }
        ctx, state = make_context(_tmp(), mode="full-auto", hook_config=hook_config)
        tc = {"name": "Echo", "arguments": {"text": "hi"}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertTrue(result.is_error)
        self.assertIn("Hook", result.error)
        self.assertIn("dangerous", result.error)

    def test_match_tools_filter(self):
        hook_config = {
            "pre_tool_use": [
                {"type": "command", "command": "echo BLOCK: only for Bash", "match_tools": ["Bash"]},
            ]
        }
        ctx, state = make_context(_tmp(), mode="full-auto", hook_config=hook_config)
        tc = {"name": "Echo", "arguments": {"text": "hi"}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertFalse(result.is_error)

    def test_permission_deny_returns_error(self):
        ctx, state = make_context(_tmp(), mode="plan")  # Write not read-only
        tc = {"name": "Write", "arguments": {"file_path": "a", "content": "b"}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertTrue(result.is_error)
        self.assertIn("权限不足", result.error)

    def test_ask_user_denied_when_user_says_no(self):
        ctx, state = make_context(_tmp(), mode="default", ask_answer="n")
        tc = {"name": "Write", "arguments": {"file_path": "a", "content": "b"}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertTrue(result.is_error)
        self.assertTrue(state["asks"])  # the prompt was shown

    def test_ask_user_approved_when_user_says_yes(self):
        ctx, state = make_context(_tmp(), mode="default", ask_answer="y")
        tc = {"name": "Write", "arguments": {"file_path": "a", "content": "b"}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertFalse(result.is_error)

    def test_always_answer_allowlists_tool_for_the_session(self):
        ctx, state = make_context(_tmp(), mode="default", ask_answer="a")
        tc = {"name": "Write", "arguments": {"file_path": "a", "content": "b"}, "id": "c1"}

        first = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertFalse(first.is_error)
        self.assertIn("Write", ctx.permissions.allowed_tools)

        second = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertFalse(second.is_error)
        self.assertEqual(len(state["asks"]), 1)  # 第二次不再询问

    def test_tool_exception_captured(self):
        ctx, state = make_context(_tmp(), mode="full-auto")
        tc = {"name": "Explode", "arguments": {}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertTrue(result.is_error)
        self.assertIn("boom", result.error)

    def test_unknown_tool(self):
        ctx, state = make_context(_tmp(), mode="full-auto")
        tc = {"name": "Ghost", "arguments": {}, "id": "c1"}
        result = asyncio.run(execute_tool_with_hooks(ctx, tc))
        self.assertTrue(result.is_error)
        self.assertIn("未知工具", result.error)

    def test_missing_required_param_is_rejected_before_execute(self):
        # Regression: BaseTool.validate() was never called by the pipeline, so an
        # incomplete tool call reached execute() and surfaced a bare KeyError.
        ctx, state = make_context(_tmp(), mode="full-auto")
        tc = {"name": "Write", "arguments": {"file_path": "a.txt"}, "id": "c1"}

        result = asyncio.run(execute_tool_with_hooks(ctx, tc))

        self.assertTrue(result.is_error)
        self.assertIn("参数校验失败", result.error)
        self.assertIn("content", result.error)

    def test_validation_lets_complete_calls_through(self):
        ctx, state = make_context(_tmp(), mode="full-auto")
        tc = {"name": "Write",
              "arguments": {"file_path": "a.txt", "content": "hi"}, "id": "c1"}

        result = asyncio.run(execute_tool_with_hooks(ctx, tc))

        self.assertFalse(result.is_error)

    def test_session_start_hook_runs(self):
        hook_config = {"session_start": [{"type": "command", "command": "echo started"}]}
        ctx, state = make_context(_tmp(), hook_config=hook_config)
        outcome = ctx.hooks.run(SESSION_START, ctx)
        self.assertFalse(outcome.blocked)


def _tmp():
    import tempfile
    return tempfile.mkdtemp(prefix="oh_hooks_")


if __name__ == "__main__":
    unittest.main()
