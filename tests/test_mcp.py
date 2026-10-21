"""Test mcp/client.py stdio JSON-RPC client (ch.10 MCP subsystem).

Drives a real subprocess stub (tests/mcp_stub_server.py) through the full
handshake, so the protocol path is exercised rather than mocked. The subsystem
previously had no tests at all.
"""
import sys
import unittest
from pathlib import Path

from openharness.mcp.client import MCPClientManager, MCPError, MCPServer

STUB = str(Path(__file__).resolve().parent / "mcp_stub_server.py")


def _spec() -> dict:
    return {"command": sys.executable, "args": [STUB]}


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


if __name__ == "__main__":
    unittest.main()
