"""权限系统 — 对应教程第 6 章 `openharness/permissions/checker.py`。

三级权限模式：
    default   — 只读操作自动通过；写操作需要用户确认 (ASK_USER)
    plan      — 只允许读取操作；所有写入被阻止
    full-auto — 所有操作自动通过（沙箱/完全信任场景）

细粒度控制：
    denied_tools   — 工具拒绝列表
    deny_paths     — 路径规则（glob）
    deny_commands  — 命令拒绝列表（正则）
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

ALLOW = "allow"
DENY = "deny"
ASK_USER = "ask_user"

PATH_PARAMS = ("file_path", "path", "notebook_path", "directory")


@dataclass
class PermissionDecision:
    verdict: str            # allow | deny | ask_user
    reason: str = ""
    prompt: str = ""        # ask_user 时展示给用户的审批文案


class PermissionChecker:
    def __init__(self, config: dict) -> None:
        self.mode: str = config.get("permission_mode") or config.get("mode") or "default"
        self.allowed_tools: set = set(config.get("allow_tools", []))
        self.denied_tools: set = set(config.get("deny_tools", []))
        self.deny_paths: List[str] = list(config.get("deny_paths", []))
        self.deny_commands: List[str] = list(config.get("deny_commands", []))
        self._command_regexes = [re.compile(p) for p in self.deny_commands]

    def set_mode(self, mode: str) -> None:
        if mode not in ("default", "plan", "full-auto"):
            raise ValueError(f"unknown permission mode: {mode}")
        self.mode = mode

    def set_denied_tools(self, names) -> None:
        self.denied_tools = set(names)

    # ---- 会话级白名单（审批时按 a，或 /permission allow） ----------------
    def allow_tool(self, name: str) -> None:
        self.allowed_tools.add(name)

    def deny_tool(self, name: str) -> None:
        self.denied_tools.add(name)

    def forget_tool(self, name: str) -> None:
        self.allowed_tools.discard(name)
        self.denied_tools.discard(name)

    def clear_allows(self) -> None:
        self.allowed_tools.clear()

    def add_path_rule(self, pattern: str) -> None:
        self.deny_paths.append(pattern)

    def add_command_rule(self, pattern: str) -> None:
        self.deny_commands.append(pattern)
        self._command_regexes.append(re.compile(pattern))

    # ---- 路径/命令的细粒度规则 -----------------------------------------
    def _check_path_rules(self, params: dict, cwd: str | None = None) -> Optional[str]:
        for key in PATH_PARAMS:
            raw = params.get(key)
            if not raw:
                continue
            # 同一条规则要同时拦住相对写法和绝对写法，否则换个写法就绕过去了
            candidates = {str(raw).replace("\\", "/")}
            try:
                p = Path(str(raw))
                if cwd and not p.is_absolute():
                    p = Path(cwd) / p
                if cwd:
                    try:
                        candidates.add(
                            p.resolve().relative_to(Path(cwd).resolve()).as_posix())
                    except (ValueError, OSError):
                        pass
                candidates.add(p.as_posix())
            except (OSError, ValueError):
                pass
            for rule in self.deny_paths:
                norm_rule = rule.replace("\\", "/")
                if any(fnmatch.fnmatch(c, norm_rule) for c in candidates):
                    return f"path '{raw}' matches deny rule '{rule}'"
        return None

    def _check_command_rules(self, params: dict) -> Optional[str]:
        cmd = params.get("command")
        if not cmd:
            return None
        for rx in self._command_regexes:
            if rx.search(cmd):
                return f"command matches deny rule '{rx.pattern}'"
        return None

    # ---- 核心检查（教程第 6 章的 check 流程） --------------------------
    def check(self, tool_name: str, params: dict, context) -> PermissionDecision:
        # 第 1 步：检查工具是否在拒绝列表中
        if tool_name in self.denied_tools:
            return PermissionDecision(DENY, reason=f"tool '{tool_name}' is in the denied tools list")

        # 第 2 步：检查路径规则
        path_violation = self._check_path_rules(params, getattr(context, "cwd", None))
        if path_violation:
            return PermissionDecision(DENY, reason=path_violation)

        # 第 2.5 步：检查命令拒绝列表（Bash 等命令类工具）
        cmd_violation = self._check_command_rules(params)
        if cmd_violation:
            return PermissionDecision(DENY, reason=cmd_violation)

        # 第 3 步：按模式决策
        tool = context.registry.get_tool(tool_name)
        read_only = bool(tool and tool.read_only)

        if self.mode == "plan":
            if read_only:
                return PermissionDecision(ALLOW, reason="plan mode: read-only tool")
            return PermissionDecision(DENY, reason=f"plan mode: '{tool_name}' is not read-only")

        if self.mode == "full-auto":
            return PermissionDecision(ALLOW, reason="full-auto mode")

        # 会话白名单：审批时按 a 或 /permission allow 后不再询问。
        # 注意顺序在 plan 之后，确保 plan 模式的只读约束不能被白名单绕过。
        if tool_name in self.allowed_tools:
            return PermissionDecision(ALLOW, reason="tool is allow-listed for this session")

        # default 模式
        if read_only:
            return PermissionDecision(ALLOW, reason="default mode: read-only tool")

        prompt = (
            f"Permission required [{self.mode}] tool '{tool_name}'\n"
            f"parameters: {self._shorten(params)}\n"
            f"Allow this operation? [y/N/a]  (a = always allow this tool in this session)"
        )
        return PermissionDecision(ASK_USER, reason="default mode: write operation", prompt=prompt)

    @staticmethod
    def _shorten(params: dict, limit: int = 400) -> str:
        try:
            import json
            text = json.dumps(params, ensure_ascii=False, default=str)
        except Exception:
            text = str(params)
        return text if len(text) <= limit else text[:limit] + "…"
