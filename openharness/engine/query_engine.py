"""Engine 初始化 — 对应教程第 12 章第 2 步。

Engine 在会话开始时组装：
    1. 加载 settings.json（权限模式 / hooks / mcp_servers / skills / memory）
    2. 初始化全部子系统（memory/skills/mcp/team/tasks/cron/hooks/permissions）
    3. 注册工具（内置 + MCP + 插件）
    4. 组装 system prompt（注入 MEMORY.md 记忆 + 技能清单 + 子 Agent 说明）
    5. 提供 create_context() 生成 Agent Loop 用的 Context
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from ..agents.team import TeamRegistry
from ..commands.registry import CommandRegistry
from ..cron.manager import CronManager
from ..hooks.executor import HookManager
from ..mcp.client import MCPClientManager
from ..memory.manager import MemoryManager
from ..paths import ensure_oh_dir
from ..permissions.checker import PermissionChecker
from ..plugins.registry import PluginContext, PluginRegistry
from ..skills.loader import SkillLoader
from ..tasks.manager import TaskManager
from .llm import build_llm
from .query import Context


def default_config(cwd: Path) -> dict:
    return {
        "cwd": str(cwd),
        # provider: lmstudio（本地 127.0.0.1:1234）| deepseek（云端）
        # base_url / api_key / model 留空时按 provider 预设解析（见 engine/llm.py::PROVIDERS）
        "provider": "lmstudio",
        "base_url": "",
        "api_key": "",
        "model": "",
        "max_turns": 30,
        "permissions": {"mode": "default", "deny_tools": [], "deny_paths": [], "deny_commands": []},
        "hooks": {},
        "mcp_servers": {},
        # 相对路径一律以配置目录 .oh/ 为根
        "skills_dirs": ["skills"],
        "memory_dir": "memory",
        "plugins_dir": "plugins",
    }


class Engine:
    def __init__(self, cwd: Optional[str] = None, config_path: Optional[str] = None):
        self.cwd = Path(cwd or Path.cwd())
        self.oh_dir = ensure_oh_dir(self.cwd)
        self.config = self._load_config(config_path)
        # 子系统
        self.memory = MemoryManager(self.oh_dir, subdir=self.config["memory_dir"])
        self.skills = SkillLoader(self._resolve_dirs(self.config["skills_dirs"]))
        self.hooks = HookManager(self.config)
        self.permissions = PermissionChecker(self.config["permissions"])
        self.team = TeamRegistry(engine=self)
        self.tasks = TaskManager(self.cwd)
        self.cron = CronManager(self.oh_dir)
        self.mcp = MCPClientManager(self.config, self.cwd)
        self.registry = self._new_registry()
        self.commands = CommandRegistry()
        self.plugins = PluginRegistry()
        self.mcp_status: dict = {}
        # 组装
        self._register_tools()
        self._load_plugins()
        self._connect_mcp()
        self._register_builtin_commands()
        self._sid: Optional[str] = None
        self._ctx: Optional[object] = None   # create_context() 后指向当前会话

    # ---- 配置 ----
    def _resolve_dirs(self, dirs) -> list[Path]:
        """相对路径以 .oh/ 为根；绝对路径原样使用。"""
        out = []
        for d in dirs or []:
            p = Path(d)
            out.append(p if p.is_absolute() else self.oh_dir / p)
        return out

    def _load_config(self, config_path: Optional[str]) -> dict:
        cfg = default_config(self.cwd)
        candidates = [Path(config_path)] if config_path else [
            self.oh_dir / "settings.json",
            self.cwd / "settings.json",          # 兼容旧位置
        ]
        for p in candidates:
            if p.exists():
                user = json.loads(p.read_text(encoding="utf-8"))
                self._deep_update(cfg, user)
                break
        return cfg

    @staticmethod
    def _deep_update(base: dict, extra: dict) -> None:
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Engine._deep_update(base[k], v)
            else:
                base[k] = v

    # ---- 组装 ----
    def _new_registry(self):
        from ..tools.registry import ToolRegistry
        return ToolRegistry()

    def _register_tools(self) -> None:
        from ..tools import register_builtin_tools
        register_builtin_tools(self.registry)

    def _load_plugins(self) -> None:
        plugin_dir = self.oh_dir / self.config.get("plugins_dir", "plugins")
        if not plugin_dir.exists():
            self.plugin_names = []
            return
        ctx = PluginContext()
        self.plugin_names = self.plugins.load_dir(plugin_dir, ctx)
        for tool in ctx.tools:
            self.registry.register(tool)
        for name, help_text, fn in ctx.commands:
            self.commands.register(name, help_text, fn)
        for name, content in ctx.skills:
            self.skills.add_runtime(name, content)

    def _connect_mcp(self) -> None:
        if not self.config["mcp_servers"]:
            return
        self.mcp_status = self.mcp.connect_all()
        self._register_mcp_tools()

    def _register_mcp_tools(self) -> None:
        """把已连接 server 的每个 tool 注册成原生工具（模型可直接调用）。"""
        from ..tools.mcp_dynamic import mcp_tools_for
        for tool in mcp_tools_for(self.mcp):
            self.registry.register(tool)

    def _register_builtin_commands(self) -> None:
        """注册内置斜杠命令（第 3 章 Commands 子系统）。

        register(name, help_text, fn) —— 与 CommandRegistry 的签名一致。
        """
        c = self.commands
        c.register("help", "列出所有可用命令", self._cmd_help)
        c.register("mode", "查看/切换权限模式 [default|plan|full-auto]", self._cmd_mode)
        c.register("memory", "显示当前长期记忆 (MEMORY.md)", self._cmd_memory)
        c.register("skills", "列出已发现的技能", self._cmd_skills)
        c.register("tasks", "列出后台任务", self._cmd_tasks)
        c.register("cron", "列出定时任务", self._cmd_cron)
        c.register("tools", "列出已注册工具", self._cmd_tools)
        c.register("mcp", "显示 MCP 服务器连接状态", self._cmd_mcp)
        c.register("agents", "列出子 Agent", self._cmd_agents)
        c.register("init", "生成 .oh/settings.json 配置模板", self._cmd_init)
        c.register("clear", "清空当前会话消息历史", self._cmd_clear)
        c.register("exit", "退出会话", self._cmd_exit)

    # ---- Context ----
    def create_context(self) -> Context:
        system_prompt = self._build_system_prompt()
        ctx = Context(
            session_id=self._session_id(),
            cwd=str(self.cwd),
            oh_dir=str(self.oh_dir),
            messages=[],
            system_prompt=system_prompt,
            tool_schemas=self.registry.get_tool_schemas(),
            llm=build_llm(self.config),
            registry=self.registry,
            permissions=self.permissions,
            hooks=self.hooks,
            memory=self.memory,
            skills=self.skills,
            mcp=self.mcp,
            team=self.team,
            tasks=self.tasks,
            cron=self.cron,
            config=self.config,
            mode=self.permissions.mode,
        )
        # 注入会话上下文供后台子系统使用
        self.cron.context = ctx
        self._ctx = ctx   # 供 /clear 等命令操作当前会话
        return ctx

    def _session_id(self) -> str:
        if self._sid is None:
            self._sid = uuid.uuid4().hex[:8]
        return self._sid

    def _build_system_prompt(self) -> str:
        parts = [
            "You are OpenHarness, an autonomous coding assistant "
            "(a 1:1 implementation of the OpenHarness tutorial architecture).",
            f"Working directory: {self.cwd}",
            f"Permission mode: {self.permissions.mode}",
        ]
        mem = self.memory.snapshot()
        if mem:
            parts.append(mem)
        sk = self.skills.summary()
        if sk:
            parts.append(sk)
        parts.append(
            "Guidelines:\n"
            "- Inspect files with Read/Glob/Grep before editing.\n"
            "- Use Write/Edit to change code; prefer minimal diffs.\n"
            "- Use Bash to run commands and tests.\n"
            "- Persist important facts to MEMORY.md / memory/*.md.\n"
            "- Load a skill with the Skill tool when a matching one exists.\n"
            "- For large or parallel work, delegate to sub-agents via the Agent tool "
            "(explore/plan/implement/review).\n"
            "- Be concise. End each turn with a short summary of what changed."
        )
        return "\n\n".join(parts)

    # ---- 内置命令 ----
    def _cmd_help(self, args: str) -> str:
        lines = [f"/{c.name} — {c.help_text}" for c in self.commands.list()]
        return "可用命令：\n" + "\n".join(lines)

    def _cmd_mode(self, args: str) -> str:
        if args.strip():
            self.permissions.set_mode(args.strip())
            return f"权限模式 -> {self.permissions.mode}"
        return f"当前权限模式: {self.permissions.mode}"

    def _cmd_memory(self, args: str) -> str:
        return self.memory.snapshot() or "（无记忆）"

    def _cmd_skills(self, args: str) -> str:
        return self.skills.summary() or "（无技能）"

    def _cmd_tasks(self, args: str) -> str:
        return self.tasks.summary() or "（无后台任务）"

    def _cmd_cron(self, args: str) -> str:
        return self.cron.summary() or "（无定时任务）"

    def _cmd_tools(self, args: str) -> str:
        tools = self.registry.list_tools()
        lines = [f"{'[只读]' if t.read_only else '[写入]'} {t.name} — {t.description}"
                 for t in tools]
        return f"已注册 {len(tools)} 个工具：\n" + "\n".join(lines)

    def _cmd_mcp(self, args: str) -> str:
        if not self.mcp_status:
            return "未配置 MCP 服务器（settings.json 的 mcp_servers）"
        dynamic = {t.name for t in self.registry.list_tools() if t.name.startswith("mcp__")}
        lines = []
        for name, status in self.mcp_status.items():
            if status.get("ok"):
                tools = ", ".join(status.get("tools") or []) or "(none)"
                resources = ", ".join(status.get("resources") or []) or "(none)"
                lines.append(f"{name}: connected | tools: {tools} | resources: {resources}")
            else:
                lines.append(f"{name}: FAILED — {status.get('error', 'unknown error')}")
        if dynamic:
            lines.append(f"原生工具 {len(dynamic)} 个：{', '.join(sorted(dynamic))}")
        return "\n".join(lines)

    def _cmd_agents(self, args: str) -> str:
        agents = self.team.list()
        if not agents:
            return "（无子 Agent）"
        return "\n".join(f"{a.agent_id} [{a.agent_type}] {a.status} — {a.name}"
                         for a in agents)

    def _cmd_init(self, args: str) -> str:
        """把 settings.example.json 复制成 .oh/settings.json（不覆盖已有文件）。"""
        target = self.oh_dir / "settings.json"
        if target.exists():
            return f"配置已存在，未覆盖：{target}"
        example = self.cwd / "settings.example.json"
        if example.exists():
            target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            return f"已生成 {target}（来自 settings.example.json）"
        target.write_text(json.dumps(default_config(self.cwd), indent=2,
                                     ensure_ascii=False) + "\n", encoding="utf-8")
        return f"已生成 {target}（默认配置）"

    def _cmd_clear(self, args: str) -> str:
        if self._ctx is not None:
            self._ctx.messages.clear()
        return "已清空会话历史"

    def _cmd_exit(self, args: str) -> str:
        raise SystemExit
