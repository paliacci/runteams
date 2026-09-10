# -*- coding: utf-8 -*-
"""助手 —— 产品最高层的对话式编排 agent(跨所有流水线)。

它自己不干具体业务(那是无头员工的活),而是通过原生工具调用理解和编排用户意图:
建/改/删流水线、配员工、连线、派卡、汇报——覆盖整个产品,不局限于某条流水线。
对话正文使用自然 Markdown；需要读取、提问或修改产品数据时调用对应的 RunTeams 工具。
产品交互只通过原生工具表达，不解析模型正文中的动作协议。
"""
import json
import os
import re
import sys

import agent_tool_registry
import automation_store as automations
import bot_context
import model_channels
import codex_threads
import runtime_capabilities
import app_secrets
from adapter_base import EXECUTION_INTERNAL_ANALYSIS, EXECUTION_USER_AGENT
from errors import Cancelled, RateLimited, Transient
from runner import run_agent
import scheduler
import product_store as store
from runteams_core import RunTeamsCore

_CORE_SERVICE = None
_CORE_SERVICE_ROOT = ""


def _core_service():
    """Use the same core database as the HTTP controller without importing app.py."""
    global _CORE_SERVICE, _CORE_SERVICE_ROOT
    root = os.path.realpath(store.core_data_root())
    if _CORE_SERVICE is None or _CORE_SERVICE_ROOT != root:
        # Chat actions and unattended automations share this service instance.
        # It must have the same native-extension resolver as the HTTP controller;
        # otherwise starting a pipeline task whose released employee uses a CLI
        # extension fails with the misleading "当前环境不能验证模型渠道扩展" error.
        def resolve_native_dependency(provider, plugin_id, refresh=False):
            channel = next((item for item in store.list_channels()
                            if item.get("provider") == provider), None)
            if channel is None:
                raise ValueError("模型渠道不存在")
            return runtime_capabilities.plugin_dependency(
                channel, plugin_id, refresh=refresh)

        _CORE_SERVICE = RunTeamsCore(
            root, credential_names_provider=app_secrets.names,
            native_dependency_resolver=resolve_native_dependency)
        _CORE_SERVICE_ROOT = root
    return _CORE_SERVICE


def _assistant_workspace():
    return store.assistant_workspace()


def _agent_tool_context(chat_id, scope_pipeline_id, view_context, conversation_context):
    """Serializable context shared by Codex dynamic tools and Claude MCP tools."""
    return {
        "chat_id": int(chat_id) if chat_id not in (None, "") else None,
        "scope_pipeline_id": (int(scope_pipeline_id)
                              if scope_pipeline_id not in (None, "") else None),
        "view_context": dict(view_context or {}),
        "conversation_context": dict(conversation_context or {}),
    }


def _claude_agent_tool_args(context, tool_names):
    """Merge RunTeams read tools into Claude's native MCP configuration."""
    command = sys.executable
    if getattr(sys, "frozen", False):
        arguments = ["--runteams-agent-tools-mcp"]
    else:
        arguments = [os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                  "agent_tools_mcp.py")]
    server_env = {
        "PYTHONNOUSERSITE": "1",
        "RUNTEAMS_AGENT_TOOL_CONTEXT": json.dumps(
            dict(context, allowed_tools=list(tool_names)), ensure_ascii=False,
            separators=(",", ":")),
    }
    config = {"mcpServers": {"runteams-agent": {
        "type": "stdio", "command": command,
        "args": arguments, "env": server_env,
    }}}
    # Do not use --strict-mcp-config here. Agent Chat must keep the user's enabled
    # Claude extensions while adding the local RunTeams context tools.
    return ["--mcp-config", json.dumps(
        config, ensure_ascii=False, separators=(",", ":"))]


def public_error(exc, config=None):
    """把 CLI/运行器异常压成可行动的产品文案，不暴露冗长诊断。"""
    config = config or {}
    channel = store.get_channel(config.get("channel_id")) if config.get("channel_id") else None
    provider = (channel or {}).get("provider")
    label = model_channels.provider_info(provider)["label"] if provider else "当前渠道"
    raw = str(exc or "").strip()
    if isinstance(exc, RateLimited):
        reset = re.search(r"resets?\s+(.+)$", raw, re.I)
        recovery = "；预计 {} 恢复".format(reset.group(1).strip()) if reset else ""
        return "{} 当前订阅用量已达上限{}。请切换到其他已连接渠道后重试。".format(label, recovery)
    if isinstance(exc, Transient):
        return "{} 连接暂时中断，请稍后重试。".format(label)
    if "超时" in raw:
        return "{} 响应超时，请重试或降低思考深度。".format(label)
    return "{} 运行失败：{}".format(label, raw[:360] or "未知错误")


