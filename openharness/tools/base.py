"""工具基类 — 对应教程第 5 章 `openharness/tools/base.py`。

BaseTool(ABC) 是所有内置工具、MCP 工具、插件工具的父类。
每个工具 = name + description + input_schema + execute()。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional


@dataclass
class ToolResult:
    """工具执行结果（观察值 Observation，回传给 LLM）。"""
    output: str = ""
    error: Optional[str] = None
    data: Any = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_text(self) -> str:
        return self.error if self.error is not None else self.output


class BaseTool(abc.ABC):
    """所有工具的抽象基类（教程第 5 章的代码模式）。"""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    input_schema: ClassVar[dict] = {}
    # 权限系统（第 6 章）：只读工具在 default 模式下免审批
    read_only: ClassVar[bool] = False
    # 第 5 章 ToolSearch：延迟加载工具默认不进 prompt，靠 ToolSearch 发现
    lazy: ClassVar[bool] = False

    def get_input_schema(self) -> dict:
        return self.input_schema

    def to_json_schema(self) -> dict:
        """OpenAI function calling 格式（127.0.0.1:1234 端点支持）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_input_schema(),
            },
        }

    @abc.abstractmethod
    async def execute(self, params: dict, context) -> ToolResult:
        """执行工具。params 已通过 JSON schema 校验。context 是 Engine 上下文。"""

    def validate(self, params: dict) -> list[str]:
        """轻量必填校验，返回错误列表。"""
        errors = []
        props = self.input_schema.get("properties", {})
        for req in self.input_schema.get("required", []):
            if req not in params or params[req] in (None, ""):
                errors.append(f"missing required parameter: {req}")
                continue
            schema = props.get(req, {})
            expected = schema.get("type")
            if expected and expected != "array" and isinstance(params[req], (list, dict)):
                errors.append(f"parameter {req} must be {expected}")
            elif expected == "array" and not isinstance(params[req], list):
                errors.append(f"parameter {req} must be array")
        return errors
