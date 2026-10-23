"""TaskStop tool — 停止运行中的后台任务。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class TaskStopTool(BaseTool):
    name = "TaskStop"
    description = "Stop a running background task."
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    async def execute(self, params, context):
        task = context.tasks.stop(params["task_id"])
        if not task:
            return ToolResult(error=f"No such task: {params['task_id']}")
        return ToolResult(output=f"Stopped {task.task_id}.")
