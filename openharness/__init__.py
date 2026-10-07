"""OpenHarness — a 1:1 LangChain implementation of the OpenHarness tutorial architecture.

Architecture (mirrors learn-open-harness.vercel.app, 12 chapters):

    Harness = Tools + Knowledge + Observation + Action + Permissions

Subsystems (chapter 3 "10 大子系统"):
    engine/     — Agent Loop 核心循环 (ch.4, ch.12)
    tools/      — 29+ 内置工具 + 注册表模式 (ch.5)
    skills/     — 技能：知识按需加载 (ch.8)
    plugins/    — 插件扩展机制 (ch.3)
    permissions/— 三级安全护栏: default / plan / full-auto (ch.6)
    hooks/      — 生命周期事件钩子 (ch.7)
    commands/   — 用户交互命令 (ch.3)
    mcp/        — 模型上下文协议客户端 (ch.10)
    memory/     — 跨会话持久化记忆 (ch.9)
    tasks/      — 后台任务管理 (ch.3)
    agents/     — 多 Agent 协作 (ch.11)
    cron/       — 定时任务调度 (ch.5 调度类工具)
    llm/        — LangChain LLM 客户端（接入 127.0.0.1:1234）
"""

__version__ = "0.1.0"
