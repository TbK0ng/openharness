"""TodoWrite — 第 5 章（Learn Claude Code s05）：会话内执行清单。

模型每次调用 TodoWrite 都会整体替换清单（不是增量打补丁）。每项：
    {"content": str, "status": "pending" | "in_progress" | "completed"}
清单保存在 context.todo_state（进程内，不落盘——s05 的机制就是会话级）。
配合 run_query 里的 nag：连续 3 回合没更新且仍有未完成项时，循环注入提醒。
"""
from __future__ import annotations

from ..tools.base import BaseTool, ToolResult

VALID_STATUS = ("pending", "in_progress", "completed")


class TodoState:
    """会话级 todo 状态（s05）。turns_since_write 由 Agent Loop 维护。"""

    def __init__(self):
        self.items: list[dict] = []
        self.turns_since_write: int = 0

    def replace(self, items: list[dict]) -> None:
        self.items = [dict(it) for it in items]
        self.turns_since_write = 0

    def pending_count(self) -> int:
        return sum(1 for it in self.items if it["status"] != "completed")

    def render(self) -> str:
        marks = {"pending": "○", "in_progress": "◐", "completed": "●"}
        lines = []
        for it in self.items:
            m = marks.get(it["status"], "?")
            lines.append(f"{m} {it['content']}  [{it['status']}]")
        return "\n".join(lines) if lines else "(empty)"


def _state(context) -> TodoState:
    st = getattr(context, "todo_state", None)
    if st is None:
        st = TodoState()
        context.todo_state = st
    return st


def todo_nag_due(context) -> bool:
    """s05 nag 条件：有清单、有未完成项、且已 3 个回合没更新。"""
    st = getattr(context, "todo_state", None)
    if st is None or not st.items:
        return False
    return st.pending_count() > 0 and st.turns_since_write >= 3


class TodoWriteTool(BaseTool):
    name = "TodoWrite"
    description = ("Replace the session todo list. Pass the FULL list every time; each "
                   "item is {content, status} with status in pending/in_progress/completed.")
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": list(VALID_STATUS)},
                    },
                    "required": ["content", "status"],
                },
            }
        },
        "required": ["todos"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        todos = params["todos"]
        bad = [t.get("content", "?") for t in todos
               if t.get("status") not in VALID_STATUS]
        if bad:
            return ToolResult(output=f"invalid status for: {', '.join(bad)}")
        st = _state(context)
        st.replace(todos)
        rendered = st.render()
        context.display("📋 TodoWrite:\n" + rendered)
        return ToolResult(output=f"Todo list updated ({st.pending_count()} open):\n{rendered}")
