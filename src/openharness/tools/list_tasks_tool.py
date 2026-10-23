"""ListTasks tool — 任务看板：列出任务及其阻塞关系（s12）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..tasks.board import board_for


class ListTasksTool(BaseTool):
    name = "ListTasks"
    description = "Show all tasks on the board with their status and blockers."
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        board = board_for(context)
        tasks = board.list()
        if not tasks:
            return ToolResult(output="No tasks yet.")
        lines = []
        for t in tasks:
            dep = f" (blocked by {', '.join(t['blockedBy'])})" if t["blockedBy"] else ""
            lines.append(f"[{t['status']}] {t['id']}: {t['subject']}{dep}")
        return ToolResult(output="\n".join(lines))
