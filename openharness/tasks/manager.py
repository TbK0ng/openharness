"""后台任务管理 — 第 3 章 Tasks 子系统。

TaskCreate 支持两种任务：
    command — 后台运行 shell 命令，实时收集输出
    agent   — 后台运行一个 general-purpose 子 Agent
TaskGet / TaskList / TaskUpdate / TaskStop 管理任务生命周期。
"""
from __future__ import annotations

import asyncio
import itertools
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Task:
    task_id: str
    kind: str                      # command | agent
    description: str
    command: Optional[str] = None
    prompt: Optional[str] = None
    status: str = "pending"        # pending / running / finished / failed / stopped
    output: str = ""
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    process: Optional[subprocess.Popen] = None
    thread: Optional[threading.Thread] = None

    def tail(self, n: int = 2000) -> str:
        return self.output[-n:]


class TaskManager:
    def __init__(self, cwd: str, engine=None):
        self.cwd = cwd
        self.engine = engine
        self._tasks: dict[str, Task] = {}
        self._counter = itertools.count(1)

    def create_command(self, description: str, command: str) -> Task:
        task = Task(task_id=f"task-{next(self._counter)}", kind="command",
                    description=description, command=command)
        self._tasks[task.task_id] = task
        task.thread = threading.Thread(target=self._run_command, args=(task,), daemon=True)
        task.status = "running"
        task.thread.start()
        return task

    def _run_command(self, task: Task) -> None:
        proc = subprocess.Popen(
            task.command, shell=True, cwd=self.cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        task.process = proc
        chunks: list[str] = []
        try:
            for line in proc.stdout:
                chunks.append(line)
                if len(task.output) + len(line) > 200_000:
                    task.output = "".join(chunks)[-200_000:]
                    chunks = [task.output]
                else:
                    task.output += line
            proc.wait()
            task.status = "finished" if proc.returncode == 0 else "failed"
            task.error = f"exit code {proc.returncode}" if proc.returncode != 0 else None
        except Exception as e:
            task.error = str(e)
            task.status = "failed"

    def create_agent(self, context, description: str, prompt: str) -> Task:
        task = Task(task_id=f"task-{next(self._counter)}", kind="agent",
                    description=description, prompt=prompt)
        self._tasks[task.task_id] = task

        def _run():
            from ..agents.team import build_sub_context, SubTask
            from ..engine.query import run_sync
            task.status = "running"
            sub_task = SubTask(agent_type="general-purpose", description=description)
            sub_task.agent_id = task.task_id
            ctx = build_sub_context(context, sub_task)
            ctx.messages.append({"role": "user", "content": prompt})
            try:
                task.output = run_sync(ctx)
                task.status = "finished"
            except Exception as e:
                task.error = str(e)
                task.status = "failed"

        task.thread = threading.Thread(target=_run, daemon=True)
        task.thread.start()
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        return list(self._tasks.values())

    def summary(self) -> str:
        if not self._tasks:
            return "(no background tasks)"
        return "\n".join(
            f"{t.task_id} [{t.status}] {t.kind}: {t.description}" for t in self._tasks.values())

    def update(self, task_id: str, status: Optional[str] = None, note: Optional[str] = None) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if status:
            task.status = status
        if note:
            task.output = f"{task.output}\n[note] {note}"
        return task

    def stop(self, task_id: str) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        if task.process is not None:
            try:
                task.process.kill()
            except Exception:
                pass
        task.status = "stopped"
        return task
