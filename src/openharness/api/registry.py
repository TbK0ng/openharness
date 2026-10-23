"""LLM 供应商注册表 — provider 预设、配置解析、模型发现。

所有 provider 都走 OpenAI 兼容协议，`build_llm` 只消费这里解析出的平面参数：

    provider 预设  →  base_url / model / api_key_env
    显式配置       →  覆盖预设（空串视为「未设置」）

新增 provider 只需在 `PROVIDERS` 里加一条预设。
"""
from __future__ import annotations

import os

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


def sanitize_proxy_env() -> None:
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
