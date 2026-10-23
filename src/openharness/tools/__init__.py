"""内置工具注册表（第 5 章）。

`register_builtin_tools(registry)` 把全部内置工具注册进 ToolRegistry。
MCP 工具、插件工具由各自子系统追加。
"""
from __future__ import annotations

from .agent_tool import AgentTool
from .ask_user_question_tool import AskUserQuestionTool
from .base import BaseTool, ToolRegistry, ToolResult
from .bash_tool import BashTool
from .claim_task_tool import ClaimTaskTool
from .compact_tool import CompactTool
from .complete_task_tool import CompleteTaskTool
from .create_task_tool import CreateTaskTool
from .cron_create_tool import CronCreateTool
from .cron_delete_tool import CronDeleteTool
from .cron_list_tool import CronListTool
from .enter_plan_mode_tool import EnterPlanModeTool
from .enter_worktree_tool import EnterWorktreeTool
from .exit_plan_mode_tool import ExitPlanModeTool
from .exit_worktree_tool import ExitWorktreeTool
from .file_edit_tool import EditTool
from .file_read_tool import ReadTool
from .file_write_tool import WriteTool
from .get_task_tool import GetTaskTool
from .glob_tool import GlobTool
from .grep_tool import GrepTool
from .list_mcp_resources_tool import ListMcpResourcesTool
from .list_tasks_tool import ListTasksTool
from .mcp_tool import MCPTool
from .memory_delete_tool import MemoryDeleteTool
from .memory_save_tool import MemorySaveTool
from .memory_search_tool import MemorySearchTool
from .notebook_edit_tool import NotebookEditTool
from .read_mcp_resource_tool import ReadMcpResourceTool
from .send_message_tool import SendMessageTool
from .skill_tool import SkillTool
from .task_create_tool import TaskCreateTool
from .task_get_tool import TaskGetTool
from .task_list_tool import TaskListTool
from .task_stop_tool import TaskStopTool
from .task_update_tool import TaskUpdateTool
from .todo_write_tool import TodoWriteTool
from .tool_search_tool import ToolSearchTool
from .web_fetch_tool import WebFetchTool
from .web_search_tool import WebSearchTool

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
