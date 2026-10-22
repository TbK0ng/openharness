"""后台任务管理 — 第 3 章 Tasks 子系统。

TaskCreate 支持两种任务：
    command — 后台运行 shell 命令，实时收集输出
    agent   — 后台运行一个 general-purpose 子 Agent
TaskGet / TaskList / TaskUpdate / TaskStop 管理任务生命周期。

持久化：每个任务一个 JSON 文件，落在 `<root>/tasks/<id>.json`
（root 通常是项目根的 .oh/）。进程退出后任务历史仍可查询；
重启时标记为 running 的任务会被标记为 interrupted（进程已不存在）。
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

#: 单任务输出上限（字符）
MAX_OUTPUT_CHARS = 200_000

#: 运行中状态的进程内取值；落盘时若发现它但进程已不在，说明跨会话残留
_LIVE_STATUSES = ("pending", "running")


@dataclass
class Task:
    task_id: str
    kind: str                      # command | agent
    description: str
    command: Optional[str] = None
    prompt: Optional[str] = None
    status: str = "pending"        # pending / running / finished / failed / stopped / interrupted
    output: str = ""
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    process: Optional[subprocess.Popen] = None
    thread: Optional[threading.Thread] = None

    def tail(self, n: int = 2000) -> str:
        return self.output[-n:]

    def to_dict(self) -> dict:
        """可 JSON 序列化的视图（进程/线程对象不进磁盘）。"""
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "description": self.description,
            "command": self.command,
            "prompt": self.prompt,
            "status": self.status,
            "output": self.output[-MAX_OUTPUT_CHARS:],
            "error": self.error,
            "created_at": self.created_at,
        }


class TaskManager:
    def __init__(self, root, engine=None):
        """root: 任务目录的父目录（通常是 .oh/）。

        注意与 task board 区分：
          - `<root>/tasks/`   后台任务历史（本模块，TaskCreate 起的进程/子 Agent）
          - `<root>/.tasks/`  任务看板（board.py，带 blockedBy 依赖 DAG）
        """
        self.root = Path(root)
        self.dir = self.root / "tasks"
        self.engine = engine
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._load()

    # ---------- 持久化 ----------
    def _path(self, task_id: str) -> Path:
        return self.dir / f"{task_id}.json"

    def _load(self) -> None:
        if not self.dir.exists():
            return
        max_seq = 0
        for p in sorted(self.dir.glob("*.json")):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                task = Task(**{k: v for k, v in raw.items()
                               if k in {f.name for f in dataclasses.fields(Task)}})
            except (OSError, ValueError, TypeError):
                continue
            # 上一次会话遗留的“运行中”任务：进程已不在
            if task.status in _LIVE_STATUSES:
                task.status = "interrupted"
                task.error = task.error or "进程已在会话结束时终止"
            self._tasks[task.task_id] = task
            if task.task_id.startswith("task-"):
                try:
                    max_seq = max(max_seq, int(task.task_id.split("-", 1)[1]))
                except ValueError:
                    pass
        if max_seq:
            self._counter = itertools.count(max_seq + 1)

    def _persist(self, task: Task) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self._path(task.task_id).write_text(
                json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass          # 落盘失败不应中断任务本身

    def _new_id(self) -> str:
        with self._lock:
            return f"task-{next(self._counter)}"

    # ---------- 创建 ----------
    def create_command(self, description: str, command: str) -> Task:
        task = Task(task_id=self._new_id(), kind="command",
                    description=description, command=command)
        task.status = "running"
        self._tasks[task.task_id] = task
        self._persist(task)
        task.thread = threading.Thread(target=self._run_command, args=(task,), daemon=True)
        task.thread.start()
        return task

    def _run_command(self, task: Task) -> None:
        try:
            proc = subprocess.Popen(
                task.command, shell=True, cwd=str(self.root),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
        except Exception as exc:  # noqa: BLE001 — 例如命令不存在
            task.error = str(exc)
            task.status = "failed"
            self._persist(task)
            return
        task.process = proc
        chunks: list[str] = []
        try:
            for line in proc.stdout:
                chunks.append(line)
                if len(task.output) + len(line) > MAX_OUTPUT_CHARS:
                    task.output = "".join(chunks)[-MAX_OUTPUT_CHARS:]
                    chunks = [task.output]
                else:
                    task.output += line
            proc.wait()
            task.status = "finished" if proc.returncode == 0 else "failed"
            task.error = f"exit code {proc.returncode}" if proc.returncode != 0 else None
        except Exception as e:  # noqa: BLE001
            task.error = str(e)
            task.status = "failed"
        finally:
            self._persist(task)

    def create_agent(self, context, description: str, prompt: str) -> Task:
        task = Task(task_id=self._new_id(), kind="agent",
                    description=description, prompt=prompt)
        task.status = "running"
        self._tasks[task.task_id] = task
        self._persist(task)

        def _run():
            from ..agents.team import SubTask, build_sub_context
            from ..engine.llm import build_llm
            from ..engine.query import run_sync
            sub_task = SubTask(agent_type="general-purpose", description=description)
            sub_task.agent_id = task.task_id
            ctx = build_sub_context(context, sub_task)
            # 独立客户端：run_sync() 会关闭 ctx.llm，不能连带关掉父会话的客户端。
            try:
                ctx.llm = build_llm(getattr(context, "config", {}) or {})
            except Exception:  # noqa: BLE001 - 保留共享客户端作为降级路径
                pass
            ctx.messages.append({"role": "user", "content": prompt})
            try:
                task.output = run_sync(ctx)
                task.status = "finished"
            except Exception as e:  # noqa: BLE001
                task.error = str(e)
                task.status = "failed"
            finally:
                self._persist(task)

        task.thread = threading.Thread(target=_run, daemon=True)
        task.thread.start()
        return task

    # ---------- 查询/更新 ----------
    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        # 最新在前，便于历史回溯
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def summary(self) -> str:
        tasks = self.list()
        if not tasks:
            return "(no background tasks)"
        return "\n".join(
            f"{t.task_id} [{t.status}] {t.kind}: {t.description}" for t in tasks)

    def update(self, task_id: str, status: Optional[str] = None,
               note: Optional[str] = None,
               description: Optional[str] = None) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if status:
            task.status = status
        if description:
            task.description = description
        if note:
            task.output = f"{task.output}\n[note] {note}"
        self._persist(task)
        return task

    def stop(self, task_id: str) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.process is not None:
            try:
                task.process.kill()
            except Exception:  # noqa: BLE001 — 已退出时 kill 失败无妨
                pass
        task.status = "stopped"
        self._persist(task)
        return task
