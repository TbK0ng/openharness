"""ExitWorktree tool — 退出隔离工作区，返回主工作区。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class ExitWorktreeTool(BaseTool):
    name = "ExitWorktree"
    description = ("Leave the current worktree and return to the main workspace. "
                   "Discards worktree changes (the worktree directory is kept).")
    input_schema = {"type": "object", "properties": {}}
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        prev = getattr(context, "_worktree_prev_cwd", None)
        if prev is None:
            return ToolResult(error="Not currently inside a worktree.")
        context.cwd = prev
        context._worktree_prev_cwd = None
        context.display(f"🌱 退出 worktree，回到 {context.cwd}")
        return ToolResult(output="Exited worktree and returned to the main workspace.")
