"""MCP 客户端 — 第 10 章：连接 stdio JSON-RPC MCP 服务器。

支持 initialize / tools/list / tools/call / resources/list / resources/read。
每个服务器一个子进程 + 一行一个 JSON 的 JSON-RPC 2.0 通道，
后台 reader 线程把响应行推入队列，_send 等待对应 id。

配置来源（合并，后者覆盖同名项）：
    1. `.oh/mcp.json`（推荐，Claude Code 兼容格式：`{"mcpServers": {...}}`）
    2. settings.json 的 `mcp_servers` 键
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional


class MCPError(Exception):
    pass


def load_mcp_config(config: dict, oh_dir: Path | str | None = None) -> dict:
    """合并 .oh/mcp.json 与 settings.json 的 mcp_servers。

    `.oh/mcp.json` 使用 Claude Code 的 `{"mcpServers": {...}}` 布局；
    也接受直接给出服务器映射的简写形式。
    """
    servers: dict = {}

    if oh_dir is not None:
        path = Path(oh_dir) / "mcp.json"
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise MCPError(f"无法解析 {path}: {exc}") from exc
            file_servers = raw.get("mcpServers", raw) if isinstance(raw, dict) else {}
            if isinstance(file_servers, dict):
                servers.update(file_servers)

    inline = config.get("mcp_servers") or {}
    if isinstance(inline, dict):
        servers.update(inline)
    return servers


class MCPServer:
    def __init__(self, name: str, spec: dict, cwd: str):
        self.name = name
        self.spec = spec
        self.cwd = cwd
        # 每个 server 可以单独放宽握手超时（重二进制冷启动很慢）
        self.timeout = float(spec.get("timeout") or 30.0)
        self.proc: Optional[subprocess.Popen] = None
        self._reader_q = None
        self._reader_thread: Optional[threading.Thread] = None
        self._next_id = 100
        self._tools: list = []
        self._resources: list = []

    # ---- JSON-RPC -------------------------------------------------------
    def _send(self, method: str, params: dict,
              timeout: float | None = None) -> dict:
        import queue
        if timeout is None:
            timeout = self.timeout
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
                    raise MCPError(
                        f"MCP server '{self.name}' exited while waiting for {method}")
                continue
            if isinstance(data, dict) and data.get("id") == req_id:
                if "error" in data:
                    raise MCPError(f"MCP {method} error: {data['error']}")
                return data.get("result", {})

    # ---- 进程管理 -------------------------------------------------------
    def start(self) -> None:
        import queue
        command = self.spec.get("command")
        if not command:
            raise MCPError(f"MCP server '{self.name}' has no command")
        # 相对命令按项目根解析（.oh/mcp.json 里写 tools/xxx.exe 即可）
        if not os.path.isabs(command) and (os.sep in command or "/" in command):
            candidate = Path(self.cwd) / command
            if candidate.exists():
                command = str(candidate)
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
            raise MCPError(f"MCP tool '{name}' error: " + "\n".join(parts))
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
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(item["text"])
                elif "blob" in item:
                    parts.append(f"<binary blob, {len(item['blob'])} b64 chars>")
        return "\n".join(parts)

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.proc = None


class MCPClientManager:
    """管理 .oh/mcp.json 与 settings.json 里配置的全部 MCP 服务器。"""

    def __init__(self, config: dict, cwd: str, oh_dir: Path | str | None = None):
        self.oh_dir = oh_dir
        self.config = load_mcp_config(config, oh_dir)
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
            except Exception as e:  # noqa: BLE001
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
