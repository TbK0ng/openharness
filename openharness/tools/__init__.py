"""内置工具注册表（第 5 章：29 个工具）。

register_builtin_tools(registry) 把全部内置工具注册进 ToolRegistry。
MCP 工具、插件工具由各自子系统追加。
"""
from __future__ import annotations

from .base import BaseTool, ToolResult
from .registry import ToolRegistry
from .file_read import ReadTool
from .file_write import WriteTool
from .file_edit import EditTool
from .file_glob import GlobTool
from .file_grep import GrepTool
from .notebook import NotebookEditTool
from .bash import BashTool
from .web_fetch import WebFetchTool
from .web_search import WebSearchTool
from .meta_tool_search import ToolSearchTool
from .meta_skill import SkillTool
from .meta_ask_user import AskUserQuestionTool
from .meta_plan import EnterPlanModeTool, ExitPlanModeTool
from .meta_worktree import EnterWorktreeTool, ExitWorktreeTool
from .multi_agent import AgentTool, SendMessageTool
from .task_tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool, TaskStopTool
from .mcp_tools import MCPTool, ListMcpResourcesTool, ReadMcpResourceTool
from .cron_tools import CronCreateTool, CronListTool, CronDeleteTool
from .memory_tools import MemorySaveTool, MemorySearchTool, MemoryDeleteTool
from .meta_todo import TodoWriteTool
from .meta_compact import CompactTool
from .task_board_tools import (
    CreateTaskTool, ListTasksTool, GetTaskTool, ClaimTaskTool, CompleteTaskTool,
)

BUILTIN_TOOLS = [
    # 文件类
    ReadTool, WriteTool, EditTool, GlobTool, GrepTool, NotebookEditTool,
    # 执行类
    BashTool,
    # Web 类
    WebFetchTool, WebSearchTool,
    # 元工具
    ToolSearchTool, SkillTool, AskUserQuestionTool,
    EnterPlanModeTool, ExitPlanModeTool, EnterWorktreeTool, ExitWorktreeTool,
    TodoWriteTool, CompactTool,
    # 多 Agent
    AgentTool, SendMessageTool,
    # 后台任务
    TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool, TaskStopTool,
    # 任务看板（s12）
    CreateTaskTool, ListTasksTool, GetTaskTool, ClaimTaskTool, CompleteTaskTool,
    # 长期记忆（第 9 章）
    MemorySaveTool, MemorySearchTool, MemoryDeleteTool,
    # MCP
    MCPTool, ListMcpResourcesTool, ReadMcpResourceTool,
    # 定时任务
    CronCreateTool, CronListTool, CronDeleteTool,
]


def register_builtin_tools(registry: ToolRegistry) -> None:
    for cls in BUILTIN_TOOLS:
        registry.register(cls())


__all__ = [
    "BaseTool", "ToolResult", "ToolRegistry", "register_builtin_tools", "BUILTIN_TOOLS",
]
