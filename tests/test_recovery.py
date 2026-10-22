"""错误恢复（s11）：Path 1 输出截断升级 / Path 2 反应式压缩 / Path 3 退避+备用模型。"""
import asyncio
import unittest
from unittest import mock

from openharness.engine.llm import LLMResponse
from openharness.engine.recovery import (
    call_with_recovery, is_prompt_too_long, is_transient,
    RecoveryState, MAX_ESCALATIONS,
)


def run(coro):
    return asyncio.run(coro)


def resp(text="OK", stop_reason="end_turn"):
    return LLMResponse(text=text, stop_reason=stop_reason)


class _Ctx:
    def __init__(self, config=None):
        self.messages = [{"role": "system", "content": "SYS"}] + \
                        [{"role": "u", "content": f"m{i}"} for i in range(10)]
        self.config = config or {"retry_base_delay": 0.0}
        self.recovery_state = None
        self.on_text = lambda t: None
        # 真实的 Context 同时有 on_event（过程事件，CLI 接的是它）
        self.on_event = lambda t: None


class TestClassifiers(unittest.TestCase):
    def test_prompt_too_long_markers(self):
        for text in ("This model's maximum context length is 8192 tokens",
                     "prompt is too long: 100k > 8192",
                     "exceeded token limit",
                     "context_length_exceeded"):
            self.assertTrue(is_prompt_too_long(RuntimeError(text)), text)

    def test_transient_markers(self):
        for text in ("connection reset", "read timeout",
                     "502 Bad Gateway", "503 Service Unavailable"):
            self.assertTrue(is_transient(RuntimeError(text)), text)

    def test_other_errors_not_matched(self):
        self.assertFalse(is_prompt_too_long(RuntimeError("connection reset")))
        self.assertFalse(is_transient(RuntimeError("prompt is too long")))
        self.assertFalse(is_transient(ValueError("bad json")))


class TestPath3Backoff(unittest.TestCase):
    def test_first_try_success(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            return resp()

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out.stop_reason, "end_turn")
        self.assertEqual(len(calls), 1)
        self.assertEqual(ctx.recovery_state.attempt, 0)

    def test_transient_errors_retry_then_succeed(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            if len(calls) <= 2:
                raise RuntimeError("connection reset")
            return resp()

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out.stop_reason, "end_turn")
        self.assertEqual(len(calls), 3)
        self.assertEqual(ctx.recovery_state.attempt, 2)

    def test_persistent_transient_error_raises_after_max(self):
        ctx = _Ctx(config={"max_retries": 2, "retry_base_delay": 0.0})
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            raise RuntimeError("connection reset")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            with self.assertRaises(RuntimeError):
                run(call_with_recovery(ctx))
        self.assertEqual(len(calls), 2)  # max_retries = 总尝试次数

    def test_non_transient_error_raises_immediately(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            raise ValueError("bad json")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            with self.assertRaises(ValueError):
                run(call_with_recovery(ctx))
        self.assertEqual(len(calls), 1)  # 非瞬时错误不重试

    def test_fallback_model_switched_after_5xx(self):
        ctx = _Ctx(config={"retry_base_delay": 0.0,
                           "fallback_model": "backup-model"})
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            if len(calls) <= 3:
                raise RuntimeError("503 Service Unavailable")
            return resp()

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out.stop_reason, "end_turn")
        self.assertEqual(ctx.recovery_state.current_model, "backup-model")


class TestPath2ReactiveCompact(unittest.TestCase):
    def test_prompt_too_long_compacts_and_retries(self):
        ctx = _Ctx()

        async def fake_stream(context, max_tokens=None):
            if len(context.messages) > 8:
                raise RuntimeError("prompt is too long")
            return resp()

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out.stop_reason, "end_turn")
        st = ctx.recovery_state
        self.assertTrue(st.has_attempted_reactive_compact)
        # reactive_compact 已把消息压缩过：占位符存在
        self.assertTrue(any("reactively compacted" in m["content"]
                            for m in ctx.messages))

    def test_repeated_prompt_too_long_raises(self):
        ctx = _Ctx(config={"retry_base_delay": 0.0})

        async def fake_stream(context, max_tokens=None):
            raise RuntimeError("maximum context length exceeded")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            with self.assertRaises(RuntimeError):
                run(call_with_recovery(ctx))
        self.assertTrue(ctx.recovery_state.has_attempted_reactive_compact)


class TestPath1Escalation(unittest.TestCase):
    def test_escalates_max_tokens_on_first_truncation(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(max_tokens)
            if len(calls) == 1:
                return resp("partial", stop_reason="max_tokens")
            return resp("full")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out.stop_reason, "end_turn")
        st = ctx.recovery_state
        self.assertEqual(st.recovery_count, 1)
        self.assertEqual(st.max_tokens, 16384)  # 8192 * 2
        # 第二次调用用了升级后的 max_tokens
        self.assertEqual(calls[1], 16384)

    def test_continues_after_escalation_then_succeeds(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            if len(calls) <= 2:
                return resp("partial", stop_reason="max_tokens")
            return resp("done")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out.stop_reason, "end_turn")
        st = ctx.recovery_state
        self.assertEqual(st.recovery_count, 2)
        # 第二次截断后并入了续写提示
        self.assertTrue(any("继续" in m["content"] for m in ctx.messages))

    def test_gives_up_after_max_escalations(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context, max_tokens=None):
            calls.append(1)
            return resp("truncated", stop_reason="max_tokens")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        # 超过 MAX_ESCALATIONS 次干预后放弃，返回截断响应（不无限循环）
        self.assertEqual(out.stop_reason, "max_tokens")
        self.assertEqual(len(calls), MAX_ESCALATIONS + 1)


if __name__ == "__main__":
    unittest.main()
