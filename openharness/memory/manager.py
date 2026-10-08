"""长期记忆 — 第 9 章：MEMORY.md 索引 + memory/ 主题文件。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List


class MemoryManager:
    def __init__(self, cwd: Path):
        self.dir = Path(cwd)
        self.index = self.dir / "MEMORY.md"

    def snapshot(self) -> str:
        """返回写入系统提示的记忆摘要（第 12 章：可选写记忆）。"""
        if not self.index.exists():
            return ""
        text = self.index.read_text(encoding="utf-8").strip()
        return f"## 长期记忆\n{text[:4000]}" if text else ""

    def save(self, topic: str, content: str):
        self.index.parent.mkdir(parents=True, exist_ok=True)
        entry = f"\n### {topic}\n{content.strip()}\n"
        if self.index.exists():
            self.index.write_text(self.index.read_text(encoding="utf-8") + entry, encoding="utf-8")
        else:
            self.index.write_text(f"# MEMORY\n{entry}", encoding="utf-8")
