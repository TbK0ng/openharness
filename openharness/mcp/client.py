"""MCP 客户端 — 第 10 章：连接 stdio JSON-RPC MCP 服务器。

支持 initialize / tools/list / tools/call / resources/list / resources/read。
每个服务器一个子进程 + 一行一个 JSON 的 JSON-RPC 2.0 通道，
后台 reader 线程把响应行推入队列，_send 等待对应 id。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Optional


class MCPError(Exception):
    pass


class MCPServer:
    def __init__(self, name: str, spec: dict, cwd: str):
        self.name = name
        self.spec = spec
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen] = None
        self._reader_q: "queue.Queue" = None
        self._reader_thread: Optional[threading.Thread] = None
        self._next_id = 100
        self._tools: list = []
        self._resources: list = []

    # ---- JSON-RPC -------------------------------------------------------
    def _send(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        import queue
        req_id = self._next_id
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise MCPError(f"MCP server '{self.name}' timed out on {method}")
            try:
                data = self._reader_q.get(timeout=0.5)
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise MCPError(f"MCP server '{self.name}' exited during {method}")
                continue
            if isinstance(data, dict) and data.get("id") == req_id:
                if "error" in data:
                    raise MCPError(f"MCP {method} error: {data['error']}")
                return data.get("result", {})
            # 其他 id / 通知 → 忽略

    def list_tools(self) -> list:
        return self._send("tools/list", {}).get("tools", [])

    def list_resources(self) -> list:
        try:
            return self._send("resources/list", {}).get("resources", [])
        except MCPError:
            return []

    def read_resource(self, uri: str) -> str:
        result = self._send("resources/read", {"uri": uri})
        contents = result.get("contents", [])
        parts = []
        for c in contents:
            if c.get("text"):
                parts.append(c["text"])
            elif c.get("blob"):
                parts.append(f"<binary {len(c['blob'])} bytes>")
        return "\n".join(parts)

    # ---- MCP 方法 -------------------------------------------------------
    def initialize(self) -> None:
        self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "openharness", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})

    def list_tools(self) -> list:
        result = self._send("tools/list", {})
        self._tools = (result or {}).get("tools", [])
        return self._tools

    def call_tool(self, tool: str, arguments: dict) -> str:
        result = self._send("tools/call", {"name": tool, "arguments": arguments})
        if (result or {}).get("isError"):
            raise MCPError(self._content_text(result))
        return self._content_text(result)

    def list_resources(self) -> list:
        result = self._send("resources/list", {})
        self._resources = (result or {}).get("resources", [])
        return self._resources

    def read_resource(self, uri: str) -> str:
        result = self._send("resources/read", {"uri": uri})
        return self._content_text(result)

    @staticmethod
    def _content_text(result: dict) -> str:
        parts = []
        for item in (result or {}).get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)

    # ---- 进程管理 -------------------------------------------------------
    def start(self) -> None:
        import queue
        command = self.spec.get("command")
        if not command:
            raise MCPError(f"MCP server '{self.name}' has no command")
        args = list(self.spec.get("args", []))
        env = dict(os.environ)
        env.update(self.spec.get("env", {}))
        self.proc = subprocess.Popen(
            [command] + args,
            cwd=self.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._reader_q = queue.Queue()

        def _reader():
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._reader_q.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()
        self.initialize()
        self._tools = self.list_tools()
        self._resources = self.list_resources()

    def initialize(self) -> dict:
        result = self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "openharness", "version": "0.1.0"},
        })
        self._notify("notifications/initialized", {})
        return result

    def _notify(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def list_tools(self) -> list:
        result = self._send("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._send("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for item in result.get("content", []):
            if item.get("text"):
                parts.append(item["text"])
            elif item.get("data") is not None:
                parts.append(json.dumps(item["data"], ensure_ascii=False))
        if result.get("isError"):
            return "[MCP error] " + "\n".join(parts)
        return "\n".join(parts)

    def list_resources(self) -> list:
        try:
            result = self._send("resources/list", {})
            return result.get("resources", [])
        except MCPError:
            return []

    def read_resource(self, uri: str) -> str:
        result = self._send("resources/read", {"uri": uri})
        parts = []
        for item in result.get("contents", []):
            if item.get("text"):
                parts.append(item["text"])
            elif item.get("blob"):
                parts.append(f"<binary {len(item['blob'])} bytes>")
        return "\n".join(parts)

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.proc = None

    # ---- JSON-RPC -------------------------------------------------------
    def _send(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        import queue
        req_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        while True:
            try:
                msg = self._reader_q.get(timeout=timeout)
            except queue.Empty:
                raise MCPError(f"MCP server '{self.name}' timed out on {method}")
            if isinstance(msg, dict) and msg.get("id") == req_id:
                if "error" in msg:
                    raise MCPError(f"MCP {method} error: {msg['error']}")
                return msg.get("result", {})
            # 服务器推送的通知（无 id）：忽略

    # ---- 能力 -----------------------------------------------------------
    def list_tools(self) -> list:
        try:
            return self._send("tools/list", {}).get("tools", [])
        except MCPError:
            return []

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        result = self._send("tools/call", {"name": tool_name, "arguments": arguments})
        parts = []
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        text = "\n".join(parts)
        if result.get("isError"):
            raise MCPError(f"MCP tool '{tool_name}' error: {text}")
        return text

    def list_resources(self) -> list:
        try:
            return self._send("resources/list", {}).get("resources", [])
        except MCPError:
            return []

    def read_resource(self, uri: str) -> str:
        result = self._send("resources/read", {"uri": uri})
        parts = []
        for item in result.get("contents", []):
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(item["text"])
                elif "blob" in item:
                    parts.append(f"<binary blob, {len(item['blob'])} b64 chars>")
        return "\n".join(parts)


class MCPClientManager:
    """管理 settings.json 里配置的全部 MCP 服务器。"""

    def __init__(self, config: dict, cwd: str):
        self.config = config.get("mcp_servers", {})
        self.cwd = cwd
        self.servers: dict[str, MCPServer] = {}

    def connect_all(self) -> dict:
        """启动并握手所有服务器。返回 {name: 状态摘要}。"""
        status = {}
        for name, spec in self.config.items():
            server = MCPServer(name, spec, self.cwd)
            try:
                server.start()
                self.servers[name] = server
                status[name] = {
                    "ok": True,
                    "tools": [t.get("name") for t in server._tools],
                    "resources": [r.get("uri") for r in server._resources],
                }
            except Exception as e:
                status[name] = {"ok": False, "error": str(e)}
                server.close()
        return status

    def server(self, name: str) -> Optional[MCPServer]:
        return self.servers.get(name)

    def all_tools(self) -> list:
        out = []
        for name, server in self.servers.items():
            for t in server._tools:
                out.append({"server": name, **t})
        return out

    def call(self, name: str, tool_name: str, arguments: dict) -> str:
        server = self.servers.get(name)
        if server is None:
            raise MCPError(f"MCP server '{name}' not connected")
        return server.call_tool(tool_name, arguments)

    def close_all(self) -> None:
        for server in self.servers.values():
            server.close()
        self.servers = {}
