"""Test engine/llm.py against the real local endpoint 127.0.0.1:1234."""
import asyncio
import unittest

from openharness.engine.llm import build_llm, close_llm, stream_response


class FakeCtx:
    def __init__(self, llm, messages, tool_schemas=None, system_prompt="You are a helpful assistant."):
        self.llm = llm
        self.messages = messages
        self.tool_schemas = tool_schemas or []
        self.system_prompt = system_prompt
        self.text_chunks = []

    def on_text(self, s):
        self.text_chunks.append(s)


class TestLLMEndpoint(unittest.TestCase):
    def _run(self, coro_fn):
        """Run async work in a fresh loop, always closing the LLM client."""
        async def wrapper():
            try:
                return await coro_fn()
            finally:
                await close_llm(self.ctx.llm)
        return asyncio.run(wrapper())

    def setUp(self):
        self.ctx = None

    def test_simple_chat(self):
        self.ctx = FakeCtx(build_llm({}), messages=[
            {"role": "user", "content": "Reply with exactly one word: pong"}
        ])
        async def go():
            return await stream_response(self.ctx)
        resp = self._run(go)
        self.assertIn("pong", resp.text.lower())
        self.assertEqual(resp.stop_reason, "end_turn")

    def test_tool_call_mapping(self):
        schemas = [{
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get the current time in a timezone.",
                "parameters": {
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                    "required": ["timezone"],
                },
            },
        }]
        self.ctx = FakeCtx(build_llm({}), messages=[
            {"role": "user", "content": "What time is it in Beijing? Use the get_time tool."}
        ], tool_schemas=schemas)
        async def go():
            return await stream_response(self.ctx)
        resp = self._run(go)
        self.assertEqual(resp.stop_reason, "tool_use")
        self.assertTrue(resp.has_tool_calls)
        self.assertEqual(resp.tool_calls[0]["name"], "get_time")
        self.assertIn("timezone", resp.tool_calls[0]["arguments"])


def test_endpoint_reachable():
    import urllib.request
    urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=5)


if __name__ == "__main__":
    unittest.main()
