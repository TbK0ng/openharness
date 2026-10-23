"""TaskGet tool — 读取后台任务状态与输出。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class TaskGetTool(BaseTool):
    name = "TaskGet"
    description = "Read a background task's status and output."
    input_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }
    read_only = True

    async def execute(self, params, context):
        task = context.tasks.get(params["task_id"])
        if not task:
            return ToolResult(error=f"No such task: {params['task_id']}")
        out = (task.output or "")[-4000:]
        return ToolResult(output=f"[{task.task_id}] status={task.status}\noutput:\n{out}")
