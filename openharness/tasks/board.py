"""任务看板 — 第 12 章（Learn Claude Code s12）：带依赖 DAG 的任务板。

与 background tasks（manager.py，s13）不同：这里的任务有显式的
blockedBy 依赖图，必须先完成阻塞者才能 claim。每个任务是一个
`.tasks/{id}.json` 文件，状态机 pending → in_progress → completed。
"""
from __future__ import annotations

import json
import pathlib
import time
import uuid


class TaskBlockedError(Exception):
    """claim 了一个仍被未完成任务阻塞的任务。"""


class TaskNotFoundError(Exception):
    """操作不存在的任务 id。"""


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class TaskBoard:
    """持久化任务板：cwd/.tasks/*.json。

    字段（一比一对应 s12）：
      id / subject / description / status / blockedBy / createdAt / completedAt
    """

    def __init__(self, root: str | pathlib.Path):
        self.root = pathlib.Path(root)
        self.dir = self.root / ".tasks"

    # ---- 基础 IO ----
    def _path(self, task_id: str) -> pathlib.Path:
        return self.dir / f"{task_id}.json"

    def _load(self, task_id: str) -> dict:
        p = self._path(task_id)
        if not p.exists():
            raise TaskNotFoundError(task_id)
        return json.loads(p.read_text(encoding="utf-8"))

    def _save(self, task: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(task["id"]).write_text(
            json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 查询 ----
    def get(self, task_id: str) -> dict:
        return self._load(task_id)

    def list(self) -> list[dict]:
        if not self.dir.exists():
            return []
        tasks = [json.loads(p.read_text(encoding="utf-8"))
                 for p in sorted(self.dir.glob("*.json"))]
        tasks.sort(key=lambda t: t.get("createdAt", 0))
        return tasks

    def is_blocked(self, task: dict) -> bool:
        """所有 blockedBy 都 completed 才算可执行。"""
        for dep in task.get("blockedBy", []):
            try:
                dep_task = self._load(dep)
            except TaskNotFoundError:
                continue  # 指向不存在任务的边忽略（与课程一致：只查状态）
            if dep_task.get("status") != "completed":
                return True
        return False
    def unclaimed(self) -> list[dict]:
        """s17 scan_unclaimed_tasks：pending、无人认领、且不被阻塞的任务。"""
        return [t for t in self.list()
                if t["status"] == "pending" and not t.get("assignee")
                and not self.is_blocked(t)]

    # ---- 状态机 ----
    def create(self, subject: str, description: str = "",
               blocked_by: list[str] | None = None) -> dict:
        task = {
            "id": _new_id(),
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": list(blocked_by or []),
            "assignee": None,
            "createdAt": time.time(),
        }
        self._save(task)
        return task

    def claim(self, task_id: str, assignee: str | None = None) -> dict:
        task = self._load(task_id)
        if task["status"] == "completed":
            raise TaskBlockedError(f"task {task_id} already completed")
        if self.is_blocked(task):
            pending = [d for d in task["blockedBy"]
                       if self._safe_status(d) != "completed"]
            raise TaskBlockedError(
                f"task {task_id} blocked by unfinished: {', '.join(pending)}")
        owner = task.get("assignee")
        if owner and owner != assignee:
            raise TaskBlockedError(f"task {task_id} already claimed by {owner}")
        task["status"] = "in_progress"
        task["assignee"] = assignee
        self._save(task)
        return task

    def complete(self, task_id: str) -> dict:
        task = self._load(task_id)
        task["status"] = "completed"
        task["completedAt"] = time.time()
        self._save(task)
        return task

    def _safe_status(self, task_id: str) -> str:
        try:
            return self._load(task_id)["status"]
        except TaskNotFoundError:
            return "missing"
