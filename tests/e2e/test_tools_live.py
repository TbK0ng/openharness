"""39 个工具逐个经真实模型触发。

按域分场景，每个场景一次 CLI 调用（省 token），模块级 fixture 跑一次，
各用例断言自己的切片。最后一个用例检查「39 个工具一个不漏」。
"""
from __future__ import annotations

import json

import pytest

from .harness import ROOT, has_live_key, oh, run_cli

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")

MCP_STUB = ROOT / "tests" / "fixtures" / "fake_mcp_server.py"

NOTEBOOK = {
    "cells": [
        {"cell_type": "code", "metadata": {}, "source": ["print('old')\n"], "outputs": [],
         "execution_count": None},
        {"cell_type": "markdown", "metadata": {}, "source": ["# title\n"]},
    ],
    "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                "name": "python3"}},
    "nbformat": 4, "nbformat_minor": 5,
}

SCENARIOS: list[tuple[str, str, dict]] = [
    ("files",
     "用 Glob 找 *.md，用 Grep 搜 alpha，用 Read 读 note.txt 的第一行，"
     "用 Write 创建 out.txt 内容写 done，再用 Edit 把 out.txt 里的 done 改成 edited。",
     {}),
    ("bash", "用 Bash 工具执行 echo oh-bash-ok，然后回复输出。", {}),
    ("memory",
     "用 MemorySave 记住一条 memory：type=project，name=build，内容「依赖用 uv 管理」。"
     "然后用 MemorySearch 查 uv，再 MemoryDelete 删掉 build。",
     {}),
    ("board",
     "用 CreateTask 建任务 A（描述 task-A）和任务 B，B 的 blocked_by 设为 A 的 id。"
     "然后 ListTasks，GetTask A，ClaimTask B（预期失败），CompleteTask A，再 ClaimTask B。",
     {}),
    ("background",
     "严格按顺序调用这五个工具，一个都不要跳过（任务 id 固定是 task-1）：\n"
     "1) TaskCreate，参数 kind=command、command=Start-Sleep 60、description=bg-probe\n"
     "2) TaskGet，参数 task_id=task-1\n"
     "3) TaskList\n"
     "4) TaskStop，参数 task_id=task-1\n"
     "5) TaskUpdate，参数 task_id=task-1、status=finished",
     {}),
    ("meta",
     "依次用这些工具：TodoWrite 写一条待办；ToolSearch 搜 memory；EnterPlanMode；ExitPlanMode。",
     {}),
    ("notebook",
     "用 NotebookEdit 把 nb.ipynb 第 0 个 cell 的源码改成 print('new')。", {}),
    ("web",
     "用 WebSearch 搜索 python 3.13 release date，然后用 WebFetch 抓取 "
     "https://example.com 并说出 page 标题。", {}),
    ("cron",
     "用 CronCreate 建一个每 5 分钟跑 command `echo tool-cron` 的任务，"
     "然后 CronList，再 CronDelete 把它删掉。", {}),
    ("worktree",
     "用 EnterWorktree 建一个名为 probe 的隔离工作区，然后 ExitWorktree 返回。", {}),
    ("compact",
     "先用 Read 读 note.txt，然后用 Compact 工具把对话压缩成摘要，再回复「压缩完成」。", {}),
    ("mcp",
     "严格做这三步，一步都不要跳过：\n"
     "1) ListMcpResources 列出全部资源；\n"
     "2) MCPTool，参数 server=stub、tool=echo、arguments={\"text\": \"hi-mcp\"}；\n"
     "3) ReadMcpResource，参数 server=stub、uri=demo://greeting。\n"
     "最后回复三步各自的结果。",
     {"mcp": True}),
]


# 每个场景必须真实触发的工具（模型偶尔漏调，fixture 会整个场景重跑一次）
REQUIRED: dict[str, list[str]] = {
    "files": ["Glob", "Grep", "Read", "Write", "Edit"],
    "bash": ["Bash"],
    "memory": ["MemorySave", "MemorySearch", "MemoryDelete"],
    "board": ["CreateTask", "ListTasks", "GetTask", "ClaimTask", "CompleteTask"],
    "background": ["TaskCreate", "TaskGet", "TaskList", "TaskStop", "TaskUpdate"],
    "meta": ["TodoWrite", "ToolSearch", "EnterPlanMode", "ExitPlanMode"],
    "notebook": ["NotebookEdit"],
    "web": ["WebSearch", "WebFetch"],
    "cron": ["CronCreate", "CronList", "CronDelete"],
    "worktree": ["EnterWorktree", "ExitWorktree"],
    "compact": ["Compact"],
    "mcp": ["ListMcpResources", "MCPTool", "ReadMcpResource"],
}


