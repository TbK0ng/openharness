"""Read 工具 — 读取文本文件（支持 offset/limit，返回行号前缀）。"""
from __future__ import annotations

from ..tools.base import BaseTool, ToolResult


class ReadTool(BaseTool):
    name = "Read"
    description = ("Read a text file from the workspace. Returns numbered lines. "
                   "Use offset (1-based line) and limit to page through large files.")
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file (absolute or workspace-relative)."},
            "offset": {"type": "integer", "description": "First line to return (1-based, default 1)."},
            "limit": {"type": "integer", "description": "Max lines to return (default 2000)."},
        },
        "required": ["file_path"],
    }

    async def execute(self, params, context) -> ToolResult:
        import pathlib
        cwd = pathlib.Path(context.cwd)
        p = pathlib.Path(params["file_path"])
        if not p.is_absolute():
            p = cwd / p
        if not p.exists():
            return ToolResult(error=f"File not found: {p}")
        if not p.is_file():
            return ToolResult(error=f"Not a file: {p}")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(error=f"Cannot read {p}: {e}")
        lines = text.splitlines()
        offset = int(params.get("offset", 1))
        limit = int(params.get("limit", 2000))
        chunk = lines[offset - 1: offset - 1 + limit]
        if not chunk:
            return ToolResult(output="(empty file or offset past end)")
        numbered = [f"{offset + i:5d}\t{ln}" for i, ln in enumerate(chunk)]
        total = len(lines)
        shown_end = offset - 1 + len(chunk)
        footer = f"\n[lines {offset}-{shown_end} of {total}]"
        return ToolResult(output="\n".join(numbered) + footer)
