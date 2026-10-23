"""ListMcpResources — 列出 MCP server 的资源。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


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
