"""长期记忆工具 — 第 9 章 MemorySave / MemorySearch / MemoryDelete。

记忆落盘在 `.oh/memory/<type>_<name>.md`，索引写入 `.oh/MEMORY.md`；
Engine 每轮组装 system prompt 时注入索引，因此保存后下一轮即可见。
"""
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


class MemorySearchTool(BaseTool):
    name = "MemorySearch"
    description = ("Search persistent memories by name, description, or body. "
                   "Omit query to list every memory.")
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "Case-insensitive substring to look for."},
        },
    }
    read_only = True

    async def execute(self, params, context):
        if getattr(context, "memory", None) is None:
            return ToolResult(error="memory subsystem not available")
        query = (params.get("query") or "").strip()
        needle = query.lower()
        hits = []
        for meta in context.memory.list_memories():
            text = context.memory.get(meta["name"]) or ""
            haystack = f"{meta['name']}\n{meta['description']}\n{text}".lower()
            if needle and needle not in haystack:
                continue
            hits.append((meta, text))
            if len(hits) >= 20:
                break
        if not hits:
            return ToolResult(output=f"No memories matched {query!r}."
                              if query else "No memories saved yet.")
        lines = [f"Found {len(hits)} memory item(s):"]
        for meta, text in hits:
            lines.append(f"- {meta['name']} [{meta['type']}] — {meta['description']}")
            if query:
                body = text.split("---", 2)[-1].strip()
                pos = body.lower().find(needle)
                snippet = body[max(0, pos - 60): pos + 160] if pos >= 0 else body[:220]
                lines.append(f"  {snippet.strip()}")
        return ToolResult(output="\n".join(lines))


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
