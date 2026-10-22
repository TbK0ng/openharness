"""多 Agent：Agent 派发与 SendMessage 续聊。

回归点：子 Agent 必须在自己的事件循环里用自建 LLM 客户端。此前它复用父会话
的 httpx 客户端，跨事件循环调用会永久阻塞（`Agent` 工具调用卡死）。
"""
from __future__ import annotations

import re

import pytest

from .harness import has_live_key, run_cli

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")


@live
@requires_live
def test_agent_spawns_and_returns_without_deadlock(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(
        ["调用 Agent 工具，参数 description=probe、agent_type=explore、prompt=只回复 OK；"
         "然后把它返回的内容告诉我",
         "--mode", "full-auto", "--max-turns", "4"],
        ws, timeout=90)
    r.assert_tool("Agent")
    assert "OK" in r.out
    assert "subagent error" not in r.out.lower(), r.out


@live
@requires_live
def test_send_message_continues_existing_subagent(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    prompt_batch = (
        "调用 Agent 工具，参数 description=probe、agent_type=explore、prompt=回复 OK\n"
        "/agents\n"
        "调用 SendMessage 工具，参数 agent_id=agent-1、message=再回复一次 OK，然后告诉我结果\n"
        "/exit\n"
    )
    # 模型偶尔会只回文本、不调工具；这是模型侧抖动，重试一次整个场景
    for _ in range(2):
        r = run_cli(["--mode", "full-auto"], ws, input_text=prompt_batch, timeout=180)
        if "Agent" in r.tool_calls():
            break
    agent_id = re.search(r"(agent-\d+) \[explore\]", r.out)
    assert agent_id, r.out
    r.assert_tool("Agent")
    r.assert_tool("SendMessage")
    assert "no sub-agent" not in r.out
