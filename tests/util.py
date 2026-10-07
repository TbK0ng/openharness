"""测试辅助：构造最小 Engine 上下文桩。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openharness.hooks.executor import HookManager
from openharness.permissions.checker import PermissionChecker
from openharness.tools.base import BaseTool, ToolResult
from openharness.tools.registry import ToolRegistry


class EchoTool(BaseTool):
    name = "Echo"
    description = "Echoes input text back."
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        return ToolResult(output=params["text"])


class WriteTool(BaseTool):
    name = "Write"
    description = "Writes text."
    input_schema = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["file_path", "content"],
    }
    read_only = False

    async def execute(self, params, context) -> ToolResult:
        return ToolResult(output=f"wrote {len(params['content'])} chars")


class ExplodingTool(BaseTool):
    name = "Explode"
    description = "Always raises."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, params, context) -> ToolResult:
        raise RuntimeError("boom")


def make_context(tmp_dir, mode="default", config=None, ask_answer="n", hook_config=None):
    cwd = str(tmp_dir)
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(WriteTool())
    registry.register(ExplodingTool())
    permissions = PermissionChecker(config or {})
    permissions.set_mode(mode)
    hooks = HookManager(hook_config or {})
    events = []
    asks = []

    class Ctx:
        def __init__(self):
            self.session_id = "test-session"
            self.registry = registry
            self.permissions = permissions
            self.hooks = hooks
            self.mode = mode
            self.cwd = cwd
            self.on_event = lambda s: events.append(str(s))
            self.ask_user = lambda prompt: asks.append(prompt) or ask_answer

    ctx = Ctx()
    return ctx, {"events": events, "asks": asks}
