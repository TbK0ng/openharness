"""任务看板工具 — 第 12 章（s12）：CreateTask / ListTasks / GetTask / ClaimTask / CompleteTask。

这些工具操作 TaskBoard（cwd/.tasks/*.json）。与 background tasks（s13，
manager.py）不同：这里有显式 blockedBy 依赖图，claim 前必须解除阻塞。
"""
from __future__ import annotations

import pathlib

from ..tools.base import BaseTool, ToolResult
from ..tasks.board import TaskBoard, TaskBlockedError, TaskNotFoundError

def _board(context) -> TaskBoard:
    """从配置目录 .oh/ 构造（或复用）任务板。

    优先用 Engine 提供的 oh_dir；直接构造 Context 的场合回退到 cwd/.oh。
    """
    from ..paths import oh_dir

    base = getattr(context, "oh_dir", None) or oh_dir(context.cwd)
    board = getattr(context, "task_board", None)
    if board is None or str(board.root) != str(base):
        board = TaskBoard(base)
        context.task_board = board
    return board


class CreateTaskTool(BaseTool):
    name = "CreateTask"
    description = ("Add a task to the board. `blocked_by` lists task ids that must be "
                   "completed before this one can be claimed.")
    input_schema = {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "blocked_by": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        board = _board(context)
        task = board.create(params.get("subject", ""), params.get("description", ""),
                            params.get("blocked_by"))
        return ToolResult(output=f"Created task {task['id']}: {task['subject']}")


class ListTasksTool(BaseTool):
    name = "ListTasks"
    description = "Show all tasks on the board with their status and blockers."
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        board = _board(context)
        tasks = board.list()
        if not tasks:
            return ToolResult(output="No tasks yet.")
        lines = []
        for t in tasks:
            dep = f" (blocked by {', '.join(t['blockedBy'])})" if t["blockedBy"] else ""
            lines.append(f"[{t['status']}] {t['id']}: {t['subject']}{dep}")
        return ToolResult(output="\n".join(lines))


class GetTaskTool(BaseTool):
    name = "GetTask"
    description = "Fetch one task by id."
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}},
                   "required": ["id"]}
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        board = _board(context)
        try:
            t = board.get(params.get("id", ""))
        except TaskNotFoundError:
            return ToolResult(output=f"No such task: {params.get("id", "")}")
        return ToolResult(output=(f"{t['id']}: {t['subject']}\n"
                                  f"status={t['status']} blockedBy={t['blockedBy']}"))


class ClaimTaskTool(BaseTool):
    name = "ClaimTask"
    description = ("Mark a task in_progress. Fails if any of its blocked_by tasks is "
                   "still unfinished.")
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}},
                   "required": ["id"]}
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        board = _board(context)
        try:
            t = board.claim(params.get("id", ""))
        except TaskNotFoundError:
            return ToolResult(output=f"No such task: {params.get("id", "")}")
        except TaskBlockedError as e:
            return ToolResult(output=f"Cannot claim: {e}")
        return ToolResult(output=f"Claimed {t['id']} (now in_progress)")


class CompleteTaskTool(BaseTool):
    name = "CompleteTask"
    description = "Mark a task completed. Unblocks any task that depended on it."
    input_schema = {"type": "object", "properties": {"id": {"type": "string"}},
                   "required": ["id"]}
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        board = _board(context)
        try:
            t = board.complete(params.get("id", ""))
        except TaskNotFoundError:
            return ToolResult(output=f"No such task: {params.get("id", "")}")
        return ToolResult(output=f"Completed {t['id']}")
