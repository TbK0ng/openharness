"""SendMessage tool — 继续与已派发的子 Agent 对话。"""
from __future__ import annotations

from .base import BaseTool, ToolResult


class SendMessageTool(BaseTool):
    name = "SendMessage"
    description = "Send a follow-up message to a previously spawned sub-agent."
    read_only = False
    input_schema = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Id of the sub-agent."},
            "message": {"type": "string", "description": "Follow-up message."},
        },
        "required": ["agent_id", "message"],
    }

    async def execute(self, params, context) -> ToolResult:
        team = context.team
        agent = team.get(params.get("agent_id", ""))
        if agent is None:
            return ToolResult(error=f"no sub-agent with id {params.get('agent_id')}")
        try:
            result = team.resume(agent, params.get("message", ""))
        except ValueError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=result or "(sub-agent returned no output)")
