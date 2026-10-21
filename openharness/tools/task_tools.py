"""后台任务工具 — TaskCreate/TaskGet/TaskList/TaskUpdate/TaskStop。"""
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
