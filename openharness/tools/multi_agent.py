"""子 Agent 工具 — Agent（spawn 子 Agent）/ SendMessage（继续对话）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..agents.team import SUBAGENT_TYPES, SubTask


class AgentTool(BaseTool):
    name = "Agent"
    description = (
        "Spawn a sub-agent with an independent context to do focused work "
        "(research, implementation, review). Returns its final answer."
    )
    read_only = False
    input_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Short label for the sub-agent task."},
            "agent_type": {"type": "string", "enum": list(SUBAGENT_TYPES.keys()),
                          "description": "Sub-agent role."},
            "prompt": {"type": "string", "description": "Full task prompt for the sub-agent."},
            "run_in_background": {"type": "boolean", "description": "Do not block; returns immediately."},
        },
        "required": ["description", "agent_type", "prompt"],
    }

    async def execute(self, params, context) -> ToolResult:
        team = context.team
        label = params.get("description", "sub-agent")
        agent_type = params.get("agent_type", "explore")
        prompt = params.get("prompt", "")
        if agent_type not in SUBAGENT_TYPES:
            return ToolResult(error=f"unknown agent_type: {agent_type}")
        bg = bool(params.get("run_in_background", False))
        agent = team.create(label, agent_type, run_in_background=bg,
                           prompt=prompt, parent=context)
        if bg:
            return ToolResult(output=f"started background agent {agent.agent_id} ({agent_type})")
        result = team.run(agent, prompt)
        return ToolResult(output=result or "(sub-agent returned no output)")


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
        if agent.context is None:
            return ToolResult(error=f"agent {agent.agent_id} has no active context yet")
        from ..engine.query import run_query_in_thread
        agent.context.messages.append({"role": "user", "content": params.get("message", "")})
        result = run_query_in_thread(agent.context)
        agent.result = result
        return ToolResult(output=result or "(sub-agent returned no output)")
