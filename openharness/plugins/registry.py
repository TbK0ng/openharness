"""插件扩展机制 — 第 3 章 Plugins 子系统。

plugins/ 目录下每个 .py 插件定义：
    PLUGIN = {"name": ..., "description": ...}
    def register(ctx) -> None   # ctx 提供 register_tool / register_command / register_skill
插件工具进入 ToolRegistry，插件命令进入 CommandRegistry，插件技能进入 SkillLoader。
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List


@dataclass
class PluginContext:
    tools: list = None
    commands: list = None
    skills: list = None

    def register_tool(self, tool) -> None:
        (self.tools or []).append(tool)

    def register_command(self, name: str, help_text: str, fn: Callable) -> None:
        (self.commands or []).append((name, help_text, fn))

    def register_skill(self, name: str, content: str) -> None:
        (self.skills or []).append((name, content))


class PluginRegistry:
    def __init__(self):
        self.plugins: dict[str, dict] = {}

    def load_dir(self, plugins_dir: Path, ctx: PluginContext) -> List[str]:
        loaded = []
        if not plugins_dir.exists():
            return loaded
        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"oh_plugin_{path.stem}", path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                self.plugins[path.stem] = {"name": path.stem, "error": str(e)}
                continue
            info = getattr(module, "PLUGIN", {"name": path.stem})
            register_fn = getattr(module, "register", None)
            if callable(register_fn):
                register_fn(ctx)
            self.plugins[info.get("name", path.stem)] = {
                "name": info.get("name", path.stem),
                "description": info.get("description", ""),
                "path": str(path),
            }
            loaded.append(info.get("name", path.stem))
        return loaded
