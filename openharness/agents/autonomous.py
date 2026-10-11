"""自主 Agent — 第 17 章（Learn Claude Code s17）：WORK → IDLE → SHUTDOWN。

teammate 生命周期（与课程一致）：
    working   正在处理已认领的任务（实际推理由外部 work_fn 完成）
    idle      任务完成后进入空闲，idle_poll 找新工作
    shutdown  收到 shutdown_request 或轮询超时后退出

idle_poll 的优先级（与课程一致）：先 consume_inbox（其他 agent 发来的消息，
shutdown_request 立即派发），再 scan_unclaimed_tasks 并 claim。多个 teammate
并发时，board.claim 的 assignee 检查保证同一任务不会被两人认领。

身份重注入：autoCompact（s08）后 messages 可能被压缩成摘要，每次进入 WORK
阶段前若 len(messages) <= 3 则重新注入身份，避免 teammate 忘记自己是谁。

consume_lead_inbox：Lead 的统一收件箱消费者——先路由协议消息更新状态，
再把所有消息注入 Lead 的对话历史（teammate 的摘要/结果进入 Lead 的上下文）。
"""
from __future__ import annotations

import dataclasses

from ..tasks.board import TaskBoard

# 参考 s17 常量：IDLE 阶段 12 次轮询 × 5 秒 = 60 秒超时
IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
MAX_WORK_ROUNDS = 10


class Inbox:
    """按名字分格的收件箱。send 入队，consume 取出并清空。"""

    def __init__(self):
        self._boxes: dict[str, list] = {}

    def send(self, to: str, message) -> None:
        self._boxes.setdefault(to, []).append(message)

    def consume(self, name: str) -> list:
        return self._boxes.pop(name, [])

    def pending(self, name: str) -> int:
        return len(self._boxes.get(name, []))


def scan_unclaimed_tasks(board: TaskBoard) -> list[dict]:
    """s17：看板上 pending、无人认领、不被阻塞的任务。"""
    return board.unclaimed()


def claim_task(board: TaskBoard, task_id: str, agent_name: str) -> dict:
    """带归属地认领（已被别人认领会抛 TaskBlockedError）。"""
    return board.claim(task_id, assignee=agent_name)


def reinject_identity(messages: list[dict], name: str, role: str) -> None:
    """s17 身份重注入：压缩后 messages 过短则重新注入身份。"""
    if len(messages) <= 3:
        messages.insert(0, {"role": "user",
                            "content": f"<identity>You are '{name}', role: {role}. "
                                       f"Continue your work.</identity>"})


def consume_lead_inbox(inbox: Inbox, name: str, history: list[dict]) -> list:
    """s17 Lead 统一收件箱消费者：路由协议消息 + 注入历史。

    返回本次取出的消息列表。shutdown_response 等协议消息先更新状态（这里
    仅记录），所有消息都注入 history，让 Lead 的 LLM 能看到 teammate 的结果。
    """
    msgs = inbox.consume(name)
    for m in msgs:
        history.append({"role": "user", "content": m if isinstance(m, str)
                        else m.get("content", str(m))})
    return msgs


@dataclasses.dataclass
class Teammate:
    name: str
    board: TaskBoard
    inbox: Inbox
    state: str = "idle"              # idle / working / shutdown
    current_task: str | None = None
    role: str = ""                   # s17 身份重注入用
    messages: list | None = None     # s17 对话历史（压缩后需重注入身份）


def _is_shutdown(msg) -> bool:
    return isinstance(msg, dict) and msg.get("type") == "shutdown_request"


def idle_poll(tm: Teammate) -> dict | None:
    """一次轮询：先收件箱（shutdown_request 立即派发），后看板。无工作返回 None。"""
    msgs = tm.inbox.consume(tm.name)
    if msgs:
        for m in msgs:
            if _is_shutdown(m):
                tm.state = "shutdown"
                return {"kind": "shutdown"}
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


def run_until_done(tm: Teammate, work_fn, poll_interval: int = IDLE_POLL_INTERVAL,
                   max_polls: int = IDLE_TIMEOUT // IDLE_POLL_INTERVAL) -> int:
    """跑完整的 WORK→IDLE→SHUTDOWN 循环，返回完成任务数。

    work_fn(task_dict) -> str：执行单个任务的「推理」（测试里用假函数）。
    每次进入 WORK 阶段前重注入身份（s17）。IDLE 阶段最多 max_polls 次轮询，
    超时或收到 shutdown_request 则退出。
    """
    if tm.messages is None:
        tm.messages = []
    done = 0
    while True:
        # 进入 WORK 阶段前重注入身份（压缩后 messages 过短）
        reinject_identity(tm.messages, tm.name, tm.role)
        work = idle_poll(tm)
        if work is None:
            tm.state = "shutdown"
            break
        if work["kind"] == "shutdown":
            break
        if work["kind"] == "inbox":
            # 普通消息注入历史，回到 WORK
            for m in work["messages"]:
                tm.messages.append({"role": "user",
                                    "content": m if isinstance(m, str) else str(m)})
            continue
        tm.state = "working"
        tm.current_task = work["task"]["id"]
        try:
            work_fn(work["task"])
        finally:
            finish_task(tm)
        done += 1
    return done
