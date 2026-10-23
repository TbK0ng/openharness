"""终端输入层 — 斜杠命令补全、持久历史、状态栏。

`prompt_toolkit` 提供跨平台（含 Windows）的行编辑能力：
    - 输入 `/` 即刻列出全部命令，继续输入按前缀过滤，菜单右侧显示帮助
    - Tab 补全命令名与参数值（如 `/mode fu<Tab>` → `full-auto`）
    - ↑/↓ 翻阅历史，历史落盘到 `.oh/history`，跨会话保留
    - 双击 Esc 请求回退上一轮（RewindRequest），由 CLI 主循环处理
    - Ctrl+C 取消当前输入（不退出会话），Ctrl+D 退出

非 TTY（管道、CI、测试）或设置了 OPENHARNESS_PLAIN_INPUT=1 时，
自动降级为内置 `input()`，行为与旧版一致。
"""
from __future__ import annotations

import os
import sys
from typing import Iterable

from ..commands.registry import Command, CommandRegistry

try:  # pragma: no cover - 缺少依赖时走降级路径
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:  # pragma: no cover
    PromptSession = None
    Completer = object  # type: ignore[assignment,misc]
    Completion = None  # type: ignore[assignment]
    FormattedText = None  # type: ignore[assignment]
    FileHistory = None  # type: ignore[assignment]
    AutoSuggestFromHistory = None  # type: ignore[assignment]
    KeyBindings = None  # type: ignore[assignment,misc]


PROMPT = "\n🧑 你: "
HINTS = "Tab 补全 · ↑↓ 历史 · Esc Esc 回退 · Ctrl+C 取消 · Ctrl+D 退出"


class RewindRequest(Exception):
    """双击 Esc 时从 prompt_toolkit 抛出，由 CLI 主循环执行会话回退。"""


def _rewind_bindings():
    """`Esc Esc` → 退出当前 prompt 并请求回退上一轮。

    prompt_toolkit 的键序列带 0.5s 超时；单按 Esc 仍保留默认的
    “忽略/元键前缀”行为（Alt+b 等不受影响）。
    """
    if KeyBindings is None:  # pragma: no cover - 降级路径
        return None
    kb = KeyBindings()

    @kb.add("escape", "escape")
    def _rewind(event) -> None:
        event.app.exit(exception=RewindRequest())

    return kb


def wants_repl() -> bool:
    """是否启用富输入（需要真实终端且未被显式关闭）。"""
    if os.environ.get("OPENHARNESS_PLAIN_INPUT"):
        return False
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def match_commands(commands: Iterable[Command], fragment: str) -> list[Command]:
    """命令名匹配：前缀优先，其次包含；空串返回全部。"""
    frag = fragment.lstrip("/").lower()
    items = list(commands)
    if not frag:
        return items
    starts = [c for c in items if c.name.lower().startswith(frag)]
    contains = [c for c in items
                if frag in c.name.lower() and not c.name.lower().startswith(frag)]
    return starts + contains


def match_choices(command: Command, fragment: str) -> list[tuple[str, str]]:
    """参数候选匹配，返回 (值, 说明)。"""
    frag = fragment.lower()
    return [(value, desc) for value, desc in command.options().items()
            if value.lower().startswith(frag)]


class SlashCommandCompleter(Completer):  # type: ignore[misc]
    """`/命令 [参数]` 的补全器。"""

    def __init__(self, registry: CommandRegistry) -> None:
        self.registry = registry

    def get_completions(self, document, complete_event):
        before = document.text_before_cursor
        if not before.startswith("/") or "\n" in before:
            return
        body = before[1:]
        if " " not in body:
            for cmd in match_commands(self.registry.list(), body):
                # 有参数的命令补全时带上空格，用户可继续 Tab 补参数
                suffix = " " if cmd.options() else ""
                yield Completion(cmd.name + suffix,
                                 start_position=-len(body),
                                 display=cmd.name,
                                 display_meta=cmd.help_text)
            return
        if body.count(" ") != 1:
            return
        name, _, fragment = body.partition(" ")
        cmd = self.registry.get(name)
        if cmd is None:
            return
        if not cmd.options():
            return
        for value, desc in match_choices(cmd, fragment):
            yield Completion(value,
                             start_position=-len(fragment),
                             display=value,
                             display_meta=desc)


def _status_text(engine) -> str:
    cfg = engine.config
    # 显示真正会用的模型名（provider 预设也算），而不是空字符串退回 provider
    try:
        from ..api.registry import resolve_provider

        model = resolve_provider(cfg).get("model") or cfg.get("provider") or "?"
    except Exception:  # noqa: BLE001 - 状态栏不允许影响输入
        model = cfg.get("model") or cfg.get("provider") or "?"
    try:
        tools = len(engine.registry.list_tools())
    except Exception:  # noqa: BLE001 - 状态栏不允许影响输入
        tools = 0
    cwd = engine.cwd.name or str(engine.cwd)
    session = getattr(engine, "session", None)
    sid = f" ⟨{session.id}/{session.kind}⟩" if session is not None else ""
    left = f" {engine.permissions.mode} │ {model} │ {tools} tools │ {cwd}{sid} "
    return f"{left}  {HINTS} "


class LineReader:
    """行输入：终端下用 prompt_toolkit，否则退回 input()。"""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.session = self._make_session() if wants_repl() else None

    def _make_session(self):
        if PromptSession is None:
            return None
        try:
            return PromptSession(
                completer=SlashCommandCompleter(self.engine.commands),
                complete_while_typing=True,
                history=FileHistory(str(self.engine.oh_dir / "history")),
                auto_suggest=AutoSuggestFromHistory(),
                key_bindings=_rewind_bindings(),
                bottom_toolbar=lambda: FormattedText(
                    [("class:bottom-toolbar", _status_text(self.engine))]),
            )
        except Exception:  # noqa: BLE001 - 终端能力异常时降级
            return None

    def read(self, default: str = "") -> str:
        """读一行（不含换行）。Ctrl+C 返回空串，EOF 抛 EOFError。

        `default` 用于回退后把原输入放回编辑缓冲；双击 Esc 会抛
        RewindRequest（不在此处吞掉，交给 CLI 主循环）。
        """
        if self.session is None:
            if default:
                print(f"↩ 已回退，原输入：{default}\n（请重新输入以发送）")
            return input(PROMPT)
        try:
            return self.session.prompt(PROMPT, default=default)
        except KeyboardInterrupt:
            return ""
