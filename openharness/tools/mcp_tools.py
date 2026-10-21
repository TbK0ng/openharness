"""MCP 工具 — MCPTool / ListMcpResources / ReadMcpResource（第 10 章）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class MCPTool(BaseTool):
    name = "MCPTool"
    description = (
        "Call a tool exposed by a connected MCP server. "
        "server = server name, tool = tool name (see engine startup report), "
        "arguments = JSON object of tool parameters."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "tool": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["server", "tool"],
    }

    async def execute(self, params, context):
        mgr = context.mcp
        if not mgr:
            return ToolResult(error="MCP manager not available.")
        server = mgr.server(params["server"])
        if not server:
            return ToolResult(error=f"Unknown MCP server '{params['server']}'.")
        try:
            result = server.call_tool(params["tool"], params.get("arguments") or {})
            return ToolResult(output=str(result))
        except Exception as e:
            return ToolResult(error=f"MCP call failed: {e}")


class ListMcpResourcesTool(BaseTool):
    name = "ListMcpResources"
    description = "List resources exposed by all connected MCP servers."
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context):
        mgr = context.mcp
        if not mgr:
            return ToolResult(output="No MCP servers connected.")
        lines = []
        for name, server in mgr.servers.items():
            try:
                for r in server.list_resources():
                    lines.append(f"- [{name}] {r.get('uri', '?')}: {r.get('name', '')}")
            except Exception as e:
                lines.append(f"- [{name}] error: {e}")
        return ToolResult(output="\n".join(lines) if lines else "No resources exposed.")


class ReadMcpResourceTool(BaseTool):
    name = "ReadMcpResource"
    description = "Read a resource from an MCP server by server name and resource URI."
    input_schema = {
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "uri": {"type": "string"},
        },
        "required": ["server", "uri"],
    }
    read_only = True

    async def execute(self, params, context):
        mgr = context.mcp
        server = mgr.server(params["server"]) if mgr else None
        if not server:
            return ToolResult(error=f"Unknown MCP server '{params['server']}'.")
        try:
            return ToolResult(output=server.read_resource(params["uri"]))
        except Exception as e:
            return ToolResult(error=f"Read failed: {e}")
