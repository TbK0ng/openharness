"""自动压缩 — 第 8 章（Learn Claude Code s08）：autoCompact 管线。

两条路径：
    maybe_auto_compact(context)   每回合预检：消息总长超过阈值才触发 LLM 摘要
    reactive_compact(messages)    prompt_too_long 时的紧急同步压缩（不依赖 LLM）

LLM 摘要走 compact_history(messages, llm_fn, breaker)，带熔断器：
连续失败达到上限后停止尝试，避免坏端点拖死整个循环。
"""
from __future__ import annotations

import dataclasses
import json
from typing import Awaitable, Callable

# ~4 字符 ≈ 1 token（OpenAI 系模型的粗略换算，教程同款近似）
CHARS_PER_TOKEN = 4


def estimate_tokens(messages: list[dict]) -> int:
    """粗略估算消息列表的 token 数。"""
    total = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    return total // CHARS_PER_TOKEN


@dataclasses.dataclass
class CircuitBreaker:
    """连续失败计数；open() 之后 compact_history 直接跳过。"""
    max_failures: int = 3
    failures: int = 0

    def open(self) -> bool:
        return self.failures >= self.max_failures

    def record_failure(self) -> None:
        self.failures += 1

    def record_success(self) -> None:
        self.failures = 0


async def compact_history(
    messages: list[dict],
    llm_fn: Callable[[str], Awaitable[str]],
    breaker: CircuitBreaker | None = None,
    keep_recent: int = 6,
) -> list[dict]:
    """把较早的消息摘要成一条 system 消息，保留最近 keep_recent 条。

    返回新列表（不改入参）。熔断打开或可压缩区间太小时原样返回。
    """
    if breaker is None:
        breaker = CircuitBreaker()
    if breaker.open():
        return list(messages)
    head = len(messages) - keep_recent
    if head < 2:
        return list(messages)
    old = messages[:head]
    transcript = "\n".join(
        f"[{m.get('role', '?')}] {str(m.get('content', ''))[:500]}" for m in old)
    try:
        summary = await llm_fn(
            "Summarize this conversation so far in under 10 lines, "
            "keeping decisions, file paths and open questions:\n" + transcript)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        return list(messages)
    out = [{"role": "system",
            "content": f"[compacted history]\n{summary}"}]
    out.extend(messages[head:])
    return out


def reactive_compact(messages: list[dict], keep_recent: int = 6) -> list[dict]:
    """紧急同步压缩：prompt_too_long 时立即截断，不依赖 LLM。

    保留第一条 system 消息与最近 keep_recent 条，中间用占位符替代。
    """
    if len(messages) <= keep_recent + 1:
        return list(messages)
    head = len(messages) - keep_recent
    dropped = messages[1:head]
    out = [messages[0]]
    out.append({"role": "system",
                "content": f"[reactively compacted: {len(dropped)} earlier "
                           "exchanges removed to fit the context window]"})
    out.extend(messages[head:])
    return out


def _breaker(context) -> CircuitBreaker:
    b = getattr(context, "compact_breaker", None)
    if b is None:
        b = CircuitBreaker()
        context.compact_breaker = b
    return b


async def maybe_auto_compact(context) -> None:
    """每回合预检：超过阈值才做 LLM 摘要压缩（就地替换 context.messages）。"""
    from .llm import llm_complete
    threshold = int((getattr(context, "config", {}) or {}).get("compact_threshold", 60_000))
    if estimate_tokens(context.messages) * CHARS_PER_TOKEN < threshold:
        return
    msgs = context.messages
    msgs[:] = await compact_history(msgs, lambda p: llm_complete(context, p),
                                    _breaker(context))
