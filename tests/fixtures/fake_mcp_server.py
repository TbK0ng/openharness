"""A minimal stdio MCP server used by tests/test_mcp.py.

Implements just enough of the protocol: initialize, tools/list, tools/call,
resources/list, resources/read. One JSON object per line on stdout.
"""
import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {
        "name": "fail",
        "description": "Always reports an error",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

RESOURCES = [{"uri": "demo://greeting", "name": "greeting", "mimeType": "text/plain"}]


def handle(msg):
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "stub"}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        if name == "echo":
            text = (params.get("arguments") or {}).get("text", "")
            return {"content": [{"type": "text", "text": text}]}
        if name == "fail":
            return {"isError": True, "content": [{"type": "text", "text": "boom"}]}
        raise ValueError(f"unknown tool {name}")
    if method == "resources/list":
        return {"resources": RESOURCES}
    if method == "resources/read":
        return {"contents": [{"uri": params.get("uri"), "text": "hello resource"}]}
    raise ValueError(f"unknown method {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if "id" not in msg:
            continue  # notification
        try:
            result = handle(msg)
        except Exception as exc:
            reply = {"jsonrpc": "2.0", "id": msg["id"],
                     "error": {"code": -32000, "message": str(exc)}}
        else:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
