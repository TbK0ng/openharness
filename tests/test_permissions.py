"""Test permissions/checker.py (ch.6 three-tier modes + fine-grained rules)."""
import unittest

from tests.util import make_context
from openharness.permissions.checker import ALLOW, ASK_USER, DENY


class TestDefaultMode(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmpdir()
        self.ctx, self.state = make_context(self.tmp, mode="default")

    def test_read_only_allowed(self):
        d = self.ctx.permissions.check("Echo", {"text": "x"}, self.ctx)
        self.assertEqual(d.verdict, ALLOW)

    def test_write_asks_user(self):
        d = self.ctx.permissions.check("Write", {"file_path": "a.txt", "content": "b"}, self.ctx)
        self.assertEqual(d.verdict, ASK_USER)
        self.assertIn("y/N", d.prompt)

    def test_denied_tool(self):
        self.ctx.permissions.denied_tools.add("Echo")
        d = self.ctx.permissions.check("Echo", {}, self.ctx)
        self.assertEqual(d.verdict, DENY)

    def test_path_rule_denies(self):
        self.ctx.permissions.add_path_rule("*/secrets/*")
        d = self.ctx.permissions.check("Write", {"file_path": "C:/x/secrets/key.txt", "content": "b"}, self.ctx)
        self.assertEqual(d.verdict, DENY)

    def test_path_rule_matches_absolute_form_of_relative_rule(self):
        """相对规则也必须拦住绝对路径写法，否则换个写法就能绕过。"""
        import os

        self.ctx.permissions.add_path_rule("secret/*")
        abs_path = os.path.join(self.tmp, "secret", "key.txt")
        d = self.ctx.permissions.check(
            "Write", {"file_path": abs_path, "content": "b"}, self.ctx)
        self.assertEqual(d.verdict, DENY)

    def test_path_rule_leaves_other_paths_alone(self):
        import os

        self.ctx.permissions.mode = "full-auto"
        self.ctx.permissions.add_path_rule("secret/*")
        d = self.ctx.permissions.check(
            "Write", {"file_path": os.path.join(self.tmp, "public.txt"), "content": "b"},
            self.ctx)
        self.assertEqual(d.verdict, ALLOW)

    def test_command_rule_denies(self):
        self.ctx.permissions.add_command_rule(r"rm\s+-rf")
        d = self.ctx.permissions.check("Bash", {"command": "rm -rf /tmp/x"}, self.ctx)
        self.assertEqual(d.verdict, DENY)


class TestPlanMode(unittest.TestCase):
    def setUp(self):
        self.ctx, self.state = make_context(_tmpdir(), mode="plan")

    def test_read_allowed(self):
        d = self.ctx.permissions.check("Echo", {"text": "x"}, self.ctx)
        self.assertEqual(d.verdict, ALLOW)

    def test_write_denied(self):
        d = self.ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, self.ctx)
        self.assertEqual(d.verdict, DENY)


class TestFullAuto(unittest.TestCase):
    def setUp(self):
        self.ctx, self.state = make_context(_tmpdir(), mode="full-auto")

    def test_write_allowed(self):
        d = self.ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, self.ctx)
        self.assertEqual(d.verdict, ALLOW)


class TestAllowList(unittest.TestCase):
    """审批时按 a（或 /permission allow）后，同类工具不再弹 y/n。"""

    def test_allow_tool_skips_ask(self):
        ctx, _ = make_context(_tmpdir(), mode="default")
        ctx.permissions.allow_tool("Write")
        d = ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, ctx)
        self.assertEqual(d.verdict, ALLOW)
        self.assertIn("allow-listed", d.reason)

    def test_allow_tools_from_config(self):
        ctx, _ = make_context(_tmpdir(), mode="default",
                             config={"allow_tools": ["Write"]})
        d = ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, ctx)
        self.assertEqual(d.verdict, ALLOW)

    def test_plan_mode_still_denies_allowlisted_write(self):
        ctx, _ = make_context(_tmpdir(), mode="plan")
        ctx.permissions.allow_tool("Write")
        d = ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, ctx)
        self.assertEqual(d.verdict, DENY)

    def test_deny_beats_allow(self):
        ctx, _ = make_context(_tmpdir(), mode="default")
        ctx.permissions.allow_tool("Write")
        ctx.permissions.deny_tool("Write")
        d = ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, ctx)
        self.assertEqual(d.verdict, DENY)

    def test_forget_tool_removes_both_lists(self):
        ctx, _ = make_context(_tmpdir(), mode="default")
        ctx.permissions.allow_tool("Write")
        ctx.permissions.deny_tool("Write")
        ctx.permissions.forget_tool("Write")
        self.assertEqual(ctx.permissions.check(
            "Write", {"file_path": "a", "content": "b"}, ctx).verdict, ASK_USER)


class TestModeSwitch(unittest.TestCase):
    def test_set_mode(self):
        ctx, _ = make_context(_tmpdir(), mode="default")
        ctx.permissions.set_mode("full-auto")
        self.assertEqual(ctx.permissions.check("Write", {"file_path": "a", "content": "b"}, ctx).verdict, ALLOW)
        with self.assertRaises(ValueError):
            ctx.permissions.set_mode("bogus")


def _tmpdir():
    import tempfile
    d = tempfile.mkdtemp(prefix="oh_test_")
    return d


if __name__ == "__main__":
    unittest.main()
