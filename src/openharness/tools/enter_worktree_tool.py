"""EnterWorktree tool — 创建并进入隔离工作区（第 5 章）。"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

from .base import BaseTool, ToolResult


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)


class EnterWorktreeTool(BaseTool):
    name = "EnterWorktree"
    description = ("Create and enter an isolated worktree (a scratch copy of the workspace) "
                   "named `name`. Changes there don't affect the main workspace until you merge.")
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        name = params["name"]
        base = pathlib.Path(context.cwd)
        from ..config.paths import oh_dir
        wt_root = (pathlib.Path(context.oh_dir) if getattr(context, "oh_dir", None)
                   else oh_dir(base)) / "worktrees"
        wt = wt_root / name
        if wt.exists():
            # 已存在，直接切换
            prev = getattr(context, "_worktree_prev_cwd", None)
            if prev is None:
                context._worktree_prev_cwd = str(base)
            context.cwd = str(wt)
            context.display(f"🌱 进入已有 worktree: {wt.name}")
            return ToolResult(output=f"Entered existing worktree '{name}'.")
        wt_root.mkdir(parents=True, exist_ok=True)
        # 尝试 git worktree
        is_git = (base / ".git").exists()
        if is_git:
            r = _run(["git", "worktree", "add", str(wt), "-b", f"worktree-{name}"], str(base))
            if r.returncode != 0:
                # 回退：复制
                shutil.copytree(base, wt, ignore=shutil.ignore_patterns(".git", ".oh", ".openharness_worktrees"))
        else:
            shutil.copytree(base, wt, ignore=shutil.ignore_patterns(".git", ".oh", ".openharness_worktrees"))
        prev = getattr(context, "_worktree_prev_cwd", None)
        if prev is None:
            context._worktree_prev_cwd = str(base)
        context.cwd = str(wt)
        context.display(f"🌱 创建并进入 worktree: {wt.name}")
        return ToolResult(output=f"Created and entered worktree '{name}'.")
