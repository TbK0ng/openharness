"""Bash 工具 — 执行 shell 命令（Windows 下默认 PowerShell，回退 cmd）。"""
from __future__ import annotations

import asyncio
import shutil
import sys

from ..tools.base import BaseTool, ToolResult


class BashTool(BaseTool):
    name = "Bash"
    description = ("Run a shell command and capture its output. On Windows this uses "
                   "PowerShell (fallback cmd). Use absolute or workspace-relative paths.")
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)."},
        },
        "required": ["command"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        command = params["command"]
        timeout = int(params.get("timeout", 60))
        cwd = context.cwd
        shell, args = self._pick_shell()
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(error=f"Command timed out after {timeout}s: {command}")
            out = (out or b"").decode("utf-8", errors="replace")
            err = (err or b"").decode("utf-8", errors="replace")
            rc = proc.returncode
            text = out
            if err:
                text += ("\n--- stderr ---\n" if text else "") + err
            if rc != 0:
                text = f"[exit {rc}]\n{text}"
            return ToolResult(output=text.strip()[:20000] or "(no output)",
                              error=None if rc == 0 else f"exit code {rc}")
        except FileNotFoundError:
            return ToolResult(error=f"Shell not found: {shell}")
        except Exception as e:
            return ToolResult(error=f"Failed to run command: {e}")

    def _pick_shell(self):
        if sys.platform == "win32":
            if shutil.which("powershell"):
                return "powershell", ["powershell", "-NoProfile", "-Command"]
            if shutil.which("cmd"):
                return "cmd", ["cmd", "/c"]
        return "sh", ["sh", "-c"]
