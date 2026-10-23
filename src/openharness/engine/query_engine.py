"""Engine 初始化 — 对应教程第 12 章第 2 步。

Engine 在会话开始时组装：
    1. 加载 settings.json（权限模式 / hooks / mcp_servers / skills / memory）
    2. 初始化全部子系统（memory/skills/mcp/team/tasks/cron/hooks/permissions）
    3. 注册工具（内置 + MCP + 插件）
    4. 组装 system prompt（注入 MEMORY.md 记忆 + 技能清单 + 子 Agent 说明）
    5. 提供 create_context() 生成 Agent Loop 用的 Context
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from ..api.client import build_llm
from ..commands.registry import CommandRegistry
from ..config.paths import ensure_oh_dir
from ..config.settings import default_config, load_config, save_permissions
from ..hooks.executor import HookManager
from ..mcp.client import MCPClientManager
from ..memory.manager import MemoryManager
from ..permissions.checker import PermissionChecker
from ..plugins.registry import PluginContext, PluginRegistry
from ..prompts.system_prompt import build_system_prompt
from ..services.cron import CronManager
from ..services.session_storage import Session, SessionStore
from ..skills.loader import SkillLoader
from ..swarm.team import TeamRegistry
from ..tasks.manager import TaskManager
from ..tools.base import ToolRegistry
from ..ui.output import is_tty
from .query import Context


class Engine:
    def __init__(self, cwd: Optional[str] = None, config_path: Optional[str] = None,
                 connect_mcp: Optional[bool] = None):
        self.cwd = Path(cwd or Path.cwd())
        self.oh_dir = ensure_oh_dir(self.cwd)
        self.config = load_config(self.cwd, self.oh_dir, config_path)
        # 子系统
        self.memory = MemoryManager(self.oh_dir, subdir=self.config["memory_dir"])
        self.skills = SkillLoader(self._resolve_dirs(self.config["skills_dirs"]))
        self.hooks = HookManager(self.config)
        self.permissions = PermissionChecker(self.config["permissions"])
        self.team = TeamRegistry(engine=self)
        self.tasks = TaskManager(self.oh_dir, engine=self)
        self.cron = CronManager(self.oh_dir, tasks=self.tasks, workdir=self.cwd)
        self.mcp = MCPClientManager(self.config, self.cwd, oh_dir=self.oh_dir)
        self.registry = self._new_registry()
        self.commands = CommandRegistry()
        self.plugins = PluginRegistry()
        self.mcp_status: dict = {}
        # 组装
        self._register_tools()
        self._load_plugins()
        # MCP 连接会启动子进程（可能很慢）。默认懒连接：首次 create_context()
        # 或显式调用 _connect_mcp() 时才连，避免每次 Engine() 都付启动代价。
        self._mcp_connected = False
        if connect_mcp is True:
            self._connect_mcp()
        self._register_builtin_commands()
        self.sessions: dict[str, Session] = {}
        self.session: Optional[Session] = None
        self.session_store = SessionStore(self.oh_dir)

    # ---- 配置 ----
    def _resolve_dirs(self, dirs) -> list[Path]:
        """相对路径以 .oh/ 为根；绝对路径原样使用。"""
        out = []
        for d in dirs or []:
            p = Path(d)
            out.append(p if p.is_absolute() else self.oh_dir / p)
        return out

    # ---- 组装 ----
    def _new_registry(self) -> ToolRegistry:
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
        if self._mcp_connected:
            return
        self._mcp_connected = True
        if not self.mcp.config:
            return
        self.mcp_status = self.mcp.connect_all()
        self._register_mcp_tools()

    def ensure_mcp(self) -> None:
        """惰性连接 MCP（在需要工具清单/状态前调用）。"""
        self._connect_mcp()

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
        c.register("help", "列出所有可用命令（/help <命令> 查看单个命令）", self._cmd_help,
                   usage="/help [命令]",
                   completer=lambda: {cmd.name: cmd.help_text
                                      for cmd in c.list()})
        c.register("mode", "查看/切换权限模式", self._cmd_mode,
                   usage="/mode [default|plan|full-auto]",
                   choices={"default": "只读自动通过，写操作需确认",
                            "plan": "只读规划，阻止所有写入",
                            "full-auto": "全部自动通过（沙箱/完全信任）"})
        c.register("new", "开启新会话（旧会话保留，可 /switch 返回）", self._cmd_new,
                   usage="/new [名称]")
        c.register("fork", "从当前会话分叉出新会话并切换过去", self._cmd_fork,
                   usage="/fork [名称]")
        c.register("side", "进入/退出临时会话（不写回原会话）", self._cmd_side,
                   usage="/side [off]",
                   choices={"off": "结束临时会话并返回原会话"})
        c.register("sessions", "列出全部会话（含已保存的会话）", self._cmd_sessions)
        c.register("switch", "切换到指定会话（含已保存会话）", self._cmd_switch,
                   usage="/switch <id|名称>",
                   completer=lambda: self.session_choices())
        c.register("rewind", "回退最后一轮对话（等价于双击 Esc）", self._cmd_rewind)
        c.register("permission", "查看/调整权限：允许、拒绝、切换模式、持久化",
                   self._cmd_permission,
                   usage="/permission [allow|deny|forget|mode|reset|save] [值]",
                   choices={"allow": "本会话自动允许某工具",
                            "deny": "禁用某工具",
                            "forget": "移除某工具的白/黑名单",
                            "mode": "切换权限模式（同 /mode）",
                            "reset": "清空本会话的自动允许",
                            "save": "把当前权限写入 .oh/settings.json"})
        c.register("memory", "显示当前长期记忆 (MEMORY.md)", self._cmd_memory)
        c.register("skills", "列出已发现的技能", self._cmd_skills)
        c.register("tasks", "列出后台任务", self._cmd_tasks)
        c.register("cron", "查看/创建/删除/立即触发定时任务", self._cmd_cron,
                   usage="/cron [list|add <分 时 日 月 周> <command|agent> <内容>|delete <id>|run <id>|start]",
                   choices={"list": "列出任务与调度器状态",
                            "add": "创建任务：/cron add */5 * * * * command echo hi",
                            "delete": "删除任务：/cron delete cron-1",
                            "run": "立即触发一次：/cron run cron-1",
                            "start": "启动调度线程"})
        c.register("tools", "列出已注册工具", self._cmd_tools)
        c.register("mcp", "显示 MCP 服务器连接状态", self._cmd_mcp)
        c.register("agents", "列出子 Agent", self._cmd_agents)
        c.register("init", "生成 .oh/settings.json 配置模板", self._cmd_init)
        c.register("clear", "清空当前会话消息历史", self._cmd_clear)
        c.register("exit", "退出会话", self._cmd_exit)

    # ---- Context / 会话 ----
    def create_context(self) -> Context:
        """当前会话的 Context；首次调用时自动开启一个 main 会话。

        LLM 客户端按需构建：/new、/fork、/side 只是复制消息，不应为
        LM Studio 付一次模型发现/连接的超时代价。
        """
        ctx = self.current_session().context
        if getattr(ctx, "llm", None) is None or getattr(ctx, "llm_closed", False):
            ctx.llm = build_llm(self.config)
            ctx.llm_closed = False
        return ctx

    def current_session(self) -> Session:
        if self.session is None:
            return self.new_session()
        return self.session

    # ---- 会话持久化 ----
    def save_session(self, session: Optional[Session] = None) -> None:
        """把 main/fork 会话写入 `.oh/sessions/`（side 临时会话跳过）。"""
        session = session or self.session
        if session is None:
            return
        self.session_store.save(
            session, getattr(session.context, "todo_state", None))

    def save_current_session(self) -> None:
        self.save_session(self.session)

    def persisted_sessions(self) -> list[dict]:
        return self.session_store.list()

    def session_choices(self) -> dict[str, str]:
        """补全/列表用：磁盘会话 + 进程内会话（内存态优先）。"""
        out = {}
        for rec in self.session_store.list():
            name = f" {rec['name']}" if rec.get("name") else ""
            out[rec["id"]] = (f"{rec['id']} [{rec['kind']}]{name}"
                              f" · {rec['message_count']} 条（已保存）")
        for session in self.sessions.values():
            out[session.id] = session.label
        return out

    def _adopt_session(self, record: dict) -> Session:
        """把磁盘记录载入成活动 Session（保持原 id/名称/消息历史）。"""
        sid = record["id"]
        existing = self.sessions.get(sid)
        if existing is not None:
            self._activate(existing)
            return existing

        ctx = self._build_context(
            sid, copy.deepcopy(record.get("messages") or []))
        todos = record.get("todos") or []
        if todos:
            from ..tools.todo_write_tool import TodoState
            state = TodoState()
            state.items = [dict(item) for item in todos if isinstance(item, dict)]
            ctx.todo_state = state
        session = Session(
            id=sid,
            context=ctx,
            kind=record.get("kind") or "main",
            name=record.get("name") or "",
            parent_id=record.get("parent_id"),
            created_at=record.get("created_at") or time.time(),
        )
        self.sessions[sid] = session
        self._activate(session)
        return session

    def close(self) -> None:
        """进程退出前的收尾：停调度线程、结束 MCP 子进程。

        不做这一步，MCP server 进程会留在后台（Windows 下父进程退出不带走子进程），
        下次启动可能因为锁竞争直接握手失败。
        """
        try:
            self.cron.stop()
        except Exception:  # noqa: BLE001 - 收尾不允许抛
            pass
        try:
            self.mcp.close_all()
        except Exception:  # noqa: BLE001
            pass

    def start_background(self) -> None:
        """启动常驻后台调度（cron）。CLI 在进入主循环前调用。"""
        if self.session is None and any(
                j.kind == "agent" for j in self.cron.list()):
            # agent 类型任务需要会话上下文（不构建 LLM，触发时子任务自建）。
            self.current_session()
        self.cron.start()

    def new_session(self, *, kind: str = "main", name: str = "",
                    seed: Optional[Session] = None) -> Session:
        """新建会话并切换过去。seed 非空时深拷贝其消息与 todo 状态。"""
        self.ensure_mcp()
        sid = uuid.uuid4().hex[:8]
        messages = copy.deepcopy(seed.context.messages) if seed is not None else []
        ctx = self._build_context(sid, messages)
        if seed is not None:
            self._copy_session_state(seed.context, ctx)
        session = Session(
            id=sid, context=ctx, kind=kind, name=name.strip(),
            parent_id=seed.id if seed is not None else None,
        )
        self.sessions[sid] = session
        self._activate(session)
        return session

    def _build_context(self, session_id: str, messages: list[dict]) -> Context:
        ctx = Context(
            session_id=session_id,
            cwd=str(self.cwd),
            oh_dir=str(self.oh_dir),
            messages=messages,
            system_prompt=self._build_system_prompt(),
            tool_schemas=self.registry.get_tool_schemas(),
            llm=None,
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
        return ctx

    @staticmethod
    def _copy_session_state(src: Context, dst: Context) -> None:
        """fork/side 只继承会话级状态；恢复状态与压缩熔断器按新会话重置。"""
        value = getattr(src, "todo_state", None)
        if value is not None:
            try:
                dst.todo_state = copy.deepcopy(value)
            except Exception:  # noqa: BLE001 - 状态拷贝失败不应阻断分叉
                pass

    def _activate(self, session: Session) -> None:
        self.session = session
        self.cron.context = session.context
        session.context.mode = self.permissions.mode

    def begin_turn(self) -> Context:
        """准备一轮 Agent Loop：刷新 system prompt / 工具表 / LLM 客户端。"""
        ctx = self.create_context()
        ctx.system_prompt = self._build_system_prompt()
        ctx.tool_schemas = self.registry.get_tool_schemas()
        ctx.mode = self.permissions.mode
        return ctx

    def find_session(self, key: str) -> Optional[Session]:
        key = key.strip()
        if not key:
            return None
        if key in self.sessions:
            return self.sessions[key]
        for s in self.sessions.values():
            if s.id.startswith(key) or (s.name and s.name == key):
                return s
        for s in self.sessions.values():
            if s.name and s.name.startswith(key):
                return s
        return None

    def switch_session(self, key: str) -> Optional[Session]:
        target = self.find_session(key)
        record = None
        if target is None:
            record = self.session_store.load(key)   # 重启后从磁盘恢复
            if record is None:
                return None

        old = self.session
        if old is not None and old is not target:
            if old.kind == "side":
                self.sessions.pop(old.id, None)     # 临时会话离开即丢弃
            else:
                self.save_session(old)              # 切换前落盘

        if target is None:
            return self._adopt_session(record)
        self._activate(target)
        return target

    def rewind_last_turn(self) -> tuple[Optional[str], str]:
        """删掉当前会话最后一轮（user + 后续 assistant/tool），返回原输入。"""
        session = self.current_session()
        messages = session.context.messages
        while messages and messages[-1].get("role") != "user":
            messages.pop()
        if not messages:
            return None, f"会话 {session.id} 已到开头，没有可回退的回合。"
        prompt = messages.pop().get("content", "")
        session.context.recovery_state = None
        self.save_session(session)
        text = prompt if isinstance(prompt, str) else str(prompt)
        return text, (f"已回退会话 {session.id} 的最后一轮（原输入已放回输入框；"
                      "文件改动不会被撤销）。")

    def _build_system_prompt(self) -> str:
        return build_system_prompt(
            cwd=self.cwd,
            mode=self.permissions.mode,
            memory=self.memory,
            skills=self.skills,
        )

    # ---- 内置命令 ----
    def _cmd_help(self, args: str) -> str:
        name = args.strip().lstrip("/")
        if name:
            cmd = self.commands.get(name)
            if cmd is None:
                return f"未知命令: /{name}（输入 /help 查看可用命令）"
            lines = [cmd.usage_line(), "", cmd.help_text]
            options = cmd.options()
            if options:
                lines.append("")
                lines += [f"  {v:<12} {d}" for v, d in options.items()]
            return "\n".join(lines)
        rows = [(c.usage_line(), c.help_text) for c in self.commands.list()]
        width = max(len(u) for u, _ in rows) + 2
        lines = [f"{u:<{width}}{h}" for u, h in rows]
        return ("可用命令：\n" + "\n".join(lines)
                + "\n\n提示：输入 / 打开补全菜单，Tab 补全命令与参数，↑/↓ 翻历史。")

    def _cmd_mode(self, args: str) -> str:
        choices = self.commands.get("mode").choices
        value = args.strip()
        if value:
            try:
                self.permissions.set_mode(value)
            except ValueError:
                valid = "|".join(choices)
                return f"未知权限模式: {value}（可选 {valid}）"
            self._sync_context_mode()
            return f"权限模式 -> {self.permissions.mode}（/permission save 可持久化）"

        # 不带参数：终端下直接给一个编号菜单，非交互环境只列选项。
        if is_tty():
            menu = (f"\n当前权限模式: {self.permissions.mode}\n"
                    + "\n".join(f"  [{i}] {name:<10} {desc}"
                                for i, (name, desc) in enumerate(choices.items(), 1))
                    + "\n选择模式（回车取消）: ")
            try:
                answer = input(menu).strip()
            except (EOFError, KeyboardInterrupt):
                return "（保持当前模式）"
            if not answer:
                return f"当前权限模式: {self.permissions.mode}（未修改）"
            names = list(choices)
            chosen = names[int(answer) - 1] if answer.isdigit() \
                and 1 <= int(answer) <= len(names) else answer
            if chosen not in choices:
                return f"未知权限模式: {answer}（可选 {'|'.join(choices)}）"
            self.permissions.set_mode(chosen)
            self._sync_context_mode()
            return f"权限模式 -> {self.permissions.mode}（/permission save 可持久化）"

        lines = [f"当前权限模式: {self.permissions.mode}", "切换：/mode <模式>"]
        lines += [f"  {name:<10} {desc}" for name, desc in choices.items()]
        lines.append("提示：/permission allow <工具> 可让某工具不再询问。")
        return "\n".join(lines)

    def _sync_context_mode(self) -> None:
        if self.session is not None:
            self.session.context.mode = self.permissions.mode

    # ---- 会话命令 ----
    def _cmd_new(self, args: str) -> str:
        old = self.session
        if old is not None:
            self.save_session(old)
            if old.kind == "side":
                self.sessions.pop(old.id, None)
        session = self.new_session(kind="main", name=args.strip())
        self.save_session(session)
        msg = f"已开启新会话 {session.label}"
        if old is not None and old.id in self.sessions and old.id != session.id:
            msg += (f"；上一会话 {old.id} 已保存"
                    f"（/sessions 查看，/switch {old.id} 返回）")
        return msg

    def _cmd_fork(self, args: str) -> str:
        parent = self.current_session()
        self.save_session(parent)
        name = args.strip() or f"fork-{parent.id}"
        child = self.new_session(kind="fork", name=name, seed=parent)
        self.save_session(child)
        return (f"已从 {parent.id} 分叉出新会话 {child.label}"
                f"（{len(child.messages)} 条消息）；"
                f"父会话已保存，/switch {parent.id} 返回。")

    def _cmd_side(self, args: str) -> str:
        action = args.strip()
        if action.lower() in ("off", "end", "exit", "close", "back", "返回"):
            return self._end_side()
        if self.session is not None and self.session.kind == "side":
            return "已在临时会话中；/side off 结束并返回原会话。"
        parent = self.current_session()
        self.save_session(parent)   # 临时会话基于最新快照
        side = self.new_session(kind="side", name=action or f"side-{parent.id}",
                                seed=parent)
        return (f"已进入临时会话 {side.label}（快照自 {parent.id}）。"
                "这里的对话不会写回原会话，也不会落盘；/side off 结束并丢弃。")

    def _end_side(self) -> str:
        session = self.session
        if session is None or session.kind != "side":
            return "当前不在临时会话中（/side 进入，/side off 返回）。"
        parent = self.sessions.get(session.parent_id) if session.parent_id else None
        self.sessions.pop(session.id, None)
        self.session_store.delete(session.id)   # side 本不落盘，防御性清理
        if parent is not None:
            self._activate(parent)
            return f"已结束临时会话 {session.id}，返回 {parent.id}。"
        fresh = self.new_session()
        return f"已结束临时会话 {session.id}，已开启新会话 {fresh.id}。"

    def _cmd_sessions(self, args: str) -> str:
        lines = []
        for s in self.sessions.values():
            mark = "*" if s is self.session else " "
            parent = f" ← {s.parent_id}" if s.parent_id else ""
            lines.append(f"{mark} {s.label} · {len(s.messages)} 条消息{parent}")
        for rec in self.session_store.list():
            if rec["id"] in self.sessions:
                continue
            parent = f" ← {rec['parent_id']}" if rec.get("parent_id") else ""
            name = f" {rec['name']}" if rec.get("name") else ""
            preview = f" · {rec['preview']}" if rec.get("preview") else ""
            lines.append(f"  {rec['id']} [{rec['kind']}]{name}"
                         f" · {rec['message_count']} 条消息（已保存）"
                         f"{parent}{preview}")
        if not lines:
            return "（无会话）"
        return ("会话（* = 当前；已保存的会话可 /switch 载入）：\n"
                + "\n".join(lines))

    def _cmd_switch(self, args: str) -> str:
        key = args.strip()
        if not key:
            return "用法：/switch <会话 id 或名称>（/sessions 查看）"
        target = self.switch_session(key)
        if target is None:
            return f"未知会话: {key}（/sessions 查看）"
        return f"已切换到会话 {target.label}（{len(target.messages)} 条消息）"

    def _cmd_rewind(self, args: str) -> str:
        text, note = self.rewind_last_turn()
        if text is None:
            return note
        return f"{note}\n↩ 原输入：{text}"

    # ---- 权限命令 ----
    def _cmd_permission(self, args: str) -> str:
        parts = args.strip().split(maxsplit=1)
        if not parts:
            return self._permission_summary()
        action = parts[0].lower()
        value = parts[1].strip() if len(parts) > 1 else ""

        if action == "mode":
            return self._cmd_mode(value)
        if action in ("allow", "deny", "forget"):
            if not value:
                return f"用法：/permission {action} <工具名>"
            if action == "allow":
                self.permissions.allow_tool(value)
                return (f"已在本会话自动允许 {value}；"
                        "以后该工具的写操作不再询问（/permission save 持久化）。")
            if action == "deny":
                self.permissions.deny_tool(value)
                return f"已禁用工具 {value}（本会话；/permission save 持久化）。"
            self.permissions.forget_tool(value)
            return f"已从允许/拒绝列表移除 {value}。"
        if action == "reset":
            self.permissions.clear_allows()
            return "已清空本会话的自动允许列表（配置里的 deny 规则不受影响）。"
        if action == "save":
            return self._save_permissions()
        return (f"未知子命令: {action}（可选 allow|deny|forget|mode|reset|save）\n"
                + self._permission_summary())

    def _permission_summary(self) -> str:
        perm = self.permissions
        allows = ", ".join(sorted(perm.allowed_tools)) or "（空）"
        denies = ", ".join(sorted(map(str, perm.denied_tools))) or "（空）"
        paths = ", ".join(perm.deny_paths) or "（空）"
        commands = ", ".join(perm.deny_commands) or "（空）"
        return ("权限状态\n"
                f"  模式      : {perm.mode}\n"
                f"  自动允许  : {allows}\n"
                f"  拒绝工具  : {denies}\n"
                f"  拒绝路径  : {paths}\n"
                f"  拒绝命令  : {commands}\n"
                "用法：/permission allow|deny|forget <工具> · mode <模式> · "
                "reset · save\n"
                "提示：审批时按 a = 本会话始终允许该工具；/permission save 写入 "
                f"{self.oh_dir / 'settings.json'}。")

    def _save_permissions(self) -> str:
        path = save_permissions(self.oh_dir / "settings.json", {
            "mode": self.permissions.mode,
            "allow_tools": sorted(self.permissions.allowed_tools),
            "deny_tools": sorted(map(str, self.permissions.denied_tools)),
            "deny_paths": list(self.permissions.deny_paths),
            "deny_commands": list(self.permissions.deny_commands),
        })
        return f"已保存权限配置到 {path}"

    def _cmd_memory(self, args: str) -> str:
        return self.memory.snapshot() or "（无记忆）"

    def _cmd_skills(self, args: str) -> str:
        return self.skills.summary() or "（无技能）"

    def _cmd_tasks(self, args: str) -> str:
        return self.tasks.summary() or "（无后台任务）"

    def _cmd_cron(self, args: str) -> str:
        parts = args.strip().split()
        usage = ("用法：/cron add <分 时 日 月 周> <command|agent> <内容>\n"
                 "      /cron list | delete <id> | run <id> | start\n"
                 "      例：/cron add */5 * * * * command echo tick")
        action = parts[0].lower() if parts else "list"

        if action in ("list", "ls", ""):
            state = "运行中" if self.cron.running else "未启动"
            summary = self.cron.summary()
            if summary == "(no scheduled jobs)":
                summary = "（无定时任务）"
            return f"调度器: {state}\n{summary}\n\n{usage}"

        if action == "add":
            if len(parts) < 8:
                return "参数不足。\n" + usage
            schedule = " ".join(parts[1:6])
            kind = parts[6].lower()
            payload = " ".join(parts[7:]).strip()
            if kind not in ("command", "agent"):
                return f"未知任务类型: {kind}（可选 command|agent）"
            try:
                job = self.cron.create(
                    schedule, kind,
                    command=payload if kind == "command" else "",
                    prompt=payload if kind == "agent" else "",
                )
            except ValueError as exc:
                return f"创建失败: {exc}\n{usage}"
            self.cron.start()
            return (f"已创建 {job.job_id}: {job}\n"
                    "调度器已启动；定时任务仅在 CLI 运行期间触发。")

        if action == "delete":
            if len(parts) < 2:
                return "用法：/cron delete <job_id>"
            ok = self.cron.delete(parts[1])
            return (f"已删除 {parts[1]}" if ok
                    else f"任务不存在: {parts[1]}")

        if action == "run":
            if len(parts) < 2:
                return "用法：/cron run <job_id>"
            ok = self.cron.run_now(parts[1])
            return (f"已立即触发 {parts[1]}（输出见 .oh/data/cron.log）"
                    if ok else f"任务不存在: {parts[1]}")

        if action == "start":
            self.cron.start()
            return "定时任务调度器已启动（进程退出后停止）"

        return f"未知子命令: {action}\n{usage}"

    def _cmd_tools(self, args: str) -> str:
        tools = self.registry.list_tools()
        lines = [f"{'[只读]' if t.read_only else '[写入]'} {t.name} — {t.description}"
                 for t in tools]
        return f"已注册 {len(tools)} 个工具：\n" + "\n".join(lines)

    def _cmd_mcp(self, args: str) -> str:
        self.ensure_mcp()
        if not self.mcp_status:
            if self.mcp.config:
                return "已配置但未连接（用 /mcp 重试，或检查 server 可执行文件路径）"
            return (f"未配置 MCP 服务器。在 {self.oh_dir / 'mcp.json'} "
                    "写入 {\"mcpServers\": {...}}，或在 settings.json 的 mcp_servers 里配置。")
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
        """生成默认 .oh/settings.json（不覆盖已有文件）。"""
        target = self.oh_dir / "settings.json"
        if target.exists():
            return f"配置已存在，未覆盖：{target}"
        target.write_text(json.dumps(default_config(self.cwd), indent=2,
                                     ensure_ascii=False) + "\n", encoding="utf-8")
        return f"已生成 {target}（默认配置）"

    def _cmd_clear(self, args: str) -> str:
        session = self.current_session()
        session.context.messages.clear()
        self.save_session(session)
        return "已清空当前会话的消息历史"

    def _cmd_exit(self, args: str) -> str:
        raise SystemExit
