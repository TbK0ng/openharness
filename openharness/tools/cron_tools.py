"""定时任务工具 — CronCreate/CronList/CronDelete（第 5 章调度类）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class CronCreateTool(BaseTool):
    name = "CronCreate"
    description = (
        "Schedule a recurring job. schedule = 5-field cron expression, "
        "kind = 'command' or 'agent', prompt/command = what to run."
    )

    async def execute(self, params, context):
        mgr = context.cron
        if mgr is None:
            return ToolResult(error="cron subsystem not available")
        task = mgr.create(
            schedule=params.get("schedule", ""),
            kind=params.get("kind", "command"),
            command=params.get("command", ""),
            prompt=params.get("prompt", ""),
        )
        return ToolResult(output=f"Created cron job {task.job_id}: {task}")


class CronListTool(BaseTool):
    name = "CronList"
    description = "List all scheduled cron jobs."

    async def execute(self, params, context):
        mgr = context.cron
        if mgr is None:
            return ToolResult(error="cron subsystem not available")
        jobs = mgr.list()
        if not jobs:
            return ToolResult(output="No cron jobs scheduled.")
        return ToolResult(output="\n".join(str(j) for j in jobs))


class CronDeleteTool(BaseTool):
    name = "CronDelete"
    description = "Delete a scheduled cron job by job_id."

    async def execute(self, params, context):
        mgr = context.cron
        if mgr is None:
            return ToolResult(error="cron subsystem not available")
        ok = mgr.delete(params.get("job_id", ""))
        return ToolResult(output=f"Deleted {params.get('job_id')}." if ok else f"Job {params.get('job_id')} not found.")
