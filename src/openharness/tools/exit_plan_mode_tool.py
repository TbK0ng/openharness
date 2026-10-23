"""ExitPlanMode tool — 退出 plan 模式，恢复 default。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class ExitPlanModeTool(BaseTool):
    name = "ExitPlanMode"
    description = ("Leave plan mode and restore the previous (default) permission mode.")
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        context.mode = "default"
        context.permissions.set_mode("default")
        context.display("🧭 退出 plan 模式（恢复 default）")
        return ToolResult(output="Exited plan mode. Default permissions restored.")
