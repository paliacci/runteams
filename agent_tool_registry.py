# -*- coding: utf-8 -*-
"""Provider-neutral native tools exposed to the general RunTeams Agent.

The registry owns product tool names, JSON schemas, risk classes and handlers.
Provider transports (Claude MCP and Codex App Server dynamic tools) must adapt
this one source instead of maintaining parallel tool catalogs.

This module deliberately does not implement an Agent loop. Claude Code and
Codex remain responsible for reasoning and tool selection; RunTeams only
dispatches its local control-plane tools.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import os


PROTOCOL = "runteams.agent-tool/v1"
RISKS = frozenset(("read", "interactive", "write"))


class AgentToolError(ValueError):
    """A safe, user-correctable native tool invocation error."""


@dataclass(frozen=True)
class AgentToolResult:
    kind: str
    message: str
    data: dict

    def envelope(self):
        return {
            "protocol": PROTOCOL,
            "kind": self.kind,
            "message": self.message,
            "data": deepcopy(self.data),
        }


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_schema: dict
    risk: str
    ui_kind: str
    handler: object

    def __post_init__(self):
        if not self.name.startswith("runteams_"):
            raise ValueError("RunTeams Agent 工具必须使用 runteams_ 前缀")
        if self.risk not in RISKS:
            raise ValueError("未知 Agent 工具风险等级：{}".format(self.risk))

    def mcp_definition(self):
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": deepcopy(self.input_schema),
        }

    def codex_definition(self):
        return {"type": "function", **self.mcp_definition()}


_TOOLS = {}


def register(tool):
    if not isinstance(tool, AgentTool):
        raise TypeError("只能注册 AgentTool")
    if tool.name in _TOOLS:
        raise ValueError("Agent 工具重复注册：{}".format(tool.name))
    _TOOLS[tool.name] = tool
    return tool


def get(name):
    return _TOOLS.get(str(name or ""))


def tools(names=None):
    selected = set(names) if names is not None else None
    return tuple(tool for name, tool in _TOOLS.items()
                 if selected is None or name in selected)


def mcp_definitions(names=None):
    return [tool.mcp_definition() for tool in tools(names)]


def codex_dynamic_definitions(names=None):
    return [tool.codex_definition() for tool in tools(names)]


def dispatch(name, arguments=None, context=None):
    tool = get(name)
    if tool is None:
        raise AgentToolError("RunTeams 不支持工具 {}".format(name or "(empty)"))
    values = arguments if isinstance(arguments, dict) else {}
    result = tool.handler(deepcopy(values), deepcopy(context or {}))
    if not isinstance(result, AgentToolResult):
        raise RuntimeError("Agent 工具 {} 返回了无效结果".format(tool.name))
    return result


def codex_call_result(result):
    """Translate a registry result to Codex App Server dynamic tool output."""
    payload = json.dumps(result.envelope(), ensure_ascii=False, separators=(",", ":"))
    return {
        "success": True,
        "contentItems": [{"type": "inputText", "text": payload}],
    }


def mcp_call_result(name, arguments=None, context=None):
    """Translate one registry invocation to a standard MCP tool result."""
    try:
        result = dispatch(name, arguments, context)
    except AgentToolError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    envelope = result.envelope()
    return {
        "content": [{"type": "text", "text": json.dumps(
            envelope, ensure_ascii=False, separators=(",", ":"))}],
        "structuredContent": envelope,
        "isError": False,
    }


_CORE_SERVICE = None
_CORE_SERVICE_ROOT = ""


def _core_service():
    """Open the same local core from both the app and standalone MCP process."""
    global _CORE_SERVICE, _CORE_SERVICE_ROOT
    import product_store
    from runteams_core import RunTeamsCore
    root = os.path.realpath(product_store.core_data_root())
    if _CORE_SERVICE is None or _CORE_SERVICE_ROOT != root:
        _CORE_SERVICE = RunTeamsCore(root)
        _CORE_SERVICE_ROOT = root
    return _CORE_SERVICE


def _positive_int(value, label):
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AgentToolError("{}必须是整数".format(label)) from exc
    if number <= 0:
        raise AgentToolError("{}必须大于 0".format(label))
    return number


def _tool_context(context):
    context = context if isinstance(context, dict) else {}
    view = context.get("view_context")
    conversation = context.get("conversation_context")
    return context, (view if isinstance(view, dict) else {}), (
        conversation if isinstance(conversation, dict) else {})


def _context_id(context, *keys):
    root, view, conversation = _tool_context(context)
    for source in (conversation, view, root):
        for key in keys:
            if source.get(key) not in (None, ""):
                return source.get(key)
    return None


def _bound_employee_id(context):
    """Return the Employee Bot binding, if this is an Employee Bot chat."""
    _root, _view, conversation = _tool_context(context)
    if (str(conversation.get("context_type") or "").strip() != "worker" or
            str(conversation.get("intent") or "chat").strip() not in {"chat", "work"}):
        return None
    return _positive_int(_context_id(
        context, "employee_id", "target_employee_id", "worker_id"), "employee_id")


def _workflow_uses_employee(workflow, employee_id):
    snapshot = workflow.get("snapshot_json") or {}
    if int(snapshot.get("employee_id") or 0) == int(employee_id):
        return True
    for position in (snapshot.get("definition") or {}).get("positions") or []:
        if int(position.get("employee_id") or 0) == int(employee_id):
            return True
    return False


def _pipeline_uses_employee(pipeline, employee_id):
    if not pipeline:
        return False
    return any(
        int(position.get("employee_id") or 0) == int(employee_id)
        for position in (pipeline.get("definition_json") or {}).get("positions") or []
    )


def _employee_summary(item):
    release = item.get("active_release") or {}
    draft = item.get("draft_json") or {}
    return {
        "id": item.get("id"),
        "name": item.get("name") or "",
        "role": draft.get("role") or release.get("role") or "",
        "published_version": release.get("version") if item.get("active_release_id") else None,
        "has_unpublished_changes": bool(item.get("has_unpublished_changes")),
    }


def _workflow_summary(item):
    snapshot = item.get("snapshot_json") or {}
    task = snapshot.get("task") or {}
    payload = task.get("payload") or {}
    context = payload.get("context") if isinstance(payload, dict) else {}
    context = context if isinstance(context, dict) else {}
    runs = item.get("employee_runs") or []
    current = next((run for run in reversed(runs)
                    if run.get("state") not in ("completed", "canceled")), None)
    result = {
        "workflow_id": item.get("id"),
        "task_id": item.get("task_id") or task.get("id"),
        "title": task.get("title") or "",
        "pipeline_id": snapshot.get("pipeline_id"),
        "pipeline_name": snapshot.get("pipeline_name") or "",
        "state": item.get("state") or "",
        "current_position": (current or {}).get("position_key"),
        "updated_at": item.get("updated_at"),
    }
    if context.get("opportunity_key"):
        result["opportunity_key"] = context.get("opportunity_key")
        result["analysis_decision"] = context.get("analysis_decision") or ""
        result["target_user"] = context.get("target_user") or ""
        result["jtbd"] = context.get("jtbd") or ""
        result["source_urls"] = [
            str(source.get("url") or "") for source in context.get("evidence") or []
            if isinstance(source, dict) and source.get("url")
        ]
    return result


def _pipeline_summary(item, employee_names=None):
    definition = item.get("definition_json") or {}
    positions = definition.get("positions") or []
    employee_names = employee_names or {}
    return {
        "id": item.get("id"),
        "name": item.get("name") or "",
        "positions": [{
            "key": position.get("key"),
            "name": position.get("name") or position.get("key") or "",
            "employee_id": position.get("employee_id"),
            "employee_name": employee_names.get(position.get("employee_id"), ""),
        } for position in positions],
        "updated_at": item.get("updated_at"),
    }


def _resolve_pipeline(arguments, context):
    core = _core_service()
    pipeline_id = _positive_int(arguments.get("pipeline_id"), "pipeline_id")
    if pipeline_id is None:
        pipeline_id = _positive_int(_context_id(
            context, "pipeline_id", "scope_pipeline_id"), "pipeline_id")
    name = str(arguments.get("name") or "").strip()
    if pipeline_id is not None:
        pipeline = core.pipeline(pipeline_id)
    elif name:
        pipeline = next((item for item in core.pipeline_catalog()
                         if item.get("name") == name), None)
    else:
        raise AgentToolError("请提供 pipeline_id 或 name；当前上下文没有默认流水线")
    if pipeline is None:
        raise AgentToolError("找不到指定流水线")
    return pipeline


def _resolve_employee(arguments, context):
    core = _core_service()
    employee_id = _positive_int(arguments.get("employee_id"), "employee_id")
    if employee_id is None:
        employee_id = _positive_int(_context_id(
            context, "employee_id", "target_employee_id", "worker_id"), "employee_id")
    name = str(arguments.get("name") or "").strip()
    if employee_id is not None:
        employee = core.employee(employee_id)
    elif name:
        employee = next((item for item in core.employee_catalog()
                         if item.get("name") == name), None)
    else:
        raise AgentToolError("请提供 employee_id 或 name；当前上下文没有默认员工")
    if employee is None:
        raise AgentToolError("找不到指定员工")
    return employee


def _get_context(_arguments, context):
    root, view, conversation = _tool_context(context)
    core = _core_service()
    pipeline_id = _context_id(context, "pipeline_id", "scope_pipeline_id")
    workflow_id = _context_id(context, "workflow_id", "run_id")
    employee_id = _context_id(context, "employee_id", "target_employee_id", "worker_id")
    resolved = {}
    bound_employee = _bound_employee_id(context)
    if pipeline_id not in (None, ""):
        pipeline = core.pipeline(_positive_int(pipeline_id, "pipeline_id"))
        if pipeline and (bound_employee is None or
                         _pipeline_uses_employee(pipeline, bound_employee)):
            employee_names = {item["id"]: item["name"] for item in core.employee_catalog()}
            resolved["pipeline"] = _pipeline_summary(pipeline, employee_names)
    if workflow_id not in (None, ""):
        workflow = core.workflow(_positive_int(workflow_id, "workflow_id"))
        if workflow and (bound_employee is None or
                         _workflow_uses_employee(workflow, bound_employee)):
            resolved["task"] = _workflow_summary(workflow)
    if employee_id not in (None, "") and (bound_employee is None or
                                          int(employee_id) == bound_employee):
        employee = core.employee(_positive_int(employee_id, "employee_id"))
        if employee and (bound_employee is None or int(employee.get("id") or 0) == bound_employee):
            resolved["employee"] = _employee_summary(employee)
    data = {
        "surface": view.get("surface") or "",
        "label": view.get("label") or conversation.get("label") or "",
        "scope_pipeline_id": root.get("scope_pipeline_id"),
        "view": {key: value for key, value in view.items()
                 if key in ("surface", "label", "pipeline_id", "pipeline_name",
                            "workflow_id", "employee_id", "worker_id", "card_id")},
        "conversation": {key: value for key, value in conversation.items()
                         if key in ("context_type", "intent", "label", "pipeline_id",
                                    "target_employee_id", "workflow_id", "card_id")},
        "resolved": resolved,
    }
    return AgentToolResult("context", "已读取当前 RunTeams 上下文。", data)


def _get_bot_context(arguments, context):
    """Read the durable, bounded facts for the Employee Bot in this chat."""
    allowed = {"employee_id", "pipeline_id", "run_id", "task_id", "state",
               "scope_type", "limit"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("Bot 上下文包含未知参数：{}".format(", ".join(extra)))
    _root, _view, conversation = _tool_context(context)
    bound_employee = _bound_employee_id(context)
    if bound_employee is None:
        raise AgentToolError("请在员工 Bot 对话中使用此工具")
    requested_employee = _positive_int(arguments.get("employee_id"), "employee_id")
    if bound_employee and requested_employee and bound_employee != requested_employee:
        raise AgentToolError("当前 Bot 只能读取绑定员工的工作事实")
    employee_id = requested_employee or bound_employee
    if employee_id is None:
        raise AgentToolError("请先在员工 Bot 对话中选择员工")
    pipeline_id = arguments.get("pipeline_id")
    if pipeline_id in (None, ""):
        pipeline_id = _context_id(context, "pipeline_id", "scope_pipeline_id")
    run_id = arguments.get("run_id")
    if run_id in (None, ""):
        run_id = _context_id(context, "run_id", "workflow_id")
    task_id = arguments.get("task_id")
    state = arguments.get("state")
    scope_type = str(arguments.get("scope_type") or conversation.get("scope_type") or
                     ("run" if run_id else "pipeline" if pipeline_id else "global")).strip()
    try:
        import bot_context
        core = _core_service()
        employee = core.employee(employee_id) or {}
        active_release = employee.get("active_release") or {}
        projection = bot_context.build(
            core, employee_id, scope_type=scope_type,
            pipeline_id=pipeline_id, run_id=run_id,
            task_id=task_id, state=state,
            release_id=active_release.get("id"),
            limit=min(_positive_int(arguments.get("limit") or 12, "limit"), 50),
        )
    except ValueError as exc:
        raise AgentToolError(str(exc)) from exc
    return AgentToolResult(
        "bot_context", "已读取员工 Bot「{}」的关联工作事实。".format(
            projection["employee"].get("name") or employee_id), projection)


def _list_pipelines(arguments, context):
    allowed = {"query", "limit"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("流水线列表包含未知参数：{}".format(", ".join(extra)))
    query = str(arguments.get("query") or "").strip().casefold()
    limit = _positive_int(arguments.get("limit") or 30, "limit")
    limit = min(limit, 100)
    core = _core_service()
    employee_names = {item["id"]: item["name"] for item in core.employee_catalog()}
    items = [item for item in core.pipeline_catalog()
             if not query or query in str(item.get("name") or "").casefold()]
    bound_employee = _bound_employee_id(context)
    if bound_employee is not None:
        items = [item for item in items
                 if _pipeline_uses_employee(item, bound_employee)]
    data = {"pipelines": [_pipeline_summary(item, employee_names)
                          for item in items[:limit]], "total": len(items)}
    return AgentToolResult("pipeline_list", "已读取 {} 条流水线。".format(
        len(data["pipelines"])), data)


def _get_pipeline(arguments, context):
    extra = sorted(set(arguments) - {"pipeline_id", "name", "task_limit"})
    if extra:
        raise AgentToolError("流水线详情包含未知参数：{}".format(", ".join(extra)))
    core = _core_service()
    pipeline = _resolve_pipeline(arguments, context)
    bound_employee = _bound_employee_id(context)
    if bound_employee is not None and not _pipeline_uses_employee(pipeline, bound_employee):
        raise AgentToolError("当前员工 Bot 只能读取自身参与的流水线")
    employee_names = {item["id"]: item["name"] for item in core.employee_catalog()}
    task_limit = min(_positive_int(arguments.get("task_limit") or 20, "task_limit"), 500)
    recent = [_workflow_summary(item) for item in core.workflow_catalog(500)
              if int((item.get("snapshot_json") or {}).get("pipeline_id") or 0)
              == int(pipeline["id"])][:task_limit]
    registry_reader = getattr(core, "opportunity_identity_catalog", None)
    registry = (registry_reader("pipeline", pipeline["id"])
                if registry_reader is not None else [])
    data = {"pipeline": _pipeline_summary(pipeline, employee_names),
            "recent_tasks": recent,
            # Complete identity ledger; recent_tasks is only a display-oriented view.
            "opportunity_registry": registry,
            "opportunity_keys": [item["opportunity_key"] for item in registry]}
    return AgentToolResult("pipeline", "已读取流水线「{}」。".format(
        pipeline.get("name") or pipeline.get("id")), data)


def _get_task(arguments, context):
    extra = sorted(set(arguments) - {"workflow_id", "task_id"})
    if extra:
        raise AgentToolError("任务详情包含未知参数：{}".format(", ".join(extra)))
    core = _core_service()
    workflow_id = _positive_int(arguments.get("workflow_id"), "workflow_id")
    task_id = _positive_int(arguments.get("task_id"), "task_id")
    if workflow_id is None and task_id is None:
        workflow_id = _positive_int(_context_id(
            context, "workflow_id", "run_id"), "workflow_id")
        if workflow_id is None:
            task_id = _positive_int(_context_id(context, "task_id", "card_id"), "task_id")
    workflow = core.workflow(workflow_id) if workflow_id is not None else next((
        item for item in core.workflow_catalog(500)
        if int(item.get("task_id") or 0) == int(task_id)), None)
    if workflow is None:
        if task_id is not None:
            task = core.task(task_id)
            if task:
                bound_employee = _bound_employee_id(context)
                pipeline = (core.pipeline(task.get("pipeline_id"))
                            if task.get("pipeline_id") not in (None, "") else None)
                pipeline_uses_employee = _pipeline_uses_employee(pipeline, bound_employee)
                if (bound_employee is not None and
                        int(task.get("employee_id") or 0) != bound_employee and
                        not pipeline_uses_employee):
                    raise AgentToolError("当前员工 Bot 只能读取自身参与的任务")
                return AgentToolResult("task", "已读取尚未运行的任务。", {
                    "task": {"id": task.get("id"), "pipeline_id": task.get("pipeline_id"),
                             "title": task.get("title"), "state": task.get("state"),
                             "payload": task.get("payload_json") or {}},
                    "workflow": None,
                })
        raise AgentToolError("找不到指定任务；请提供 workflow_id 或 task_id")
    bound_employee = _bound_employee_id(context)
    if bound_employee is not None and not _workflow_uses_employee(workflow, bound_employee):
        raise AgentToolError("当前员工 Bot 只能读取自身参与的任务")
    snapshot = workflow.get("snapshot_json") or {}
    task = snapshot.get("task") or {}
    import bot_context as _bot_context
    runs = []
    for run in workflow.get("employee_runs") or []:
        result = run.get("output_json") or {}
        run_events = []
        for event in (run.get("events") or [])[-100:]:
            event_data = event.get("data_json") or {}
            run_events.append({
                "id": event.get("id"),
                "type": event.get("type"),
                "created_at": event.get("created_at"),
                "actor_id": event.get("actor_id"),
                "correlation_id": event.get("correlation_id"),
                "source": event.get("source"),
                "data": _bot_context._safe_value(event_data),
            })
        runs.append({
            "id": run.get("id"), "position_key": run.get("position_key"),
            "state": run.get("state"), "attempt": run.get("attempt"),
            "summary": result.get("summary") or "", "issues": result.get("issues") or [],
            "work_order": _bot_context._safe_value(run.get("input_json") or {}),
            "output": _bot_context._safe_value(result.get("output") or {}),
            "artifacts": _bot_context._safe_value(run.get("artifacts") or []),
            "events": run_events,
            "updated_at": run.get("updated_at"),
        })
    data = {
        "task": {"id": task.get("id"), "title": task.get("title") or "",
                 "payload": task.get("payload") or {}},
        "workflow": _workflow_summary(workflow),
        "employee_runs": runs,
        "workflow_events": [{
            "id": event.get("id"),
            "type": event.get("type"),
            "created_at": event.get("created_at"),
            "actor_id": event.get("actor_id"),
            "correlation_id": event.get("correlation_id"),
            "source": event.get("source"),
            "data": _bot_context._safe_value(event.get("data_json") or {}),
        } for event in (workflow.get("events") or [])[-100:]],
    }
    audit_reader = getattr(core, "audit_timeline", None)
    if callable(audit_reader):
        timeline = audit_reader("workflow", workflow.get("id"))
        if timeline:
            data["evidence"] = {
                "audit_ref": "audit:workflow:{}".format(workflow.get("id")),
                "integrity": timeline.get("integrity"),
                "events": [{
                    "reference": "event:{}".format(event.get("id")),
                    "type": event.get("type"),
                    "stream": event.get("stream"),
                    "created_at": event.get("created_at"),
                    "actor_id": event.get("actor_id"),
                    "correlation_id": event.get("correlation_id"),
                    "source": event.get("source"),
                } for event in (timeline.get("events") or [])[-24:]],
            }
    return AgentToolResult("task", "已读取任务「{}」。".format(
        task.get("title") or workflow.get("task_id")), data)


def _get_employee(arguments, context):
    extra = sorted(set(arguments) - {"employee_id", "name", "task_limit"})
    if extra:
        raise AgentToolError("员工详情包含未知参数：{}".format(", ".join(extra)))
    core = _core_service()
    employee = _resolve_employee(arguments, context)
    bound_employee = _bound_employee_id(context)
    if bound_employee is not None and int(employee.get("id") or 0) != bound_employee:
        raise AgentToolError("当前员工 Bot 只能读取绑定员工")
    task_limit = _positive_int(arguments.get("task_limit"), "task_limit") or 50
    task_limit = min(task_limit, 500)
    draft = employee.get("draft_json") or {}
    release = employee.get("active_release") or {}
    data = {
        "employee": _employee_summary(employee),
        "draft": {
            "role": draft.get("role") or "",
            "program": draft.get("program") or {},
            "runtime": draft.get("runtime") or {},
            "capability_count": len(draft.get("capabilities") or []),
        },
        "published": {
            "role": release.get("role") or "",
            "program": release.get("program") or {},
            "runtime": release.get("runtime") or {},
            "capability_count": len(release.get("capabilities") or []),
        } if release else None,
        "recent_tasks": [_workflow_summary(item) for item in
                         core.employee_workflow_catalog(employee["id"], task_limit)],
        # Complete identity ledger; recent_tasks is only a display-oriented view.
        "opportunity_registry": (
            core.opportunity_identity_catalog("employee", employee["id"])
            if getattr(core, "opportunity_identity_catalog", None) is not None else []),
    }
    data["opportunity_keys"] = [item["opportunity_key"]
                                 for item in data["opportunity_registry"]]
    return AgentToolResult("employee", "已读取员工「{}」。".format(
        employee.get("name") or employee.get("id")), data)


def _query_opportunities(arguments, _context):
    """Read the durable opportunity result projection without exposing SQL.

    This is intentionally a read-only, provider-neutral tool.  Agents get the
    same complete identity scan that powers the documents/result UI, while the
    core service remains the only place that knows how task, run and artifact
    facts are joined.
    """
    allowed = {"query", "limit", "include_output"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("机会查询包含未知参数：{}".format(", ".join(extra)))
    query = str(arguments.get("query") or "").strip()
    if len(query) > 240:
        raise AgentToolError("机会查询不能超过 240 个字符")
    limit = _positive_int(arguments.get("limit"), "limit")
    include_output = arguments.get("include_output", False)
    if not isinstance(include_output, bool):
        raise AgentToolError("include_output 必须是布尔值")
    items = _core_service().opportunity_catalog(
        query=query, limit=limit or 0, include_output=include_output)
    return AgentToolResult(
        "opportunity_list",
        "已读取 {} 条机会记录。".format(len(items)),
        {
            "opportunities": items,
            "total": len(items),
            # limit is only a caller-facing view limit; omitted/zero means the
            # complete ledger was scanned and returned.
            "complete_scan": not bool(limit),
        },
    )


def _list_documents(arguments, _context):
    """Read the unified document catalog without exposing storage details."""
    allowed = {"query", "limit"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("文档列表包含未知参数：{}".format(", ".join(extra)))
    query = str(arguments.get("query") or "").strip()
    if len(query) > 240:
        raise AgentToolError("文档查询不能超过 240 个字符")
    limit = _positive_int(arguments.get("limit"), "limit") or 100
    limit = min(limit, 500)
    items = _core_service().document_catalog(limit=limit, query=query)
    # The link is an app-internal Markdown target.  It is deliberately exposed
    # by the Agent tool rather than persisted as another database field.
    items = [dict(item, internal_link="runteams://document/{}".format(item["id"]))
             for item in items]
    return AgentToolResult(
        "document_list", "已读取 {} 份文档。".format(len(items)),
        {"documents": items, "total": len(items)},
    )


def _get_document(arguments, _context):
    """Read one document's content, lineage, revisions and live data binding."""
    allowed = {"document_id", "document_key", "name", "include_content"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("文档详情包含未知参数：{}".format(", ".join(extra)))
    include_content = arguments.get("include_content", True)
    if not isinstance(include_content, bool):
        raise AgentToolError("include_content 必须是布尔值")
    document_id = _positive_int(arguments.get("document_id"), "document_id")
    key = str(arguments.get("document_key") or "").strip()
    name = str(arguments.get("name") or "").strip()
    core = _core_service()
    item = core.document_detail(document_id, include_content=include_content) if document_id else None
    if item is None:
        needle = key or name
        if not needle:
            raise AgentToolError("请提供 document_id、document_key 或 name")
        candidates = core.document_catalog(limit=500, query=needle)
        item = next((candidate for candidate in candidates
                     if (key and candidate.get("document_key") == key)
                     or (name and candidate.get("name") == name)), None)
        if item is not None:
            item = core.document_detail(item["id"], include_content=include_content)
    if item is None:
        raise AgentToolError("找不到指定文档")
    item = dict(item, internal_link="runteams://document/{}".format(item["id"]))
    return AgentToolResult("document", "已读取文档「{}」。".format(
        item.get("name") or item.get("id")), {"document": item})


def _propose_document(arguments, _context):
    """Prepare a user-confirmed document create/update proposal.

    Content and data bindings are explicit so an Agent cannot silently overwrite
    a document based on an untyped natural-language guess.  The core service
    performs the final schema and path validation when the proposal is applied.
    """
    allowed = {"operation", "document_id", "document_key", "name", "content",
               "data_view", "note", "summary"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("文档提案包含未知参数：{}".format(", ".join(extra)))
    operation = str(arguments.get("operation") or "").strip().casefold()
    if operation not in ("create", "update"):
        raise AgentToolError("operation 必须是 create 或 update")
    name = str(arguments.get("name") or "").strip()
    content = arguments.get("content")
    if operation == "create" and not name:
        raise AgentToolError("创建文档必须提供 name")
    if content is not None and (not isinstance(content, str) or not content.strip()):
        raise AgentToolError("文档 content 必须是非空文本")
    if isinstance(content, str) and len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise AgentToolError("文档 content 超过 2 MB")
    document_id = _positive_int(arguments.get("document_id"), "document_id")
    document_key = str(arguments.get("document_key") or "").strip()
    if operation == "update" and document_id is None and not document_key and not name:
        raise AgentToolError("更新文档必须提供 document_id、document_key 或 name")
    view = arguments.get("data_view")
    if view is not None and not isinstance(view, dict):
        raise AgentToolError("data_view 必须是对象")
    action = {"op": "create_document" if operation == "create" else "update_document"}
    for key in ("document_id", "document_key", "name", "content", "data_view", "note"):
        if arguments.get(key) not in (None, ""):
            action[key] = deepcopy(arguments[key])
    summary = str(arguments.get("summary") or "").strip() or (
        "创建文档「{}」".format(name) if operation == "create" else
        "更新文档{}".format("「{}」".format(name or document_key) if (name or document_key) else ""))
    return _proposal(summary, [action])


def _require_text(arguments, key, label, limit=4000):
    value = str(arguments.get(key) or "").strip()
    if not value:
        raise AgentToolError("{}不能为空".format(label))
    if len(value) > limit:
        raise AgentToolError("{}不能超过 {} 个字符".format(label, limit))
    return value


def _proposal(summary, actions):
    return AgentToolResult(
        "change_proposal", summary,
        {"summary": summary, "actions": deepcopy(actions), "count": len(actions)},
    )


def _propose_pipeline(arguments, _context):
    allowed = {"operation", "name", "new_name", "positions", "summary"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("流水线提案包含未知参数：{}".format(", ".join(extra)))
    operation = str(arguments.get("operation") or "").strip()
    if operation not in ("create", "update"):
        raise AgentToolError("operation 必须是 create 或 update")
    _root, _view, conversation = _tool_context(_context)
    if (str(conversation.get("context_type") or "").strip() == "worker" and
            str(conversation.get("intent") or "chat").strip() in {"chat", "work"}):
        raise AgentToolError("员工 Bot 对话不直接修改流水线；如需调整流程，请转到流水线对话")
    name = _require_text(arguments, "name", "流水线名称", 120)
    raw_positions = arguments.get("positions")
    positions = None
    if raw_positions is not None:
        if not isinstance(raw_positions, list) or not raw_positions:
            raise AgentToolError("岗位顺序必须是非空数组")
        positions = []
        for raw in raw_positions:
            if not isinstance(raw, dict) or not str(raw.get("name") or "").strip() \
                    or not str(raw.get("employee") or "").strip():
                raise AgentToolError("每个岗位必须包含 name 和 employee")
            positions.append({"name": str(raw["name"]).strip(),
                              "employee": str(raw["employee"]).strip()})
    if operation == "create" and not positions:
        raise AgentToolError("创建流水线必须提供岗位顺序")
    action = {"op": "create_pipeline" if operation == "create" else "update_pipeline",
              "name": name}
    if positions is not None:
        action["positions"] = positions
    new_name = str(arguments.get("new_name") or "").strip()
    if new_name:
        action["to"] = new_name
    summary = str(arguments.get("summary") or "").strip() or (
        "创建流水线「{}」".format(name) if operation == "create" else
        "更新流水线「{}」".format(name))
    return _proposal(summary, [action])


def _propose_task(arguments, _context):
    allowed = {"pipeline", "employee", "title", "objective", "context", "inputs",
               "acceptance", "dedupe_key", "source_run_id", "summary"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("任务提案包含未知参数：{}".format(", ".join(extra)))
    pipeline = str(arguments.get("pipeline") or "").strip()
    employee = str(arguments.get("employee") or "").strip()
    if not pipeline and not employee:
        _root, _view, conversation = _tool_context(_context)
        if (str(conversation.get("context_type") or "").strip() == "worker" and
                str(conversation.get("intent") or "chat").strip() in {"chat", "work"}):
            bound = _resolve_employee({}, _context)
            employee = str(bound.get("name") or "").strip()
    if bool(pipeline) == bool(employee):
        raise AgentToolError("pipeline 和 employee 必须且只能提供一个")
    title = _require_text(arguments, "title", "任务名称", 200)
    objective = _require_text(arguments, "objective", "任务目标", 8000)
    context = arguments.get("context")
    if context is None:
        context = {}
    if isinstance(context, str):
        context = {"brief": context.strip()} if context.strip() else {}
    if not isinstance(context, dict):
        raise AgentToolError("任务上下文必须是对象或文本")
    inputs = arguments.get("inputs") or []
    if not isinstance(inputs, list):
        raise AgentToolError("任务资料必须是数组")
    normalized_inputs = []
    for index, item in enumerate(inputs, 1):
        if not isinstance(item, dict):
            raise AgentToolError("第 {} 项任务资料必须是对象".format(index))
        name = str(item.get("name") or "").strip()
        content = str(item.get("content") or "")
        if not name or not content.strip():
            raise AgentToolError("每项任务资料必须包含 name 和 content")
        normalized_inputs.append({
            "name": name[:200], "content": content,
            **({"source_ref": str(item.get("source_ref"))[:1000]}
               if item.get("source_ref") else {}),
        })
    acceptance = arguments.get("acceptance") or []
    if not isinstance(acceptance, list):
        raise AgentToolError("验收标准必须是字符串数组")
    action = {
        "op": "create_task" if pipeline else "create_employee_task",
        "title": title,
        "objective": objective, "context": context,
        "acceptance": [str(item).strip() for item in acceptance if str(item).strip()],
    }
    if normalized_inputs:
        action["inputs"] = normalized_inputs
    action["pipeline" if pipeline else "employee"] = pipeline or employee
    dedupe_key = str(arguments.get("dedupe_key") or "").strip()[:200]
    if dedupe_key:
        action["dedupe_key"] = dedupe_key
    source_run_id = _positive_int(arguments.get("source_run_id"), "source_run_id")
    if source_run_id is not None:
        action["source_run_id"] = source_run_id
    summary = str(arguments.get("summary") or "").strip() or (
        "在「{}」创建并运行任务「{}」".format(pipeline or employee, title))
    return _proposal(summary, [action])


def _propose_tasks(arguments, _context):
    """Prepare one proposal containing several independent ordinary tasks."""
    allowed = {"pipeline", "employee", "tasks", "summary"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("批量任务提案包含未知参数：{}".format(", ".join(extra)))
    pipeline = str(arguments.get("pipeline") or "").strip()
    employee = str(arguments.get("employee") or "").strip()
    if not pipeline and not employee:
        _root, _view, conversation = _tool_context(_context)
        if (str(conversation.get("context_type") or "").strip() == "worker" and
                str(conversation.get("intent") or "chat").strip() in {"chat", "work"}):
            bound = _resolve_employee({}, _context)
            employee = str(bound.get("name") or "").strip()
    if bool(pipeline) == bool(employee):
        raise AgentToolError("pipeline 和 employee 必须且只能提供一个")
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise AgentToolError("批量任务至少包含一项任务")
    if len(raw_tasks) > 10:
        raise AgentToolError("一次最多创建 10 项任务")
    actions = []
    for index, raw in enumerate(raw_tasks, 1):
        if not isinstance(raw, dict):
            raise AgentToolError("第 {} 项任务必须是对象".format(index))
        task = dict(raw)
        task["pipeline" if pipeline else "employee"] = pipeline or employee
        task.pop("summary", None)
        proposal = _propose_task(task, _context)
        actions.extend(proposal.data["actions"])
    summary = str(arguments.get("summary") or "").strip() or (
        "在「{}」创建并运行 {} 项任务".format(pipeline or employee, len(actions)))
    return _proposal(summary, actions)


def _propose_automation(arguments, _context):
    allowed = {"operation", "name", "prompt", "enabled", "schedule_kind",
               "interval_sec", "schedule", "channel", "model", "reasoning_effort",
               "summary"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("自动化提案包含未知参数：{}".format(", ".join(extra)))
    operation = str(arguments.get("operation") or "").strip()
    if operation not in ("upsert", "delete"):
        raise AgentToolError("operation 必须是 upsert 或 delete")
    _root, _view, conversation = _tool_context(_context)
    if (str(conversation.get("context_type") or "").strip() == "worker" and
            str(conversation.get("intent") or "chat").strip() in {"chat", "work"}):
        raise AgentToolError("员工 Bot 对话不直接修改自动化；请转到自动化对话")
    name = _require_text(arguments, "name", "自动化名称", 120)
    if operation == "delete":
        action = {"op": "delete_automation", "name": name}
        summary = str(arguments.get("summary") or "").strip() or "删除自动化「{}」".format(name)
        return _proposal(summary, [action])
    prompt = _require_text(arguments, "prompt", "自动化执行内容", 12000)
    action = {"op": "upsert_automation", "name": name, "prompt": prompt}
    for key in ("enabled", "schedule_kind", "interval_sec", "schedule", "channel",
                "model", "reasoning_effort"):
        if arguments.get(key) not in (None, ""):
            action[key] = deepcopy(arguments[key])
    summary = str(arguments.get("summary") or "").strip() or "保存自动化「{}」".format(name)
    return _proposal(summary, [action])


def _present_employee_draft(arguments, _context):
    extra = sorted(set(arguments) - {"reply", "draft"})
    if extra:
        raise AgentToolError("员工草稿包含未知参数：{}".format(", ".join(extra)))
    draft = arguments.get("draft")
    if not isinstance(draft, dict):
        raise AgentToolError("draft 必须是对象")
    name = str(draft.get("name") or "").strip()
    instructions = str(draft.get("instructions") or "").strip()
    if not name or not instructions:
        raise AgentToolError("员工草稿必须包含 name 和 instructions")
    program = draft.get("program") if isinstance(draft.get("program"), dict) else {}
    steps = program.get("steps") or []
    if not isinstance(steps, list) or not steps:
        raise AgentToolError("员工草稿至少需要一个工作步骤")
    interface = draft.get("interface") if isinstance(draft.get("interface"), dict) else {}
    if not isinstance(interface.get("input"), dict) or not isinstance(
            interface.get("output"), dict):
        raise AgentToolError("员工草稿必须包含完整的 input/output 接口")
    tests = draft.get("tests") or []
    if not isinstance(tests, list):
        raise AgentToolError("员工草稿 tests 必须是数组")
    if any(not isinstance(item, dict) or not item.get("covers") for item in tests):
        raise AgentToolError("每个员工测试用例都必须声明 covers")
    reply = str(arguments.get("reply") or "").strip() or "员工调整草稿已经准备好。"
    return AgentToolResult(
        "employee_draft", reply,
        {"reply": reply, "draft": deepcopy(draft), "draft_ready": True},
    )


def _request_choice(arguments, _context):
    allowed = {"question", "options"}
    extra = sorted(set(arguments) - allowed)
    if extra:
        raise AgentToolError("选择工具包含未知参数：{}".format(", ".join(extra)))
    question = str(arguments.get("question") or "").strip()
    if not question:
        raise AgentToolError("选择问题不能为空")
    if len(question) > 500:
        raise AgentToolError("选择问题不能超过 500 个字符")
    raw_options = arguments.get("options")
    if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 5:
        raise AgentToolError("选择项必须有 2～5 个")
    options, labels = [], set()
    for raw in raw_options:
        if not isinstance(raw, dict):
            raise AgentToolError("每个选择项必须包含 label 和 description")
        extra = sorted(set(raw) - {"label", "description"})
        if extra:
            raise AgentToolError("选择项包含未知参数：{}".format(", ".join(extra)))
        label = str(raw.get("label") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not label or len(label) > 80:
            raise AgentToolError("选择项标题不能为空且不能超过 80 个字符")
        if len(description) > 240:
            raise AgentToolError("选择项说明不能超过 240 个字符")
        if label in labels:
            raise AgentToolError("选择项标题不能重复")
        labels.add(label)
        options.append({"label": label, "description": description})
    return AgentToolResult(
        kind="choice",
        message="RunTeams 已显示选择卡片；等待用户在下一条消息中选择。",
        data={"questions": [{"id": "choice", "question": question,
                              "options": options}]},
    )


register(AgentTool(
    name="runteams_request_choice",
    description=(
        "Ask the user one blocking multiple-choice question when missing information "
        "would materially change the result. RunTeams renders it as a choice card."),
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "One focused question."},
            "options": {
                "type": "array", "minItems": 2, "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["label", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["question", "options"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="choice",
    handler=_request_choice,
))


register(AgentTool(
    name="runteams_get_context",
    description=(
        "Read the current RunTeams page, conversation target and resolved local objects. "
        "Call this before assuming what pipeline, task or employee the user means."),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    risk="read",
    ui_kind="context",
    handler=_get_context,
))


register(AgentTool(
    name="runteams_get_bot_context",
    description=(
        "Read the bounded, read-only work history for the Employee Bot in the current chat: "
        "employee release, related pipeline runs, employee results and artifact references. "
        "Filters are exact structured IDs/states, never semantic similarity; defaults to the "
        "bound Bot employee and never exposes credentials or unrelated employees."),
    input_schema={
        "type": "object",
        "properties": {
            "employee_id": {"type": "integer", "minimum": 1},
            "pipeline_id": {"type": "integer", "minimum": 1},
            "run_id": {"type": "integer", "minimum": 1},
            "task_id": {"type": "integer", "minimum": 1},
            "state": {"type": "string", "enum": [
                "ready", "running", "completed", "failed", "blocked", "needs_human",
                "needs_approval", "interrupted", "waiting_retry", "canceled", "paused",
                "superseded",
            ], "description": "Optional exact WorkflowRun state."},
            "scope_type": {"type": "string", "enum": ["global", "pipeline", "run"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_get_bot_context,
))


register(AgentTool(
    name="runteams_list_pipelines",
    description=(
        "List local RunTeams pipelines with their ordered positions and assigned employees. "
        "Use query to narrow by pipeline name."),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional pipeline-name search."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_list_pipelines,
))


register(AgentTool(
    name="runteams_get_pipeline",
    description=(
        "Read one RunTeams pipeline, its ordered positions, assigned employees and recent "
        "task runs. The returned opportunity_registry/opportunity_keys are the complete "
        "unpaginated identity ledger; recent_tasks is only a display summary. Omit both "
        "identifiers to use the current conversation/page pipeline."),
    input_schema={
        "type": "object",
        "properties": {
            "pipeline_id": {"type": "integer", "minimum": 1},
            "name": {"type": "string"},
            "task_limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_get_pipeline,
))


register(AgentTool(
    name="runteams_get_task",
    description=(
        "Read one RunTeams task/workflow, including payload, status and employee run "
        "summaries. Omit identifiers to use the task currently shown in RunTeams."),
    input_schema={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer", "minimum": 1},
            "task_id": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_get_task,
))


register(AgentTool(
    name="runteams_get_employee",
    description=(
        "Read one RunTeams employee's draft, published contract and recent direct work. "
        "The returned opportunity_registry/opportunity_keys are the complete unpaginated "
        "identity ledger; recent_tasks is only a display summary. Omit identifiers to use "
        "the employee targeted by the current conversation."),
    input_schema={
        "type": "object",
        "properties": {
            "employee_id": {"type": "integer", "minimum": 1},
            "name": {"type": "string"},
            "task_limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_get_employee,
))


register(AgentTool(
    name="runteams_query_opportunities",
    description=(
        "Read the complete durable opportunity result projection across RunTeams. "
        "Results combine task context, analysis conclusions, evidence and linked "
        "documents; use query to narrow the view. Omit limit to scan the full ledger. "
        "This is read-only and does not create or mutate opportunities."),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional text search."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10000,
                      "description": "Optional returned-view limit; the ledger is scanned first."},
            "include_output": {"type": "boolean",
                               "description": "Include the structured work result payload."},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_query_opportunities,
))


register(AgentTool(
    name="runteams_list_documents",
    description=(
        "Read the unified RunTeams document catalog, including documents authored by "
        "employees and Agent Chat. This is read-only; use query to narrow the list. "
        "Each result includes internal_link; use it as the Markdown link target when "
        "one RunTeams document should reference another."),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional text search."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_list_documents,
))


register(AgentTool(
    name="runteams_get_document",
    description=(
        "Read one document's content, revision lineage and any live product data view. "
        "Provide document_id, document_key or exact name; this is read-only. The result "
        "includes internal_link for linking to this document from RunTeams Markdown."),
    input_schema={
        "type": "object",
        "properties": {
            "document_id": {"type": "integer", "minimum": 1},
            "document_key": {"type": "string"},
            "name": {"type": "string"},
            "include_content": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    risk="read",
    ui_kind="tool",
    handler=_get_document,
))


register(AgentTool(
    name="runteams_propose_document",
    description=(
        "Prepare a user-confirmed document create/update proposal. A document can contain "
        "Agent-authored narrative plus a safe named data view (currently opportunities); "
        "the proposal does not write until the user presses Apply. Automations may apply it "
        "within their authorized run."),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["create", "update"]},
            "document_id": {"type": "integer", "minimum": 1},
            "document_key": {"type": "string"},
            "name": {"type": "string"},
            "content": {"type": "string"},
            "data_view": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["opportunities"]},
                    "query": {"type": "string", "maxLength": 240},
                    "columns": {"type": "array", "maxItems": 12,
                                "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "note": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["operation"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="proposal",
    handler=_propose_document,
))


register(AgentTool(
    name="runteams_propose_pipeline_change",
    description=(
        "Prepare a user-confirmed RunTeams pipeline create/update proposal. This tool "
        "does not mutate data; RunTeams renders an Apply card and only writes after the "
        "user confirms it."),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["create", "update"]},
            "name": {"type": "string", "description": "Current or new pipeline name."},
            "new_name": {"type": "string", "description": "Optional new name for update."},
            "positions": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "employee": {"type": "string"},
                    },
                    "required": ["name", "employee"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["operation", "name"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="proposal",
    handler=_propose_pipeline,
))


register(AgentTool(
    name="runteams_propose_task",
    description=(
        "Prepare a task for exactly one RunTeams pipeline or one published employee. "
        "RunTeams asks a user to Apply, while automations apply it immediately."),
    input_schema={
        "type": "object",
        "properties": {
            "pipeline": {"type": "string"},
            "employee": {"type": "string"},
            "title": {"type": "string"},
            "objective": {"type": "string"},
            "context": {"type": "object", "additionalProperties": True},
            "inputs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                        "source_ref": {"type": "string"},
                    },
                    "required": ["name", "content"],
                    "additionalProperties": False,
                },
            },
            "acceptance": {"type": "array", "items": {"type": "string"}},
            "dedupe_key": {"type": "string"},
            "source_run_id": {
                "type": "integer", "minimum": 1,
                "description": "Optional exact completed WorkflowRun to use as historical context.",
            },
            "summary": {"type": "string"},
        },
        "required": ["title", "objective"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="proposal",
    handler=_propose_task,
))


register(AgentTool(
    name="runteams_propose_tasks",
    description=(
        "Prepare one user-confirmed proposal that creates and starts several independent "
        "tasks for exactly one pipeline or one published employee. Automations apply it "
        "without another confirmation. Use dedupe_key for recurring discovery work."),
    input_schema={
        "type": "object",
        "properties": {
            "pipeline": {"type": "string"},
            "employee": {"type": "string"},
            "tasks": {
                "type": "array", "minItems": 1, "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "objective": {"type": "string"},
                        "context": {"type": "object", "additionalProperties": True},
                        "inputs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "content": {"type": "string"},
                                    "source_ref": {"type": "string"},
                                },
                                "required": ["name", "content"],
                                "additionalProperties": False,
                            },
                        },
                        "acceptance": {"type": "array", "items": {"type": "string"}},
                        "dedupe_key": {"type": "string"},
                        "source_run_id": {
                            "type": "integer", "minimum": 1,
                            "description": "Optional exact completed WorkflowRun to use as historical context.",
                        },
                    },
                    "required": ["title", "objective"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["tasks"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="proposal",
    handler=_propose_tasks,
))


register(AgentTool(
    name="runteams_propose_automation",
    description=(
        "Prepare a user-confirmed RunTeams automation upsert/delete proposal. This tool "
        "does not mutate automation state before the user presses Apply."),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["upsert", "delete"]},
            "name": {"type": "string"},
            "prompt": {"type": "string"},
            "enabled": {"type": "boolean"},
            "schedule_kind": {"type": "string"},
            "interval_sec": {"type": "integer", "minimum": 1},
            "schedule": {"type": "string"},
            "channel": {"type": "string"},
            "model": {"type": "string"},
            "reasoning_effort": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["operation", "name"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="proposal",
    handler=_propose_automation,
))


register(AgentTool(
    name="runteams_present_employee_draft",
    description=(
        "Present a complete employee design draft for user review. This tool only creates "
        "the structured draft card; it does not publish or save the employee."),
    input_schema={
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "draft": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "goal": {"type": "string"},
                    "instructions": {"type": "string"},
                    "program": {
                        "type": "object",
                        "properties": {
                            "objective": {"type": "string"},
                            "steps": {
                                "type": "array", "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "name": {"type": "string"},
                                        "instructions": {"type": "string"},
                                    },
                                    "required": ["id", "name", "instructions"],
                                    "additionalProperties": True,
                                },
                            },
                            "delivery": {
                                "type": "object",
                                "properties": {
                                    "acceptance_criteria": {
                                        "type": "string",
                                    },
                                },
                                "additionalProperties": True,
                            },
                            "deliverables": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string"},
                                        "name": {"type": "string"},
                                        "required": {"type": "boolean"},
                                    },
                                    "required": ["path", "name", "required"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["objective", "steps"],
                        "additionalProperties": True,
                    },
                    "capabilities": {
                        "type": "array",
                        "items": {
                            "oneOf": [{
                                "type": "object",
                                "properties": {
                                    "package_id": {"type": "integer", "minimum": 1},
                                    "capability_id": {"type": "string"},
                                },
                                "required": ["package_id", "capability_id"],
                                "additionalProperties": False,
                            }, {
                                "type": "object",
                                "properties": {
                                    "provider": {"type": "string"},
                                    "plugin_id": {"type": "string"},
                                },
                                "required": ["provider", "plugin_id"],
                                "additionalProperties": False,
                            }],
                        },
                    },
                    "interface": {
                        "type": "object",
                        "properties": {
                            "input": {"type": "object", "additionalProperties": True},
                            "output": {"type": "object", "additionalProperties": True},
                        },
                        "required": ["input", "output"],
                        "additionalProperties": False,
                    },
                    "tests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "work_order": {
                                    "type": "object",
                                    "properties": {
                                        "objective": {"type": "string"},
                                        "context": {"type": "object", "additionalProperties": True},
                                        "inputs": {"type": "array", "items": {}},
                                        "expected_output": {"type": "object", "additionalProperties": True},
                                        "acceptance": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["objective", "context", "inputs",
                                                 "expected_output", "acceptance"],
                                    "additionalProperties": False,
                                },
                                "expected_status": {
                                    "type": "string",
                                    "enum": ["completed", "blocked", "needs_human", "failed"],
                                },
                                "expected_route": {
                                    "type": "string",
                                    "enum": ["completed", "exception"],
                                },
                                "downstream_employee_id": {"type": "integer", "minimum": 1},
                                "fixtures": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "path": {"type": "string"},
                                            "content": {"type": "string"},
                                            "executable": {"type": "boolean"},
                                        },
                                        "required": ["path", "content"],
                                        "additionalProperties": False,
                                    },
                                },
                                "covers": {
                                    "type": "array", "minItems": 1,
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["id", "name", "work_order", "expected_status",
                                         "covers"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "instructions", "program", "interface"],
                "additionalProperties": True,
            },
        },
        "required": ["draft"],
        "additionalProperties": False,
    },
    risk="interactive",
    ui_kind="draft",
    handler=_present_employee_draft,
))
