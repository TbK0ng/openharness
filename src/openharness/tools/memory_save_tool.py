"""MemorySave tool — 写入长期记忆（第 9 章）。"""
from __future__ import annotations

from ..memory.manager import MEMORY_TYPES, MemoryError
from .base import BaseTool, ToolResult


class MemorySaveTool(BaseTool):
    name = "MemorySave"
    description = (
        "Persist a durable fact (user preference, feedback, project convention, "
        "or reference). Writes .oh/memory/<type>_<name>.md and updates MEMORY.md; "
        "the index is injected into every future turn. Use this instead of editing "
        "MEMORY.md by hand."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short unique memory name."},
            "description": {"type": "string",
                            "description": "One line shown in the MEMORY.md index."},
            "type": {"type": "string", "enum": list(MEMORY_TYPES),
                     "description": "user | feedback | project | reference"},
            "body": {"type": "string",
                     "description": "Full memory text. Include why it matters."},
        },
        "required": ["name", "description", "type", "body"],
    }
    read_only = False

    async def execute(self, params, context):
        if getattr(context, "memory", None) is None:
            return ToolResult(error="memory subsystem not available")
        try:
            path = context.memory.save(
                name=params["name"],
                description=params["description"],
                mtype=params["type"],
                body=params["body"],
            )
        except MemoryError as exc:
            return ToolResult(error=str(exc))
        context.display(f"🧠 记忆已保存: {params['name']}")
        return ToolResult(
            output=f"Saved memory '{params['name']}' -> {path}. "
                   "It is indexed in MEMORY.md and visible from the next turn.")
