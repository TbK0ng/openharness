"""EnterPlanMode / ExitPlanMode — 切换权限模式（第 6 章 plan 模式）。"""
from __future__ import annotations

from ..tools.base import BaseTool, ToolResult


class EnterPlanModeTool(BaseTool):
    name = "EnterPlanMode"
    description = ("Switch the session into plan mode: only read-only operations are allowed. "
                   "Good for exploring and designing before making changes.")
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        context.mode = "plan"
        context.permissions.set_mode("plan")
        context.display("🧭 进入 plan 模式（只读）")
        return ToolResult(output="Entered plan mode. Only read-only tools are permitted now.")


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
