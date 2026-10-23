"""MCPTool — 调用已连接 MCP server 暴露的工具（第 10 章）。"""
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
