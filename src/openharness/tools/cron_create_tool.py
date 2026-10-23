"""CronCreate tool — 创建定时任务（第 5 章调度类）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class CronCreateTool(BaseTool):
    name = "CronCreate"
    description = (
        "Schedule a recurring job. schedule = 5-field cron expression, "
        "kind = 'command' or 'agent', prompt/command = what to run."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "schedule": {"type": "string",
                         "description": "5-field cron expression, e.g. '*/5 * * * *'."},
            "kind": {"type": "string", "enum": ["command", "agent"],
                     "description": "What to run when the job fires."},
            "command": {"type": "string",
                        "description": "Shell command to run (when kind='command')."},
            "prompt": {"type": "string",
                       "description": "Prompt for the sub-agent (when kind='agent')."},
        },
        "required": ["schedule", "kind"],
    }

    async def execute(self, params, context):
        mgr = context.cron
        if mgr is None:
            return ToolResult(error="cron subsystem not available")
        try:
            task = mgr.create(
                schedule=params.get("schedule", ""),
                kind=params.get("kind", "command"),
                command=params.get("command", ""),
                prompt=params.get("prompt", ""),
            )
        except ValueError as exc:
            return ToolResult(error=str(exc))
        mgr.start()   # 保证即使不在 CLI 主循环里也能触发
        context.display(f"⏰ 定时任务已创建: {task.job_id}")
        return ToolResult(output=f"Created cron job {task.job_id}: {task} "
                                 "(scheduler running)")
