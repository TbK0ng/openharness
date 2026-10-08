"""Write 工具 — 创建/覆盖文件。"""
from __future__ import annotations

from ..tools.base import BaseTool, ToolResult


class WriteTool(BaseTool):
    name = "Write"
    description = "Create a new file or overwrite an existing file with the given content. Parent directories are created automatically."
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file."},
            "content": {"type": "string", "description": "Full content to write."},
        },
        "required": ["file_path", "content"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        import pathlib
        cwd = pathlib.Path(context.cwd)
        p = pathlib.Path(params["file_path"])
        if not p.is_absolute():
            p = cwd / p
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(params["content"], encoding="utf-8")
        except Exception as e:
            return ToolResult(error=f"Cannot write {p}: {e}")
        return ToolResult(output=f"Wrote {len(params['content'])} characters to {p}")
