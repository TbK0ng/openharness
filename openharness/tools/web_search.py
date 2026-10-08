"""WebSearch 工具 — 网络搜索（默认 DuckDuckGo HTML 端点，无 API key）。"""
from __future__ import annotations

import re
import urllib.request
import urllib.parse
import html as html_lib

from ..tools.base import BaseTool, ToolResult

_HEADERS = {"User-Agent": "Mozilla/5.0 (OpenHarness)"}


class WebSearchTool(BaseTool):
    name = "WebSearch"
    description = ("Search the web and return a list of results (title, url, snippet). "
                   "Use WebFetch to read a result in full.")
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
        },
        "required": ["query"],
    }
    read_only = True

    async def execute(self, params, context) -> ToolResult:
        query = params["query"]
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read(2_000_000)
            text = raw.decode("utf-8", "ignore")
        except Exception as e:
            return ToolResult(error=f"search failed: {e}")
        results = _parse(text)
        if not results:
            return ToolResult(output=f"No results found for: {query}")
        lines = [f"Query: {query}", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
        return ToolResult(output="\n".join(lines))


def _parse(text: str) -> list:
    out = []
    # DuckDuckGo HTML: result links live in <a class="result__a" href="...">title</a>
    # and snippets in <a class="result__snippet"...>text</a>
    links = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, flags=re.S)
    snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', text, flags=re.S)
    for i, (href, title) in enumerate(links[:10]):
        clean_href = _clean_url(href)
        clean_title = html_lib.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        snip = ""
        if i < len(snippets):
            snip = html_lib.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()
        out.append({"title": clean_title, "url": clean_href, "snippet": snip})
    return out


def _clean_url(href: str) -> str:
    # DDG wraps real URL in /l/?uddg=<encoded>
    m = re.search(r"uddg=([^&]+)", href)
    if m:
        return urllib.parse.unquote(m.group(1))
    return href
