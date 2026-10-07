"""Agent Loop 核心 — 对应教程第 4 章 `openharness/engine/query.py` 与第 12 章完整旅程。

流程（第 4 章动画的 5 步）：
    第 1 步：把消息发给 LLM，获取响应
    第 2 步：LLM 返回响应——文本（任务完成）或工具调用
    第 3 步：权限检查 + 执行工具，把结果（Observation）回传给 LLM
    第 4 步：回到循环顶部
    第 5 步：任务完成，返回最终响应
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..hooks.executor import execute_tool_with_hooks
from .llm import LLMResponse, close_llm, stream_response


@dataclass
class Context:
    """Engine 运行上下文（第 12 章第 2 步 Engine 初始化组装出的对象）。

    内置/ MCP / 插件工具通过 registry 访问；各子系统（memory/skills/mcp/
    team/tasks/cron）作为字段注入，供工具在执行时调用。
    """
    session_id: str
    cwd: str
    messages: List[dict]
    system_prompt: str
    tool_schemas: List[dict]
    llm: object
    # 子系统
    registry: object
    permissions: object
    hooks: object
    memory: Optional[object] = None
    skills: Optional[object] = None
    mcp: Optional[object] = None
    team: Optional[object] = None
    tasks: Optional[object] = None
    cron: Optional[object] = None
    config: dict = field(default_factory=dict)
    # 控制
    max_turns: int = 50
    # 展示回调
    on_text: Callable[[str], None] = lambda s: None
    on_event: Callable[[str], None] = lambda s: None

    def display(self, s: str) -> None:
        self.on_event(s)


async def run_query(context: Context) -> str:
    """执行 Agent Loop，直到任务完成或达到 max_turns。返回最终文本。"""
    for _turn in range(context.max_turns):
        # 第 1 步：把消息发给 LLM，获取响应
        response: LLMResponse = await stream_response(context)

        # 第 2 步：LLM 返回响应——文本（任务完成）或工具调用
        if not response.has_tool_calls:
            # 第 5 步：任务完成，返回最终响应
            return response.text

        # 第 3 步：权限检查 + 执行工具，把结果回传给 LLM
        for tc in response.tool_calls:
            context.display(f"🔧 调用工具 {tc['name']}")
            result = await execute_tool_with_hooks(context, tc)
            # 把工具结果（Observation）追加为 tool 消息
            context.messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "content": result.to_text(),
            })
            context.display(f"   ↳ 返回 {len(result.to_text())} 字符")

        # 第 4 步：回到循环顶部（自动）

    context.display("⚠️ 已达到最大回合数，停止循环")
    return "(reached max turns)"


def run_query_sync(context: Context) -> str:
    """CLI 用的同步入口：跑一轮 Agent Loop 并妥善关闭 httpx 客户端。"""
    async def _run():
        try:
            return await run_query(context)
        finally:
            await close_llm(context.llm)

    return asyncio.run(_run())
