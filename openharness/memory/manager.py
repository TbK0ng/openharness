"""长期记忆 — 对应教程第 9 章 `openharness/memory/`。

OpenHarness 的记忆机制（文件 = 持久化，索引 = 高效访问）：

- ``MEMORY.md`` 是索引文件，列出所有记忆条目的标题和链接；
  每次对话开始时被加载到上下文中（Engine 组装 system prompt 时注入）。
- ``memory/`` 目录下每条记忆是一个独立的 Markdown 文件，按类型命名，
  含 frontmatter（name / description / type）与正文。
- 四种记忆类型：user（用户）、feedback（反馈）、project（项目）、reference（参考）。

生命周期：创建 → 索引 → 加载 → 使用 → 更新/删除。
Agent 在使用记忆前会验证信息是否仍然准确（记忆可能过时）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

#: 第 9 章定义的四种记忆类型
MEMORY_TYPES: Tuple[str, ...] = ("user", "feedback", "project", "reference")

_TYPE_LABELS = {
    "user": "用户记忆",
    "feedback": "反馈记忆",
    "project": "项目记忆",
    "reference": "参考记忆",
}


class MemoryError(ValueError):
    """记忆操作违反第 9 章契约（未知类型、不存在的记忆等）。"""


def _parse_frontmatter(text: str) -> Tuple[dict, str]:
    """解析 YAML 子集 frontmatter（与 skills/loader.py 同一约定）。"""
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


def _slug(name: str) -> str:
    """文件名安全化：保留字母数字（含中文）与连字符，其余替换为 -。"""
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip(), flags=re.UNICODE)
    return s.strip("-") or "memory"


_INDEX_LINE = re.compile(r"^- \[(?P<name>.+?)\]\((?P<link>.+?)\) — (?P<desc>.*)$")


class MemoryManager:
    def __init__(self, cwd: Path, subdir: str = "memory"):
        self.root = Path(cwd)
        self.dir = self.root / subdir
        self.index = self.root / "MEMORY.md"

    # ---------- 创建 + 索引 ----------

    def save(self, name: str, description: str, mtype: str, body: str) -> Path:
        """创建一条记忆并登记到 MEMORY.md 索引。同名记忆幂等覆盖。"""
        if mtype not in MEMORY_TYPES:
            raise MemoryError(f"未知记忆类型 {mtype!r}，必须是 {MEMORY_TYPES} 之一")
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{mtype}_{_slug(name)}.md"
        text = (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {mtype}\n"
            "---\n\n"
            f"{body.strip()}\n"
        )
        path.write_text(text, encoding="utf-8")
        self._reindex(path, name, description)
        return path

    def _reindex(self, path: Path, name: str, description: str) -> None:
        rel = path.relative_to(self.root).as_posix()
        entries = [e for e in self._read_entries() if e["link"] != rel]
        entries.append({"name": name, "link": rel, "description": description})
        lines = [f"- [{e['name']}]({e['link']}) — {e['description']}" for e in entries]
        self.index.write_text("# MEMORY\n\n" + "\n".join(lines) + "\n", encoding="utf-8")

    def _read_entries(self) -> List[dict]:
        if not self.index.exists():
            return []
        out = []
        for ln in self.index.read_text(encoding="utf-8").splitlines():
            m = _INDEX_LINE.match(ln)
            if m:
                g = m.groupdict()
                out.append({"name": g["name"], "link": g["link"],
                            "description": g["desc"]})
        return out

    # ---------- 加载 ----------

    def list_memories(self) -> List[dict]:
        """直接扫描 memory/*.md（不依赖索引），返回全部记忆的元数据。"""
        out = []
        if not self.dir.exists():
            return out
        for p in sorted(self.dir.glob("*.md")):
            try:
                meta, _ = _parse_frontmatter(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            out.append({
                "name": meta.get("name", p.stem),
                "description": meta.get("description", ""),
                "type": meta.get("type", ""),
                "path": str(p),
            })
        return out

    def get(self, name: str) -> Optional[str]:
        """按名取回单条记忆的完整文本（含 frontmatter）。"""
        for m in self.list_memories():
            if m["name"] == name:
                return Path(m["path"]).read_text(encoding="utf-8")
        return None

    def load_all(self) -> str:
        """使用阶段：拼接全部记忆正文，供 Agent 调整行为。"""
        parts = []
        for m in self.list_memories():
            parts.append(Path(m["path"]).read_text(encoding="utf-8").strip())
        return "\n\n".join(parts)

    def snapshot(self) -> str:
        """写入系统提示的记忆摘要（第 12 章：MEMORY.md 索引常驻上下文）。"""
        if not self.index.exists() or not self.list_memories():
            return ""
        text = self.index.read_text(encoding="utf-8").strip()
        return f"## 长期记忆\n{text[:4000]}" if text else ""

    # ---------- 更新 / 删除 ----------

    def update(self, name: str, description: Optional[str] = None,
               body: Optional[str] = None) -> Path:
        """更新已有记忆的 description / 正文，同步刷新索引行。"""
        target = next((m for m in self.list_memories() if m["name"] == name), None)
        if target is None:
            raise MemoryError(f"记忆不存在：{name!r}")
        path = Path(target["path"])
        meta, old_body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        desc = description if description is not None else target["description"]
        new_body = body if body is not None else old_body.strip()
        path.write_text(
            "---\n"
            f"name: {name}\n"
            f"description: {desc}\n"
            f"type: {meta.get('type', 'user')}\n"
            "---\n\n"
            f"{new_body}\n",
            encoding="utf-8",
        )
        self._reindex(path, name, desc)
        return path

    def delete(self, name: str) -> bool:
        """删除记忆文件并移除索引行；不存在返回 False。"""
        target = next((m for m in self.list_memories() if m["name"] == name), None)
        if target is None:
            return False
        rel = Path(target["path"]).relative_to(self.root).as_posix()
        entries = [e for e in self._read_entries() if e["link"] != rel]
        lines = [f"- [{e['name']}]({e['link']}) — {e['description']}" for e in entries]
        self.index.write_text("# MEMORY\n\n" + "\n".join(lines) + ("\n" if lines else ""),
                              encoding="utf-8")
        Path(target["path"]).unlink()
        return True
