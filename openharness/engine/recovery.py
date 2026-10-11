"""错误恢复 — 第 11 章（Learn Claude Code s11）：重试 / 退避 / 升级。

RecoveryState 记录一次会话的尝试次数与退避参数；call_with_recovery 包装
stream_response：

    prompt_too_long  → reactive_compact 紧急压缩后立即重试（不消耗退避等待）
    其他瞬时错误      → 指数退避（base_delay * 2**attempt）后重试
    超过 max_retries  → 抛出原始异常

backoff sleep 走 asyncio.sleep，测试里把 base_delay 设成 0 即可跳过等待。
"""
from __future__ import annotations

import asyncio
import dataclasses


@dataclasses.dataclass
class RecoveryState:
    attempt: int = 0
    max_retries: int = 3
    base_delay: float = 0.5
    prompt_too_long_count: int = 0


def _state(context) -> RecoveryState:
    st = getattr(context, "recovery_state", None)
    if st is None:
        cfg = context.config or {}
        st = RecoveryState(
            max_retries=int(cfg.get("max_retries", 3)),
            base_delay=float(cfg.get("retry_base_delay", 0.5)))
        context.recovery_state = st
    return st


def is_prompt_too_long(exc: BaseException) -> bool:
    """按消息文本识别「上下文超长」类错误（各家 API 措辞不同）。"""
    text = str(exc).lower().replace("_", " ").replace("-", " ")
    markers = ("too long", "maximum context", "context length",
               "token limit", "prompt is too long", "max tokens")
    return any(m in text for m in markers)


async def call_with_recovery(context):
    """带恢复地调用一次 LLM。返回 stream_response 的结果。"""
    from .llm import stream_response
    st = _state(context)
    while True:
        try:
            return await stream_response(context)
        except Exception as exc:
            if is_prompt_too_long(exc):
                # 升级路径：紧急压缩后立刻重试
                from .compact import reactive_compact
                context.messages[:] = reactive_compact(context.messages)
                st.prompt_too_long_count += 1
                st.attempt += 1
                if st.prompt_too_long_count > st.max_retries:
                    raise
                continue
            # 普通瞬时错误：指数退避
            st.attempt += 1
            if st.attempt > st.max_retries:
                raise
            delay = st.base_delay * (2 ** (st.attempt - 1))
            if delay > 0:
                await asyncio.sleep(delay)
