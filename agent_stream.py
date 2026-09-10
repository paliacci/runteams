# -*- coding: utf-8 -*-
"""Small, provider-neutral helpers for live Agent conversation events.

Providers stream ordinary assistant text plus native tool-call events. Product
interactions use native tools; assistant text is never wrapped in a JSON reply
envelope.
"""
import json
import re


_SENSITIVE_KEY = re.compile(r"(?:secret|token|password|passwd|api[_-]?key|credential|authorization|cookie)", re.I)

_RUNTEAMS_TOOL_LABELS = {
    "runteams_request_choice": "请求用户选择",
    "runteams_get_context": "读取当前上下文",
    "runteams_list_pipelines": "读取流水线列表",
    "runteams_get_pipeline": "读取流水线详情",
    "runteams_get_task": "读取任务详情",
    "runteams_get_employee": "读取员工详情",
    "runteams_propose_pipeline_change": "整理流水线改动",
    "runteams_propose_task": "整理任务方案",
    "runteams_propose_automation": "整理自动化改动",
    "runteams_present_employee_draft": "整理员工草稿",
}


def _tool_label(name):
    raw = str(name or "")
    direct = _RUNTEAMS_TOOL_LABELS.get(raw)
    if direct:
        return direct
    # Claude prefixes MCP tools with the server namespace in stream events.
    matched = next((label for tool, label in _RUNTEAMS_TOOL_LABELS.items()
                    if raw.endswith("__" + tool) or raw.endswith("/" + tool)), None)
    return matched or raw


def _safe_value(value, depth=0):
    """Bound provider metadata and mask fields that may contain credentials."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 40:
                result["…"] = "已省略其余字段"
                break
            result[str(key)] = "••••" if _SENSITIVE_KEY.search(str(key)) else _safe_value(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        items = [_safe_value(item, depth + 1) for item in list(value)[:40]]
        if len(value) > 40:
            items.append("…")
        return items
    if isinstance(value, str):
        return value if len(value) <= 4000 else value[:4000] + "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


def _output_text(value):
    if value in (None, ""):
        return ""
    safe = _safe_value(value)
    if isinstance(safe, str):
        return safe[-6000:]
    return json.dumps(safe, ensure_ascii=False, indent=2)[-6000:]


def emit(callback, event):
    """Send a structured event when the callback supports the live protocol."""
    sink = getattr(callback, "on_event", None)
    if callable(sink) and isinstance(event, dict):
        sink(event)


def step_event(item, status, *, detail="", output=""):
    """Normalize a provider tool item into the shared conversation schema."""
    item = item or {}
    kind = str(item.get("type") or "tool")
    step_id = str(item.get("id") or item.get("tool_use_id") or
                  "{}:{}".format(kind, item.get("command") or item.get("name") or ""))
    if kind in ("commandExecution", "command_execution"):
        label = str(item.get("command") or "运行命令")
        step_kind = "command"
    elif kind in ("fileChange", "file_change"):
        changes = item.get("changes") or []
        first_path = str((changes[0] or {}).get("path") or "") if changes else ""
        label = ("更新 " + first_path.rsplit("/", 1)[-1]) if first_path else "更新文件"
        step_kind = "file"
    elif kind in ("mcpToolCall", "mcp_tool_call"):
        arguments = item.get("arguments") or {}
        tool = str(item.get("tool") or item.get("name") or "")
        task_tool = str(arguments.get("tool_id") or "") if isinstance(arguments, dict) else ""
        label = _tool_label(task_tool or tool) or str(item.get("server") or "调用扩展")
        step_kind = "tool"
    elif kind in ("dynamicToolCall", "dynamic_tool_call"):
        tool = str(item.get("tool") or item.get("name") or "")
        label = _tool_label(tool) or "调用工具"
        step_kind = "tool"
    elif kind in ("webSearch", "web_search"):
        label = "搜索 " + str(item.get("query") or "")
        step_kind = "search"
    else:
        label = _tool_label(item.get("name") or item.get("command") or kind) or "执行步骤"
        step_kind = "tool"
    metadata = {}
    if kind in ("mcpToolCall", "mcp_tool_call"):
        metadata = {"server": item.get("server") or "", "tool": item.get("tool") or item.get("name") or "",
                    "arguments": _safe_value(item.get("arguments") or {})}
    elif kind in ("dynamicToolCall", "dynamic_tool_call"):
        metadata = {"namespace": item.get("namespace") or "",
                    "tool": item.get("tool") or item.get("name") or "",
                    "arguments": _safe_value(item.get("arguments") or {})}
    elif kind in ("fileChange", "file_change"):
        metadata = {"changes": _safe_value(item.get("changes") or [])}
    return {
        "kind": "step",
        "id": step_id[:180],
        "step_kind": step_kind,
        "label": label.replace("\n", " ").strip()[:240],
        "status": status,
        "detail": str(detail or "")[:2000],
        "output": _output_text(output or item.get("result") or item.get("error") or ""),
        "meta": metadata,
    }


class ReplyDeltaStream:
    """Emit unseen assistant-text deltas, including a provider's final replay."""

    def __init__(self, callback):
        self.callback = callback
        self.raw = ""
        self.emitted = ""

    def feed(self, fragment, complete=False):
        if not fragment:
            return ""
        text = str(fragment)
        if complete:
            # Providers replay the authoritative full response in their final
            # event after sending incremental deltas. Only emit its unseen suffix.
            if not text.startswith(self.emitted):
                return ""
            delta = text[len(self.emitted):]
            self.raw = text
        else:
            delta = text
            self.raw += text
        if not delta:
            return ""
        self.emitted += delta
        emit(self.callback, {"kind": "reply_delta", "delta": delta})
        return delta
