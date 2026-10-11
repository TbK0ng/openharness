"""自主 Agent — 第 17 章（Learn Claude Code s17）：WORK → IDLE → SHUTDOWN。

teammate 生命周期：
    working   正在处理已认领的任务（实际推理由外部 work_fn 完成）
    idle      任务完成后进入空闲，idle_poll 找新工作
    shutdown  收件箱空且看板没有可认领任务时退出

idle_poll 的优先级（与课程一致）：先 consume_inbox（其他 agent 发来的消息），
再 scan_unclaimed_tasks 并 claim。多个 teammate 并发时，board.claim 的
assignee 检查保证同一任务不会被两人认领。
"""
from __future__ import annotations

import dataclasses

from ..tasks.board import TaskBoard


class Inbox:
    """按名字分格的收件箱。send 入队，consume 取出并清空。"""

    def __init__(self):
        self._boxes: dict[str, list[str]] = {}

    def send(self, to: str, message: str) -> None:
        self._boxes.setdefault(to, []).append(message)

    def consume(self, name: str) -> list[str]:
        return self._boxes.pop(name, [])

    def pending(self, name: str) -> int:
        return len(self._boxes.get(name, []))


def scan_unclaimed_tasks(board: TaskBoard) -> list[dict]:
    """s17：看板上 pending、无人认领、不被阻塞的任务。"""
    return board.unclaimed()


def claim_task(board: TaskBoard, task_id: str, agent_name: str) -> dict:
    """带归属地认领（已被别人认领会抛 TaskBlockedError）。"""
    return board.claim(task_id, assignee=agent_name)


@dataclasses.dataclass
class Teammate:
    name: str
    board: TaskBoard
    inbox: Inbox
    state: str = "idle"              # idle / working / shutdown
    current_task: str | None = None


def idle_poll(tm: Teammate) -> dict | None:
    """一次轮询：先收件箱，后看板。无工作返回 None。"""
    msgs = tm.inbox.consume(tm.name)
    if msgs:
        return {"kind": "inbox", "messages": msgs}
    tasks = scan_unclaimed_tasks(tm.board)
    if not tasks:
        return None
    task = tm.board.claim(tasks[0]["id"], assignee=tm.name)
    return {"kind": "task", "task": task}


def finish_task(tm: Teammate, result: str = "") -> None:
    """完成当前任务，回到 idle。"""
    if tm.current_task is not None:
        tm.board.complete(tm.current_task)
        tm.current_task = None
    tm.state = "idle"


def run_until_done(tm: Teammate, work_fn) -> int:
    """跑完整的 WORK→IDLE→SHUTDOWN 循环，返回完成任务数。

    work_fn(task_dict) -> str：执行单个任务的「推理」（测试里用假函数）。
    收件箱消息会被取出交回给编排者（可能产生新任务），不直接消耗。
    """
    done = 0
    while True:
        work = idle_poll(tm)
        if work is None:
            tm.state = "shutdown"
            break
        if work["kind"] == "inbox":
            continue
        tm.state = "working"
        tm.current_task = work["task"]["id"]
        try:
            work_fn(work["task"])
        finally:
            finish_task(tm)
        done += 1
    return done
