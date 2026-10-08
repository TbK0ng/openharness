"""Test the builtin tool set (ch.5): registry, read_only classification, real file IO."""
import asyncio
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openharness.permissions.checker import ALLOW, ASK_USER, DENY
from openharness.tools import BUILTIN_TOOLS, register_builtin_tools
from openharness.tools.registry import ToolRegistry

TMP_ROOT = Path(__file__).resolve().parents[1] / "_tmp_tests"

# 教程第 6 章：这些工具在 default 模式自动通过、plan 模式仍可执行
EXPECTED_READ_ONLY = {
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "ToolSearch",
    "Skill", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "TaskGet", "TaskList", "ListMcpResources", "ReadMcpResource", "CronList",
}


def _run(coro):
    return asyncio.run(coro)


class Ctx:
    """工具执行所需的最小上下文（用真实临时目录）。

    权限检查器要通过 context.registry 查工具的 read_only 标记，
    所以这里必须带上真实的 ToolRegistry。
    """

    def __init__(self, cwd, registry=None):
        self.cwd = str(cwd)
        self.session_id = "test"
        self.messages = []
        self.events = []
        if registry is None:
            registry = ToolRegistry()
            register_builtin_tools(registry)
        self.registry = registry

    def display(self, s):
        self.events.append(str(s))

    def on_event(self, s):
        self.events.append(str(s))

    def ask_user(self, prompt):
        return "y"


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        register_builtin_tools(self.reg)

    def test_registers_all_builtin_tools(self):
        self.assertEqual(len(self.reg.list_tools()), len(BUILTIN_TOOLS))
        self.assertEqual(len(BUILTIN_TOOLS), 29)  # 教程第 5 章的 29 个内置工具

    def test_every_tool_has_name_description_and_schema(self):
        for t in self.reg.list_tools():
            self.assertTrue(t.name, "tool needs a name")
            self.assertTrue(t.description, f"{t.name} needs a description")
            schema = t.get_input_schema()
            self.assertEqual(schema.get("type"), "object", f"{t.name} schema must be object")

    def test_json_schema_shape_for_llm(self):
        schemas = self.reg.get_tool_schemas()
        self.assertEqual(len(schemas), 29)
        for s in schemas:
            self.assertEqual(s["type"], "function")
            self.assertIn("name", s["function"])
            self.assertIn("parameters", s["function"])

    def test_read_only_classification(self):
        actual = {t.name for t in self.reg.list_tools() if t.read_only}
        self.assertEqual(actual, EXPECTED_READ_ONLY)

    def test_mutating_tools_are_not_read_only(self):
        for name in ("Write", "Edit", "Bash", "NotebookEdit"):
            self.assertFalse(self.reg.get_tool(name).read_only, f"{name} must not be read-only")

    def test_search_finds_tool_by_keyword(self):
        found = {t.name for t in self.reg.search("file")}
        self.assertTrue(found)

    def test_get_unknown_tool_returns_none(self):
        self.assertIsNone(self.reg.get_tool("NoSuchTool"))


class TestFileTools(unittest.TestCase):
    """Read/Write/Edit/Glob/Grep 对真实临时目录操作。"""

    def setUp(self):
        self.dir = TMP_ROOT / "filetools"
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.reg = ToolRegistry()
        register_builtin_tools(self.reg)
        self.ctx = Ctx(self.dir)

    def _call(self, name, params):
        tool = self.reg.get_tool(name)
        return _run(tool.execute(params, self.ctx))

    def test_write_then_read_roundtrip(self):
        r = self._call("Write", {"file_path": "hello.txt", "content": "line1\nline2\n"})
        self.assertFalse(r.is_error, r.error)
        r = self._call("Read", {"file_path": "hello.txt"})
        self.assertFalse(r.is_error, r.error)
        self.assertIn("line1", r.output)
        self.assertIn("line2", r.output)

    def test_read_missing_file_is_error_not_crash(self):
        r = self._call("Read", {"file_path": "nope.txt"})
        self.assertTrue(r.is_error)
        self.assertIn("not found", r.output.lower() + (r.error or "").lower())

    def test_read_paging_with_offset_and_limit(self):
        self._call("Write", {"file_path": "big.txt", "content": "\n".join(f"L{i}" for i in range(1, 11))})
        r = self._call("Read", {"file_path": "big.txt", "offset": 3, "limit": 2})
        self.assertIn("L3", r.output)
        self.assertIn("L4", r.output)
        self.assertNotIn("L5", r.output)

    def test_edit_replaces_exact_string(self):
        self._call("Write", {"file_path": "a.py", "content": "if user == None:\n    pass\n"})
        r = self._call("Edit", {
            "file_path": "a.py",
            "old_string": "if user == None:",
            "new_string": "if user is not None:",
        })
        self.assertFalse(r.is_error, r.error)
        self.assertIn("is not None", (self.dir / "a.py").read_text(encoding="utf-8"))

    def test_edit_missing_old_string_is_error(self):
        self._call("Write", {"file_path": "b.py", "content": "x = 1\n"})
        r = self._call("Edit", {"file_path": "b.py", "old_string": "absent", "new_string": "y"})
        self.assertTrue(r.is_error)

    def test_glob_finds_files_by_pattern(self):
        (self.dir / "sub").mkdir()
        (self.dir / "sub" / "one.py").write_text("x", encoding="utf-8")
        (self.dir / "two.py").write_text("x", encoding="utf-8")
        r = self._call("Glob", {"pattern": "**/*.py"})
        self.assertFalse(r.is_error, r.error)
        self.assertIn("two.py", r.output)
        self.assertIn("one.py", r.output)

    def test_grep_searches_file_contents(self):
        (self.dir / "g.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        r = self._call("Grep", {"pattern": "alpha"})
        self.assertFalse(r.is_error, r.error)
        self.assertIn("alpha", r.output)


class TestPermissionIntegrationWithTools(unittest.TestCase):
    """工具分类要真的影响权限判定（第 6 章）。"""

    def setUp(self):
        self.dir = TMP_ROOT / "perm"
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.reg = ToolRegistry()
        register_builtin_tools(self.reg)
        self.ctx = Ctx(self.dir)

    def _check(self, checker, tool, params):
        return checker.check(tool, params, self.ctx)

    def test_read_allowed_in_default_mode(self):
        from openharness.permissions.checker import PermissionChecker
        c = PermissionChecker({"mode": "default"})
        self.assertEqual(self._check(c, "Read", {"file_path": "a"}).verdict, ALLOW)

    def test_write_asks_in_default_mode(self):
        from openharness.permissions.checker import PermissionChecker
        c = PermissionChecker({"mode": "default"})
        self.assertEqual(self._check(c, "Write", {"file_path": "a", "content": "b"}).verdict, ASK_USER)

    def test_write_denied_in_plan_mode(self):
        from openharness.permissions.checker import PermissionChecker
        c = PermissionChecker({"mode": "plan"})
        self.assertEqual(self._check(c, "Write", {"file_path": "a", "content": "b"}).verdict, DENY)

    def test_read_allowed_in_plan_mode(self):
        from openharness.permissions.checker import PermissionChecker
        c = PermissionChecker({"mode": "plan"})
        self.assertEqual(self._check(c, "Read", {"file_path": "a"}).verdict, ALLOW)

    def test_bash_denied_by_command_rule(self):
        from openharness.permissions.checker import PermissionChecker
        c = PermissionChecker({"mode": "full-auto", "deny_commands": [r"rm\s+-rf"]})
        self.assertEqual(self._check(c, "Bash", {"command": "rm -rf /"}).verdict, DENY)


if __name__ == "__main__":
    unittest.main()
