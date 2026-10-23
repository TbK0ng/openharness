"""ClaimTask tool — 任务看板：认领任务（s12）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..tasks.board import TaskBlockedError, TaskNotFoundError, board_for


class ClaimTaskTool(BaseTool):
    name = "ClaimTask"
    description = ("Mark a task in_progress. Fails if any of its blocked_by tasks is "
                   "still unfinished.")
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}},
                   "required": ["id"]}
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        board = board_for(context)
        try:
            t = board.claim(params.get("id", ""))
        except TaskNotFoundError:
            return ToolResult(output=f"No such task: {params.get('id', '')}")
        except TaskBlockedError as e:
            return ToolResult(output=f"Cannot claim: {e}")
        return ToolResult(output=f"Claimed {t['id']} (now in_progress)")
