"""CreateTask tool — 任务看板：新建任务（s12）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..tasks.board import board_for


class CreateTaskTool(BaseTool):
    name = "CreateTask"
    description = ("Add a task to the board. `blocked_by` lists task ids that must be "
                   "completed before this one can be claimed.")
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "blocked_by": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        board = board_for(context)
        task = board.create(params.get("subject", ""), params.get("description", ""),
                            params.get("blocked_by"))
        return ToolResult(output=f"Created task {task['id']}: {task['subject']}")
