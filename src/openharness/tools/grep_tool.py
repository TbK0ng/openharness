"""Grep 工具 — 按正则搜索文件内容（教程：基于 ripgrep，此处含纯 Python 回退）。"""
from __future__ import annotations

import pathlib
import re
import shutil

from .base import BaseTool, ToolResult


class GrepTool(BaseTool):
    name = "Grep"
    description = ("Search file contents with a regex. Returns 'path:line: text' matches. "
                   "Use 'include' to restrict to a glob (e.g. '*.py').")
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for."},
            "path": {"type": "string", "description": "File or directory to search (default: workspace root)."},
            "include": {"type": "string", "description": "Glob filter for filenames, e.g. '*.py'."},
            "max_matches": {"type": "integer", "description": "Stop after N matches (default 250)."},
        },
        "required": ["pattern"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        cwd = pathlib.Path(context.cwd)
        target = pathlib.Path(params.get("path", ""))
        if not target.is_absolute():
            target = cwd / target
        if not target.exists():
            return ToolResult(error=f"Path not found: {target}")
        try:
            rx = re.compile(params["pattern"])
        except re.error as e:
            return ToolResult(error=f"Invalid regex: {e}")
        include = params.get("include", "")
        max_matches = int(params.get("max_matches", 250))

        if shutil.which("rg"):
            matches = _rg_search(target, rx, include, max_matches)
        else:
            matches = _py_search(target, rx, include, max_matches)

        if not matches:
            return ToolResult(output="No matches found.")
        return ToolResult(output="\n".join(matches))


def _rg_search(target, rx, include, max_matches):
    """用 ripgrep（若可用）。"""
    import subprocess
    args = ["rg", "--line-number", "--no-heading", "-e", rx.pattern]
    if include:
        args += ["--glob", include]
    args.append(str(target))
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
        lines = proc.stdout.splitlines()[:max_matches]
        return lines
    except Exception:
        return _py_search(target, rx, include, max_matches)


def _py_search(target, rx, include, max_matches):
    """纯 Python 回退。"""
    from .glob_tool import compile_glob
    files = []
    if target.is_file():
        files = [target]
    else:
        include_rx = compile_glob(include) if include else None
        for rel in walk_files(target):
            full = target / rel
            if include_rx is not None and not include_rx.fullmatch(rel.rsplit("/", 1)[-1] if "/" in rel else rel):
                continue
            files.append(full)
    matches = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if rx.search(line):
                        rel = f
                        matches.append(f"{rel}:{lineno}: {line.rstrip()[:300]}")
                        if len(matches) >= max_matches:
                            return matches
        except (PermissionError, OSError):
            continue
    return matches


def walk_files(base):
    from .glob_tool import walk_files as _wf
    return _wf(base)
