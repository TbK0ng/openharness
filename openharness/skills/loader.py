"""技能加载 — 对应教程第 8 章 `openharness/skills/`。

每个技能是一个 Markdown 文件，含 frontmatter（name/description），
按主题目录发现；Skill 工具按需加载内容注入上下文。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = text[m.end():]
    return meta, body


class SkillLoader:
    def __init__(self, dirs: List[Path]):
        self.dirs = [Path(d) for d in dirs]
        self._skills: dict[str, dict] = {}
        self.scan()

    def scan(self) -> None:
        self._skills = {}
        for d in self.dirs:
            if not d.exists():
                continue
            # 技能按主题组织：既支持 skills/*.md，也支持 skills/<topic>/SKILL.md
            files = sorted(d.glob("*.md")) + sorted(d.glob("*/SKILL.md"))
            for p in files:
                try:
                    text = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                meta, body = _parse_frontmatter(text)
                name = meta.get("name") or p.stem
                self._skills[name] = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "path": str(p),
                    "content": text,
                }

    def summary(self) -> str:
        """给系统提示用的技能清单（教程第 8 章：只放索引，正文按需加载）。"""
        return self.summary_for_prompt()

    def list_skills(self) -> List[dict]:
        return [
            {"name": s["name"], "description": s["description"]}
            for s in self._skills.values()
        ]

    def get(self, name: str) -> Optional[str]:
        s = self._skills.get(name)
        return s["content"] if s else None

    def summary_for_prompt(self) -> str:
        if not self._skills:
            return ""
        lines = [f"- {s['name']}: {s['description']}" for s in self._skills.values()]
        return "可用技能（用 Skill 工具按名加载）：\n" + "\n".join(lines)
