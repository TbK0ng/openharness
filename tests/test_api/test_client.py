"""Test api/client.py against the real local endpoint 127.0.0.1:1234.

这些是集成测试：端点不可达时自动 skip，并且每次调用都有超时上限，
避免本地模型没起来时整个测试套件挂住。
"""
import asyncio
import socket
import unittest

from openharness.api.client import build_llm, close_llm, stream_response
from openharness.api.registry import DEFAULT_MODEL_CONFIG, discover_model

ENDPOINT_TIMEOUT = 60  # 本地 27B 量化模型冷启动可能较慢，但不应无限等待


def endpoint_reachable(timeout: float = 3.0) -> bool:
    host, port = "127.0.0.1", 1234
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def skip_unless_endpoint():
    if not endpoint_reachable():
        raise unittest.SkipTest("127.0.0.1:1234 (LM Studio) 不可达")


class FakeCtx:
    def __init__(self, llm, messages, tool_schemas=None, system_prompt="You are a helpful assistant."):
        self.llm = llm
        self.messages = messages
        self.tool_schemas = tool_schemas or []
        self.system_prompt = system_prompt
        self.text_chunks = []

    def on_text(self, s):
        self.text_chunks.append(s)


class TestModelDiscovery(unittest.TestCase):
    """模型名不再硬编码：端点换模型后仍能自动适配。"""

    def test_discover_model_returns_loaded_model(self):
        skip_unless_endpoint()
        model = discover_model(DEFAULT_MODEL_CONFIG["base_url"])
        self.assertTrue(model, "端点应返回至少一个已加载模型")

    def test_build_llm_falls_back_to_discovered_model(self):
        skip_unless_endpoint()
        llm = build_llm({})
        self.assertTrue(getattr(llm, "model_name", ""), "build_llm 应自动填入发现的模型")


class TestLLMEndpoint(unittest.TestCase):
    def _run(self, coro_fn):
        """Run async work in a fresh loop, always closing the LLM client."""
        async def wrapper():
            try:
                return await asyncio.wait_for(coro_fn(), timeout=ENDPOINT_TIMEOUT)
            finally:
                await close_llm(self.ctx.llm)
        return asyncio.run(wrapper())

    def setUp(self):
        skip_unless_endpoint()
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
    """端点可达性探针（不可达时 skip，不算失败）。"""
    skip_unless_endpoint()
    import urllib.request
    urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=5)


if __name__ == "__main__":
    unittest.main()


def test_assistant_message_without_tool_calls_maps_cleanly():
    """多轮会话回归：没有 tool_calls 的 assistant 消息不能带 tool_calls=None。

    langchain-core 1.x 的 AIMessage 用 pydantic 校验该字段，None 会被拒绝，
    结果是用户在第二句话时直接收到 ValidationError。
    """
    from langchain_core.messages import AIMessage

    from openharness.api.client import to_langchain_messages

    out = to_langchain_messages([{"role": "assistant", "content": "hi"}])
    assert isinstance(out[0], AIMessage)
    assert out[0].tool_calls == []
    assert out[0].content == "hi"


def test_assistant_tool_call_and_tool_result_mapping():
    from openharness.api.client import to_langchain_messages

    out = to_langchain_messages([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "name": "Read", "arguments": {"file_path": "a.txt"}}]},
        {"role": "tool", "tool_call_id": "call_1", "name": "Read", "content": "x"},
    ])
    assert out[0].tool_calls[0]["name"] == "Read"
    assert out[0].tool_calls[0]["args"] == {"file_path": "a.txt"}
    assert out[1].tool_call_id == "call_1"