CORE_SYS = """你是 RunTeams.ai 的产品助手。RunTeams 的核心单位是员工：员工由固定工作程序、运行配置和已冻结的员工技能组成；流水线只负责按顺序组合已发布员工；任务启动时冻结流水线和员工发布版本，员工之间用结构化结果交接。

你可以使用当前 Agent CLI 的原生文件、终端、搜索、扩展和 RunTeams 工具完成工作，不要把自己限制成一个只会输出产品动作的路由器。涉及当前页面或具体 RunTeams 对象的事实，应优先调用 runteams_get_context、runteams_get_bot_context、runteams_list_pipelines、runteams_get_pipeline、runteams_get_task、runteams_get_employee、runteams_query_opportunities、runteams_list_documents、runteams_get_document 核实，不要凭摘要猜测；需要需求挖掘历史、分析结论或机会文档时，使用机会和文档读取工具，不要重新猜测或重复创建记录。文档整理必须使用 runteams_propose_document：正文可以由你组织，数据库内容用安全的数据视图绑定，不能写 SQL、伪造事实或直接改文件。需要引用另一篇 RunTeams 文档时，先读取文档目录并使用返回的 internal_link 作为 Markdown 链接目标；不要编造 artifact ID 或内部路径。创建或调整员工应引导用户进入「团队」里的员工 AI 对话；能力应组合到员工，不直接绑定流水线。

对 RunTeams 产品数据的有影响改动必须使用正式提案工具：流水线使用 runteams_propose_pipeline_change，单项任务使用 runteams_propose_task，同一流水线或同一员工的多项独立任务使用 runteams_propose_tasks，自动化使用 runteams_propose_automation，文档使用 runteams_propose_document。任务必须且只能选择一个去向：交给流水线，或直接交给已发布员工。普通对话中的提案需要用户确认后应用；无人值守自动化会在本次运行中自动应用。必须按当前对话目标说明的真实执行方式表述结果，不要绕过工具直接修改产品数据库。

只有缺失的信息会实质改变结果且无法合理默认时才提问。此时必须调用 runteams_request_choice 提出一个聚焦问题并给出 2～5 个选项，禁止把选项写成普通文本或 Markdown 列表。

最终回复直接使用自然、简洁的中文 Markdown。不要输出 JSON 外壳，不要复述工具参数，也不要暴露内部动作协议。"""


def _find_core_pipeline(name):
    name = str(name or "").strip()
    return next((item for item in _core_service().pipeline_catalog()
                 if item["name"] == name), None)


def _find_core_employee(name):
    name = str(name or "").strip()
    return next((item for item in _core_service().employee_catalog()
                 if item["name"] == name), None)


def _core_pipeline_definition(raw_positions):
    employees = {item["name"]: item for item in _core_service().employee_catalog()}
    positions = []
    for index, raw in enumerate(raw_positions or []):
        if not isinstance(raw, dict):
            raise ValueError("流水线岗位格式无效")
        employee_name = str(raw.get("employee") or "").strip()
        employee = employees.get(employee_name)
        if employee is None:
            raise ValueError("找不到员工「{}」".format(employee_name))
        if not employee.get("active_release_id"):
            raise ValueError("员工「{}」尚未发布".format(employee_name))
        key = "position-{}".format(index + 1)
        positions.append({"key": key,
                          "name": str(raw.get("name") or key).strip(),
                          "employee_id": employee["id"]})
    if not positions:
        raise ValueError("流水线至少需要一个岗位")
    return {"schema": "runteams.pipeline/v1", "positions": positions,
            "edges": [{"from": positions[index]["key"],
                       "to": positions[index + 1]["key"]}
                      for index in range(len(positions) - 1)]}


def _apply_automation(action):
    op = str(action.get("op") or "").strip()
    name = str(action.get("name") or ("新自动化" if op == "upsert_automation" else "")).strip()
    current = next((item for item in automations.list_automations()
                    if item["name"] == name), None)
    if op == "delete_automation":
        if not current:
            return "找不到自动化「{}」".format(name), None
        if not scheduler.cancel_scheduled_automation(
                current["id"], "自动化已删除", wait_timeout=5):
            raise ValueError("自动化正在停止，请稍后再试")
        automations.trash_automation(current["id"])
        return "自动化「{}」已移到垃圾箱".format(name), None
    requested_channel = str(action.get("channel") or "").strip().lower()
    channel = next((item for item in store.list_channels()
                    if requested_channel and requested_channel in (
                        str(item.get("name") or "").lower(),
                        str(item.get("provider") or "").lower())), None)
    item = automations.save_automation({
        "name": name,
        "prompt": action.get("prompt") or (current or {}).get("prompt") or "",
        "schedule_kind": (action.get("schedule_kind")
                          or (current or {}).get("schedule_kind") or "interval"),
        "interval_sec": (action.get("interval_sec")
                         or (current or {}).get("interval_sec") or 3600),
        "schedule": (action.get("schedule") if isinstance(action.get("schedule"), dict)
                     else (current or {}).get("schedule") or {}),
        "enabled": action.get("enabled", (current or {}).get("enabled", True)),
        "channel_id": (channel or {}).get("id") or (current or {}).get("channel_id"),
        "model": (action.get("model") if "model" in action
                  else (current or {}).get("model") or ""),
        "reasoning_effort": (action.get("reasoning_effort")
                             if "reasoning_effort" in action
                             else (current or {}).get("reasoning_effort") or ""),
    }, current["id"] if current else None)
    return "{}自动化「{}」".format("更新" if current else "创建", item["name"]), None


def _bot_handoff_context(employee, title, context, action_context):
    """Hydrate a direct Bot task with the newest bounded historical record."""
    action_context = action_context if isinstance(action_context, dict) else {}
    conversation = action_context.get("conversation_context")
    conversation = conversation if isinstance(conversation, dict) else {}
    if (str(conversation.get("context_type") or "").strip() != "worker" or
            str(conversation.get("intent") or "chat").strip() not in {"chat", "work"}):
        return context
    requested_run_id = conversation.get("source_run_id") or conversation.get("run_id")
    explicit_source_run_id = conversation.get("source_run_id")
    try:
        employee_id = int(employee.get("id") or 0)
    except (TypeError, ValueError):
        return context
    if not employee_id:
        return context
    active_release = employee.get("active_release") or {}
    try:
        projection = bot_context.build(
            _core_service(), employee_id,
            scope_type=conversation.get("scope_type") or "global",
            pipeline_id=conversation.get("pipeline_id"),
            run_id=requested_run_id,
            release_id=active_release.get("id"),
            limit=12,
        )
        handoff = bot_context.latest_completed_work(projection)
    except (TypeError, ValueError):
        handoff = None
    if not handoff:
        if explicit_source_run_id not in (None, ""):
            raise ValueError("找不到可交接的已完成 WorkflowRun：{}".format(
                explicit_source_run_id))
        return context
    hydrated = dict(context)
    source_context = handoff.get("task_context") or {}
    if isinstance(source_context, dict):
        # Keep the user's new request authoritative. Identity is regenerated so
        # this handoff cannot deduplicate against its source task.
        for key, value in source_context.items():
            if key not in {"opportunity_key", "dedupe_key"}:
                hydrated.setdefault(key, value)
        if not hydrated.get("opportunity_key") and source_context.get("opportunity_key"):
            source_id = handoff.get("task_id") or handoff.get("workflow_run_id") or "history"
            safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", str(title or "handoff")).strip("-")
            hydrated["opportunity_key"] = "bot-handoff-{}-{}".format(source_id, safe_title[:80])
    hydrated["bot_memory"] = handoff
    hydrated.setdefault("upstream_position", "employee_bot_memory")
    hydrated.setdefault("upstream_output", handoff.get("result") or {})
    return hydrated


