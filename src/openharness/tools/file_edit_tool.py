"""Edit 工具 — 精确替换文件中的字符串（要求唯一匹配）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class EditTool(BaseTool):
    name = "Edit"
    description = ("Replace an exact string in a file. old_string must match exactly once "
                   "(including whitespace/newlines); new_string replaces it.")
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file."},
            "old_string": {"type": "string", "description": "Exact text to find (must be unique)."},
            "new_string": {"type": "string", "description": "Replacement text (empty deletes)."},
        },
        "required": ["file_path", "old_string", "new_string"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        import pathlib
        cwd = pathlib.Path(context.cwd)
        p = pathlib.Path(params["file_path"])
        if not p.is_absolute():
            p = cwd / p
        if not p.is_file():
            return ToolResult(error=f"File not found: {p}")
        text = p.read_text(encoding="utf-8", errors="replace")
        old, new = params["old_string"], params["new_string"]
        count = text.count(old)
        if count == 0:
            return ToolResult(error=f"old_string not found in {p.name}. Read the file to get exact text.")
        if count > 1:
            return ToolResult(error=f"old_string matches {count} times in {p.name}; provide a longer unique string.")
        p.write_text(text.replace(old, new), encoding="utf-8")
        return ToolResult(output=f"Edited {p.name} (1 replacement)")
