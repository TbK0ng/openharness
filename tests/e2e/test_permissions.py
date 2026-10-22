"""权限护栏：三级模式与细粒度拒绝规则，全部经真实模型发起操作。"""
from __future__ import annotations

import pytest

from .harness import has_live_key, run_cli

live = pytest.mark.live
requires_live = pytest.mark.skipif(not has_live_key(), reason="需要 DEEPSEEK_API_KEY")


def _denied(r) -> bool:
    """用户视角：被拦截时模型会转述原因，措辞不固定，只要求「说清了被拒」。"""
    text = r.out.lower()
    return any(k in text for k in
               ("deny rule", "权限不足", "permission", "denied", "拒绝", "被拒", "plan mode"))


def _cfg(mode="default", **extra):
    perms = {"mode": mode, "deny_tools": [], "deny_paths": [], "deny_commands": []}
    perms.update(extra)
    return {"permissions": perms}


@live
@requires_live
def test_plan_mode_blocks_writes_but_allows_reads(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("alpha\n", encoding="utf-8")
    r = run_cli(["用 Read 读 note.txt，然后用 Write 创建 plan-out.txt 内容写 x"],
                ws, config=_cfg("plan"), timeout=180)
    r.assert_tool("Read")
    assert "alpha" in r.out
    assert not (ws / "plan-out.txt").exists(), "plan 模式下不应该写出文件"
    assert _denied(r), r.text[-1500:]


@live
@requires_live
def test_deny_path_blocks_one_target_only(tmp_path):
    ws = tmp_path / "ws"
    (ws / "secret").mkdir(parents=True)
    r = run_cli(
        ["先用 Write 创建 secret/leak.txt 内容写 bad，再用 Write 创建 public.txt 内容写 ok"],
        ws, config=_cfg("full-auto", deny_paths=["secret/*"]), timeout=180)
    assert not (ws / "secret" / "leak.txt").exists()
    assert _denied(r), r.text[-1500:]
    assert (ws / "public.txt").exists(), "未被规则命中的路径应照常写入"


@live
@requires_live
def test_deny_command_regex_blocks_matching_bash(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    r = run_cli(["用 Bash 执行 echo blocked-echo"], ws,
                config=_cfg("full-auto", deny_commands=["echo"]), timeout=180)
    r.assert_tool("Bash")
    assert _denied(r), r.text[-1500:]
