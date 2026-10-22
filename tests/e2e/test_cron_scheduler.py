"""cron 调度器真实触发：进程活着时按分钟跑一次，输出落到 cron.log。"""
from __future__ import annotations

import sys
import time

import pytest

from . import pty as ptymod
from .harness import oh, pty_env

pytestmark = pytest.mark.skipif(not ptymod.available,
                                reason="需要 pywinpty（ConPTY）才能让进程保持存活")

live = pytest.mark.live


@live
def test_scheduler_fires_on_its_own(tmp_path):
    """不手动 /cron run，等调度线程自己到点触发（最长 100 秒）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    term = ptymod.PTY([sys.executable, "-m", "openharness.cli"], ws, pty_env(),
                      cols=120, rows=40)
    try:
        term.wait_for("🧑 你:", timeout=40)
        term.send_line("/cron add */1 * * * * command echo cron-firing-e2e")
        term.wait_for("已创建", timeout=20)

        log = oh(ws) / "data" / "cron.log"
        deadline = time.time() + 100
        while time.time() < deadline:
            if log.exists() and "cron-firing-e2e" in log.read_text(
                    encoding="utf-8", errors="replace"):
                break
            time.sleep(1)
        assert log.exists(), "cron.log 没有生成"
        assert "cron-firing-e2e" in log.read_text(encoding="utf-8", errors="replace")
    finally:
        term.close()
