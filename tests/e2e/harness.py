"""用户视角的驱动层：以真实子进程启动 openharness CLI。

每个用例在自己的临时工作目录里跑，运行时状态落在 `<ws>/.oh/`，
不碰仓库根的 `.oh/`（那里是真人使用的状态）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OH = ".oh"


def has_live_key() -> bool:
    """真实模型链路是否可用（e2e 里的 live 用例需要）。"""
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def oh(ws: Path) -> Path:
    return ws / OH


def _env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "OH_DIR"}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env["PYTHONIOENCODING"] = "utf-8"
    # 强制走 input() 分支：管道环境下 prompt_toolkit 不可用，行为必须可预测
    env["OPENHARNESS_PLAIN_INPUT"] = "1"
    if extra:
        env.update(extra)
    return env


@dataclass
class CLIRun:
    args: list[str]
    rc: int
    out: str
    err: str
    elapsed: float

    @property
    def text(self) -> str:
        return self.out + self.err

    def tool_calls(self) -> list[str]:
        """从事件流里抽出模型实际调用的工具名，按出现顺序。

        REPL 模式下提示符 `🧑 你: ` 不带换行，工具事件可能和它挤在同一行，
        所以按「行内出现」而不是「行首匹配」来抽。
        """
        names = []
        for line in self.text.splitlines():
            if "调用工具" not in line:
                continue
            rest = line.split("调用工具", 1)[1].strip()
            if rest:
                names.append(rest.split()[0])
        return names

    def assert_tool(self, name: str) -> None:
        assert name in self.tool_calls(), f"未触发工具 {name}；实际: {self.tool_calls()}\n{self.text[-3000:]}"


def run_cli(
    args: list[str],
    ws: Path,
    *,
    input_text: str | None = None,
    timeout: float = 180,
    env_extra: dict | None = None,
    config: dict | None = None,
) -> CLIRun:
    """跑一次 `python -m openharness.cli`。input_text 模拟用户在 REPL 里敲的键。"""
    if config is not None:
        import json

        target = oh(ws)
        target.mkdir(parents=True, exist_ok=True)
        (target / "settings.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    started = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "openharness.cli", *args],
        cwd=str(ws),
        input=input_text if input_text is not None else "",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=_env(env_extra),
    )
    return CLIRun(args=args, rc=proc.returncode, out=proc.stdout, err=proc.stderr,
                  elapsed=time.time() - started)



def pty_env(extra: dict | None = None) -> dict:
    """PTY 用例的环境：保留 TTY 判定，不要强制降级到 input()。"""
    env = _env(extra)
    env.pop("OPENHARNESS_PLAIN_INPUT", None)
    return env
