"""Test plugins/registry.py + Engine plugin wiring (ch.3 Plugins subsystem).

Regression coverage for a silent failure: PluginContext's list fields defaulted
to None and register_* appended to a throwaway list, so every plugin tool,
command and skill was discarded without error.
"""
import tempfile
import textwrap
import unittest
from pathlib import Path

from openharness.engine.query_engine import Engine
from openharness.plugins.registry import PluginContext, PluginRegistry


PLUGIN_SOURCE = textwrap.dedent(
    '''
    from openharness.tools.base import BaseTool, ToolResult

    PLUGIN = {"name": "demo", "description": "demo plugin"}


    class DemoTool(BaseTool):
        name = "DemoTool"
        description = "Demo tool from a plugin."
        input_schema = {"type": "object", "properties": {}}
        read_only = True

        async def execute(self, params, context):
            return ToolResult(output="demo")


    def register(ctx):
        ctx.register_tool(DemoTool())
        ctx.register_command("demo", "demo command", lambda args: "ok")
        ctx.register_skill("demo-skill", "# Demo Skill\\n\\nBody.")
    '''
)


class TestPluginContext(unittest.TestCase):
    def test_lists_start_empty_not_none(self):
        ctx = PluginContext()
        self.assertEqual(ctx.tools, [])
        self.assertEqual(ctx.commands, [])
        self.assertEqual(ctx.skills, [])

    def test_register_accumulates(self):
        ctx = PluginContext()
        tool = object()
        ctx.register_tool(tool)
        ctx.register_command("c", "help", lambda a: "x")
        ctx.register_skill("s", "# S\\nbody")

        self.assertEqual(ctx.tools, [tool])
        self.assertEqual(len(ctx.commands), 1)
        self.assertEqual(ctx.commands[0][0], "c")
        self.assertEqual(ctx.commands[0][1], "help")
        self.assertEqual(ctx.skills, [("s", "# S\\nbody")])

    def test_registrations_do_not_leak_between_contexts(self):
        first, second = PluginContext(), PluginContext()
        first.register_tool(object())
        self.assertEqual(second.tools, [])


class TestPluginLoadDir(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (self.dir / "demo.py").write_text(PLUGIN_SOURCE, encoding="utf-8")

    def test_load_dir_collects_tool_command_skill(self):
        registry = PluginRegistry()
        ctx = PluginContext()

        loaded = registry.load_dir(self.dir, ctx)

        self.assertEqual(loaded, ["demo"])
        self.assertEqual([t.name for t in ctx.tools], ["DemoTool"])
        self.assertEqual(ctx.commands[0][0], "demo")
        self.assertEqual(ctx.skills[0][0], "demo-skill")

    def test_broken_plugin_is_reported_not_raised(self):
        (self.dir / "broken.py").write_text("raise RuntimeError('nope')", encoding="utf-8")
        registry = PluginRegistry()
        ctx = PluginContext()

        loaded = registry.load_dir(self.dir, ctx)

        self.assertIn("broken", registry.plugins)
        self.assertIn("nope", registry.plugins["broken"]["error"])


class TestEnginePluginWiring(unittest.TestCase):
    def test_plugin_tool_command_skill_reach_engine(self):
        cwd = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (cwd / "plugins").mkdir()
        (cwd / "plugins" / "demo.py").write_text(PLUGIN_SOURCE, encoding="utf-8")

        engine = Engine(cwd=str(cwd))

        self.assertEqual(engine.plugin_names, ["demo"])
        # tool registered in the live registry
        self.assertIsNotNone(engine.registry.get_tool("DemoTool"))
        # command registered with help text (previously raised on a 3-tuple unpack)
        command = engine.commands.get("demo")
        self.assertIsNotNone(command)
        self.assertEqual(command.help_text, "demo command")
        self.assertEqual(command.fn(""), "ok")
        # skill registered into the loader
        content = engine.skills.get("demo-skill")
        self.assertIsNotNone(content)
        self.assertIn("Body.", content)


if __name__ == "__main__":
    unittest.main()
