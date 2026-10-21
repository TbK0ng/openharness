"""Test engine/query.py Agent Loop message protocol.

The loop previously appended `role="tool"` results without first appending the
assistant message carrying `tool_calls`. Lenient endpoints (LM Studio) accepted
it; strict OpenAI-compatible ones (DeepSeek) reject the request with 400:
"Messages with role 'tool' must be a response to a preceding message with
'tool_calls'". These tests pin the protocol shape without needing a network.
"""
import asyncio
import unittest

import openharness.engine.llm as llm_mod
from openharness.engine.llm import LLMResponse
from openharness.engine.query import run_query
from openharness.engine.query_engine import Engine


class _ScriptedLLM:
    """Returns scripted responses in order, recording what it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    async def __call__(self, context, max_tokens=None):
        self.seen.append([dict(m) for m in context.messages])
        return self.responses.pop(0)


def _tool_call(name="TodoWrite", args=None, call_id="c1"):
    return {"id": call_id, "name": name, "arguments": args or {}}


def _run(responses, max_turns=5):
    engine = Engine(cwd=".")
    ctx = engine.create_context()
    ctx.permissions.set_mode("full-auto")
    ctx.max_turns = max_turns

    scripted = _ScriptedLLM(responses)
    original = llm_mod.stream_response
    llm_mod.stream_response = scripted
    try:
        out = asyncio.run(run_query(ctx))
    finally:
        llm_mod.stream_response = original
    return ctx, out, scripted


class TestToolCallProtocol(unittest.TestCase):
    def test_assistant_tool_calls_precede_tool_result(self):
        responses = [
            LLMResponse(text="", stop_reason="tool_use",
                        tool_calls=[_tool_call("TodoWrite",
                                               {"todos": [{"content": "x", "status": "pending"}]})]),
            LLMResponse(text="done", stop_reason="end_turn", tool_calls=[]),
        ]
        ctx, out, scripted = _run(responses)

        self.assertEqual(out, "done")
        roles = [m["role"] for m in ctx.messages]
        self.assertEqual(roles, ["assistant", "tool"])

        # The assistant message must carry the same tool_call id the tool
        # message answers.
        assistant = ctx.messages[0]
        self.assertEqual(assistant["tool_calls"][0]["id"], "c1")
        self.assertEqual(ctx.messages[1]["tool_call_id"], "c1")

    def test_second_request_contains_well_formed_history(self):
        # This is the exact shape a strict endpoint validates.
        responses = [
            LLMResponse(text="", stop_reason="tool_use", tool_calls=[_tool_call("CronList")]),
            LLMResponse(text="done", stop_reason="end_turn", tool_calls=[]),
        ]
        ctx, out, scripted = _run(responses)

        second_request = scripted.seen[1]
        tool_calls = {tc["id"] for m in second_request if m.get("tool_calls")
                      for tc in m["tool_calls"]}
        answered = {m.get("tool_call_id") for m in second_request if m["role"] == "tool"}

        self.assertTrue(answered, "a tool result must be present")
        self.assertLessEqual(answered, tool_calls,
                             "every tool result must answer a declared tool_call")

    def test_multiple_tool_calls_answered_in_one_assistant_message(self):
        responses = [
            LLMResponse(text="", stop_reason="tool_use",
                        tool_calls=[_tool_call("CronList", call_id="a"),
                                    _tool_call("TaskList", call_id="b")]),
            LLMResponse(text="done", stop_reason="end_turn", tool_calls=[]),
        ]
        ctx, out, _ = _run(responses)

        assistants = [m for m in ctx.messages if m["role"] == "assistant"]
        self.assertEqual(len(assistants), 1)
        self.assertEqual([tc["id"] for tc in assistants[0]["tool_calls"]], ["a", "b"])
        self.assertEqual([m["tool_call_id"] for m in ctx.messages if m["role"] == "tool"],
                         ["a", "b"])


class TestLoopTermination(unittest.TestCase):
    def test_plain_text_response_returns_immediately(self):
        ctx, out, scripted = _run([LLMResponse(text="hello", stop_reason="end_turn")])

        self.assertEqual(out, "hello")
        self.assertEqual(ctx.messages, [])
        self.assertEqual(len(scripted.seen), 1)

    def test_max_turns_stops_the_loop(self):
        looping = [LLMResponse(text="", stop_reason="tool_use",
                               tool_calls=[_tool_call("CronList")])] * 5
        ctx, out, scripted = _run(looping, max_turns=3)

        self.assertIn("max turns", out)
        self.assertEqual(len(scripted.seen), 3)


if __name__ == "__main__":
    unittest.main()
