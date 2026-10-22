"""Test mcp/client.py stdio JSON-RPC client (ch.10 MCP subsystem).

Drives a real subprocess stub (tests/mcp_stub_server.py) through the full
handshake, so the protocol path is exercised rather than mocked. The subsystem
previously had no tests at all.
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from openharness.engine.query_engine import Engine
from openharness.hooks.executor import execute_tool_with_hooks
from openharness.mcp.client import (
    MCPClientManager,
    MCPError,
    MCPServer,
    load_mcp_config,
)

STUB = str(Path(__file__).resolve().parent / "mcp_stub_server.py")


def _spec() -> dict:
    return {"command": sys.executable, "args": [STUB]}


class TestMcpConfigFile(unittest.TestCase):
    """MCP servers are configured in .oh/mcp.json (Claude Code layout)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        self.oh = self.dir / ".oh"
        self.oh.mkdir()

    def _write(self, payload):
        (self.oh / "mcp.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_mcp_servers_key(self):
        self._write({"mcpServers": {"a": _spec()}})
        self.assertEqual(load_mcp_config({}, self.oh), {"a": _spec()})

    def test_accepts_bare_mapping_shorthand(self):
        self._write({"a": _spec()})
        self.assertEqual(load_mcp_config({}, self.oh), {"a": _spec()})

    def test_missing_file_yields_empty(self):
        self.assertEqual(load_mcp_config({}, self.oh), {})

    def test_inline_settings_override_file(self):
        self._write({"mcpServers": {"a": _spec(), "b": _spec()}})
        merged = load_mcp_config({"mcp_servers": {"b": {"command": "other"}}}, self.oh)

        self.assertEqual(merged["b"], {"command": "other"})
        self.assertIn("a", merged)

    def test_corrupt_file_raises_mcp_error(self):
        (self.oh / "mcp.json").write_text("{nope", encoding="utf-8")
        with self.assertRaises(MCPError):
            load_mcp_config({}, self.oh)

    def test_engine_connects_from_oh_mcp_json(self):
        self._write({"mcpServers": {"stub": _spec()}})

        engine = Engine(cwd=str(self.dir))
        ctx = engine.create_context()

        self.assertIn("stub", engine.mcp_status)
        self.assertTrue(engine.mcp_status["stub"]["ok"])
        self.assertIn("mcp__stub__echo",
                      {t.name for t in engine.registry.list_tools()})
        engine.mcp.close_all()

    def test_engine_close_terminates_mcp_children(self):
        """Engine.close() 必须带走 MCP 子进程，否则退出后残留会撞锁。"""
        self._write({"mcpServers": {"stub": _spec()}})
        engine = Engine(cwd=str(self.dir))
        engine.ensure_mcp()
        procs = [s.proc for s in engine.mcp.servers.values()]
        self.assertTrue(procs, "stub server 应当已启动")

        engine.close()

        self.assertEqual(engine.mcp.servers, {})
        self.assertTrue(all(p.poll() is not None for p in procs),
                        "子进程应在 close() 后退出")

    def test_mcp_connection_is_lazy(self):
        self._write({"mcpServers": {"stub": _spec()}})

        engine = Engine(cwd=str(self.dir))

        self.assertFalse(engine._mcp_connected)
        self.assertEqual(engine.mcp.servers, {})
        engine.create_context()
        self.assertTrue(engine._mcp_connected)
        engine.mcp.close_all()

    def test_relative_command_resolves_against_project_root(self):
        # A relative `command` should resolve against the project root, so the
        # process launches (the stub is a plain script, so it starts and fails
        # the handshake — but the error must NOT be "file not found").
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        (bin_dir / "srv.py").write_text(Path(STUB).read_text(encoding="utf-8"),
                                        encoding="utf-8")
        self._write({"mcpServers": {"rel": {"command": "bin/srv.py"}}})

        manager = MCPClientManager({"mcp_servers": {}}, str(self.dir), oh_dir=self.oh)
        status = manager.connect_all()
        manager.close_all()

        self.assertIn("rel", status)
        error = status["rel"].get("error", "")
        self.assertNotIn("No such file", error)
        self.assertNotIn("WinError 2", error)


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer("stub", _spec(), str(Path.cwd()))
        self.server.start()

    def tearDown(self):
        self.server.close()

    def test_handshake_discovers_tools_and_resources(self):
        names = [t["name"] for t in self.server._tools]
        self.assertIn("echo", names)
        self.assertIn("fail", names)
        self.assertEqual([r["uri"] for r in self.server._resources], ["demo://greeting"])

    def test_call_tool_returns_text(self):
        self.assertEqual(self.server.call_tool("echo", {"text": "hi"}), "hi")

    def test_call_tool_error_is_surfaced(self):
        with self.assertRaises(MCPError) as ctx:
            self.server.call_tool("fail", {})
        self.assertIn("boom", str(ctx.exception))

    def test_read_resource_returns_text(self):
        self.assertIn("hello resource", self.server.read_resource("demo://greeting"))

    def test_unknown_method_raises_mcp_error(self):
        with self.assertRaises(MCPError):
            self.server._send("no/such/method", {})


class TestMCPClientManager(unittest.TestCase):
    def setUp(self):
        self.manager = MCPClientManager({"mcp_servers": {"stub": _spec()}}, str(Path.cwd()))
        self.status = self.manager.connect_all()

    def tearDown(self):
        self.manager.close_all()

    def test_connect_all_reports_ok_and_tools(self):
        self.assertTrue(self.status["stub"]["ok"])
        self.assertIn("echo", self.status["stub"]["tools"])

    def test_all_tools_is_namespaced_by_server(self):
        tools = self.manager.all_tools()
        self.assertTrue(tools)
        self.assertTrue(all(t["server"] == "stub" for t in tools))

    def test_call_routes_to_named_server(self):
        self.assertEqual(self.manager.call("stub", "echo", {"text": "routed"}), "routed")

    def test_call_unknown_server_raises(self):
        with self.assertRaises(MCPError):
            self.manager.call("nope", "echo", {})

    def test_close_all_clears_servers(self):
        self.manager.close_all()
        self.assertEqual(self.manager.servers, {})

    def test_bad_command_reports_failure_without_raising(self):
        manager = MCPClientManager(
            {"mcp_servers": {"bad": {"command": "definitely-not-a-real-binary-xyz"}}},
            str(Path.cwd()),
        )
        status = manager.connect_all()
        self.assertFalse(status["bad"]["ok"])
        self.assertIn("error", status["bad"])


class TestMcpTools(unittest.TestCase):
    """MCPTool/ListMcpResources/ReadMcpResource called the manager with methods
    that do not exist (get_server / servers()), so every one of them raised."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (self.dir / ".oh").mkdir(exist_ok=True)
        (self.dir / ".oh" / "settings.json").write_text(
            json.dumps({"mcp_servers": {"stub": _spec()}}), encoding="utf-8")
        self.engine = Engine(cwd=str(self.dir))
        self.ctx = self.engine.create_context()
        self.ctx.permissions.set_mode("full-auto")

    def tearDown(self):
        self.engine.mcp.close_all()

    def _run(self, name, args):
        return asyncio.run(execute_tool_with_hooks(
            self.ctx, {"name": name, "arguments": args}))

    def test_mcp_tool_calls_remote_tool(self):
        result = self._run("MCPTool", {"server": "stub", "tool": "echo",
                                       "arguments": {"text": "roundtrip"}})
        self.assertFalse(result.is_error)
        self.assertIn("roundtrip", result.output)

    def test_mcp_tool_unknown_server_is_clean_error(self):
        result = self._run("MCPTool", {"server": "nope", "tool": "echo"})
        self.assertTrue(result.is_error)
        self.assertIn("Unknown MCP server", result.error)

    def test_mcp_tool_remote_failure_is_surfaced(self):
        result = self._run("MCPTool", {"server": "stub", "tool": "fail"})
        self.assertTrue(result.is_error)
        self.assertIn("boom", result.error)

    def test_list_mcp_resources(self):
        result = self._run("ListMcpResources", {})
        self.assertFalse(result.is_error)
        self.assertIn("demo://greeting", result.output)

    def test_read_mcp_resource(self):
        result = self._run("ReadMcpResource",
                           {"server": "stub", "uri": "demo://greeting"})
        self.assertFalse(result.is_error)
        self.assertIn("hello resource", result.output)


class TestDynamicMcpTools(unittest.TestCase):
    """MCP tools should be exposed as first-class tools, not only via MCPTool."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="oh_test_"))
        (self.dir / ".oh").mkdir(exist_ok=True)
        (self.dir / ".oh" / "settings.json").write_text(
            json.dumps({"mcp_servers": {"stub": _spec()}}), encoding="utf-8")
        self.engine = Engine(cwd=str(self.dir))
        self.ctx = self.engine.create_context()
        self.ctx.permissions.set_mode("full-auto")

    def tearDown(self):
        self.engine.mcp.close_all()

    def test_discovered_tools_are_registered(self):
        names = {t.name for t in self.engine.registry.list_tools()}
        self.assertIn("mcp__stub__echo", names)

    def test_dynamic_tool_carries_remote_schema(self):
        tool = self.engine.registry.get_tool("mcp__stub__echo")
        self.assertEqual(tool.input_schema["properties"]["text"]["type"], "string")

    def test_dynamic_tool_executes_remotely(self):
        tool = self.engine.registry.get_tool("mcp__stub__echo")
        result = asyncio.run(tool.execute({"text": "native"}, self.ctx))
        self.assertFalse(result.is_error)
        self.assertEqual(result.output, "native")

    def test_dynamic_tools_appear_in_llm_schema(self):
        names = {s["function"]["name"] for s in self.engine.registry.get_tool_schemas()}
        self.assertIn("mcp__stub__echo", names)

    def test_dynamic_tool_name_is_sanitised(self):
        from openharness.tools.mcp_dynamic import _safe_name
        self.assertEqual(_safe_name("my server", "do.th!ng"), "mcp__my_server__do_th_ng")


if __name__ == "__main__":
    unittest.main()
