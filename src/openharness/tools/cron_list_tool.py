"""CronList tool — 列出全部定时任务。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class CronListTool(BaseTool):
    name = "CronList"
    description = "List all scheduled cron jobs."
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context):
        mgr = context.cron
        if mgr is None:
            return ToolResult(error="cron subsystem not available")
        jobs = mgr.list()
        if not jobs:
            return ToolResult(output="No cron jobs scheduled.")
        return ToolResult(output="\n".join(str(j) for j in jobs))
