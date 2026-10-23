"""AskUserQuestion 工具 — 向用户提问并等待回答。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class AskUserQuestionTool(BaseTool):
    name = "AskUserQuestion"
    description = ("Ask the user a short question and wait for their answer. "
                   "Use when you need clarification or a decision you cannot make alone.")
    input_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to ask."},
        },
        "required": ["question"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        q = params["question"]
        context.display(f"❓ {q}")
        try:
            answer = context.ask_user(q)
        except Exception:
            answer = ""
        return ToolResult(output=f"User answered: {answer}" if answer else "User provided no answer.")
