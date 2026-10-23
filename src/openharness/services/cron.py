"""定时任务调度 — 第 5 章调度类（CronCreate/CronList/CronDelete）。

CronManager 持久化到 <root>/data/cron.json（root 通常是 .oh/）；后台线程每秒
检查到期任务并触发：
    command — 直接 shell 执行，输出追加到 .oh/data/cron.log
    agent   — 通过 TaskManager 创建后台 agent 任务

调度器必须显式 `start()`（CLI 启动时自动调用；CronCreate 工具创建任务后
也会启动）。进程退出即停止，因此定时任务只在 CLI 运行期间触发。
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class CronJob:
    job_id: str
    schedule: str
    kind: str
    command: str = ""
    prompt: str = ""
    active: bool = True
    # 上次触发的分钟时间戳（epoch 分钟）；持久化以避免重启后同分钟重复触发
    last_fired: int = 0

    def __str__(self):
        return (f"[{self.job_id}] {self.schedule} {self.kind}: "
                f"{self.command or self.prompt}")


def _cron_field_match(field: str, value: int) -> bool:
    """单个 5 字段 cron 项匹配：*, */n, a, a-b, a,b,c 组合。"""
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and value % step == 0:
                return True
            continue
        if "-" in part:
            lo, hi = part.split("-")
            if int(lo) <= value <= int(hi):
                return True
            continue
        if part.isdigit() and int(part) == value:
            return True
    return False


def cron_due(schedule: str, now: datetime) -> bool:
    parts = schedule.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    return (
        _cron_field_match(minute, now.minute)
        and _cron_field_match(hour, now.hour)
        and _cron_field_match(dom, now.day)
        and _cron_field_match(month, now.month)
        and _cron_field_match(dow, (now.weekday() + 1) % 7)  # 0=周日
    )


class CronManager:
    def __init__(self, cwd, tasks=None, context=None, workdir=None):
        # cwd 是状态根（通常是 .oh/）；workdir 是 command 任务的执行目录（项目根）。
        self.cwd = Path(cwd)
        self.workdir = Path(workdir) if workdir is not None else self.cwd
        self.tasks = tasks
        self.context = context  # 由 Engine 注入，供 agent 类型任务使用
        self._file = self.cwd / "data" / "cron.json"
        self._jobs: list[CronJob] = []
        self._counter = itertools.count(1)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._load()

    # ---- 持久化 ----
    def _load(self):
        self._jobs = []
        if not self._file.exists():
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        fields = {f.name for f in dataclasses.fields(CronJob)}
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                self._jobs.append(CronJob(
                    **{k: v for k, v in item.items() if k in fields}))
            except TypeError:
                continue
        # 计数器从已有 job id 续上，避免重启后 cron-1 重复
        numbers = [int(m.group(1)) for j in self._jobs
                   if (m := re.fullmatch(r"cron-(\d+)", j.job_id))]
        self._counter = itertools.count(max(numbers, default=0) + 1)

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps([dataclasses.asdict(j) for j in self._jobs],
                       ensure_ascii=False, indent=2),
            encoding="utf-8")

    def _log(self, text: str) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file.parent / "cron.log", "a", encoding="utf-8") as fh:
                fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except OSError:
            pass

    # ---- CRUD ----
    def create(self, schedule: str, kind: str, command: str = "",
               prompt: str = "") -> CronJob:
        schedule = " ".join(schedule.split())
        if len(schedule.split()) != 5:
            raise ValueError("cron schedule must have exactly 5 fields")
        if kind not in ("command", "agent"):
            raise ValueError("cron kind must be 'command' or 'agent'")
        if kind == "command" and not command.strip():
            raise ValueError("command job requires a non-empty command")
        if kind == "agent" and not prompt.strip():
            raise ValueError("agent job requires a non-empty prompt")
        job = CronJob(job_id=f"cron-{next(self._counter)}", schedule=schedule,
                      kind=kind, command=command, prompt=prompt)
        self._jobs.append(job)
        self._save()
        return job

    def list(self) -> list[CronJob]:
        return list(self._jobs)

    def summary(self) -> str:
        if not self._jobs:
            return "(no scheduled jobs)"
        return "\n".join(
            f"{j.job_id} {j.schedule} {j.kind}: {j.command or j.prompt}"
            for j in self._jobs)

    def delete(self, job_id: str) -> bool:
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.job_id != job_id]
        if len(self._jobs) != before:
            self._save()
        return len(self._jobs) != before

    # ---- 调度 ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="oh-cron", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        self._thread = None

    def run_now(self, job_id: str) -> bool:
        """立即触发一次（/cron run 与测试用），并标记本分钟已触发。"""
        job = next((j for j in self._jobs if j.job_id == job_id), None)
        if job is None:
            return False
        job.last_fired = int(time.time()) // 60
        self._save()
        self._fire(job)
        return True

    def _loop(self):
        while not self._stop.is_set():
            now = datetime.now()
            stamp = int(time.time()) // 60
            for job in list(self._jobs):
                if not job.active or job.last_fired == stamp:
                    continue
                try:
                    due = cron_due(job.schedule, now)
                except (ValueError, TypeError):
                    due = False
                if not due:
                    continue
                job.last_fired = stamp
                self._save()
                self._fire(job)
            self._stop.wait(1.0)

    def _fire(self, job: CronJob):
        self._log(f"fire {job.job_id} {job.kind}: {job.command or job.prompt}")
        if job.kind == "agent":
            if self.tasks is None or self.context is None:
                self._log(f"skip {job.job_id}: agent scheduler has no context")
                return
            try:
                task = self.tasks.create_agent(
                    self.context, f"cron {job.job_id}", job.prompt)
                self._log(f"agent task {task.task_id} started")
            except Exception as exc:  # noqa: BLE001 — 后台任务失败不能杀调度线程
                self._log(f"agent task failed: {exc}")
            return
        if job.kind == "command":
            try:
                with open(self._file.parent / "cron.log", "a",
                          encoding="utf-8") as fh:
                    subprocess.Popen(
                        job.command, shell=True, cwd=str(self.workdir),
                        stdout=fh, stderr=subprocess.STDOUT)
            except Exception as exc:  # noqa: BLE001
                self._log(f"command failed to start: {exc}")
