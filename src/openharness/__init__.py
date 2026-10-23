"""OpenHarness — a 1:1 LangChain implementation of the OpenHarness tutorial architecture.

Architecture (mirrors learn-open-harness.vercel.app, 12 chapters):

    Harness = Tools + Knowledge + Observation + Action + Permissions

Subsystems (chapter 3 "10 大子系统"):
    api/        — provider 预设 + LangChain LLM 客户端 (ch.4)
    engine/     — Agent Loop 核心循环、Engine 装配、错误恢复 (ch.4, ch.11, ch.12)
    tools/      — 内置工具 + 注册表模式，一个工具一个模块 (ch.5)
    prompts/    — system prompt 组装 (ch.4)
    config/     — `.oh/` 路径约定与 settings 加载
    services/   — 会话落盘、autoCompact、cron 调度等常驻服务
    ui/         — REPL 行编辑与终端输出
    skills/     — 技能：知识按需加载 (ch.8)
    plugins/    — 插件扩展机制 (ch.3)
    permissions/— 三级安全护栏: default / plan / full-auto (ch.6)
    hooks/      — 生命周期事件钩子 (ch.7)
    commands/   — 用户交互命令 (ch.3)
    mcp/        — 模型上下文协议客户端 (ch.10)
    memory/     — 跨会话持久化记忆 (ch.9)
    tasks/      — 后台任务管理 + 任务看板 (ch.3, s12)
    swarm/      — 多 Agent 协作（子 Agent / 自主 Teammate）(ch.11, s17)
"""

__version__ = "0.1.0"
