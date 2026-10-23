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
from ..api.client import LLMResponse, close_llm


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
    # 配置目录（.oh/）——任务板、cron 等持久化状态的根
    oh_dir: Optional[str] = None
    memory: Optional[object] = None
    skills: Optional[object] = None
    mcp: Optional[object] = None
    team: Optional[object] = None
    tasks: Optional[object] = None
    cron: Optional[object] = None
    config: dict = field(default_factory=dict)
    # s05/s08/s11 会话状态（工具与循环共同读写）
    todo_state: Optional[object] = None
    compact_breaker: Optional[object] = None
    recovery_state: Optional[object] = None
    task_board: Optional[object] = None
    # 控制
    mode: str = "default"
    max_turns: int = 50
    # 展示回调
    on_text: Callable[[str], None] = lambda s: None
    on_event: Callable[[str], None] = lambda s: None
    # 交互式提问（AskUserQuestion 工具用；CLI 提供）
    ask_user: Callable[[str], str] = lambda q: ""

    def display(self, s: str) -> None:
        self.on_event(s)


async def run_query(context: Context) -> str:
    """执行 Agent Loop，直到任务完成或达到 max_turns。返回最终文本。"""
    from ..services.compact import maybe_auto_compact
    from .recovery import call_with_recovery
    from ..tools.todo_write_tool import todo_nag_due

    for _turn in range(context.max_turns):
        # s08：回合预检——上下文超阈值时先做 LLM 摘要压缩
        await maybe_auto_compact(context)

        # 第 1 步：把消息发给 LLM，获取响应（s11：带重试/退避/升级）
        response: LLMResponse = await call_with_recovery(context)

        # 第 2 步：LLM 返回响应——文本（任务完成）或工具调用
        if not response.has_tool_calls:
            # 第 5 步：任务完成，返回最终响应。
            # 多轮会话需要把回复写回历史，否则下一轮模型只看到连续的 user 消息。
            context.messages.append({"role": "assistant", "content": response.text})
            return response.text

        # 第 3 步：权限检查 + 执行工具，把结果回传给 LLM
        # 协议要求：role=tool 的消息必须紧跟一条带 tool_calls 的 assistant 消息。
        # DeepSeek 等严格的 OpenAI 兼容端点会以 400 拒绝缺少该前置消息的请求，
        # 因此这里必须先把 LLM 的 tool_calls 回显进历史。
        context.messages.append({
            "role": "assistant",
            "content": response.text or "",
            "tool_calls": [
                {"id": tc["id"], "name": tc["name"],
                 "arguments": tc.get("arguments") or {}}
                for tc in response.tool_calls
            ],
        })
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

        # s05：TodoWrite nag——连续 3 回合没更新清单且仍有未完成项时注入提醒
        st = getattr(context, "todo_state", None)
        if st is not None and st.items:
            st.turns_since_write += 1
            if todo_nag_due(context):
                context.display("⏰ 待办清单已 3 个回合未更新，请推进状态")
                context.messages.append({
                    "role": "system",
                    "content": "Reminder: your todo list has open items that were not "
                               "updated for 3 turns. Update statuses with TodoWrite.",
                })

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
            # 事件循环随 asyncio.run 结束，底层 httpx 客户端不能跨循环复用；
            # 下一轮由 Engine.begin_turn() 重建客户端。
            context.llm_closed = True

    return asyncio.run(_run())


# 别名：工具/团队模块里用 run_sync 引用
run_sync = run_query_sync


def run_query_in_thread(context: Context, close_llm_after: bool = False) -> str:
    """在独立线程里跑 Agent Loop（线程内新建事件循环）。

    与 run_query_sync 的区别：默认不关闭 context.llm（子 Agent 与父会话共享
    客户端，不能提前关闭）。供工具 / 团队在已运行的事件循环内阻塞调用。

    `close_llm_after=True` 时在该线程自己的事件循环里关闭客户端——子 Agent
    必须这样收尾：它的 httpx 客户端是在这个循环里创建的。
    """
    import threading
    box: dict = {}

    def _go():
        async def _run():
            try:
                return await run_query(context)
            finally:
                if close_llm_after:
                    await close_llm(context.llm)

        try:
            box["text"] = asyncio.run(_run())
        except Exception as e:  # noqa: BLE001
            box["error"] = str(e)

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise RuntimeError(box["error"])
    return box.get("text", "")
