"""错误恢复（s11）：重试 / 指数退避 / prompt_too_long 升级。"""
import asyncio
import unittest
from unittest import mock

from openharness.engine.recovery import (
    call_with_recovery, is_prompt_too_long,
)


def run(coro):
    return asyncio.run(coro)


class _Ctx:
    def __init__(self, config=None):
        self.messages = [{"role": "system", "content": "SYS"}] + \
                        [{"role": "u", "content": f"m{i}"} for i in range(10)]
        self.config = config or {"retry_base_delay": 0.0}
        self.recovery_state = None


class TestIsPromptTooLong(unittest.TestCase):
    def test_markers(self):
        for text in ("This model's maximum context length is 8192 tokens",
                     "prompt is too long: 100k > 8192",
                     "exceeded token limit",
                     "context_length_exceeded"):
            self.assertTrue(is_prompt_too_long(RuntimeError(text)), text)

    def test_other_errors_not_matched(self):
        self.assertFalse(is_prompt_too_long(RuntimeError("connection reset")))
        self.assertFalse(is_prompt_too_long(ValueError("bad json")))


class TestCallWithRecovery(unittest.TestCase):
    def test_first_try_success(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context):
            calls.append(1)
            return "OK"

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out, "OK")
        self.assertEqual(len(calls), 1)
        self.assertEqual(ctx.recovery_state.attempt, 0)

    def test_transient_errors_retry_then_succeed(self):
        ctx = _Ctx()
        calls = []

        async def fake_stream(context):
            calls.append(1)
            if len(calls) <= 2:
                raise RuntimeError("connection reset")
            return "OK"

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out, "OK")
        self.assertEqual(len(calls), 3)
        self.assertEqual(ctx.recovery_state.attempt, 2)

    def test_persistent_transient_error_raises_after_max(self):
        ctx = _Ctx(config={"max_retries": 2, "retry_base_delay": 0.0})
        calls = []

        async def fake_stream(context):
            calls.append(1)
            raise RuntimeError("boom")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            with self.assertRaises(RuntimeError):
                run(call_with_recovery(ctx))
        self.assertEqual(len(calls), 3)  # max_retries + 1 次尝试

    def test_prompt_too_long_compacts_and_retries(self):
        ctx = _Ctx()

        async def fake_stream(context):
            if len(context.messages) > 8:
                raise RuntimeError("prompt is too long")
            return "OK"

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            out = run(call_with_recovery(ctx))
        self.assertEqual(out, "OK")
        st = ctx.recovery_state
        self.assertEqual(st.prompt_too_long_count, 1)
        # reactive_compact 已把消息压缩过：占位符存在、总量变小
        self.assertTrue(any("reactively compacted" in m["content"]
                            for m in ctx.messages))

    def test_repeated_prompt_too_long_raises(self):
        ctx = _Ctx(config={"max_retries": 2, "retry_base_delay": 0.0})

        async def fake_stream(context):
            raise RuntimeError("maximum context length exceeded")

        with mock.patch("openharness.engine.llm.stream_response", fake_stream):
            with self.assertRaises(RuntimeError):
                run(call_with_recovery(ctx))
        self.assertGreaterEqual(ctx.recovery_state.prompt_too_long_count, 2)


if __name__ == "__main__":
    unittest.main()
