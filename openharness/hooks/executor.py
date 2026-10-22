"""Hook 系统 — 对应教程第 7 章 `openharness/hooks/executor.py`。

4 个生命周期时机：
    SESSION_START / SESSION_END / PRE_TOOL_USE / POST_TOOL_USE

4 种 Hook 实现类型：
    command — 执行 Shell 命令（通过环境变量传参；stdout 含 'BLOCK:' 或退出码 2 可拦截）
    http    — POST JSON 到 URL（响应 {"block": true, "reason": ...} 可拦截）
    prompt  — 让 LLM 判断（输出 'allow' 或 'block: <原因>'）
    agent   — 启动子 Agent 判断

配置方式（settings.json，教程第 7 章示例）：
    {
      "hooks": {
        "pre_tool_use": [
          {"type": "command", "command": "echo '即将执行工具: $TOOL_NAME'", "match_tools": ["Bash"]}
        ],
        "post_tool_use": [
          {"type": "command", "command": "echo '工具执行完成: $TOOL_NAME'"}
        ]
      }
    }
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Optional

# 注意：ToolResult 在函数内延迟导入，避免 hooks → tools → engine → query → hooks 的循环导入

SESSION_START = "session_start"
SESSION_END = "session_end"
PRE_TOOL_USE = "pre_tool_use"
POST_TOOL_USE = "post_tool_use"

ALL_EVENTS = (SESSION_START, SESSION_END, PRE_TOOL_USE, POST_TOOL_USE)

COMMAND_TIMEOUT = 30


def _await_in_thread(coro):
    """在独立线程里跑协程并取回结果。

    HookManager.run() 是同步 API，但它可能被已经是 async 的代码
    （execute_tool_with_hooks、后台任务线程）调用；此时不能再起一个
    事件循环或直接 await，所以用一根一次性线程 + asyncio.run 隔离。
    """
    import asyncio
    import threading
    box: dict = {}

    def _go():
        try:
            box["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001 — 转为 hook 故障，不阻塞主流程
            box["error"] = exc

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


@dataclass
class HookOutcome:
    blocked: bool = False
    reason: str = ""
    logs: list = None

    def __post_init__(self):
        if self.logs is None:
            self.logs = []


class HookManager:
    def __init__(self, config: dict) -> None:
        # 兼容两种传参：完整 settings（含 "hooks" 键）或 事件→hooks 映射
        raw = config["hooks"] if "hooks" in config else config
        self.hooks: dict[str, list] = {event: list(raw.get(event, [])) for event in ALL_EVENTS}

    # ------------------------------------------------------------------
    def run(self, event: str, context, tool_call: Optional[dict] = None,
            result: Optional[ToolResult] = None) -> HookOutcome:
        """运行某个时机上的所有 Hook；任一要求拦截则返回 blocked=True。"""
        outcome = HookOutcome()
        for hook in self.hooks.get(event, []):
            if tool_call is not None:
                match = hook.get("match_tools")
                if match and tool_call.get("name") not in match:
                    continue
            payload = self._payload(event, context, tool_call, result)
            try:
                if hook.get("type") == "command":
                    blocked, reason, log = self._run_command_hook(hook, payload)
                elif hook.get("type") == "http":
                    blocked, reason, log = self._run_http_hook(hook, payload)
                elif hook.get("type") == "prompt":
                    blocked, reason, log = self._run_prompt_hook(hook, payload, context)
                elif hook.get("type") == "agent":
                    blocked, reason, log = self._run_agent_hook(hook, payload, context)
                else:
                    blocked, reason, log = False, "", f"unknown hook type: {hook.get('type')}"
            except Exception as exc:  # Hook 自身故障不阻塞主流程
                blocked, reason, log = False, "", f"hook error: {exc}"
            if log:
                outcome.logs.append(log)
                context.on_event(f"🪝 hook[{event}] {log}")
            if blocked:
                outcome.blocked = True
                outcome.reason = reason or f"blocked by hook '{event}'"
                return outcome
        return outcome

    def _payload(self, event, context, tool_call, result) -> dict:
        return {
            "event": event,
            "session_id": context.session_id,
            "cwd": context.cwd,
            "tool_name": (tool_call or {}).get("name"),
            "tool_params": (tool_call or {}).get("arguments"),
            "result_output": result.to_text()[:2000] if result is not None else None,
            "result_is_error": result.is_error if result is not None else None,
        }

    # ---- command hook -------------------------------------------------
    def _run_command_hook(self, hook: dict, payload: dict):
        cmd = hook.get("command", "")
        if not cmd:
            return False, "", "empty command hook"
        env = dict(os.environ)
        env.update({
            "HOOK_EVENT": payload["event"],
            "TOOL_NAME": str(payload.get("tool_name") or ""),
            "TOOL_ARGS_JSON": json.dumps(payload.get("tool_params") or {}, ensure_ascii=False, default=str),
            "SESSION_ID": payload["session_id"],
            "CWD": payload["cwd"],
        })
        env.update({k: str(v) for k, v in hook.get("env", {}).items()})
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=COMMAND_TIMEOUT, env=env, cwd=payload["cwd"],
            )
        except subprocess.TimeoutExpired:
            return False, "", f"command hook timed out: {cmd}"
        stdout = (proc.stdout or "").strip()
        log = stdout[:300] if stdout else f"exit={proc.returncode}"
        if "BLOCK:" in stdout:
            return True, stdout.split("BLOCK:", 1)[1].strip() or "command hook", log
        if proc.returncode == 2:
            return True, (proc.stderr or "command hook exit 2").strip(), log
        return False, "", log

    # ---- http hook ----------------------------------------------------
    def _run_http_hook(self, hook: dict, payload: dict):
        url = hook.get("url", "")
        if not url:
            return False, "", "empty url hook"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=hook.get("timeout", 10)) as resp:
            body = resp.read().decode("utf-8", "replace")
        try:
            data = json.loads(body)
        except Exception:
            return False, "", f"http hook non-json response: {body[:200]}"
        if data.get("block"):
            return True, str(data.get("reason", "http hook")), "http hook block"
        return False, "", f"http hook ok ({len(body)} bytes)"

    # ---- prompt hook ---------------------------------------------------
    def _run_prompt_hook(self, hook: dict, payload: dict, context):
        prompt_template = hook.get("prompt", "")
        if not prompt_template:
            return False, "", "empty prompt hook"
        prompt = prompt_template.replace("{tool_name}", str(payload.get("tool_name")))
        prompt += f"\n\nTool call details:\n{json.dumps(payload, ensure_ascii=False, default=str)[:3000]}"
        prompt += "\n\nRespond with exactly 'allow' or 'block: <reason>'."
        from ..engine.llm import llm_complete
        # HookManager.run() 是同步 API（且可能已在事件循环内被调用），
        # 因此这里与 agent hook 一致：把协程放到独立线程里跑。
        answer = _await_in_thread(llm_complete(context, prompt))
        answer = (answer or "").strip().lower()
        if answer.startswith("block"):
            reason = answer.split(":", 1)[1].strip() if ":" in answer else "prompt hook"
            return True, reason, f"prompt hook: {answer[:200]}"
        return False, "", f"prompt hook: {answer[:100]}"

    # ---- agent hook ----------------------------------------------------
    def _run_agent_hook(self, hook: dict, payload: dict, context):
        instruction = hook.get("instruction", "Evaluate this tool call and decide allow or block.")
        task = f"{instruction}\n\nTool call: {json.dumps(payload, ensure_ascii=False, default=str)[:3000]}\n\nRespond with exactly 'allow' or 'block: <reason>'."
        if not hasattr(context, "team") or context.team is None:
            return False, "", "agent hook skipped (no team registry)"
        agent = context.team.create(
            label=f"hook-{payload.get('tool_name')}",
            prompt=task,
            subagent_type="general-purpose",
            parent=context,
            max_turns=hook.get("max_turns", 6),
            on_event=lambda s: context.on_event(f"🪝 [hook-agent] {s}"),
        )
        result_text = context.team.run(agent, task, foreground=True)
        text = (result_text or "").strip().lower()
        if text.startswith("block"):
            reason = text.split(":", 1)[1].strip() if ":" in text else "agent hook"
            return True, reason, f"agent hook: {text[:200]}"
        return False, "", f"agent hook: {text[:100]}"


# ----------------------------------------------------------------------
# 教程第 7 章的核心函数：Hook → 权限检查 → 执行 → PostHook
# ----------------------------------------------------------------------
async def execute_tool_with_hooks(context, tool_call: dict) -> ToolResult:
    """第 1 步：执行 PreToolUse 钩子；若拦截直接返回。
    第 2 步：权限检查（在 Hook 之后）。
    第 3 步：真正执行工具。
    第 4 步：执行 PostToolUse 钩子。
    """
    from ..tools.base import ToolResult

    name = tool_call.get("name", "")
    params = tool_call.get("arguments") or {}

    # 第 1 步：PreToolUse Hook
    pre = context.hooks.run(PRE_TOOL_USE, context, tool_call)
    if pre.blocked:
        return ToolResult(error=f"操作被 Hook 阻止: {pre.reason}")

    # 第 2 步：权限检查
    decision = context.permissions.check(name, params, context)
    if decision.verdict == "deny":
        return ToolResult(error=f"权限不足: {decision.reason}")
    if decision.verdict == "ask_user":
        context.on_event(decision.prompt)
        answer = (context.ask_user(decision.prompt) or "").strip().lower()
        if answer in ("a", "always", "all"):
            # 本会话白名单：后续同类工具调用不再弹出审批。
            context.permissions.allow_tool(name)
            context.on_event(f"✅ 已在当前会话自动允许工具 {name}")
        elif answer not in ("y", "yes"):
            return ToolResult(error="权限不足: 用户拒绝了该操作 (ask_user -> denied)")

    # 第 3 步：真正执行工具
    tool = context.registry.get_tool(name)
    if tool is None:
        return ToolResult(error=f"未知工具: {name}")
    errors = tool.validate(params)
    if errors:
        return ToolResult(error=f"参数校验失败: {'; '.join(errors)}")
    try:
        result = await tool.execute(params, context)
    except Exception as exc:
        result = ToolResult(error=f"tool '{name}' raised: {exc}")

    # 第 4 步：PostToolUse Hook
    post = context.hooks.run(POST_TOOL_USE, context, tool_call, result)
    if post.blocked:
        result = ToolResult(output=result.to_text(), error=f"操作被 PostToolUse Hook 阻止: {post.reason}")

    return result
