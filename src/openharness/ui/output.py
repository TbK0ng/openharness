"""终端输出 — 横幅、编码降级、事件打印。

CLI 的 stdout 可能是 Windows GBK 控制台：emoji 直接 print 会抛
UnicodeEncodeError 并中断会话，因此所有输出都走 `emit()`。
"""
from __future__ import annotations

import sys

BANNER = """\
╭──────────────────────────────────────────────╮
│  OpenHarness  ·  Tools + Knowledge +          │
│  Observation + Action + Permissions           │
│  LLM: provider 见 .oh/settings.json           │
│  /help 查看命令   exit 退出                    │
╰──────────────────────────────────────────────╯"""


def is_tty() -> bool:
    """命令内部是否可以直接读 stdin（终端菜单）；管道/测试环境返回 False。"""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def safe_text(text: str) -> str:
    """把终端编码无法表示的字符（Windows GBK 控制台上的 emoji）降级为 '?'。"""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(enc)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(enc, errors="replace").decode(enc, errors="replace")


def emit(text: str = "") -> None:
    """安全打印一行（必要时再降级为 ASCII）。"""
    try:
        print(safe_text(text), flush=True)
    except UnicodeEncodeError:
        print(safe_text(text).encode("ascii", errors="replace").decode("ascii"), flush=True)


def print_assistant(text: str) -> None:
    emit(f"\n[assistant] {text}\n")
