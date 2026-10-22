"""子系统：插件、技能、钩子、MCP、cron、会话与记忆的持久化。"""
from __future__ import annotations

import json
import re
import sys
import time

import pytest

from .harness import ROOT, has_live_key, oh, run_cli

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")

PLUGIN_SRC = '''
from openharness.tools.base import BaseTool, ToolResult


class EchoTool(BaseTool):
    name = "Echo"
    description = "Echo the given text back."
    input_schema = {"type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"]}
    read_only = True

    async def execute(self, params, context):
        return ToolResult(output=params["text"])


PLUGIN = {"name": "extra", "description": "e2e 测试插件"}


def hello(args):
    return f"plugin-hello {args}".strip()


def register(ctx):
    ctx.register_tool(EchoTool())
    ctx.register_command("hello", "插件注册的命令", hello)
    ctx.register_skill("plug-skill", "# 插件技能\\n用 uv 跑测试。")
'''

SKILL_MD = """---
name: demo
description: 演示技能：回答颜色相关问题时先说「蓝色」
---

# 演示技能

当被问到喜欢的颜色时，必须回答「蓝色」。
"""


def test_plugin_adds_tool_command_and_skill(tmp_path):
    ws = tmp_path / "ws"
    (oh(ws) / "plugins").mkdir(parents=True)
    (oh(ws) / "plugins" / "extra.py").write_text(PLUGIN_SRC, encoding="utf-8")
    r = run_cli([], ws, input_text="/tools\n/hello world\n/skills\n/help\n/exit\n")
    assert "已注册 40 个工具" in r.out, "插件工具没有进入注册表"
    assert "[只读] Echo" in r.out
    assert "plugin-hello world" in r.out
    assert "插件注册的命令" in r.out, "插件命令没有进入 /help"


def test_skill_file_is_discovered_and_loaded(tmp_path):
    ws = tmp_path / "ws"
    (oh(ws) / "skills").mkdir(parents=True)
    (oh(ws) / "skills" / "demo.md").write_text(SKILL_MD, encoding="utf-8")
    r = run_cli([], ws, input_text="/skills\n/exit\n")
    assert "demo" in r.out
    assert "演示技能" in r.out


@live
@requires_live
def test_skill_tool_injects_instructions(tmp_path):
    ws = tmp_path / "ws"
    (oh(ws) / "skills").mkdir(parents=True)
    (oh(ws) / "skills" / "demo.md").write_text(SKILL_MD, encoding="utf-8")
    r = run_cli(["用 Skill 工具加载 demo 技能，然后回答你最喜欢什么颜色，只要颜色词"],
                ws, timeout=180)
    assert r.rc == 0, r.text
    r.assert_tool("Skill")
    assert "蓝色" in r.out


def test_hook_blocks_tool_and_reports_reason(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = {"hooks": {"pre_tool_use": [{
        "type": "command",
        "command": 'python -c "print(\'BLOCK: e2e-hook-says-no\')"',
        "match_tools": ["Write"],
    }]}}
    (oh(ws)).mkdir(parents=True, exist_ok=True)
    (oh(ws) / "settings.json").write_text(json.dumps(cfg), encoding="utf-8")
    if not has_live_key():
        pytest.skip("需要 DEEPSEEK_API_KEY")
    r = run_cli(["用 Write 工具创建 hooked.txt，内容写 hi", "--mode", "full-auto"],
                ws, timeout=180)
    assert "操作被 Hook 阻止" in r.out or "e2e-hook-says-no" in r.out, r.text
    assert not (ws / "hooked.txt").exists()


def test_mcp_server_connects_and_exposes_tools(tmp_path):
    """用仓库自带的 stdio stub 验证：连接、工具清单、原生工具注册。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    (oh(ws)).mkdir(parents=True, exist_ok=True)
    (oh(ws) / "mcp.json").write_text(json.dumps({"mcpServers": {
        "stub": {"command": sys.executable,
                 "args": [str(ROOT / "tests" / "mcp_stub_server.py")]}}}),
        encoding="utf-8")
    r = run_cli([], ws, input_text="/mcp\n/tools\n/exit\n", timeout=120)
    assert "stub: connected" in r.out, r.text
    assert "tools: echo, fail" in r.out
    assert "resources: demo://greeting" in r.out
    assert "mcp__stub__echo" in r.out, "原生 MCP 工具应注册进注册表"


def test_cron_add_run_and_log(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli([], ws,
                input_text="/cron add * * * * * command echo cron-e2e-tick\n"
                           "/cron list\n/exit\n")
    # 先拿到 id，再用真实 id 触发一次
    job_id = re.search(r"已创建 ([\w-]+):", r.out).group(1)
    assert "cron-e2e-tick" in r.out
    r2 = run_cli([], ws, input_text=f"/cron run {job_id}\n/exit\n")
    assert "已立即触发" in r2.out
    log = oh(ws) / "data" / "cron.log"
    deadline = time.time() + 20
    while time.time() < deadline:
        if log.exists() and "cron-e2e-tick" in log.read_text(encoding="utf-8",
                                                             errors="replace"):
            break
        time.sleep(0.3)
    assert log.exists(), "cron.log 没有生成"
    assert "cron-e2e-tick" in log.read_text(encoding="utf-8", errors="replace")
    r3 = run_cli([], ws, input_text=f"/cron delete {job_id}\n/cron list\n/exit\n")
    assert f"已删除 {job_id}" in r3.out
    assert "（无定时任务）" in r3.out


@live
@requires_live
def test_session_survives_process_restart(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r1 = run_cli(["记住数字 4242，只回复 OK", "--no-banner"], ws, timeout=180)
    assert "OK" in r1.out
    files = list((oh(ws) / "sessions").glob("*.json"))
    assert files, "会话没有落盘"

    r2 = run_cli([], ws, input_text="/sessions\n/exit\n")
    sid = re.search(r"(\w{8}) \[main\]", r2.out).group(1)
    assert "已保存" in r2.out, "重启后 /sessions 看不到落盘的会话"

    r3 = run_cli([], ws, input_text=f"/switch {sid}\n我刚才让你记住的数字是多少？只回复数字\n/exit\n",
                 timeout=180)
    assert "4242" in r3.out, "跨进程 /switch 之后模型看不到历史"


@live
@requires_live
def test_memory_survives_process_restart_and_is_injected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r1 = run_cli(["用 MemorySave 记住 type=project name=stack，内容「这个项目用 uv 管理依赖」",
                  "--no-banner", "--mode", "full-auto"], ws, timeout=180)
    r1.assert_tool("MemorySave")
    mem = oh(ws) / "memory" / "project_stack.md"
    assert mem.exists(), "记忆文件没有落盘"

    r2 = run_cli([], ws, input_text="/memory\n/exit\n")
    assert "stack" in r2.out

    r3 = run_cli(["这个项目的依赖用什么管理？只回复工具名", "--no-banner"], ws, timeout=180)
    assert "uv" in r3.out.lower(), "记忆索引没有注入 system prompt"


@live
@requires_live
def test_background_task_lifecycle_including_stop(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(
        ["用 TaskCreate 起一个 kind=command 的后台任务，命令是 PowerShell 的 "
         "'Start-Sleep 45'；然后立刻用 TaskStop 停掉它，再用 TaskList 列出",
         "--mode", "full-auto", "--max-turns", "8"],
        ws, timeout=240)
    r.assert_tool("TaskCreate")
    r.assert_tool("TaskStop")
    assert "stopped" in r.out.lower() or "已停止" in r.out
