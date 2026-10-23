"""NotebookEdit 工具 — 编辑 Jupyter notebook 的 cell。"""
from __future__ import annotations

import json
import pathlib

from .base import BaseTool, ToolResult


class NotebookEditTool(BaseTool):
    name = "NotebookEdit"
    description = ("Edit a cell in a Jupyter notebook (.ipynb). cell_id is the 0-based cell index. "
                   "new_source replaces the cell's source; leave empty to delete the cell.")
    input_schema = {
        "type": "object",
        "properties": {
            "notebook_path": {"type": "string", "description": "Path to the .ipynb file."},
            "cell_id": {"type": "integer", "description": "0-based index of the cell."},
            "new_source": {"type": "string", "description": "New source for the cell."},
        },
        "required": ["notebook_path", "cell_id"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        cwd = pathlib.Path(context.cwd)
        p = pathlib.Path(params["notebook_path"])
        if not p.is_absolute():
            p = cwd / p
        if not p.exists():
            return ToolResult(error=f"Notebook not found: {p}")
        try:
            nb = json.loads(p.read_text(encoding="utf-8"))
            cells = nb.get("cells", [])
            idx = int(params["cell_id"])
            if idx < 0 or idx >= len(cells):
                return ToolResult(error=f"cell_id {idx} out of range (0..{len(cells)-1})")
            new_source = params.get("new_source", "")
            if new_source == "":
                cells.pop(idx)
            else:
                cell = cells[idx]
                cell["source"] = new_source.splitlines(keepends=True)
                cell.pop("outputs", None)
                cell.pop("execution_count", None)
            p.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
            return ToolResult(output=f"Updated cell {idx} in {p.name}")
        except Exception as e:
            return ToolResult(error=f"Notebook edit failed: {e}")
