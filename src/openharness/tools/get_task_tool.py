"""GetTask tool — 任务看板：按 id 查询任务（s12）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..tasks.board import TaskNotFoundError, board_for


class GetTaskTool(BaseTool):
    name = "GetTask"
    description = "Fetch one task by id."
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}},
                   "required": ["id"]}
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        board = board_for(context)
        try:
            t = board.get(params.get("id", ""))
        except TaskNotFoundError:
            return ToolResult(output=f"No such task: {params.get('id', '')}")
        return ToolResult(output=(f"{t['id']}: {t['subject']}\n"
                                  f"status={t['status']} blockedBy={t['blockedBy']}"))
