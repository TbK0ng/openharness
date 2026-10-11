"""autoCompact（s08）：LLM 摘要 / 熔断器 / 紧急压缩。"""
import asyncio
import unittest
from unittest import mock

from openharness.engine.compact import (
    CircuitBreaker, compact_history, estimate_tokens,
    reactive_compact, maybe_auto_compact,
)


def run(coro):
    return asyncio.run(coro)


class TestEstimateTokens(unittest.TestCase):
    def test_scales_with_content(self):
        small = [{"role": "user", "content": "hi"}]
        big = [{"role": "user", "content": "x" * 400}]
        self.assertGreater(estimate_tokens(big), estimate_tokens(small))
        self.assertEqual(estimate_tokens([]), 0)


class TestCircuitBreaker(unittest.TestCase):
    def test_opens_after_max_failures(self):
        b = CircuitBreaker(max_failures=2)
        self.assertFalse(b.open())
        b.record_failure()
        self.assertFalse(b.open())
        b.record_failure()
        self.assertTrue(b.open())

    def test_success_resets(self):
        b = CircuitBreaker(max_failures=1)
        b.record_failure()
        self.assertTrue(b.open())
        b.record_success()
        self.assertFalse(b.open())


class TestCompactHistory(unittest.TestCase):
    def test_summarizes_old_keeps_recent(self):
        msgs = [{"role": "u", "content": f"m{i}"} for i in range(10)]
        async def llm(prompt):
            self.assertIn("[u] m0", prompt)
            return "SUMMARY"
        out = run(compact_history(msgs, llm, keep_recent=4))
        self.assertEqual(out[0], {"role": "system",
                                  "content": "[compacted history]\nSUMMARY"})
        self.assertEqual(len(out), 1 + 4)
        self.assertEqual(out[-1]["content"], "m9")
        # 原列表不被修改
        self.assertEqual(len(msgs), 10)

    def test_open_breaker_passthrough(self):
        msgs = [{"role": "u", "content": f"m{i}"} for i in range(10)]
        b = CircuitBreaker(max_failures=1)
        b.record_failure()
        async def llm(prompt):
            raise AssertionError("must not be called")
        out = run(compact_history(msgs, llm, breaker=b, keep_recent=4))
        self.assertEqual(out, msgs)

    def test_llm_failure_records_and_passthrough(self):
        msgs = [{"role": "u", "content": f"m{i}"} for i in range(10)]
        b = CircuitBreaker(max_failures=3)
        async def llm(prompt):
            raise RuntimeError("boom")
        out = run(compact_history(msgs, llm, breaker=b, keep_recent=4))
        self.assertEqual(out, msgs)
        self.assertEqual(b.failures, 1)

    def test_too_few_messages_noop(self):
        msgs = [{"role": "u", "content": "only"}]
        async def llm(prompt):
            raise AssertionError("must not be called")
        out = run(compact_history(msgs, llm, keep_recent=6))
        self.assertEqual(out, msgs)


class TestReactiveCompact(unittest.TestCase):
    def test_keeps_first_placeholder_recent(self):
        msgs = [{"role": "system", "content": "SYS"}] + \
               [{"role": "u", "content": f"m{i}"} for i in range(10)]
        out = reactive_compact(msgs, keep_recent=4)
        self.assertEqual(out[0]["content"], "SYS")
        self.assertIn("reactively compacted", out[1]["content"])
        self.assertEqual(len(out), 2 + 4)
        self.assertEqual(out[-1]["content"], "m9")

    def test_small_list_unchanged(self):
        msgs = [{"role": "u", "content": "a"}, {"role": "u", "content": "b"}]
        self.assertEqual(reactive_compact(msgs, keep_recent=6), msgs)


class _Ctx:
    def __init__(self, messages, config=None):
        self.messages = messages
        self.config = config or {}
        self.compact_breaker = None


class TestMaybeAutoCompact(unittest.TestCase):
    def test_below_threshold_noop(self):
        ctx = _Ctx([{"role": "u", "content": "short"}])
        run(maybe_auto_compact(ctx))
        self.assertEqual(len(ctx.messages), 1)
        self.assertIsNone(ctx.compact_breaker)

    def test_above_threshold_compacts_via_llm(self):
        long_msgs = [{"role": "u", "content": "x" * 1000} for _ in range(20)]
        ctx = _Ctx(long_msgs, config={"compact_threshold": 100})
        with mock.patch("openharness.engine.llm.llm_complete",
                        new=lambda c, p: _fake_llm()):
            run(maybe_auto_compact(ctx))
        self.assertEqual(ctx.messages[0]["role"], "system")
        self.assertIn("SUMMARY", ctx.messages[0]["content"])
        self.assertIsInstance(ctx.compact_breaker, CircuitBreaker)


async def _fake_llm():
    return "SUMMARY"


if __name__ == "__main__":
    unittest.main()
