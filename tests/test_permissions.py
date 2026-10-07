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
