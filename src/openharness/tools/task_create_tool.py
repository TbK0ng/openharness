"""TaskCreate tool — 启动后台任务（s13）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class TaskCreateTool(BaseTool):
    name = "TaskCreate"
    description = (
        "Start a background task. kind='command' runs a shell command; "
        "kind='agent' runs a general-purpose sub-agent on a prompt. "
        "Returns the task id; use TaskGet to read output."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["command", "agent"]},
            "command": {"type": "string", "description": "Shell command (kind=command)"},
            "prompt": {"type": "string", "description": "Task for the agent (kind=agent)"},
            "description": {"type": "string"},
        },
        "required": ["kind"],
    }

    async def execute(self, params, context):
        mgr = context.tasks
        if not mgr:
            return ToolResult(error="TaskManager not available.")
        kind = params.get("kind", "command")
        desc = params.get("description", f"{kind} task")
        if kind == "command":
            cmd = params.get("command", "")
            if not cmd:
                return ToolResult(error="command is required for kind=command.")
            task = mgr.create_command(desc, cmd)
        else:
            prompt = params.get("prompt", "")
            if not prompt:
                return ToolResult(error="prompt is required for kind=agent.")
            task = mgr.create_agent(context, desc, prompt)
        return ToolResult(output=f"Started task {task.task_id} ({task.kind}): {task.description}")
