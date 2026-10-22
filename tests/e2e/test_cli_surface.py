"""CLI 表面：参数、一次性 prompt、横幅、斜杠命令分派。

这些用例全部以子进程方式驱动真实 CLI —— 用户能看到的每一行输出都来自这里。
"""
from __future__ import annotations

import pytest

from .harness import has_live_key, run_cli

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")


def test_banner_reports_ready_state(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli([], ws, input_text="/exit\n")
    assert r.rc == 0, r.text
    assert "工作目录" in r.out
    assert "配置目录" in r.out
    assert "权限模式: default" in r.out
    assert "已注册工具: 39" in r.out
    assert "已保存会话: 0" in r.out


def test_no_prompt_enters_repl_and_exits_on_command(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli([], ws, input_text="/help\n/exit\n")
    assert r.rc == 0, r.text
    assert "输入你的请求" in r.out
    assert "再见 👋" in r.out
    assert "/permission" in r.out          # /help 列出了命令


def test_unknown_command_suggests_closest(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli([], ws, input_text="/mod\n/exit\n")
    assert "未知命令" in r.out
    assert "你是想输入 /mode 吗" in r.out


def test_bare_slash_shows_help(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli([], ws, input_text="/\n/exit\n")
    assert "未知命令" not in r.out
    assert "/tools" in r.out


@live
@requires_live
def test_one_shot_prompt_answers_then_exits(tmp_path):
    """一次性 prompt 必须跑完就退出，不落到 REPL（否则脚本/CI 会挂住）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(["只回复两个字：收到", "--no-banner"], ws, timeout=120)
    assert r.rc == 0, r.text
    assert "收到" in r.out
    assert "输入你的请求，或 /help" not in r.out, "一次性 prompt 后不应进入 REPL"
    assert "再见" not in r.out
    assert r.elapsed < 90


@live
@requires_live
def test_one_shot_full_auto_runs_real_tools(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    r = run_cli(
        ["读 note.txt，然后只回复第二行内容", "--no-banner", "--mode", "full-auto",
         "--max-turns", "5"],
        ws, timeout=180,
    )
    assert r.rc == 0, r.text
    assert "beta" in r.out
    assert r.tool_calls(), r.text
