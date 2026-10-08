"""ToolSearch 工具 — 检索（含延迟加载的）全部已注册工具。"""
from __future__ import annotations

from ..tools.base import BaseTool, ToolResult


class ToolSearchTool(BaseTool):
    name = "ToolSearch"
    description = ("Search available tools (including deferred/lazy ones) by keyword. "
                   "Returns matching tool names with short descriptions.")
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        hits = context.registry.search(params["query"])
        if not hits:
            return ToolResult(output=f"No tools matching '{params['query']}'.")
        lines = [f"- {t.name}: {t.description}" for t in hits[:20]]
        return ToolResult(output="\n".join(lines))
