"""CLI 参数与失败路径：--config / --cwd / --max-turns / --provider 的错误提示。"""
from __future__ import annotations

import json

import pytest

from .fake_llm import FakeLLM
from .harness import has_live_key, run_cli

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")


def test_config_flag_points_at_file(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = tmp_path / "custom.json"
    cfg.write_text(json.dumps({"permissions": {"mode": "plan"}}), encoding="utf-8")
    r = run_cli(["--config", str(cfg)], ws, input_text="/exit\n")
    assert "权限模式: plan" in r.out


def test_cwd_flag_changes_workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir(parents=True)
    r = run_cli(["--cwd", str(other)], ws, input_text="/exit\n")
    assert str(other) in r.out


def test_invalid_provider_is_rejected_by_argparse(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(["--provider", "nope"], ws, input_text="")
    assert r.rc == 2
    assert "invalid choice" in r.err.lower()


def test_missing_api_key_fails_with_readable_message(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(["只回复 OK", "--no-banner"],
                ws, env_extra={"DEEPSEEK_API_KEY": ""}, timeout=120)
    assert r.rc in (0, 1)
    assert "api_key" in r.text.lower() or "密钥" in r.text
    assert "Traceback" not in r.err


def test_unreachable_local_provider_reports_error_not_traceback(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(["只回复 OK", "--no-banner", "--provider", "lmstudio"],
                ws, timeout=120)
    assert "Traceback" not in r.err
    assert r.rc != 0 or "失败" in r.out


@live
@requires_live
def test_max_turns_stops_the_loop(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "many.txt").write_text("line1\nline2\n", encoding="utf-8")
    r = run_cli(["用 Bash 连续执行十条不同的 echo 命令", "--no-banner",
                 "--mode", "full-auto", "--max-turns", "1"], ws, timeout=180)
    # --max-turns 限制的是「回合」不是「工具调用数」：一回合可以并行发多个调用
    assert "已达到最大回合数" in r.out
    assert r.tool_calls()


def test_model_flag_overrides_settings(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with FakeLLM([("ok", "好")]) as srv:
        cfg = {"base_url": srv.base_url, "api_key": "k", "model": "from-settings",
               "retry_base_delay": 0, "max_retries": 3}
        r = run_cli(["只回复 OK", "--no-banner", "--model", "from-cli"], ws,
                    config=cfg, timeout=120,
                    env_extra={"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
    assert r.rc == 0, r.text
    assert srv.requests[-1]["model"] == "from-cli", "--model 应覆盖 settings 里的模型名"
