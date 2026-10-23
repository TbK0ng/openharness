"""LLM 客户端 — 用 LangChain 接入 OpenAI 兼容端点（LM Studio / DeepSeek）。

对应教程第 4 章的 `stream_response(messages, tools)` 抽象：
把 OpenHarness 的消息字典格式 ↔ LangChain 消息对象互转，
并把 OpenAI 的 finish_reason="tool_calls" 映射为教程的 stop_reason="tool_use"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from .registry import PROVIDERS, discover_model, resolve_provider, sanitize_proxy_env


@dataclass
class LLMResponse:
    """一次 LLM 调用的结果（教程第 4 章的 response）。"""
    text: str = ""
    stop_reason: str = "end_turn"          # "tool_use" | "end_turn" | "max_tokens"
    tool_calls: List[dict] = field(default_factory=list)   # [{"id","name","arguments"}]
    usage: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return self.stop_reason == "tool_use"


def build_llm(config: dict) -> ChatOpenAI:
    """构建 LangChain ChatOpenAI 客户端。

    支持 LM Studio（本地）与 DeepSeek（云端），两者都走 OpenAI 兼容协议；
    由 `config["provider"]` 决定 base_url / 模型名 / 密钥来源。

    注意：timeout 必须传 httpx.Timeout（不可哈希），否则 langchain-openai
    会走 lru_cache 复用同一个底层 httpx 客户端，导致多实例共享/误关。
    """
    sanitize_proxy_env()
    m = resolve_provider(config)

    # 本地端点（LM Studio）模型名会随加载的模型变化，留空则自动发现。
    if not m.get("model"):
        if not m.get("discover"):
            raise ValueError(
                f"provider {m['provider']!r} 需要显式配置 model（例如 deepseek-flash）")
        m["model"] = discover_model(m["base_url"], m.get("api_key") or "lm-studio")

    if not m.get("api_key"):
        env_name = PROVIDERS.get(m["provider"], {}).get("api_key_env")
        hint = f"设置环境变量 {env_name} 或在 settings.json 里填写 api_key" if env_name \
            else "在 settings.json 里填写 api_key"
        raise ValueError(f"provider {m['provider']!r} 缺少 API key：{hint}")

    timeout = m.get("timeout", 300)
    if not isinstance(timeout, httpx.Timeout):
        timeout = httpx.Timeout(timeout)
    return ChatOpenAI(
        base_url=m["base_url"],
        api_key=m["api_key"],
        model=m["model"],
        temperature=m.get("temperature", 0.2),
        timeout=timeout,
        # 重试统一由 engine/recovery.py 负责：SDK 再自己重试一次会叠加放大，
        # 也会把连续 5xx 吞掉，导致「连续故障切换备用模型」永远不会触发。
        max_retries=0,
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
            content = msg.get("content", "") or ""
            raw_calls = msg.get("tool_calls") or []
            if raw_calls:
                out.append(AIMessage(content=content, tool_calls=[
                    {"name": tc["name"], "args": tc.get("arguments") or {}, "id": tc["id"]}
                    for tc in raw_calls
                ]))
            else:
                # 传 tool_calls=None 会被 langchain-core 的 pydantic 校验拒绝，
                # 导致第二轮对话直接失败；没有工具调用时就不要带这个字段。
                out.append(AIMessage(content=content))
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
    finish = (getattr(ai, "response_metadata", None) or {}).get("finish_reason", "")
    if tool_calls:
        stop_reason = "tool_use"
    elif finish == "length":
        stop_reason = "max_tokens"      # Path 1：输出截断
    else:
        stop_reason = "end_turn"
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


async def stream_response(context, max_tokens: int = None) -> LLMResponse:
    """教程第 4 章第 1 步：把消息发给 LLM，获取响应。

    context 需提供: llm (ChatOpenAI), messages (dict 列表), tool_schemas, on_text。
    max_tokens: Path 1 升级后的输出上限（None 用模型默认）。
    """
    llm = context.llm
    lc_messages = to_langchain_messages(
        [{"role": "system", "content": context.system_prompt}] + context.messages
    )
    # 顺序很重要：bind_tools 之后必须再 bind，否则 model / max_tokens 会被丢掉
    # （RunnableBinding.bind_tools 会重建绑定，前面的 kwargs 不保留）。
    if context.tool_schemas:
        llm = llm.bind_tools(context.tool_schemas)
    # Path 3：备用模型切换（recovery_state.current_model）
    st = getattr(context, "recovery_state", None)
    if st is not None and getattr(st, "current_model", None):
        llm = llm.bind(model=st.current_model)
    if max_tokens is not None:
        llm = llm.bind(max_tokens=max_tokens)
    ai = await llm.ainvoke(lc_messages)
    response = _from_langchain(ai)
    if response.text:
        context.on_text(response.text)
    return response


async def llm_complete(context, prompt: str) -> str:
    """不带工具的纯文本补全（供 hook 的 prompt 事件与压缩使用；在事件循环内 await）。"""
    from langchain_core.messages import HumanMessage, SystemMessage
    ai = await context.llm.ainvoke(
        [SystemMessage(content="You are a helpful assistant."),
         HumanMessage(content=prompt)]
    )
    return ai.content if isinstance(ai.content, str) else str(ai.content)
