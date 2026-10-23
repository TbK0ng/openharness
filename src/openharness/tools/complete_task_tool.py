"""CompleteTask tool — 任务看板：完成任务并解除依赖（s12）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..tasks.board import TaskNotFoundError, board_for


class CompleteTaskTool(BaseTool):
    name = "CompleteTask"
    description = "Mark a task completed. Unblocks any task that depended on it."
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}},
                   "required": ["id"]}
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        board = board_for(context)
        try:
            t = board.complete(params.get("id", ""))
        except TaskNotFoundError:
            return ToolResult(output=f"No such task: {params.get('id', '')}")
        return ToolResult(output=f"Completed {t['id']}")
