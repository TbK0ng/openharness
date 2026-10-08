"""Skill 工具 — 按需加载技能内容（第 8 章：知识按需加载）。"""
from __future__ import annotations

from ..tools.base import BaseTool, ToolResult


class SkillTool(BaseTool):
    name = "Skill"
    description = ("Load a skill by name to inject its domain knowledge/instructions into the "
                   "current conversation. Use when a task matches a skill's 'when to use'.")
    input_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        skills = context.skills
        if skills is None:
            return ToolResult(error="Skills system not available.")
        content = skills.get(params["name"])
        if content is None:
            names = ", ".join(s["name"] for s in skills.list_skills()) or "(none)"
            return ToolResult(error=f"Unknown skill '{params['name']}'. Available: {names}")
        return ToolResult(output=content)
