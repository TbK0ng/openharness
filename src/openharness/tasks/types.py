"""后台任务的数据模型。"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

#: 单任务输出上限（字符）
MAX_OUTPUT_CHARS = 200_000


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
