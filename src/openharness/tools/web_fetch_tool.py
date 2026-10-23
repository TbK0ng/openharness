"""WebFetch 工具 — 抓取 URL 并提取正文文本。"""
from __future__ import annotations

import re
import urllib.request
import html as html_lib

from .base import BaseTool, ToolResult

_HEADERS = {"User-Agent": "Mozilla/5.0 (OpenHarness)"}
_MAX_CHARS = 20000


class WebFetchTool(BaseTool):
    name = "WebFetch"
    description = "Fetch a URL and return its main text content (HTML stripped). Good for reading a known page."
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute URL (http/https)."},
        },
        "required": ["url"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        url = params["url"]
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult(error="url must start with http:// or https://")
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read(2_000_000)
        except Exception as e:
            return ToolResult(error=f"fetch failed: {e}")
        text = _to_text(raw)
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "\n…[truncated]"
        return ToolResult(output=f"URL: {url}\n\n{text}")


def _to_text(raw: bytes) -> str:
    low = raw[:1024].lower()
    if b"<html" in low or b"<!doctype" in low:
        body = re.sub(rb"<(script|style)[^>]*>.*?</\1>", b" ", raw, flags=re.S | re.I)
        body = re.sub(rb"<[^>]+>", b" ", body)
        s = html_lib.unescape(body.decode("utf-8", "ignore"))
    else:
        s = raw.decode("utf-8", "ignore")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
