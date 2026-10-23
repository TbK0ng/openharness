"""CronDelete tool — 按 job_id 删除定时任务。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class CronDeleteTool(BaseTool):
    name = "CronDelete"
    description = "Delete a scheduled cron job by job_id."
    input_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Id of the cron job to delete."},
        },
        "required": ["job_id"],
    }

    async def execute(self, params, context):
        mgr = context.cron
        if mgr is None:
            return ToolResult(error="cron subsystem not available")
        ok = mgr.delete(params.get("job_id", ""))
        return ToolResult(output=f"Deleted {params.get('job_id')}." if ok else f"Job {params.get('job_id')} not found.")
