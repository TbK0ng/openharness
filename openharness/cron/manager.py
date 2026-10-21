"""定时任务调度 — 第 5 章调度类（CronCreate/CronList/CronDelete）。

CronManager 持久化到 data/cron.json；后台线程每秒检查到期任务并触发：
    command — 直接 shell 执行
    agent   — 通过 TaskManager 创建后台 agent 任务
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import threading
import time
from dataclasses import dataclass, field
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


def cron_due(schedule: str, now) -> bool:
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
    def __init__(self, cwd, tasks=None, context=None):
        self.cwd = Path(cwd)
        self.tasks = tasks
        self.context = context  # 由 Engine 注入，供 agent 类型任务使用
        self._file = self.cwd / "data" / "cron.json"
        self._jobs: list[CronJob] = []
        self._counter = itertools.count(1)
        self._thread: Optional[threading.Thread] = None
        self._load()

    def _load(self):
        if self._file.exists():
            try:
                raw = json.loads(self._file.read_text())
                self._jobs = [CronJob(**j) for j in raw]
            except Exception:
                self._jobs = []

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(
            [dataclasses.asdict(j) for j in self._jobs], indent=2))

    def create(self, schedule: str, kind: str, command: str = "", prompt: str = "") -> CronJob:
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
            f"{j.job_id} {j.schedule} {j.kind}: {j.command or j.prompt}" for j in self._jobs)

    def delete(self, job_id: str) -> bool:
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.job_id != job_id]
        self._save()
        return len(self._jobs) != before

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        last_fired: dict[str, int] = {}
        while True:
            now = time.localtime()
            for job in self._jobs:
                if not job.active:
                    continue
                if not cron_due(job.schedule, now):
                    continue
                minute_stamp = int(time.time()) // 60
                if last_fired.get(job.job_id) == minute_stamp:
                    continue
                last_fired[job.job_id] = minute_stamp
                self._fire(job)
            time.sleep(1)

    def _fire(self, job: CronJob):
        if job.kind == "agent":
            if self.tasks is None or self.context is None:
                return
            self.tasks.create_agent(self.context, job.prompt, job.prompt)
        elif job.kind == "command":
            import subprocess
            subprocess.Popen(job.command, shell=True)
