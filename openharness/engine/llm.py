"""LLM 客户端 — 用 LangChain 接入 127.0.0.1:1234（LM Studio, OpenAI 兼容）。

对应教程第 4 章的 `stream_response(messages, tools)` 抽象：
把 OpenHarness 的消息字典格式 ↔ LangChain 消息对象互转，
并把 OpenAI 的 finish_reason="tool_calls" 映射为教程的 stop_reason="tool_use"。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

DEFAULT_MODEL_CONFIG = {
    "base_url": "http://127.0.0.1:1234/v1",
    "api_key": "lm-studio",          # LM Studio 接受任意非空 key
    "model": "Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf",
    "temperature": 0.2,
    "timeout": 300,
    "max_retries": 2,
}


def _sanitize_proxy_env() -> None:
    """规范化 NO_PROXY：httpx2（openai SDK 的依赖）会把 '[::1]' 包成非法 URL 'all://[[::1]]'。
    去掉 IPv6 条目的方括号并去重；代理配置本身保持不变，127.0.0.1 仍走直连。"""
    for var in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(var)
        if not value:
            continue
        parts = []
        for entry in value.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith("[") and entry.endswith("]"):
                entry = entry[1:-1]
            if entry and entry not in parts:
                parts.append(entry)
        os.environ[var] = ",".join(parts)


@dataclass
class LLMResponse:
    """一次 LLM 调用的结果（教程第 4 章的 response）。"""
    text: str = ""
    stop_reason: str = "end_turn"          # "tool_use" | "end_turn"
    tool_calls: List[dict] = field(default_factory=list)   # [{"id","name","arguments"}]
    usage: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return self.stop_reason == "tool_use"


def build_llm(config: dict) -> ChatOpenAI:
    """构建 LangChain ChatOpenAI 客户端（指向本地 LM Studio 端点）。

    注意：timeout 必须传 httpx.Timeout（不可哈希），否则 langchain-openai
    会走 lru_cache 复用同一个底层 httpx 客户端，导致多实例共享/误关。
    """
    _sanitize_proxy_env()
    m = dict(DEFAULT_MODEL_CONFIG)
    m.update(config.get("model", {}))
    timeout = m.get("timeout", 300)
    if not isinstance(timeout, httpx.Timeout):
        timeout = httpx.Timeout(timeout)
    return ChatOpenAI(
        base_url=m["base_url"],
        api_key=m.get("api_key", "lm-studio"),
        model=m["model"],
        temperature=m.get("temperature", 0.2),
        timeout=timeout,
        max_retries=m.get("max_retries", 2),
    )


def to_langchain_messages(messages: List[dict]) -> list:
    """OpenHarness 消息字典 → LangChain 消息对象。"""
    out = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            out.append(SystemMessage(content=msg.get("content", "")))
        elif role == "user":
            out.append(HumanMessage(content=msg.get("content", "")))
        elif role == "assistant":
            tool_calls = None
            if msg.get("tool_calls"):
                tool_calls = [
                    {"name": tc["name"], "args": tc.get("arguments") or {}, "id": tc["id"]}
                    for tc in msg["tool_calls"]
                ]
            out.append(AIMessage(content=msg.get("content", "") or "", tool_calls=tool_calls))
        elif role == "tool":
            out.append(ToolMessage(content=msg.get("content", ""), tool_call_id=msg.get("tool_call_id", "")))
    return out


def _from_langchain(ai: AIMessage) -> LLMResponse:
    tool_calls = []
    for tc in ai.tool_calls or []:
        tool_calls.append({
            "id": tc.get("id") or f"call_{len(tool_calls)}",
            "name": tc["name"],
            "arguments": tc.get("args") or {},
        })
    stop_reason = "tool_use" if tool_calls else "end_turn"
    usage = {}
    um = getattr(ai, "usage_metadata", None)
    if um:
        usage = {"input_tokens": um.get("input_tokens", 0),
                 "output_tokens": um.get("output_tokens", 0),
                 "total_tokens": um.get("total_tokens", 0)}
    return LLMResponse(text=ai.content or "", stop_reason=stop_reason,
                       tool_calls=tool_calls, usage=usage)


async def close_llm(llm: ChatOpenAI) -> None:
    """关闭底层 httpx 客户端。

    langchain-openai 未暴露 close API；openai 客户端把 httpx 包装器
    存在 root_client / root_async_client 的 `_client` 属性里，这里直接关闭，
    避免事件循环关闭后出现 'Event loop is closed' / ResourceWarning。
    """
    for attr in ("root_client", "root_async_client"):
        root = getattr(llm, attr, None)
        if root is None:
            continue
        hc = getattr(root, "_client", None)
        if hc is None or getattr(hc, "is_closed", False):
            continue
        try:
            aclose = getattr(hc, "aclose", None)
            if aclose is not None:
                await aclose()
            elif hasattr(hc, "close"):
                hc.close()
        except Exception:
            pass


async def stream_response(context) -> LLMResponse:
    """教程第 4 章第 1 步：把消息发给 LLM，获取响应。

    context 需提供: llm (ChatOpenAI), messages (dict 列表), tool_schemas, on_text。
    """
    llm = context.llm
    lc_messages = to_langchain_messages(
        [{"role": "system", "content": context.system_prompt}] + context.messages
    )
    llm_with_tools = llm.bind_tools(context.tool_schemas) if context.tool_schemas else llm
    ai = await llm_with_tools.ainvoke(lc_messages)
    response = _from_langchain(ai)
    if response.text:
        context.on_text(response.text)
    return response
