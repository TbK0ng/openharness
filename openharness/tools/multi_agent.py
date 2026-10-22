"""子 Agent 工具 — Agent（spawn 子 Agent）/ SendMessage（继续对话）。"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..agents.team import SUBAGENT_TYPES


class AgentTool(BaseTool):
    name = "Agent"
    description = (
        "Spawn a sub-agent with an independent context to do focused work "
        "(research, implementation, review). Returns its final answer followed "
        "by [agent_id: ...] — pass that id to SendMessage to continue the thread."
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
        body = result or "(sub-agent returned no output)"
        # 把 id 一起返回：否则调用方拿不到句柄，SendMessage 永远用不上。
        return ToolResult(output=f"{body}\n\n[agent_id: {agent.agent_id}]")


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
