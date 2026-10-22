"""本地假的 OpenAI 兼容端点：按脚本返回 5xx / 截断 / 正常响应。

用来在真 CLI 进程上验证 engine/recovery.py 的三条恢复路径，
不需要真实模型，也不需要网络。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLM:
    """script 每项：
    ("ok", text)          → 正常完成
    ("length", text)      → finish_reason=length（输出截断）
    ("status", code, msg) → 直接返回错误状态码
    脚本用尽后重复最后一条。
    """

    def __init__(self, script: list[tuple]) -> None:
        self.script = list(script)
        self.requests: list[dict] = []
        self._i = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {}
                outer.requests.append(body)
                outer._respond(self, body)

            def log_message(self, *args) -> None:  # 静音
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    # ---- 生命周期 ----
    def start(self) -> "FakeLLM":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> "FakeLLM":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    # ---- 应答 ----
    def _respond(self, handler: BaseHTTPRequestHandler, body: dict) -> None:
        item = self.script[min(self._i, len(self.script) - 1)]
        self._i += 1

        if item[0] == "status":
            code, message = item[1], item[2]
            payload = json.dumps(
                {"error": {"message": message, "type": "server_error"}}).encode()
            handler.send_response(code)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
            return

        kind, text = item
        payload = json.dumps({
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": body.get("model") or "fake-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "length" if kind == "length" else "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)


def max_tokens_of(request: dict) -> int | None:
    """从请求体里取出输出上限（不同模型字段名不同）。"""
    for key in ("max_tokens", "max_completion_tokens"):
        if request.get(key) is not None:
            return int(request[key])
    return None
