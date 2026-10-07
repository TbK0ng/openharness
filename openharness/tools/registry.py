"""工具注册表 — 对应教程第 5 章 `openharness/tools/registry.py`。

注册表模式：内置工具、MCP 动态工具、插件工具统一注册、统一发现。
"""
from __future__ import annotations

from typing import List, Optional

from .base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_tool_schemas(self, include_lazy: bool = False) -> list[dict]:
        """生成发给 LLM 的 tools 参数（OpenAI function 格式）。"""
        return [
            t.to_json_schema()
            for t in self._tools.values()
            if include_lazy or not t.lazy
        ]

    def search(self, query: str) -> list[BaseTool]:
        """ToolSearch 工具用：按关键词在（含延迟工具的）全部工具中检索。"""
        q = query.lower().split()
        out = []
        for t in self._tools.values():
            hay = f"{t.name} {t.description}".lower()
            if all(part in hay for part in q if part):
                out.append(t)
        return out
