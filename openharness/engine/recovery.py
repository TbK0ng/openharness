"""错误恢复 — 第 11 章（Learn Claude Code s11）：重试 / 退避 / 升级。

一比一实现参考课程的三条恢复路径：
  Path 1  输出截断（finish_reason == "length"）→ 升级 max_tokens 重试，
          最多 recovery_count 次，仍截断则把已生成内容并入消息继续。
  Path 2  上下文溢出（prompt_too_long 异常）→ 反应式压缩一次，
          仍溢出则放弃（抛出，交由主循环收尾）。
  Path 3  瞬时故障（连接重置等）→ 指数退避重试，连续 502/503 切换备用模型。
"""
from __future__ import annotations

from typing import Optional

# Path 1：输出截断后最多再升级重试的次数
MAX_ESCALATIONS = 3
# Path 3：连续瞬时故障触发备用模型切换的阈值
FALLBACK_THRESHOLD = 3

# 上下文溢出（prompt_too_long）的异常文本标记。
# 注意：输出截断（max_tokens）不抛异常，而是以 finish_reason="length" 正常返回，
# 由 Path 1 经 stop_reason 识别，故此处标记只匹配上下文溢出。
_PTL_MARKERS = (
    "too long", "maximum context", "context length",
    "prompt is too long", "context_length", "token limit",
)


def is_prompt_too_long(exc: BaseException) -> bool:
    """判断异常是否为上下文溢出（Path 2）。"""
    text = str(exc).lower()
    return any(m in text for m in _PTL_MARKERS)


def is_transient(exc: BaseException) -> bool:
    """判断异常是否为瞬时故障（Path 3）：连接重置 / 超时 / 5xx。"""
    text = str(exc).lower()
    return any(m in text for m in (
        "connection", "reset", "timeout", "timed out",
        "502", "503", "504", "unavailable", "temporarily",
    ))


class RecoveryState:
    """单次会话的恢复状态（跨 Path 共享）。"""

    def __init__(self, max_retries: int = 10, initial_model: Optional[str] = None):
        self.max_retries = max_retries
        self.max_tokens = 8192          # Path 1 升级起点
        self.has_escalated = False      # Path 1：是否已升级过 max_tokens
        self.recovery_count = 0         # Path 1：已升级重试次数
        self.has_attempted_reactive_compact = False  # Path 2：是否已压缩过
        self.consecutive_5xx = 0        # Path 3：连续瞬时故障计数
        self.current_model = initial_model
        self.attempt = 0                # Path 3：当前重试序号（日志用）


async def call_with_recovery(context) -> object:
    """主入口：按 Path 2 → Path 1 顺序处理，Path 3 在 _with_retry 内。

    返回最终响应（Path 1 续写后的新响应，或首次成功响应）。
    Path 2 无法恢复时抛出 RuntimeError，交由主循环收尾。
    """
    st = context.recovery_state
    if st is None:
        st = context.recovery_state = RecoveryState(
            max_retries=(context.config or {}).get("max_retries", 10),
            initial_model=(context.config or {}).get("model"),
        )
    while True:
        try:
            response = await _with_retry(context, st)   # Path 3
        except BaseException as exc:
            if is_prompt_too_long(exc):
                # Path 2：反应式压缩一次，仍溢出则放弃
                if not st.has_attempted_reactive_compact:
                    from openharness.engine.compact import reactive_compact
                    context.messages[:] = reactive_compact(context.messages)
                    st.has_attempted_reactive_compact = True
                    continue
                raise RuntimeError(
                    "prompt_too_long 在反应式压缩后仍溢出，放弃恢复") from exc
            raise
        # Path 1：输出截断 → 首次升级 max_tokens 重试，其后并入续写，
        # 总干预次数受 MAX_ESCALATIONS 约束，超限则返回截断响应放弃。
        if getattr(response, "stop_reason", None) == "max_tokens":
            if st.recovery_count >= MAX_ESCALATIONS:
                return response          # 放弃：返回截断响应
            st.recovery_count += 1
            if not st.has_escalated:
                st.max_tokens *= 2       # 第一次截断：升级输出上限重试
                st.has_escalated = True
            else:
                # 已升级仍截断：把已生成内容并入消息，让模型继续
                context.messages.append(
                    {"role": "assistant", "content": response.text})
                context.messages.append(
                    {"role": "user", "content": "（继续，不要重复已生成内容）"})
            continue
        return response


async def _with_retry(context, st: RecoveryState) -> object:
    """Path 3：瞬时故障指数退避重试，连续 5xx 切换备用模型。"""
    from openharness.engine import llm
    last_exc: Optional[BaseException] = None
    for attempt in range(st.max_retries):
        st.attempt = attempt
        try:
            response = await llm.stream_response(context, max_tokens=st.max_tokens)
            st.consecutive_5xx = 0
            return response
        except BaseException as exc:
            last_exc = exc
            if is_prompt_too_long(exc):
                raise                       # 交给 Path 2
            if not is_transient(exc):
                raise                       # 非瞬时错误，直接抛出
            await _backoff(attempt, context)
            if _is_5xx(exc):
                st.consecutive_5xx += 1
                if st.consecutive_5xx >= FALLBACK_THRESHOLD:
                    _switch_fallback(context, st)
    raise last_exc


def _is_5xx(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(code in text for code in ("502", "503", "504"))


def _switch_fallback(context, st: RecoveryState) -> None:
    fallback = (context.config or {}).get("fallback_model")
    if fallback and st.current_model != fallback:
        st.current_model = fallback
        # 走 on_event（过程提示）：on_text 是正文流，CLI 没接，用户会看不到
        context.on_event(f"[recovery] 连续瞬时故障，切换备用模型 {fallback}")


async def _backoff(attempt: int, context) -> None:
    """指数退避：base * 2^attempt，受 config['retry_base_delay'] 控制。"""
    import asyncio
    base = (context.config or {}).get("retry_base_delay", 0.0)
    if base > 0:
        await asyncio.sleep(base * (2 ** attempt))
