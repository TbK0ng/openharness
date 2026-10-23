"""ReadMcpResource — 按 URI 读取 MCP 资源。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


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
