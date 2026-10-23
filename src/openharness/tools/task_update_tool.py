"""TaskUpdate tool — 更新后台任务。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class TaskUpdateTool(BaseTool):
    name = "TaskUpdate"
    description = "Update a task's description or mark it done."
    input_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "running", "finished", "failed"]},
        },
        "required": ["task_id"],
    }

    async def execute(self, params, context):
        task = context.tasks.get(params["task_id"])
        if not task:
            return ToolResult(error=f"No such task: {params['task_id']}")
        task = context.tasks.update(
            params["task_id"],
            status=params.get("status"),
            description=params.get("description"),
        )
        return ToolResult(output=f"Updated {task.task_id}: {task.description} [{task.status}]")
