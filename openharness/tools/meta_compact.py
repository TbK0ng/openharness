"""Compact — 第 8 章（s08）：模型主动触发的压缩。

与 maybe_auto_compact（每回合自动）不同，这是工具：模型判断上下文太长时
自己调用，立即对 context.messages 执行 LLM 摘要压缩（带熔断）。
"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from ..engine.compact import CircuitBreaker, compact_history, estimate_tokens


class CompactTool(BaseTool):
    name = "Compact"
    description = ("Compress the conversation so far into a summary message. Use when "
                   "the context is getting long and older turns are no longer needed.")
    input_schema = {"type": "object", "properties": {}}
    read_only = True

    async def execute(self, params: dict, context) -> ToolResult:
        from ..engine.llm import llm_complete
        breaker = getattr(context, "compact_breaker", None)
        if breaker is None:
            breaker = CircuitBreaker()
            context.compact_breaker = breaker
        before = estimate_tokens(context.messages)
        msgs = context.messages
        msgs[:] = await compact_history(msgs, lambda p: llm_complete(context, p), breaker)
        after = estimate_tokens(msgs)
        return ToolResult(output=f"compacted: ~{before} tokens -> ~{after} tokens")
