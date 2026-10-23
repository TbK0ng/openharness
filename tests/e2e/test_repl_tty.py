"""真实终端（ConPTY）下的交互体验：Tab 补全、↑ 历史、双击 Esc、Ctrl+C/D、审批弹窗。

限制（已实测）：ConPTY 的字节流只包含 prompt_toolkit 的行内重绘，
`/` 补全菜单和底部状态栏这两块浮动区域不会出现在捕获流里。因此这里验证
「按键行为」与「它们的数据源」（`match_commands` / `_status_text`），
浮动区域的观感需要人工看一眼真实终端。
"""
from __future__ import annotations

import sys

import pytest

from . import pty as ptymod
from .harness import has_live_key, pty_env

pytestmark = pytest.mark.skipif(not ptymod.available,
                                reason="需要 pywinpty（ConPTY）才能驱动真实终端")

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")


def spawn(ws, *args):
    argv = [sys.executable, "-m", "openharness.cli", *args]
    term = ptymod.PTY(argv, ws, pty_env(), cols=140, rows=45)
    term.wait_for("🧑 你:", timeout=40)
    return term


def _engine(tmp_path):
    from openharness.engine.query_engine import Engine

    ws = tmp_path / "ws"
    ws.mkdir()
    return Engine(cwd=str(ws))


def test_prompt_is_rendered_in_a_real_terminal(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        body = term.wait_for("输入你的请求", timeout=20)
        assert "🧑 你:" in body
        term.send("\x04")
        term.wait_for("再见", timeout=10)


def test_status_bar_reports_mode_model_tools_and_session(tmp_path):
    engine = _engine(tmp_path)
    from openharness.ui.repl import _status_text

    text = _status_text(engine)
    assert "default" in text
    assert "deepseek-flash" in text, "状态栏应显示解析后的模型名"
    assert "39 tools" in text
    assert "Tab 补全" in text


def test_slash_menu_data_covers_every_command(tmp_path):
    from openharness.ui.repl import match_commands

    engine = _engine(tmp_path)
    everything = match_commands(engine.commands.list(), "")
    assert len(everything) == 19
    assert all(c.help_text for c in everything)
    filtered = match_commands(engine.commands.list(), "per")
    assert [c.name for c in filtered][0] == "permission"
    assert "mode" in [c.name for c in match_commands(engine.commands.list(), "mo")]


def test_tab_completes_mode_argument_and_runs(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send("/mode fu")
        term.pause()
        term.send("\t")                    # Tab 补全成 full-auto
        term.pause()
        term.send("\r")
        term.wait_for(r"权限模式 -> full-auto", timeout=15)
        term.send("\x04")
        term.wait_for("再见", timeout=10)


def test_up_arrow_replays_previous_command(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send_line("/mode plan")
        term.wait_for("权限模式 -> plan", timeout=15)
        term.wait_quiet(quiet=0.4)
        mark = term.mark()
        term.send("\x1b[A")                # ↑ 取回上一条
        term.pause()
        term.send("\r")
        term.wait_since(mark, "权限模式 -> plan", timeout=15)
        term.send("\x04")
        term.wait_for("再见", timeout=10)


def test_ctrl_c_cancels_current_input_and_keeps_session(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send("半截输入")
        term.pause()
        term.send("\x03")                  # Ctrl+C 取消
        term.pause()
        term.send_line("/mode plan")
        term.wait_for("权限模式 -> plan", timeout=15)
        term.send("\x04")
        term.wait_for("再见", timeout=10)


def test_unknown_slash_command_hints_in_terminal(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send_line("/mod")
        term.wait_for("你是想输入 /mode 吗", timeout=15)
        term.send("\x04")
        term.wait_for("再见", timeout=10)


@live
@requires_live
def test_double_esc_rewinds_last_turn(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        mark = term.mark()
        term.send_line("只回复两个字：收到")
        term.wait_since(mark, r"\[assistant\] 收到", timeout=120)
        term.wait_since(mark, "🧑 你:", timeout=30)   # 下一轮提示符就绪
        term.send("\x1b")                  # Esc Esc（分两次发送，连写会被当成粘贴）
        term.pause(0.3)
        term.send("\x1b")
        body = term.wait_since(mark, "已回退", timeout=20)
        assert "收到" in body
        term.send("\x03")                  # 回退会把原输入放回编辑框，先取消再退出
        term.pause(0.3)
        term.send("\x04")
        term.wait_for("再见", timeout=10)


@live
@requires_live
def test_permission_prompt_then_always_allow(tmp_path):
    """default 模式下写操作弹审批；按 a 后同类操作不再询问。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send_line("用 Write 工具创建 hello.txt，内容写 hi")
        term.wait_for("Allow this operation?", timeout=120)
        assert "选择 [y/a/N]" in term.text
        term.send_line("a")
        term.wait_for("已在当前会话自动允许工具 Write", timeout=120)
        term.wait_for(r"\[assistant\]", timeout=120)
        assert (ws / "hello.txt").read_text(encoding="utf-8").strip() == "hi"

        mark = term.mark()
        term.send_line("再用 Write 创建 second.txt，内容写 ok")
        term.wait_since(mark, r"\[assistant\]", timeout=120)
        assert "Allow this operation?" not in term.since(mark), "按过 a 之后不应再弹 Write 的审批"
        assert (ws / "second.txt").exists()
        term.send("\x04")
        term.wait_for("再见", timeout=10)


@live
@requires_live
def test_permission_answer_y_allows_only_that_call(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send_line("用 Write 创建 once.txt 内容写 ok")
        term.wait_for("Allow this operation?", timeout=120)
        term.send_line("y")
        term.wait_for(r"\[assistant\]", timeout=120)
        assert (ws / "once.txt").exists()

        mark = term.mark()
        term.send_line("用 Write 创建 twice.txt 内容写 ok")
        term.wait_since(mark, "Allow this operation?", timeout=120)
        term.send_line("N")
        term.wait_since(mark, r"\[assistant\]", timeout=120)
        assert not (ws / "twice.txt").exists(), "y 只授权当次调用"
        term.send("\x04")
        term.wait_for("再见", timeout=10)


@live
@requires_live
def test_permission_allow_command_skips_prompt(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send_line("/permission allow Write")
        term.wait_quiet(quiet=0.4)
        mark = term.mark()
        term.send_line("用 Write 创建 allowed.txt 内容写 ok")
        term.wait_since(mark, r"\[assistant\]", timeout=120)
        assert "Allow this operation?" not in term.since(mark)
        assert (ws / "allowed.txt").exists()
        term.send("\x04")
        term.wait_for("再见", timeout=10)


@live
@requires_live
def test_ask_user_question_tool_reaches_the_terminal(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        term.send_line("用 AskUserQuestion 问我：今天几号？")
        term.wait_for("今天几号", timeout=120)
        term.send_line("22 号")
        term.wait_since(0, r"\[assistant\]", timeout=120)
        assert "22" in term.text
        term.send("\x04")
        term.wait_for("再见", timeout=10)


def test_mode_menu_number_switches_in_terminal(tmp_path):
    """终端里 /mode 不给参数会弹编号菜单，输入序号即切换。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    with spawn(ws) as term:
        mark = term.mark()
        term.send_line("/mode")
        term.wait_since(mark, "选择模式", timeout=15)
        term.send_line("2")
        term.wait_since(mark, r"权限模式 -> plan", timeout=15)
        term.send("\x04")
        term.wait_for("再见", timeout=10)