def _apply_core(a, action_context=None):
    """Apply only the compact Employee/Pipeline/Workflow contract used by the product UI."""
    op = str((a or {}).get("op") or "").strip()
    core = _core_service()
    if op == "create_document":
        item = core.create_agent_document(
            a.get("name"), a.get("content"), document_key=a.get("document_key"),
            data_view=a.get("data_view"), note=a.get("note", ""))
        return "创建文档「{}」".format(item.get("name") or a.get("name")), {
            "document_id": item.get("id")}
    if op == "update_document":
        document_id = a.get("document_id")
        if document_id not in (None, ""):
            try:
                document_id = int(document_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("文档 ID 无效") from exc
        else:
            needle = str(a.get("document_key") or a.get("name") or "").strip()
            if not needle:
                raise ValueError("更新文档需要 document_id、document_key 或 name")
            candidates = core.document_catalog(limit=500, query=needle)
            exact = next((item for item in candidates
                          if item.get("document_key") == needle
                          or item.get("name") == needle), None)
            document_id = (exact or (candidates[0] if candidates else {})).get("id")
            if not document_id:
                raise ValueError("找不到文档「{}」".format(needle))
        item = core.update_agent_document(
            document_id, name=a.get("name"), content=a.get("content"),
            data_view=a.get("data_view"), note=a.get("note", ""))
        return "更新文档「{}」".format(item.get("name") or a.get("name") or document_id), {
            "document_id": item.get("id")}
    if op == "create_pipeline":
        name = str(a.get("name") or "新流水线").strip()
        pipeline_id = core.create_pipeline(name, _core_pipeline_definition(a.get("positions")))
        return "新建流水线「{}」".format(name), {"focus_pid": pipeline_id}
    if op == "update_pipeline":
        pipeline = _find_core_pipeline(a.get("name"))
        if pipeline is None:
            return "找不到流水线「{}」".format(a.get("name")), None
        definition = pipeline["definition_json"]
        if "positions" in a:
            definition = _core_pipeline_definition(a.get("positions"))
            states = (pipeline.get("definition_json") or {}).get("states") or []
            if states:
                definition["states"] = states
        name = str(a.get("to") or pipeline["name"]).strip()
        core.update_pipeline(pipeline["id"], name, definition)
        return "更新流水线「{}」".format(name), {"focus_pid": pipeline["id"]}
    if op in ("create_task", "create_employee_task"):
        pipeline = _find_core_pipeline(a.get("pipeline")) if op == "create_task" else None
        employee = (_find_core_employee(a.get("employee"))
                    if op == "create_employee_task" else None)
        if op == "create_task" and pipeline is None:
            return "找不到流水线「{}」".format(a.get("pipeline")), None
        if op == "create_employee_task" and employee is None:
            return "找不到员工「{}」".format(a.get("employee")), None
        if employee is not None and not employee.get("active_release_id"):
            return "员工「{}」尚未发布".format(employee["name"]), None
        objective = str(a.get("objective") or "").strip()
        if not objective:
            raise ValueError("任务工作目标不能为空")
        context = a.get("context")
        if context is None:
            context = {}
        if isinstance(context, str):
            context = {"brief": context.strip()} if context.strip() else {}
        if not isinstance(context, dict):
            raise ValueError("任务背景必须是文本或对象")
        if op == "create_employee_task":
            handoff_context = action_context if isinstance(action_context, dict) else {}
            source_run_id = a.get("source_run_id")
            if source_run_id not in (None, ""):
                handoff_context = dict(handoff_context)
                conversation_context = dict(
                    handoff_context.get("conversation_context") or {})
                conversation_context.update({
                    "source_run_id": source_run_id,
                    "run_id": source_run_id,
                    "scope_type": "run",
                })
                handoff_context["conversation_context"] = conversation_context
            context = _bot_handoff_context(
                employee, a.get("title"), context, handoff_context)
        dedupe_key = str(a.get("dedupe_key") or "").strip()
        if dedupe_key:
            context.setdefault("opportunity_key", dedupe_key)
            existing = (core.find_task_by_context(
                pipeline["id"], "opportunity_key", dedupe_key,
                include_trashed=True) if pipeline is not None else
                core.find_employee_task_by_context(
                    employee["id"], "opportunity_key", dedupe_key,
                    include_trashed=True))
            if existing is not None:
                # A previous apply may have created the task but failed while
                # compiling its workflow (for example, a transient extension
                # inventory error).  Retrying the same deduped action must be
                # able to finish that task instead of silently leaving it in
                # ready state forever.  start_workflow is idempotent and
                # returns the existing run when one already exists.
                if not existing.get("trashed_at"):
                    core.start_workflow(existing["id"], source=action_context)
                return "「{}」已记录，跳过重复机会".format(
                    existing.get("title") or a.get("title")), {
                        "focus_pid": pipeline["id"] if pipeline is not None else None}
        acceptance = a.get("acceptance") if isinstance(a.get("acceptance"), list) else []
        payload = {"objective": objective, "context": context,
                   "inputs": (a.get("inputs") if isinstance(a.get("inputs"), list) else []),
                   "acceptance": [str(item).strip() for item in acceptance
                                  if str(item).strip()]}
        task_id = (core.create_task(pipeline["id"], a.get("title"), payload)
                   if pipeline is not None else
                   core.create_employee_task(employee["id"], a.get("title"), payload))
        # A concurrent request may have won the unique identity race, or the
        # canonical record may be in trash. Never restart that historical task.
        existing_task = core.task(task_id)
        if existing_task is not None and existing_task.get("trashed_at"):
            return "「{}」已记录，跳过重复机会".format(
                existing_task.get("title") or a.get("title")), {
                    "focus_pid": pipeline["id"] if pipeline is not None else None}
        workflow_id = core.start_workflow(task_id, source=action_context)
        automation_run_id = int((action_context or {}).get("automation_run_id") or 0)
        if automation_run_id:
            event = {
                "workflow_run_id": workflow_id, "task_id": task_id,
                "task_title": str(a.get("title") or "").strip(),
            }
            if pipeline is not None:
                event.update({"pipeline_id": pipeline["id"],
                              "pipeline_name": pipeline["name"]})
            else:
                event.update({"employee_id": employee["id"],
                              "employee_name": employee["name"]})
            automations.add_automation_run_event(automation_run_id, "workflow", event)
        owner = pipeline or employee
        result_text = ("在「{}」创建并启动任务「{}」" if pipeline is not None else
                       "交给「{}」并启动任务「{}」")
        return result_text.format(owner["name"], a.get("title")), {
                "focus_pid": pipeline["id"] if pipeline is not None else None,
                "workflow_run": workflow_id}
    if op in ("upsert_automation", "delete_automation"):
        return _apply_automation(a)
    raise ValueError("当前核心不支持动作 {}".format(op or "(空)"))


def _context_excerpt(value, limit=180):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:max(1, limit - 1)].rstrip() + "…"


