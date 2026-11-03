# -*- coding: utf-8 -*-
"""Small, provider-neutral helpers for live Agent conversation events.

Providers stream ordinary assistant text plus native tool-call events. Product
interactions use native tools; assistant text is never wrapped in a JSON reply
envelope.
"""
import json
import re
import shlex


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
    "runteams_creator_source": "编辑员工资源",
}


def _tool_label(name):
    raw = str(name or "")
    direct = _RUNTEAMS_TOOL_LABELS.get(raw)
    if direct:
        return direct
    # Claude prefixes MCP tools with the server namespace in stream events.
    matched = next((label for tool, label in _RUNTEAMS_TOOL_LABELS.items()
                    if raw.endswith("__" + tool) or raw.endswith("/" + tool)), None)
    if matched:return matched
    from runteams_core.agent_tool_registry import get
    tool=get(raw.rsplit('__',1)[-1].rsplit('/',1)[-1])
    return tool.display_label if tool and tool.display_label else raw


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


def present_step(event):
    """Explain a verified rg file-list miss without rewriting its native status.

    Fail closed on compound/unknown commands, diagnostics and other exit codes.
    This also projects old saved traces without changing their stored receipts.
    """
    if not isinstance(event, dict) or event.get('kind') != 'step':
        return event
    meta = event.get('meta') or {}
    if not isinstance(meta, dict):
        return event
    if (event.get('step_kind') != 'command' or event.get('status') != 'failed'
            or meta.get('exitCode') != 1 or str(event.get('output') or '').strip()
            or str(event.get('detail') or '').strip()):
        return event
    try:
        command = str(meta.get('command') or '')
        if len(command) >= 4000 or '…' in command:
            return event
        tokens = shlex.split(command)
        if (len(tokens) == 3 and tokens[0].rsplit('/', 1)[-1] in ('sh', 'bash', 'zsh')
                and tokens[1] in ('-c', '-lc')):
            command = tokens[2]
            tokens = shlex.split(command)
        if any(char in command for char in ';|&<>`()$\\\n\r'):
            return event
        if len(tokens) < 2 or tokens[0].rsplit('/', 1)[-1] != 'rg' or tokens[1] != '--files':
            return event
        index = 2
        while index < len(tokens):
            token = tokens[index]
            if token in ('--hidden', '--no-ignore', '--no-ignore-vcs', '--no-ignore-parent',
                         '--no-ignore-dot', '--no-ignore-global', '--follow', '-L'):
                index += 1
            elif token in ('-g', '--glob'):
                index += 2
                if index > len(tokens):
                    return event
            elif token.startswith('-'):
                return event
            else:
                index += 1
    except ValueError:
        return event
    return {**event, 'meta': {**meta, 'outcome': 'no_matching_files'}}


def present_trace_events(events):
    return [{**item, 'event': present_step(item.get('event'))}
            if isinstance(item, dict) and item.get('type') == 'agent_event' else item
            for item in events]


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
    if kind in ('commandExecution', 'command_execution'):
        metadata = {'command': _safe_value(item.get('command') or ''),
                    'cwd': str(item.get('cwd') or '')}
        # Preserve native display facts; never derive command intent from model prose.
        if isinstance(item.get('commandActions'), list):
            metadata['commandActions'] = _safe_value(item['commandActions'])
        for key in ('exitCode', 'durationMs'):
            value = item.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metadata[key] = value
    elif kind in ("mcpToolCall", "mcp_tool_call"):
        metadata = {"server": item.get("server") or "", "tool": item.get("tool") or item.get("name") or "",
                    "arguments": _safe_value(item.get("arguments") or {})}
    elif kind in ("dynamicToolCall", "dynamic_tool_call"):
        metadata = {"namespace": item.get("namespace") or "",
                    "tool": item.get("tool") or item.get("name") or "",
                    "arguments": _safe_value(item.get("arguments") or {})}
    elif kind in ("fileChange", "file_change"):
        metadata = {"changes": _safe_value(item.get("changes") or [])}
    return present_step({
        "kind": "step",
        "id": step_id[:180],
        "step_kind": step_kind,
        "label": label.replace("\n", " ").strip()[:240],
        "status": status,
        "detail": str(detail or "")[:2000],
        "output": _output_text(output or item.get("result") or item.get("error") or ""),
        "meta": metadata,
    })


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
                self.raw = self.emitted = text
                emit(self.callback, {'kind': 'reply_reset', 'text': text})
                return text
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


def runtime_item_event(item, active):
    """Presentation phases from actual native items, never inferred from prose."""
    item = item or {}
    kind = str(item.get('type') or '').replace('_', '').replace('-', '').lower()
    phase = {'reasoning': 'thinking', 'contextcompaction': 'compacting'}.get(kind)
    if phase:
        return {'kind': 'runtime_status', 'phase': phase,
                'id': str(item.get('id') or kind), 'active': bool(active)}


def provider_error_event(error, will_retry=False):
    """Only explicit native classifications receive dedicated error layouts."""
    error = error if isinstance(error, dict) else {}
    info = error.get('codexErrorInfo')
    code = info if isinstance(info, str) else next(iter(info), '') if isinstance(info, dict) else ''
    if code in ('serverOverloaded', 'usageLimitExceeded'):
        return {'kind': 'provider_error', 'code': code, 'will_retry': will_retry is True}


def rate_limits_event(snapshot):
    """Carry only typed window data; never derive reset times from error text."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    windows = []
    for key in ('primary', 'secondary'):
        value = snapshot.get(key)
        if not isinstance(value, dict):
            continue
        used, reset = value.get('usedPercent'), value.get('resetsAt')
        if isinstance(used, (int, float)) and not isinstance(used, bool):
            windows.append({'usedPercent': used, 'resetsAt': reset if
                isinstance(reset, (int, float)) and not isinstance(reset, bool) else None})
    return {'kind': 'rate_limits', 'windows': windows}
