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
    # LM Studio 一次只加载一个模型，且模型名带量化后缀、换模型就变。
    # 留空表示「向端点查询当前已加载的模型」，避免硬编码失效。
    "model": "",
    "temperature": 0.2,
    "timeout": 300,
    "max_retries": 2,
}

# 供应商预设（均走 OpenAI 兼容协议）。`api_key_env` 是读取密钥的环境变量；
# 配置里的 `api_key` 优先级更高，留空时回退到环境变量。
PROVIDERS = {
    "lmstudio": {
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key": "lm-studio",      # 本地端点不校验
        "api_key_env": None,
        "model": "",                 # 留空 -> 自动发现已加载模型
        "discover": True,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "api_key_env": "DEEPSEEK_API_KEY",
        "model": "deepseek-flash",
        "discover": False,           # 云端模型名固定，不做发现
    },
}


def resolve_provider(config: dict) -> dict:
    """把平面配置解析成 build_llm 需要的完整参数。

    优先级：显式配置 > 供应商预设 > DEFAULT_MODEL_CONFIG。
    `base_url` / `api_key` / `model` 既可以写在顶层，也可以写在
    嵌套的 `model` 字典里（兼容旧格式）。
    """
    nested = config.get("model") if isinstance(config.get("model"), dict) else {}
    provider = config.get("provider") or "deepseek"
    preset = PROVIDERS.get(provider)
    if preset is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"未知 provider: {provider!r}（可选: {known}）")

    merged = dict(DEFAULT_MODEL_CONFIG)
    merged.update({k: v for k, v in preset.items() if k not in ("api_key_env", "discover")})
    merged["provider"] = provider
    merged["discover"] = preset.get("discover", False)
    # 旧格式把参数放在嵌套的 model 字典里；此时顶层 model 必须清空，
    # 否则会残留成 dict 并传给 ChatOpenAI。
    if nested:
        merged["model"] = ""

    # 显式覆盖：顶层优先于嵌套；空串视为「未设置」，让预设生效。
    # 顶层的 `model` 若仍是字典（旧格式），说明参数在嵌套层，不作覆盖。
    for key in ("base_url", "api_key", "model", "temperature", "timeout", "max_retries"):
        if nested.get(key) not in (None, ""):
            merged[key] = nested[key]
        top = config.get(key)
        if top not in (None, "") and not (key == "model" and isinstance(top, dict)):
            merged[key] = top

    if not merged.get("api_key") and preset.get("api_key_env"):
        merged["api_key"] = os.environ.get(preset["api_key_env"], "")
    return merged


def discover_model(base_url: str, api_key: str = "lm-studio", timeout: float = 5.0) -> str:
    """向 OpenAI 兼容端点查询当前（已加载的）模型 id。

    优先返回 status=loaded 的模型；查不到时返回空串，由调用方决定回退策略。
    """
    import json
    import urllib.request

    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    models = data.get("data") or []
    for m in models:
        status = (m.get("status") or {}).get("value")
        if status == "loaded":
            return m.get("id") or ""
    return (models[0].get("id") or "") if models else ""


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
    """构建 LangChain ChatOpenAI 客户端。

    支持 LM Studio（本地）与 DeepSeek（云端），两者都走 OpenAI 兼容协议；
    由 `config["provider"]` 决定 base_url / 模型名 / 密钥来源。

    注意：timeout 必须传 httpx.Timeout（不可哈希），否则 langchain-openai
    会走 lru_cache 复用同一个底层 httpx 客户端，导致多实例共享/误关。
    """
    _sanitize_proxy_env()
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
    # Path 3：备用模型切换（recovery_state.current_model）
    st = getattr(context, "recovery_state", None)
    if st is not None and getattr(st, "current_model", None):
        llm = llm.bind(model=st.current_model)
    if max_tokens is not None:
        llm = llm.bind(max_tokens=max_tokens)
    lc_messages = to_langchain_messages(
        [{"role": "system", "content": context.system_prompt}] + context.messages
    )
    llm_with_tools = llm.bind_tools(context.tool_schemas) if context.tool_schemas else llm
    ai = await llm_with_tools.ainvoke(lc_messages)
    response = _from_langchain(ai)
    if response.text:
        context.on_text(response.text)
    return response


async def llm_complete(context, prompt: str) -> str:
    """不带工具的纯文本补全（供 hook 的 prompt 事件使用；在事件循环内 await）。"""
    from langchain_core.messages import HumanMessage, SystemMessage
    ai = await context.llm.ainvoke(
        [SystemMessage(content="You are a helpful assistant."),
         HumanMessage(content=prompt)]
    )
    return ai.content if isinstance(ai.content, str) else str(ai.content)
