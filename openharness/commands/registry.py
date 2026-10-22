"""用户交互命令 — 第 3 章 Commands 子系统（CLI 斜杠命令）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Command:
    name: str
    help_text: str
    fn: Callable
    # 用法串（含参数占位），用于 /help 与补全；留空时按 /name 渲染
    usage: str = ""
    # 第一个位置参数的候选值 {值: 说明}，供 CLI 补全与 /help 提示
    choices: dict[str, str] = field(default_factory=dict)
    # 动态候选（如 /help 的候选是全部命令）；优先于 choices
    completer: Optional[Callable[[], dict[str, str]]] = None

    def usage_line(self) -> str:
        return self.usage or f"/{self.name}"

    def options(self) -> dict[str, str]:
        """该命令第一个参数的候选值；出错时静默返回空（补全不能拖垮输入）。"""
        if self.completer is not None:
            try:
                return dict(self.completer())
            except Exception:  # noqa: BLE001
                return {}
        return self.choices


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, name: str, help_text: str, fn: Callable, *,
                 usage: str = "", choices: dict[str, str] | list[str] | None = None,
                 completer: Optional[Callable[[], dict[str, str]]] = None) -> None:
        if choices is None:
            parsed: dict[str, str] = {}
        elif isinstance(choices, dict):
            parsed = dict(choices)
        else:
            parsed = {c: "" for c in choices}
        key = name.lstrip("/")
        self._commands[key] = Command(
            name=key, help_text=help_text, fn=fn,
            usage=usage or (f"/{key} [{'|'.join(parsed)}]" if parsed else ""),
            choices=parsed,
            completer=completer,
        )

    def get(self, name: str) -> Optional[Command]:
        return self._commands.get(name.lstrip("/"))

    def list(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)
