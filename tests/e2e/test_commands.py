"""19 条斜杠命令：用户在 REPL 里逐条敲，检查真实输出。"""
from __future__ import annotations

import json
import re

from .harness import oh, run_cli

ALL_COMMANDS = [
    "help", "mode", "new", "fork", "side", "sessions", "switch", "rewind",
    "permission", "memory", "skills", "tasks", "cron", "tools", "mcp",
    "agents", "init", "clear", "exit",
]


def _repl(tmp_path, lines: list[str], name: str = "ws"):
    ws = tmp_path / name
    ws.mkdir()
    return ws, run_cli([], ws, input_text="\n".join([*lines, "/exit"]) + "\n")


def test_help_lists_every_registered_command(tmp_path):
    _, r = _repl(tmp_path, ["/help"])
    for name in ALL_COMMANDS:
        assert f"/{name}" in r.out, f"/help 漏了 /{name}"


def test_help_for_single_command(tmp_path):
    _, r = _repl(tmp_path, ["/help cron"])
    assert "/cron" in r.out and "定时任务" in r.out


def test_tools_lists_all_and_marks_write_scope(tmp_path):
    _, r = _repl(tmp_path, ["/tools"])
    assert "已注册 39 个工具" in r.out
    assert "[只读] Read" in r.out
    assert "[写入] Bash" in r.out


def test_empty_subsystems_report_clearly(tmp_path):
    _, r = _repl(tmp_path, ["/memory", "/skills", "/tasks", "/agents", "/mcp"])
    assert "（无记忆）" in r.out
    assert "（无技能）" in r.out
    assert "no background tasks" in r.out
    assert "（无子 Agent）" in r.out
    assert "未配置 MCP 服务器" in r.out


def test_cron_list_reports_scheduler_state(tmp_path):
    _, r = _repl(tmp_path, ["/cron list"])
    assert "调度器: 运行中" in r.out
    assert "（无定时任务）" in r.out


def test_mode_lists_then_switches(tmp_path):
    _, r = _repl(tmp_path, ["/mode", "/mode plan", "/mode full-auto", "/permission"])
    assert "当前权限模式: default" in r.out
    assert "权限模式 -> plan" in r.out
    assert "权限模式 -> full-auto" in r.out
    assert "模式      : full-auto" in r.out


def test_permission_allow_and_deny_are_reflected(tmp_path):
    _, r = _repl(tmp_path, ["/permission allow Bash", "/permission deny Write",
                            "/permission"])
    assert "自动允许  : Bash" in r.out
    assert "拒绝工具  : Write" in r.out


def test_permission_save_persists_to_settings(tmp_path):
    ws, r = _repl(tmp_path, ["/permission mode plan", "/permission save"])
    assert "权限模式" in r.out
    saved = json.loads((oh(ws) / "settings.json").read_text(encoding="utf-8"))
    assert saved["permissions"]["mode"] == "plan"


def test_permission_save_then_restart_keeps_mode(tmp_path):
    ws, _ = _repl(tmp_path, ["/permission mode plan", "/permission save"])
    r = run_cli([], ws, input_text="/exit\n")
    assert "权限模式: plan" in r.out


def test_init_creates_config_then_refuses_to_clobber(tmp_path):
    ws, r = _repl(tmp_path, ["/init", "/init"])
    assert "已生成" in r.out
    assert "配置已存在，未覆盖" in r.out
    cfg = json.loads((oh(ws) / "settings.json").read_text(encoding="utf-8"))
    assert cfg["provider"] == "deepseek"


def test_session_lifecycle_new_fork_side(tmp_path):
    _, r = _repl(tmp_path, ["/new e2e", "/fork f1", "/side", "/sessions", "/side off",
                            "/rewind", "/switch"])
    assert re.search(r"已开启新会话 \w+ \[main\] e2e", r.out)
    assert re.search(r"已从 \w+ 分叉出新会话 \w+ \[fork\] f1", r.out)
    assert re.search(r"已进入临时会话 \w+ \[side\]", r.out)
    assert "[main] e2e" in r.out and "[fork] f1" in r.out and "[side]" in r.out
    assert "已结束临时会话" in r.out
    assert "没有可回退的回合" in r.out
    assert "用法：/switch" in r.out


def test_clear_and_exit(tmp_path):
    _, r = _repl(tmp_path, ["/clear"])
    assert "已清空当前会话的消息历史" in r.out
    assert "再见 👋" in r.out
