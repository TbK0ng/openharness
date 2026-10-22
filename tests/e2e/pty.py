"""真实终端驱动（ConPTY）——用 pywinpty 起一个伪终端跑 CLI。

只有走真 TTY，prompt_toolkit 的 `/` 菜单、Tab 补全、↑↓ 历史、双击 Esc、
底部状态栏和权限审批弹窗才会出现；管道模式下它们全部降级。
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

try:  # pragma: no cover - 非 Windows 或无 pywinpty 时整组用例跳过
    import winpty
except ImportError:  # pragma: no cover
    winpty = None

ANSI = re.compile(
    r"\x1b\[[0-9;?]*[a-zA-Z]"      # CSI
    r"|\x1b\][^\x07]*\x07"          # OSC
    r"|\x1b[()][A-Z0-9]"            # charset
    r"|\x1b[=>NOM]"                 # 单字符序列
)

available = winpty is not None


def clean(raw: str) -> str:
    """去掉 ANSI 控制序列与回车，便于按可读文本断言。"""
    out = ANSI.sub("", raw).replace("\r", "")
    return re.sub(r"\n{3,}", "\n\n", out)


class PTY:
    """一个跑着 CLI 的伪终端。"""

    def __init__(self, argv: list[str], cwd: Path, env: dict,
                 cols: int = 120, rows: int = 40) -> None:
        self.proc = winpty.PtyProcess.spawn(
            argv, cwd=str(cwd), env=env, dimensions=(rows, cols))
        self._buf = ""
        self._lock = threading.Lock()
        self._alive = True
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        while self._alive:
            try:
                chunk = self.proc.read(8192)
            except EOFError:
                break
            except Exception:  # noqa: BLE001 - 进程退出时的各种 OSError
                break
            if not chunk:
                break
            with self._lock:
                self._buf += chunk

    # ---- 读 ----
    @property
    def raw(self) -> str:
        with self._lock:
            return self._buf

    @property
    def text(self) -> str:
        return clean(self.raw)

    def wait_for(self, pattern: str, timeout: float = 30, strip: bool = True) -> str:
        """等到输出里出现正则 pattern，返回当前（清理后的）全文。"""
        deadline = time.time() + timeout
        rx = re.compile(pattern)
        while time.time() < deadline:
            body = self.text if strip else self.raw
            if rx.search(body):
                return body
            if not self.proc.isalive():
                break
            time.sleep(0.05)
        raise AssertionError(
            f"等待 {pattern!r} 超时（{timeout}s）；当前输出：\n{self.text[-2500:]}")

    def wait_since(self, mark: int, pattern: str, timeout: float = 30) -> str:
        """等 mark 之后新产生的输出里出现 pattern。"""
        deadline = time.time() + timeout
        rx = re.compile(pattern)
        while time.time() < deadline:
            body = clean(self.raw[mark:])
            if rx.search(body):
                return body
            if not self.proc.isalive():
                break
            time.sleep(0.05)
        raise AssertionError(
            f"mark 之后未见 {pattern!r}（{timeout}s）；新增输出：\n"
            f"{clean(self.raw[mark:])[-1500:]}")

    def wait_quiet(self, quiet: float = 0.8, timeout: float = 60) -> str:
        """等到输出不再变化（用于「敲完键，等界面稳定」）。"""
        deadline = time.time() + timeout
        last, stable_since = self.raw, time.time()
        while time.time() < deadline:
            time.sleep(0.1)
            if self.raw != last:
                last, stable_since = self.raw, time.time()
            elif time.time() - stable_since >= quiet:
                return self.text
        return self.text

    # ---- 写 ----
    def send(self, data: str) -> None:
        self.proc.write(data)

    def send_line(self, line: str) -> None:
        self.send(line + "\r")

    def pause(self, seconds: float = 0.35) -> None:
        """给 prompt_toolkit 一点时间重绘/处理按键（连发会被当成粘贴）。"""
        time.sleep(seconds)

    def mark(self) -> int:
        """记住当前位置，便于只看此后的输出。"""
        return len(self.raw)

    def since(self, mark: int) -> str:
        return clean(self.raw[mark:])

    # ---- 收尾 ----
    def close(self, timeout: float = 10) -> int:
        self._alive = False
        try:
            if self.proc.isalive():
                self.proc.terminate(force=True)
        except Exception:  # noqa: BLE001
            pass
        return self.proc.exitstatus or 0

    def __enter__(self) -> "PTY":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