def _seed(ws, spec):
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "note.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (ws / "readme.md").write_text("# hi\n", encoding="utf-8")
    (ws / "nb.ipynb").write_text(json.dumps(NOTEBOOK), encoding="utf-8")
    if spec.get("mcp"):
        import sys

        (oh(ws)).mkdir(parents=True, exist_ok=True)
        (oh(ws) / "mcp.json").write_text(json.dumps({"mcpServers": {
            "stub": {"command": sys.executable, "args": [str(MCP_STUB)]}}}),
            encoding="utf-8")


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    if not has_live_key():
        pytest.skip("需要 DEEPSEEK_API_KEY")
    base = tmp_path_factory.mktemp("tools")
    out: dict[str, object] = {}
    for name, prompt, spec in SCENARIOS:
        if spec.get("mcp") and not MCP_STUB.exists():
            out[name] = None
            continue
        ws = base / name
        _seed(ws, spec)
        for _attempt in range(2):
            r = run_cli([prompt, "--no-banner", "--mode", "full-auto",
                         "--max-turns", "14"], ws, timeout=300)
            if not set(REQUIRED.get(name, [])) - set(r.tool_calls()):
                break
        out[name] = (r, ws)
    return out


def _run(runs, name):
    entry = runs[name]
    if entry is None:
        pytest.skip(f"{name} 场景缺少依赖")
    return entry


def test_file_tools(runs):
    r, ws = _run(runs, "files")
    for tool in ("Glob", "Grep", "Read", "Write", "Edit"):
        r.assert_tool(tool)
    assert (ws / "out.txt").read_text(encoding="utf-8").strip() == "edited"


def test_bash(runs):
    r, _ = _run(runs, "bash")
    r.assert_tool("Bash")
    assert "oh-bash-ok" in r.out


def test_memory_tools(runs):
    r, ws = _run(runs, "memory")
    for tool in ("MemorySave", "MemorySearch", "MemoryDelete"):
        r.assert_tool(tool)
    assert not (oh(ws) / "memory" / "project_build.md").exists(), "MemoryDelete 没删掉文件"


def test_task_board_dag(runs):
    r, _ = _run(runs, "board")
    for tool in ("CreateTask", "ListTasks", "GetTask", "ClaimTask", "CompleteTask"):
        r.assert_tool(tool)
    assert "blocked by unfinished" in r.out, "依赖未完成时 ClaimTask 应该失败"


def test_background_tasks(runs):
    r, _ = _run(runs, "background")
    for tool in ("TaskCreate", "TaskGet", "TaskList", "TaskStop", "TaskUpdate"):
        r.assert_tool(tool)


def test_meta_tools(runs):
    r, _ = _run(runs, "meta")
    for tool in ("TodoWrite", "ToolSearch", "EnterPlanMode", "ExitPlanMode"):
        r.assert_tool(tool)


def test_notebook_edit(runs):
    r, ws = _run(runs, "notebook")
    r.assert_tool("NotebookEdit")
    nb = json.loads((ws / "nb.ipynb").read_text(encoding="utf-8"))
    assert "new" in "".join(nb["cells"][0]["source"])


def test_web_tools(runs):
    r, _ = _run(runs, "web")
    r.assert_tool("WebSearch")
    r.assert_tool("WebFetch")
    assert "search failed" not in r.out or "example.com" in r.out.lower()


def test_cron_tools(runs):
    r, ws = _run(runs, "cron")
    for tool in ("CronCreate", "CronList", "CronDelete"):
        r.assert_tool(tool)
    data = oh(ws) / "data" / "cron.json"
    if data.exists():
        assert "tool-cron" not in data.read_text(encoding="utf-8")


def test_worktree_tools(runs):
    r, ws = _run(runs, "worktree")
    r.assert_tool("EnterWorktree")
    r.assert_tool("ExitWorktree")
    assert (oh(ws) / "worktrees" / "probe").exists(), "worktree 目录应保留"


def test_compact_tool(runs):
    r, _ = _run(runs, "compact")
    r.assert_tool("Compact")
    assert "压缩完成" in r.out


def test_mcp_tools(runs):
    r, _ = _run(runs, "mcp")
    for tool in ("ListMcpResources", "MCPTool", "ReadMcpResource"):
        r.assert_tool(tool)
    assert "未配置 MCP" not in r.out


def test_every_registered_tool_was_exercised(runs):
    """39 个工具必须每个都在这套 e2e 里被真实触发过。"""
    from openharness.tools import register_builtin_tools
    from openharness.tools.base import ToolRegistry

    reg = ToolRegistry()
    register_builtin_tools(reg)
    registered = {t.name for t in reg.list_tools()}
    assert len(registered) == 39

    exercised: set[str] = set()
    for name, _, _ in SCENARIOS:
        entry = runs.get(name)
        if entry is None:
            continue
        exercised.update(entry[0].tool_calls())
    # 这三个由 test_subsystems / test_agents / test_repl_tty 覆盖
    exercised |= {"Skill", "Agent", "SendMessage", "AskUserQuestion"}

    assert registered - exercised == set(), f"这些工具没有被任何 e2e 场景触发：{registered - exercised}"