def _core_state_context():
    """Small read-only projection of the ten-table core for conversations and automations."""
    core = _core_service()
    employees = core.employee_catalog()
    employee_names = {item["id"]: item["name"] for item in employees}
    pipelines = core.pipeline_catalog()
    workflows = core.workflow_catalog(30)
    lines = ["## 员工（{} 名）".format(len(employees))]
    for item in employees:
        release = item.get("active_release") or {}
        lines.append("- {} · {} · {}".format(
            item["name"], "已发布 v{}".format(release.get("version") or "")
            if item.get("active_release_id") else "草稿",
            _context_excerpt((item.get("draft_json") or {}).get("role"), 180)))
    lines.append("\n## 流水线（{} 条）".format(len(pipelines)))
    for pipeline in pipelines:
        positions = (pipeline.get("definition_json") or {}).get("positions") or []
        order = " → ".join("{}（{}）".format(
            position.get("name") or position.get("key"),
            employee_names.get(position.get("employee_id"), "员工不存在"))
            for position in positions)
        related = [item for item in workflows
                   if int((item.get("snapshot_json") or {}).get("pipeline_id") or 0)
                   == int(pipeline["id"])]
        states = ", ".join("{}:{}".format(
            _context_excerpt((item.get("snapshot_json") or {}).get("task", {}).get("title"), 60),
            item.get("state") or "未知") for item in related[:8])
        lines.append("- {} · 岗位 {}{}".format(
            pipeline["name"], order or "(空)", (" · 最近任务 " + states) if states else ""))
    schedules = automations.list_automations()
    if schedules:
        lines.append("\n## 自动化（{} 项）".format(len(schedules)))
        for item in schedules:
            lines.append("- {} · {} · {}".format(
                item.get("name") or "未命名", "已启用" if item.get("enabled") else "已暂停",
                item.get("last_status") or "还未运行"))
    return "\n".join(lines)


def _clean_title(value):
    title = " ".join(str(value or "").split()).strip(" \t\r\n。，！？!?：:；;\"'《》")[:40]
    return "" if title in ("新对话", "未命名对话") else title


def _clean_options(value):
    """Normalize optional clarification choices returned by general Agent Chat."""
    result = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("title") or "").strip()
            description = str(item.get("description") or item.get("desc") or "").strip()
        elif isinstance(item, (str, int, float)):
            label, description = str(item).strip(), ""
        else:
            continue
        if not label or len(label) > 60 or any(row["label"] == label for row in result):
            continue
        result.append({"label": label, "description": description[:120]})
        if len(result) >= 5:
            break
    return result


def _native_choice_request(value):
    """Normalize the first actionable native request_user_input question."""
    for request in value if isinstance(value, list) else []:
        if not isinstance(request, dict):
            continue
        for question in request.get("questions") or []:
            if not isinstance(question, dict):
                continue
            options = _clean_options(question.get("options"))
            prompt = str(question.get("question") or "").strip()[:500]
            if prompt and 2 <= len(options) <= 5:
                return prompt, options
    return "", []


def _native_tool_result(value, kind):
    """Return the last valid RunTeams native tool envelope of ``kind``."""
    for item in reversed(value if isinstance(value, list) else []):
        if (isinstance(item, dict)
                and item.get("protocol") == agent_tool_registry.PROTOCOL
                and item.get("kind") == kind
                and isinstance(item.get("data"), dict)):
            return item
    return None


