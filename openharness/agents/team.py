"""多 Agent 协作 — 第 11 章：TeamRegistry + 子 Agent 类型。

三种子 Agent：
    explore         — 只读工具（Read/Glob/Grep/...），用于快速调查
    plan            — 只读工具，用于制定计划
    general-purpose — 全工具集，执行实际任务

TeamRegistry.create() 纯注册；TeamRegistry.run() 是唯一执行入口。
子 Agent 的 Agent Loop 始终在独立线程内运行（线程内新建事件循环），因此
可以在已运行的主事件循环内阻塞等待其结果。
run_pipeline / fan_out_async 提供串行与并行的多 Agent 编排。
"""
from __future__ import annotations

import asyncio
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# 只读工具白名单（explore / plan 子 Agent 可用）。
# 名称必须与 ToolRegistry 中真实注册的工具名一致；Read-only 的元工具
# （TodoWrite/Compact/EnterPlanMode 等）会改动会话状态，不在此列。
READONLY_TOOLS = {
    "Read", "Glob", "Grep", "WebFetch", "WebSearch",
    "ListMcpResources", "ReadMcpResource",
}

# 子 Agent 系统提示（第 11 章）
SUBAGENT_SYSTEM = {
    "explore": "You are an exploration subagent. Use read-only tools to "
               "quickly investigate the codebase and report concise findings.",
    "plan": "You are a planning subagent. Use read-only tools to understand "
            "the task and produce a clear step-by-step plan.",
    "general-purpose": "You are a general-purpose subagent. Complete the task "
                       "using the available tools.",
}

# 子 Agent 类型定义（供 Agent 工具 / 调用方枚举）
SUBAGENT_TYPES = {
    "explore": {"read_only": True, "description": "read-only investigation"},
    "plan": {"read_only": True, "description": "planning"},
    "general-purpose": {"read_only": False, "description": "full execution"},
}


@dataclass
class SubTask:
    """一次子 Agent 任务描述。"""
    agent_type: str
    description: str
    prompt: str = ""
    agent_id: Optional[str] = None
    max_turns: int = 25


@dataclass
class SubAgent:
    agent_id: str
    name: str
    agent_type: str
    status: str = "created"          # created / running / done / error
    result: Optional[str] = None
    context: Optional[object] = None
    thread: Optional[threading.Thread] = None
    parent: Optional[object] = None
    max_turns: int = 25
    on_event: Optional[object] = None


def build_sub_context(parent, task: SubTask):
    """为子 Agent 构造独立 Context（独立历史、按类型过滤工具）。"""
    from ..engine.query import Context

    reg = parent.registry
    if task.agent_type in ("explore", "plan"):
        tools = [t for t in reg.list_tools() if t.name in READONLY_TOOLS]
    else:
        tools = reg.list_tools()

    return Context(
        session_id=f"sub-{task.agent_id}",
        cwd=parent.cwd,
        messages=[],
        system_prompt=SUBAGENT_SYSTEM.get(
            task.agent_type, SUBAGENT_SYSTEM["general-purpose"]),
        tool_schemas=[t.to_json_schema() for t in tools],
        llm=parent.llm,
        registry=reg,
        permissions=parent.permissions,
        hooks=parent.hooks,
        memory=parent.memory,
        skills=parent.skills,
        mcp=parent.mcp,
        team=None,           # 禁止递归 spawn
        tasks=None,
        cron=None,
        config=parent.config,
        max_turns=task.max_turns,
    )


def _run_subagent_thread(agent: SubAgent, ctx) -> None:
    """线程内跑子 Agent 的 Agent Loop（新建事件循环）。"""
    from ..engine.query import run_query_in_thread
    agent.status = "running"
    if agent.on_event is not None:
        ctx.on_event = agent.on_event
    try:
        agent.result = run_query_in_thread(ctx)
        agent.status = "done"
    except Exception as e:  # noqa: BLE001
        agent.status = "error"
        agent.result = f"subagent error: {e}"
    finally:
        agent.context = ctx


