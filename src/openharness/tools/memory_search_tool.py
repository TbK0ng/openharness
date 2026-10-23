"""MemorySearch tool — 检索长期记忆。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


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
