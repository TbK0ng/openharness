"""错误恢复（s11）端到端：面对会 5xx / 截断 / 上下文溢出的端点，CLI 仍能给出答案。

用本地假端点（tests/e2e/fake_llm.py）制造故障，进程是真 CLI，配置是真配置。
"""
from __future__ import annotations

import json

from .fake_llm import FakeLLM, max_tokens_of
from .harness import run_cli


def _cfg(srv: FakeLLM, **extra) -> dict:
    cfg = {
        "base_url": srv.base_url,
        "api_key": "fake-key",
        "model": "fake-model",
        "retry_base_delay": 0,
        "max_retries": 6,
    }
    cfg.update(extra)
    return cfg


def _run(srv: FakeLLM, ws, **extra):
    return run_cli(["只回复 OK", "--no-banner"], ws, config=_cfg(srv, **extra),
                   timeout=120, env_extra={"NO_PROXY": "127.0.0.1,localhost",
                                           "no_proxy": "127.0.0.1,localhost"})


def test_transient_5xx_is_retried_then_succeeds(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("status", 503, "service temporarily unavailable"),
                  ("status", 503, "service temporarily unavailable"),
                  ("ok", "恢复成功")]) as srv:
        r = _run(srv, ws)
    assert r.rc == 0, r.text
    assert "恢复成功" in r.out
    assert len(srv.requests) == 3, "两次 5xx 之后应当重试到成功"


def test_three_5xx_switches_to_fallback_model(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("status", 503, "service temporarily unavailable")] * 3
                 + [("ok", "备用模型回答")]) as srv:
        r = _run(srv, ws, fallback_model="backup-model")
    assert r.rc == 0, r.text
    assert "备用模型回答" in r.out
    assert "切换备用模型 backup-model" in r.out, "用户应当看到降级提示"
    assert [q.get("model") for q in srv.requests][-1] == "backup-model"


def test_truncated_output_escalates_max_tokens(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("length", "半截"), ("ok", "完整回答")]) as srv:
        r = _run(srv, ws)
    assert r.rc == 0, r.text
    assert "完整回答" in r.out
    assert len(srv.requests) == 2
    first, second = (max_tokens_of(q) for q in srv.requests)
    assert second is not None and (first is None or second > first), \
        f"第二次请求应放大输出上限：{first} -> {second}"


def test_context_overflow_reactive_compact_then_retry(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("status", 400,
                   "This model's maximum context length is 8192 tokens"),
                  ("ok", "压缩后回答")]) as srv:
        r = _run(srv, ws)
    assert r.rc == 0, r.text
    assert "压缩后回答" in r.out
    assert len(srv.requests) == 2, "上下文溢出应先压缩再重试"
    assert len(srv.requests[1]["messages"]) <= len(srv.requests[0]["messages"])


def test_non_transient_error_is_not_retried(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("status", 401, "invalid api key")]) as srv:
        r = _run(srv, ws)
    assert r.rc == 1, r.text
    assert "invalid api key" in r.text.lower() or "请求失败" in r.out
    assert len(srv.requests) == 1, "401 不该重试"


def test_auto_compact_summarizes_when_threshold_crossed(tmp_path):
    """多轮对话里 token 估算越过 compact_threshold 时，历史应被摘要替换。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("ok", "好的")]) as srv:
        r = run_cli([], ws, config=_cfg(srv, compact_threshold=80), timeout=180,
                    input_text="\n".join(f"说第{i}句" for i in range(1, 6)) + "\n/exit\n")
    assert r.rc == 0, r.text
    assert len(srv.requests) >= 5
    last_messages = json.dumps(srv.requests[-1]["messages"], ensure_ascii=False)
    assert "[compacted history]" in last_messages, "越过阈值后应把早期历史摘要掉"
