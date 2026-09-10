#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STDIO MCP transport for the general RunTeams Agent tool registry."""
import json
import os
import sys

import agent_tool_registry


def _server_context():
    try:
        value = json.loads(os.environ.get("RUNTEAMS_AGENT_TOOL_CONTEXT") or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _allowed_tools(context):
    names = context.get("allowed_tools") if isinstance(context, dict) else None
    if not isinstance(names, list):
        return None
    return [str(name) for name in names if agent_tool_registry.get(name)]


def dispatch_rpc(message, context=None):
    context = context if isinstance(context, dict) else _server_context()
    allowed = _allowed_tools(context)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion") or "2024-11-05"
        result = {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "runteams-agent-tools", "version": "1.0.0"},
            "instructions": "Use RunTeams tools for product context and control-plane actions.",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": agent_tool_registry.mcp_definitions(allowed)}
    elif method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        if allowed is not None and name not in allowed:
            result = {"content": [{"type": "text", "text":
                       "RunTeams 当前会话没有启用工具 {}".format(name or "(empty)")}],
                      "isError": True}
        else:
            result = agent_tool_registry.mcp_call_result(
                name, params.get("arguments") or {}, context)
    else:
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Method not found"}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    context = _server_context()
    for line in sys.stdin:
        message = None
        try:
            message = json.loads(line)
            response = dispatch_rpc(message, context)
            if response is not None:
                sys.stdout.write(json.dumps(
                    response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            request_id = message.get("id") if isinstance(message, dict) else None
            if request_id is not None:
                sys.stdout.write(json.dumps({
                    "jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32603, "message": str(exc)},
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
