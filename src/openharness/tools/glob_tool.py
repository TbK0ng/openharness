"""Glob 工具 — 按文件名模式搜索文件（只读）。"""
from __future__ import annotations

import pathlib
import re

from .base import BaseTool, ToolResult


class GlobTool(BaseTool):
    name = "Glob"
    description = ("Find files by glob pattern (e.g. '**/*.py', 'src/*.txt'). "
                   "Returns matching paths relative to the search dir.")
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'."},
            "path": {"type": "string", "description": "Directory to search (default: workspace root)."},
        },
        "required": ["pattern"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        cwd = pathlib.Path(context.cwd)
        base = pathlib.Path(params.get("path", ""))
        if not base.is_absolute():
            base = cwd / base
        if not base.exists():
            return ToolResult(error=f"Directory not found: {base}")
        if not base.is_dir():
            base = base.parent
        pattern = params["pattern"]
        rx = compile_glob(pattern)
        if rx is None:
            return ToolResult(error=f"Invalid glob pattern: {pattern}")
        results = []
        for rel in walk_files(base):
            if rx.fullmatch(rel):
                results.append(rel)
        results.sort()
        if not results:
            return ToolResult(output="No files matched.")
        shown = results[:500]
        footer = f"\n[{len(results)} matches" + (", showing first 500]" if len(results) > 500 else "]")
        return ToolResult(output="\n".join(shown) + footer)


def compile_glob(pattern: str):
    """glob -> regex。支持 * ? 和 **。"""
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
            continue
        ch = pattern[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    try:
        return re.compile("".join(out))
    except re.error:
        return None


def walk_files(base):
    """产出 base 下所有文件（相对 posix 路径），跳过隐藏目录。"""
    stack = [base]
    while stack:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if entry.is_dir():
                if not entry.name.startswith("."):
                    stack.append(entry)
            elif entry.is_file():
                yield entry.relative_to(base).as_posix()
