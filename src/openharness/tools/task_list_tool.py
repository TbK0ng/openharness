"""TaskList tool — 列出全部后台任务。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class TaskListTool(BaseTool):
    name = "TaskList"
    description = "List all background tasks with status."
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context):
        tasks = context.tasks.list()
        if not tasks:
            return ToolResult(output="No tasks.")
        lines = [f"{t.task_id} [{t.status}] {t.kind}: {t.description}" for t in tasks]
        return ToolResult(output="\n".join(lines))
