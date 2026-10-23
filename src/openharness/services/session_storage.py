"""会话模型 — /new /fork /side 与回退的载体。

一个 Session 拥有一份独立的 Agent Loop Context（消息历史、todo、恢复状态
等），因此切换会话不会互相污染。Engine 只把“当前会话”暴露给 CLI：

    main — 普通会话（启动时的默认会话，/new 再开一个）
    fork — /fork 从某个会话深拷贝出的分支，parent_id 指向来源
    side — /side 开启的临时会话，退出时直接丢弃（不落盘）

main / fork 通过 SessionStore 持久化到 `.oh/sessions/<id>.json`；重启后
`/sessions` 仍能看到，`/switch <id>` 会把消息历史载入新 Context。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型检查，避免循环导入
    from ..engine.query import Context


@dataclass
class Session:
    id: str
    context: "Context"
    kind: str = "main"                 # main | fork | side
    name: str = ""
    parent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    @property
    def messages(self) -> list[dict]:
        return self.context.messages

    @property
    def label(self) -> str:
        name = f" {self.name}" if self.name else ""
        return f"{self.id} [{self.kind}]{name}"


class SessionStore:
    """会话落盘：`.oh/sessions/<id>.json`。

    只保存 main/fork；side 是临时会话，`save()` 直接返回 None。文件损坏
    或格式不符时跳过，不让历史存储影响会话启动。
    """

    def __init__(self, root: Path | str, subdir: str = "sessions") -> None:
        self.root = Path(root)
        self.dir = self.root / subdir

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    def save(self, session: Session, todo_state=None) -> Optional[Path]:
        if session.kind == "side":
            return None
        todos = []
        items = getattr(todo_state, "items", None)
        if items:
            todos = [dict(item) for item in items if isinstance(item, dict)]
        data = {
            "id": session.id,
            "kind": session.kind,
            "name": session.name,
            "parent_id": session.parent_id,
            "created_at": session.created_at,
            "updated_at": time.time(),
            "messages": list(session.messages),
            "todos": todos,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(session.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(path)
        return path

    def _read(self, path: Path) -> Optional[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or not data.get("id"):
            return None
        if not isinstance(data.get("messages"), list):
            data["messages"] = []
        return data

    def list(self) -> list[dict]:
        """会话摘要（不含 messages），最近更新时间在前。"""
        if not self.dir.exists():
            return []
        out = []
        for path in self.dir.glob("*.json"):
            data = self._read(path)
            if data is None:
                continue
            messages = data.get("messages") or []
            preview = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    preview = str(msg.get("content", "")).replace("\n", " ")[:60]
                    break
            out.append({
                "id": data["id"],
                "kind": data.get("kind", "main"),
                "name": data.get("name", ""),
                "parent_id": data.get("parent_id"),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "message_count": len(messages),
                "preview": preview,
            })
        out.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        return out

    def load(self, key: str) -> Optional[dict]:
        """按完整 id、id 前缀或名称载入会话（含 messages）。"""
        key = key.strip()
        if not key:
            return None
        exact = self._path(key)
        if exact.exists():
            return self._read(exact)
        name_hits, prefix_hits = [], []
        for path in self.dir.glob("*.json"):
            data = self._read(path)
            if data is None:
                continue
            name = data.get("name") or ""
            if name == key:
                name_hits.append(data)
            elif path.stem.startswith(key) or (name and name.startswith(key)):
                prefix_hits.append(data)
        hits = name_hits or prefix_hits
        if not hits:
            return None
        return max(hits, key=lambda d: d.get("updated_at", 0))

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True
