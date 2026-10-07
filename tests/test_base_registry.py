"""Test tools/base.py + tools/registry.py (ch.5 patterns)."""
import unittest

from tests.util import EchoTool, WriteTool
from openharness.tools.base import BaseTool, ToolResult
from openharness.tools.registry import ToolRegistry


class TestToolResult(unittest.TestCase):
    def test_ok(self):
        r = ToolResult(output="hi")
        self.assertFalse(r.is_error)
        self.assertEqual(r.to_text(), "hi")

    def test_error(self):
        r = ToolResult(error="bad")
        self.assertTrue(r.is_error)
        self.assertEqual(r.to_text(), "bad")


class TestBaseTool(unittest.TestCase):
    def test_json_schema(self):
        s = EchoTool().to_json_schema()
        self.assertEqual(s["type"], "function")
        self.assertEqual(s["function"]["name"], "Echo")
        self.assertIn("text", s["function"]["parameters"]["properties"])

    def test_validate_missing_required(self):
        errs = WriteTool().validate({})
        self.assertTrue(any("file_path" in e for e in errs))

    def test_validate_ok(self):
        self.assertEqual(WriteTool().validate({"file_path": "a", "content": "b"}), [])


class TestRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        self.assertIs(reg.get_tool("Echo"), reg._tools["Echo"])
        self.assertIsNone(reg.get_tool("Nope"))

    def test_schemas_exclude_lazy(self):
        class Lazy(BaseTool):
            name = "LazyTool"
            description = "lazy"
            input_schema = {"type": "object", "properties": {}}
            lazy = True
            async def execute(self, params, context):
                return ToolResult()
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(Lazy())
        names = [s["function"]["name"] for s in reg.get_tool_schemas()]
        self.assertIn("Echo", names)
        self.assertNotIn("LazyTool", names)
        names2 = [s["function"]["name"] for s in reg.get_tool_schemas(include_lazy=True)]
        self.assertIn("LazyTool", names2)

    def test_search(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        hits = reg.search("echo")
        self.assertEqual([t.name for t in hits], ["Echo"])
        self.assertEqual(reg.search("nonexistentzzz"), [])


if __name__ == "__main__":
    unittest.main()