class TeamRegistry:
    """管理当前会话里的全部子 Agent（教程第 11 章）。

    create() 纯注册；run() 是唯一执行入口。
    """

    def __init__(self, engine=None) -> None:
        self.engine = engine
        self.agents: dict[str, SubAgent] = {}
        self.tasks: list[SubTask] = []
        self._counter = itertools.count(1)

    def create(self, name: str = None, subagent_type: str = "general-purpose",
               run_in_background: bool = False, *,
               label: str = None, prompt: str = "",
               parent: object = None, max_turns: int = 25,
               on_event=None, description: str = None) -> SubAgent:
        """注册子 Agent（不运行）。

        兼容多种调用方：
            create(name, subagent_type, run_in_background)
            create(label=..., prompt=..., subagent_type=..., parent=...,
                   max_turns=..., on_event=...)
        """
        agent_id = f"agent-{next(self._counter)}"
        task = SubTask(
            agent_type=subagent_type,
            description=description or name or label or "sub-agent",
            prompt=prompt or "",
            agent_id=agent_id,
            max_turns=max_turns,
        )
        self.tasks.append(task)
        agent = SubAgent(
            agent_id=agent_id,
            name=task.description,
            agent_type=subagent_type,
            parent=parent,
            max_turns=max_turns,
            on_event=on_event,
        )
        self.agents[agent_id] = agent
        return agent

    def get(self, agent_id: str) -> Optional[SubAgent]:
        return self.agents.get(agent_id)

    def list(self) -> list[SubAgent]:
        return list(self.agents.values())

    def tools_for(self, subagent_type: str) -> list:
        if self.engine is None:
            return []
        reg = self.engine.registry
        if subagent_type in ("explore", "plan"):
            return [t for t in reg.list_tools() if t.name in READONLY_TOOLS]
        return reg.list_tools()

    def run(self, agent: SubAgent, prompt: Optional[str] = None,
            foreground: bool = True) -> str:
        """运行一个已注册的子 Agent（唯一执行入口）。"""
        parent = agent.parent
        if parent is None:
            raise ValueError(f"subagent {agent.agent_id} has no parent context")
        task = SubTask(
            agent_type=agent.agent_type,
            description=agent.name,
            prompt=prompt or "",
            agent_id=agent.agent_id,
            max_turns=agent.max_turns,
        )
        if agent.context is not None:
            ctx = agent.context  # 续跑：复用已有会话
        else:
            ctx = build_sub_context(parent, task)
        ctx.messages.append({"role": "user", "content": prompt or ""})
        if foreground:
            _run_subagent_thread(agent, ctx)
            return agent.result or ""
        agent.thread = threading.Thread(
            target=_run_subagent_thread, args=(agent, ctx), daemon=True)
        agent.thread.start()
        return f"Started background agent {agent.agent_id}."


def run_pipeline(context, prompts: list[str]) -> list[str]:
    """串行编排：逐个跑 general-purpose 子 Agent，收集结果。"""
    team = context.team
    results = []
    for i, prompt in enumerate(prompts):
        agent = team.create(f"pipeline-{i + 1}", "general-purpose", parent=context,
                            max_turns=20)
        results.append(team.run(agent, prompt, foreground=True))
    return results


async def fan_out_async(context, prompts: list[str]) -> list[str]:
    """并行编排：同时跑多个 general-purpose 子 Agent（各自独立线程）。"""
    team = context.team

    def _one(i: int, prompt: str) -> str:
        agent = team.create(f"fanout-{i + 1}", "general-purpose", parent=context,
                            max_turns=20)
        team.run(agent, prompt, foreground=False)
        if agent.thread is not None:
            agent.thread.join()
        return agent.result or ""

    return list(await asyncio.gather(
        *[asyncio.to_thread(_one, i, p) for i, p in enumerate(prompts)]))
