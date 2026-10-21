"""动态 MCP 工具 — 把已连接 MCP server 的每个 tool 包装成原生工具（第 10 章）。

MCPTool 只能逐个手写 server/tool 名去调用；这里在 Engine 启动时把
`tools/list` 的结果动态注册进 ToolRegistry，模型即可像调用内置工具一样
直接使用 MCP 工具。
"""
from __future__ import annotations

import re

from .base import BaseTool, ToolResult


def _safe_name(server: str, tool: str) -> str:
    """OpenAI function 名只允许 [a-zA-Z0-9_-]，且需可读：mcp__<server>__<tool>。"""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{server}__{tool}")
    return f"mcp__{clean}"[:64]


def make_mcp_tool(server_name: str, tool_spec: dict, manager) -> BaseTool:
    """为一个 MCP tool 生成 BaseTool 实例。"""
    remote_name = tool_spec.get("name", "")
    schema = tool_spec.get("inputSchema") or {"type": "object", "properties": {}}
    if not isinstance(schema, dict) or schema.get("type") != "object":
        schema = {"type": "object", "properties": {}}
    description = tool_spec.get("description") or f"MCP tool '{remote_name}' from '{server_name}'."

    class _DynamicMCPTool(BaseTool):
        name = _safe_name(server_name, remote_name)
        input_schema = schema
        read_only = False          # MCP 工具可写，交给权限系统判定

        async def execute(self, params, context):
            try:
                return ToolResult(output=manager.call(server_name, remote_name, params))
            except Exception as exc:  # noqa: BLE001 — 统一转为工具错误
                return ToolResult(error=f"MCP call failed ({server_name}/{remote_name}): {exc}")

    _DynamicMCPTool.description = description
    return _DynamicMCPTool()


def mcp_tools_for(manager) -> list[BaseTool]:
    """为所有已连接 server 的全部 tool 生成工具实例。"""
    out = []
    for entry in manager.all_tools():
        server_name = entry.get("server", "")
        spec = {k: v for k, v in entry.items() if k != "server"}
        if not spec.get("name"):
            continue
        out.append(make_mcp_tool(server_name, spec, manager))
    return out
