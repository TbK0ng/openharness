"""MemoryDelete tool — 删除长期记忆及其索引项。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class MemoryDeleteTool(BaseTool):
    name = "MemoryDelete"
    description = "Delete a persistent memory by name (removes its file and index line)."
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Memory name to delete."},
        },
        "required": ["name"],
    }
    read_only = False

    async def execute(self, params, context):
        if getattr(context, "memory", None) is None:
            return ToolResult(error="memory subsystem not available")
        name = params["name"]
        if not context.memory.delete(name):
            return ToolResult(error=f"memory not found: {name!r}")
        context.display(f"🧠 记忆已删除: {name}")
        return ToolResult(output=f"Deleted memory '{name}' and its index entry.")
