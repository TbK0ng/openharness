"""TodoWrite（s05）：整体替换清单 + 3 回合 nag。"""
import asyncio
import unittest

from openharness.tools.meta_todo import (
    TodoState, TodoWriteTool, todo_nag_due,
)


class _Ctx:
    def __init__(self):
        self.todo_state = None
        self.shown = []

    def display(self, s):
        self.shown.append(str(s))


def run(coro):
    return asyncio.run(coro)


class TestTodoState(unittest.TestCase):
    def test_replace_resets_turns(self):
        st = TodoState()
        st.replace([{"content": "a", "status": "pending"}])
        st.turns_since_write = 5
        st.replace([{"content": "b", "status": "completed"}])
        self.assertEqual(st.turns_since_write, 0)
        self.assertEqual(st.pending_count(), 0)

    def test_render_marks(self):
        st = TodoState()
        st.replace([
            {"content": "a", "status": "pending"},
            {"content": "b", "status": "in_progress"},
            {"content": "c", "status": "completed"},
        ])
        out = st.render()
        self.assertIn("○ a", out)
        self.assertIn("◐ b", out)
        self.assertIn("● c", out)

    def test_render_empty(self):
        self.assertEqual(TodoState().render(), "(empty)")


class TestTodoNag(unittest.TestCase):
    def test_no_state_no_nag(self):
        ctx = _Ctx()
        self.assertFalse(todo_nag_due(ctx))

    def test_fresh_write_no_nag(self):
        ctx = _Ctx()
        ctx.todo_state = TodoState()
        ctx.todo_state.replace([{"content": "a", "status": "pending"}])
        self.assertFalse(todo_nag_due(ctx))

    def test_three_stale_turns_with_open_items_nags(self):
        ctx = _Ctx()
        ctx.todo_state = TodoState()
        ctx.todo_state.replace([{"content": "a", "status": "pending"}])
        ctx.todo_state.turns_since_write = 3
        self.assertTrue(todo_nag_due(ctx))

    def test_all_done_no_nag_even_if_stale(self):
        ctx = _Ctx()
        ctx.todo_state = TodoState()
        ctx.todo_state.replace([{"content": "a", "status": "completed"}])
        ctx.todo_state.turns_since_write = 9
        self.assertFalse(todo_nag_due(ctx))


class TestTodoWriteTool(unittest.TestCase):
    def test_replaces_and_displays(self):
        ctx = _Ctx()
        res = run(TodoWriteTool().execute(
            {"todos": [{"content": "x", "status": "pending"}]}, ctx))
        self.assertIn("1 open", res.output)
        self.assertTrue(any("📋" in s for s in ctx.shown))
        self.assertEqual(ctx.todo_state.items[0]["content"], "x")

    def test_invalid_status_rejected(self):
        ctx = _Ctx()
        res = run(TodoWriteTool().execute(
            {"todos": [{"content": "x", "status": "bogus"}]}, ctx))
        self.assertIn("invalid status", res.output)
        self.assertIsNone(ctx.todo_state)


if __name__ == "__main__":
    unittest.main()
