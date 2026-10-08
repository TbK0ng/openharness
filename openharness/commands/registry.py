"""用户交互命令 — 第 3 章 Commands 子系统（CLI 斜杠命令）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Command:
    name: str
    help_text: str
    fn: Callable


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, name: str, help_text: str, fn: Callable) -> None:
        self._commands[name.lstrip("/")] = Command(name=name, help_text=help_text, fn=fn)

    def get(self, name: str):
        return self._commands.get(name.lstrip("/"))

    def list(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)