def _native_change_proposal(value):
    """Merge every proposal emitted in one Agent turn without dropping earlier work."""
    envelopes = [item for item in (value if isinstance(value, list) else [])
                 if (isinstance(item, dict)
                     and item.get("protocol") == agent_tool_registry.PROTOCOL
                     and item.get("kind") == "change_proposal"
                     and isinstance(item.get("data"), dict))]
    if not envelopes:
        return None
    actions = []
    summaries = []
    for envelope in envelopes:
        data = envelope["data"]
        actions.extend(item for item in data.get("actions") or []
                       if isinstance(item, dict))
        summary = str(data.get("summary") or envelope.get("message") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
    return {
        "protocol": agent_tool_registry.PROTOCOL,
        "kind": "change_proposal",
        "message": "；".join(summaries),
        "data": {"summary": "；".join(summaries), "actions": actions,
                 "count": len(actions)},
    }


def _native_choice_from_results(value):
    envelope = _native_tool_result(value, "choice")
    if not envelope:
        return "", []
    return _native_choice_request([{"questions": envelope["data"].get("questions") or []}])


def _generate_missing_title(channel, message, reply, model, effort):
    """仅在正常首轮漏填 title 时，用同一官方 CLI 做一次兜底。"""
    adapter = model_channels.adapter_for(channel)
    prompt = ("请根据下面这段对话生成一个简洁、具体、可区分的中文会话标题。"
              "控制在 6～18 个汉字，不加引号、句号、编号或‘关于’；只输出标题本身。\n\n"
              "用户：{}\n助手：{}".format(message[:800], reply[:800]))
    result = run_agent(adapter, prompt, execution_profile=EXECUTION_INTERNAL_ANALYSIS,
                        mode="judge", model=model,
                        reasoning_effort=effort, timeout_sec=60,
                        cwd=_assistant_workspace())
    return _clean_title(result.text)


def _normalize_capabilities(value):
    result = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").lower()
        if kind not in ("plugin", "skill", "mcp", "command"):
            continue
        ident = str(item.get("id") or item.get("name") or "").strip()[:240]
        if not ident or not re.match(r"^[\w.\-:/@ ]+$", ident, re.UNICODE):
            continue
        label = str(item.get("label") or item.get("name") or ident).strip()[:120]
        trigger = str(item.get("trigger_name") or "").strip()[:160]
        if trigger and not re.match(r"^[\w.\-:/@]+$", trigger, re.UNICODE):
            trigger = ""
        plugin_id = str(item.get("plugin_id") or "").strip()[:240]
        mention_id = str(item.get("mention_id") or "").strip()[:80]
        if mention_id and not re.match(r"^[A-Za-z0-9_-]+$", mention_id):
            mention_id = ""
        mention_token = "[[capability:{}]]".format(mention_id) if mention_id else ""
        result.append({"kind": kind, "id": ident, "label": label or ident,
                       "trigger_name": trigger, "plugin_id": plugin_id,
                       "mention_id": mention_id, "mention_token": mention_token})
        if len(result) >= 12:
            break
    return result


def _capability_context(capabilities, provider):
    if not capabilities:
        return ("# 本轮显式能力\n用户没有为本轮消息指定重点能力。"
                "这不限制 Agent：仍可按任务需要使用当前渠道已安装并启用的插件、Skills、MCP，"
                "以及 CLI 原生的文件、终端、搜索等工具。")
    lines = ["# 本轮显式能力", "用户为本轮消息指定了以下重点能力。"
             "优先按标记理解它们负责的任务范围，但这不是能力白名单；"
             "完成任务所需时仍可使用当前渠道其他已安装并启用的能力及 CLI 原生工具："]
    for item in capabilities:
        kind, label = item["kind"], item["label"]
        mention = item.get("mention_token")
        prefix = (mention + " = ") if mention else ""
        if kind == "skill":
            trigger = item.get("trigger_name") or item["id"].split(":")[-1]
            token = model_channels.provider_info(provider)["command_prefix"] + trigger
            lines.append("- {}Skill {}（显式触发：{}）".format(prefix, label, token))
        elif kind == "plugin":
            lines.append("- {}官方扩展 {}（ID：{}）".format(prefix, label, item["id"]))
        elif kind == "mcp":
            lines.append("- {}MCP {}（使用已配置的连接）".format(prefix, label))
        elif item["id"] == "plan":
            lines.append("- 计划模式：只分析并给出可执行计划，不调用任何 RunTeams 提案或写入工具。")
    if any(item.get("mention_token") for item in capabilities):
        lines.append("上述 [[capability:...]] 标记出现在用户原句的具体位置；按标记前后的语义判断该能力负责的任务范围，不要将多个能力的分工混在一起。")
    return "\n".join(lines)


def _channel_capability_context(channel):
    """Expose a bounded, read-only view of the capabilities inherited by Agent Chat."""
    try:
        inventory = runtime_capabilities.inventory(
            channel, workspace_root=_assistant_workspace())
    except Exception as exc:
        return ("# 渠道能力清单\n能力清单暂时无法读取（{}）。"
                "不要据此断言某项能力未安装；可使用当前 Agent 的原生文件和终端工具继续检查。"
                .format(str(exc)[:160]))

    plugins = [item for item in inventory.get("plugins") or []
               if item.get("installed") and item.get("enabled", True)]
    skills = [item for item in inventory.get("skills") or []
              if item.get("enabled", True)]
    mcp_servers = [item for item in inventory.get("mcp_servers") or []
                   if item.get("enabled", True)]

    def names(items, keys, limit):
        values = []
        for item in items:
            value = next((str(item.get(key) or "").strip() for key in keys
                          if str(item.get(key) or "").strip()), "")
            if value and value not in values:
                values.append(value[:120])
        shown = values[:limit]
        suffix = "（另有 {} 项）".format(len(values) - limit) if len(values) > limit else ""
        return "、".join(shown) + suffix if shown else "无"

    runtime = inventory.get("runtime") or {}
    runtime_state = "可用" if runtime.get("installed") else "不可用"
    lines = [
        "# 当前渠道能力清单（只读快照）",
        "运行时：{}；以下能力由 Agent Chat 默认继承，不要求用户逐项勾选。".format(runtime_state),
        "- 已安装并启用的插件：{}".format(names(plugins, ("display_name", "name", "id"), 30)),
        "- 已启用的 Skills：{}".format(names(skills, ("name", "id"), 40)),
        "- 已配置并启用的 MCP：{}".format(names(mcp_servers, ("name",), 30)),
        "插件、Skill 与 MCP 是不同类型；回答是否安装或配置时必须按清单类型准确表述。",
        "清单不完整或需要确认本机状态时，直接使用原生文件/终端能力检查，"
        "不要要求用户替 Agent 去扩展页面搜索。未安装能力不得静默安装；安装、移除或扩大系统权限仍需用户确认。",
    ]
    return "\n".join(lines)


# 有分量的方案才走"先预览再确认"(产品级闸,不是 agent 工具):动作多或含不可逆操作
_DESTRUCTIVE = {"delete_automation"}
_CONFIRM_BEFORE_APPLY = {"create_pipeline", "update_pipeline", "create_task",
                         "create_employee_task",
                         "upsert_automation", "create_document", "update_document"}


def _consequential(actions):
    return (len(actions) >= 3
            or any((a or {}).get("op") in _DESTRUCTIVE for a in actions)
            or any((a or {}).get("op") in _CONFIRM_BEFORE_APPLY for a in actions))


def apply_actions(actions, action_context=None):
    """Deterministically apply only the current core product action contract."""
    applied, run_cards, focus_pid = [], [], None
    for a in (actions or []):
        try:
            summary, eff = _apply_core(a, action_context)
            applied.append(summary)
            if eff:
                if eff.get("focus_pid"):
                    focus_pid = eff["focus_pid"]
                if eff.get("run_card"):
                    run_cards.append(eff["run_card"])
        except Exception as e:
            applied.append("✗ 动作失败:{}".format(str(e)[:140]))
    return applied, run_cards, focus_pid


def _conversation_context_guidance(config):
    """Keep product workflow guidance out of the user's visible starter message."""
    context = config.get("context") if isinstance(config, dict) else {}
    context = context if isinstance(context, dict) else {}
    context_type = str(context.get("context_type") or "general").strip()
    intent = str(context.get("intent") or "general").strip()
    if context_type == "pipeline" and intent == "create":
        return ("# 当前对话目标\n用户正在创建流水线。先理解这项工作要持续完成什么、工作从哪里进入、"
                "怎样算完成；信息足够后设计最小可运行的员工与流转。不要为了显得完整而增加岗位。"
                "涉及实际创建或修改时，先给用户看清楚方案，再按确认执行。")
    if context_type == "pipeline":
        return ("# 当前对话目标\n用户正在管理现有流水线。结合当前流水线状态判断是在排查问题、调整流程还是创建任务。"
                "优先保留有效结构，只改动实现用户目标所需的部分；修改前先说明影响。"
                "如果要创建任务，必须先读取流水线首个岗位的已发布员工详情，核对其 input interface、程序门禁和必需的 context/inputs；"
                "只要用户目标没有提供这些必需字段，就先通过 runteams_request_choice 聚焦询问或说明缺口，禁止提交一个已知会在第一岗立即 needs_human/blocked 的任务提案。"
                "任务提案中的 objective、context、inputs 和 acceptance 必须与该岗位契约逐项对应。")
    if context_type == "automation" and intent == "create":
        return ("# 当前对话目标\n用户正在创建自动化。理解要重复完成的工作和运行时间，"
                "把它整理成简洁、可独立执行的提示与计划；只有关键时间信息缺失时才追问。")
    if context_type == "automation" and intent == "run":
        return ("# 当前对话目标\n这是一次无人值守的自动化运行。读取所需事实并直接完成计划内工作；"
                "提交变更提案后 RunTeams 会在本次运行中自动应用，不要要求用户再次确认，"
                "最终回复应按已实际提交的结果表述。没有符合条件的结果时诚实说明，不创建占位数据。")
    if context_type == "automation":
        return ("# 当前对话目标\n用户正在查看一次自动化运行。优先解释本次结果和问题；"
                "只有用户明确要求时才调整后续自动化配置。")
    if context_type == "worker" and intent in ("chat", "work"):
        worker_name = str(context.get("worker_name") or context.get("label") or "当前员工 Bot").strip()
        return ("# 当前对话目标\n用户正在和员工 Bot「{}」对话，重点是了解它负责的工作、"
                "工作方式、近期结果，或直接交给它一项工作。先使用当前员工上下文核实职责、输入、"
                "交付和工作记录，再回答或执行；不要把这次对话误当成修改员工配置的设计会话。"
                "只有用户明确要求改变职责、流程或能力时，才说明将转入团队里的员工调整流程。".format(worker_name))
    return ("# 当前对话目标\n用户可能要创建员工、搭建流水线，或直接完成一项工作。"
            "如果是创建员工，先明确职责、输入、交付和完成标准；如果是搭建流水线，先明确持续目标、入口和完成条件；"
            "如果是一次性工作，信息足够后直接研究、分析、创作或执行。只在缺失信息会实质改变结果时追问。")


def run_chat(message, history, config=None, attachments=None, chat_id=None, on_activity=None,
             capabilities=None, auto_apply=False, cancel_event=None, action_context=None,
             view_context=None):
    config = config or {}
    attachments = attachments or []
    capabilities = _normalize_capabilities(capabilities)
    # Agent Chat is the user's interactive top-level agent.  It inherits the
    # selected channel's native capabilities by default; capability mentions
    # scope a request but are not a global kill switch.  Worker isolation is
    # handled separately by agent_sessions and remains unchanged.
    extensions_enabled = True
    view_context = view_context if isinstance(view_context, dict) else {}
    scope_id = config.get("scope_pipeline_id") or view_context.get("pipeline_id")
    scope = _core_service().pipeline(scope_id) if scope_id else None
    scope_context = ("# 对话作用范围\n当前默认流水线是「{}」。用户没有明说其他流水线时，"
                     "流水线级动作的 pipeline 填「{}」；用户明确指定其他流水线时按用户指定操作。".format(
                         scope["name"], scope["name"])
                     if scope else
                     "# 对话作用范围\n全部核心流水线。无法唯一确定目标时不要猜测或执行，请用户说明。")
    conversation = config.get("context") if isinstance(config.get("context"), dict) else {}
    bound_pipeline_id = conversation.get("pipeline_id") or config.get("scope_pipeline_id")
    view_pipeline_id = view_context.get("pipeline_id")
    if scope and bound_pipeline_id and (not view_pipeline_id or str(view_pipeline_id) != str(bound_pipeline_id)):
        # 专用会话或已选择流水线的普通会话以固定上下文为准，避免右侧正在查看的
        # 其他页面偷偷改变 Agent 的操作目标。
        view_context = {}
    surface = str(view_context.get("surface") or "").strip()[:40]
    label = str(view_context.get("label") or "").strip()[:160]
    identity = ", ".join("{}={}".format(key, view_context.get(key)) for key in (
        "pipeline_id", "node_id", "worker_id", "card_id", "run_id")
                         if view_context.get(key) not in (None, ""))
    view_context_text = (("# 当前页面\n用户发送这条消息时正在查看「{}」（页面类型：{}{}）。"
                          "这是环境感知上下文：没有固定对象且用户没有另行指定时，可把它作为本轮默认目标；"
                          "用户明确表达和固定对象始终优先。".format(
                              label, surface, ("；" + identity) if identity else "")) if surface and label else
                         "# 当前页面\n本轮没有提供可用的页面上下文；只依据对话作用范围、固定对象和用户表述判断目标。")
    channel = store.get_channel(config.get("channel_id")) or store.get_default_channel()
    if not channel or not channel.get("enabled"):
        raise RuntimeError("会话选择的模型渠道不可用")
    import chat_attachments
    persisted_codex_thread = (config.get("runtime_thread_id")
                              if (channel.get("provider") == "codex"
                                  and config.get("runtime_provider") == "codex") else "")
    history_text, history_images = chat_attachments.history_context(chat_id, history)
    if persisted_codex_thread:
        # 官方 thread 已持有前序 turn；重复注入本地历史会让同一句话进入上下文两次。
        history_text, history_images = "", []
    attachment_context, image_paths = ("", [])
    if attachments:
        attachment_context, image_paths = chat_attachments.prompt_context(chat_id, attachments)
    image_paths = list(dict.fromkeys(history_images + image_paths))
    build_workspace = _assistant_workspace()
    if (channel.get("provider") != "codex" and chat_id
            and config.get("runtime_thread_id")):
        # 中途切到其他厂商后，旧 Codex thread 不再代表完整本地对话；下次
        # 切回 Codex 时新建官方 thread，并从本地历史重新建立上下文。
        store.set_chat_runtime(chat_id, "", "")
    extension_context = (_capability_context(capabilities, channel.get("provider")) + "\n\n" +
                         _channel_capability_context(channel))
    needs_title = bool(chat_id and config.get("title_source") == "pending")
    conversation_context = _conversation_context_guidance(config)
    bot_projection = None
    employee_bot_release = None
    employee_bot_chat = (str(conversation.get("context_type") or "").strip() == "worker" and
                          str(conversation.get("intent") or "chat").strip() in {"chat", "work"})
    if employee_bot_chat:
        try:
            employee_id = int(config.get("employee_id") or
                              conversation.get("target_employee_id") or
                              conversation.get("target_worker_id") or
                              conversation.get("worker_id"))
        except (TypeError, ValueError):
            employee_id = 0
        if employee_id:
            try:
                employee = _core_service().employee(employee_id) or {}
                employee_bot_release = employee.get("active_release") or {}
                # A Bot chat binds the employee, not a permanent release. Keep
                # the latest effective release as a compact listing/diagnostic
                # value; historical turns and WorkflowRuns retain provenance.
                store.set_chat_employee_release(
                    chat_id, employee_bot_release.get("id"),
                    employee_bot_release.get("digest", ""))
                projection = bot_context.build(
                    _core_service(), employee_id,
                    scope_type=config.get("scope_type") or conversation.get("scope_type") or
                    ("pipeline" if bound_pipeline_id else "global"),
                    pipeline_id=bound_pipeline_id,
                    run_id=config.get("scope_run_id") or conversation.get("run_id"),
                    release_id=employee_bot_release.get("id"),
                )
                bot_projection = projection
                conversation_context += "\n\n" + bot_context.prompt_text(projection)
            except (TypeError, ValueError):
                # A Bot can still answer from its durable conversation if a
                # deleted/invalid scope is encountered; do not turn a read
                # projection failure into a generic provider failure.
                conversation_context += (
                    "\n\n# 当前员工 Bot 事实\n暂时无法读取关联工作记录；请明确说明需要查看的运行或任务。")
    state_context = ("# 当前状态\n" + _core_state_context()) if not employee_bot_chat else (
        "# 当前状态\n当前为员工 Bot 会话，仅使用上方绑定员工的只读事实投影；"
        "不要主动枚举或读取无关员工、流水线或自动化。")
    instructions = (CORE_SYS + "\n\n" + scope_context + "\n\n" + view_context_text + "\n\n" + conversation_context + "\n\n" + extension_context +
                    "\n\n" + state_context +
                    (("\n\n# 已有对话历史（仅用于建立新的官方会话）\n" + history_text)
                     if history_text else "") +
                    (("\n\n" + attachment_context) if attachment_context else "") +
                    "\n\n最终直接回复用户；交互和产品改动使用对应原生工具。")
    prompt = instructions + "\n\n# 用户这句话\n" + message
    adapter = model_channels.adapter_for(channel)
    if hasattr(adapter, "configure_requirements"):
        plugin_requirements, mcp_requirements = [], []
        for item in capabilities:
            if item["kind"] == "plugin":
                plugin_requirements.append(item["id"])
            elif item["kind"] == "skill":
                plugin_requirements.append(item.get("plugin_id") or "selected-skill")
            elif item["kind"] == "mcp":
                mcp_requirements.append(item["id"])
        adapter.configure_requirements({"inherit_native": True,
                                        "plugins": plugin_requirements,
                                        "mcp_servers": mcp_requirements})
    model, effort = model_channels.normalize_selection(
        channel, config.get("model"), config.get("reasoning_effort"))
    agent_timeout = 900
    extra_args = []
    tool_context = _agent_tool_context(
        chat_id, scope_id, view_context, conversation)
    general_tools = [tool for tool in agent_tool_registry.tools()
                     if tool.name != "runteams_present_employee_draft"]
    general_tool_names = [tool.name for tool in general_tools]
    if channel.get("provider") == "codex":
        for path in image_paths:
            extra_args += ["--image", path]
    elif channel.get("provider") == "claude-code":
        extra_args += _claude_agent_tool_args(tool_context, general_tool_names)
    official_title = ""
    runtime_thread_id = ""
    native_input_requests = []
    native_tool_results = []
    if channel.get("provider") == "codex" and chat_id:
        result = codex_threads.run_turn(
            channel, persisted_codex_thread, message, instructions,
            model=model, effort=effort, cwd=build_workspace,
            image_paths=image_paths, extensions_enabled=extensions_enabled,
            timeout=agent_timeout, on_activity=on_activity,
            execution_profile=EXECUTION_USER_AGENT,
            cancel_event=cancel_event,
            tool_context=tool_context,
            tool_names=general_tool_names,
            on_thread=lambda thread_id, title: store.set_chat_runtime(
                chat_id, "codex", thread_id, title),
            on_title=lambda title: store.set_chat_official_title(chat_id, title))
        response_text = result["text"]
        official_title = result.get("title") or ""
        runtime_thread_id = result.get("thread_id") or ""
        result_meta = result.get("meta") or {}
        native_input_requests = result.get("user_input_requests") or []
        native_tool_results = result.get("native_tool_results") or []
    else:
        res = run_agent(adapter, prompt, execution_profile=EXECUTION_USER_AGENT,
                         mode="judge", model=model,
                         reasoning_effort=effort, timeout_sec=agent_timeout,
                         extra_args=extra_args, cwd=build_workspace,
                         on_activity=on_activity, cancel_event=cancel_event)
        response_text = res.text
        result_meta = res.meta or {}
        native_tool_results = result_meta.get("native_tool_results") or []
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled("运行已停止")
    native_question, native_options = _native_choice_from_results(native_tool_results)
    if not native_question:
        native_question, native_options = _native_choice_request(native_input_requests)
    native_proposal = _native_change_proposal(native_tool_results)
    reply = (response_text or "").strip() or "(无回复)"
    actions, generated_title, options, response_type = [], "", [], "message"
    if native_question and native_options:
        reply, actions, options, response_type = native_question, [], native_options, "choice"
    elif native_proposal:
        proposal_data = native_proposal["data"]
        actions = proposal_data.get("actions") or []
        options = []
        reply = reply or proposal_data.get("summary") or native_proposal.get("message")
    if needs_title and not generated_title and not official_title:
        try:
            generated_title = _generate_missing_title(
                channel, message, reply, model, effort)
        except Exception:
            generated_title = ""
    if needs_title and generated_title and not official_title and chat_id:
        if channel.get("provider") == "codex":
            if runtime_thread_id:
                try:
                    codex_threads.set_name(channel, runtime_thread_id, generated_title)
                except Exception:
                    pass
        # 优先使用同一轮回复里的标题；漏填时使用上面的同渠道官方 CLI 补偿结果。
        store.set_chat_channel_title(chat_id, generated_title)
        official_title = generated_title
    if any(item["kind"] == "command" and item["id"] == "plan" for item in capabilities):
        actions = []
        native_proposal = None
    base = {"reply": reply or "(无回复)",
            "channel_id": channel["id"], "model": model, "reasoning_effort": effort,
            "extensions_enabled": extensions_enabled, "capabilities": capabilities,
            "official_title": official_title, "cost": result_meta.get("cost_usd"),
            "options": [] if actions else options}
    if bot_projection is not None:
        base["context_refs"] = list(bot_projection.get("context_refs") or [])
    if employee_bot_release:
        base["employee_bot_release"] = {
            "id": employee_bot_release.get("id"),
            "version": employee_bot_release.get("version"),
            "digest": str(employee_bot_release.get("digest") or "")[:128],
        }
    if actions and ((native_proposal is not None) or _consequential(actions)) and not auto_apply:
        # 不落地:返回待确认提案,由外壳(UI)展示、用户点头后才调 apply-plan 执行
        base.update({"pending": True, "plan": {"actions": actions, "count": len(actions)},
                     "applied": [], "run_cards": [], "focus_pid": None})
        return base
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled("运行已停止")
    applied, run_cards, focus_pid = apply_actions(actions, action_context=action_context)
    base.update({"applied": applied, "run_cards": run_cards, "focus_pid": focus_pid})
    return base
