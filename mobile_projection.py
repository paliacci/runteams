# -*- coding: utf-8 -*-
"""Build the explicit, privacy-minimized mobile read model.

This module is the only boundary allowed to turn local RunTeams state into a
cross-device snapshot. Queries and output objects both use field allowlists;
workspace paths, prompts, run bodies, credentials, and artifact storage keys
must never be added here.
"""
import copy
import calendar
import datetime
import hashlib
import json
import os
import platform
import re
import time

import product_store as store
import attention
from runteams_core import RunTeamsCore
from runteams_core.contracts import pipeline_order


SCHEMA_VERSION = 1
MAX_PIPELINES = 50
MAX_TASKS_PER_PIPELINE = 500
MAX_RECORDS_PER_CARD = 12
MAX_WORKFLOWS = 100
MAX_ACTIVITY = 50
MAX_INTERVENTIONS = 100
MAX_DOCUMENTS_PER_CARD = 20
_DOCUMENT_READABLE_SUFFIXES = (
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".log", ".yaml", ".yml", ".xml")
_DOCUMENT_KIND_LABELS = {".md": "文档", ".markdown": "文档", ".json": "结构化数据",
                         ".csv": "表格", ".tsv": "表格", ".pdf": "PDF",
                         ".png": "图片", ".jpg": "图片", ".jpeg": "图片",
                         ".gif": "图片", ".webp": "图片", ".svg": "图片"}

_MOBILE_ENTITLEMENT_FEATURES = (
    "mobile.app", "mobile.view", "mobile.control", "mobile.push", "mobile.live_activity",
    "mobile.multi_host",
)
_MOBILE_ENTITLEMENT_LIMITS = (
    "mobile.hosts", "mobile.devices",
)

_ACTIVE_CHAIN_STATUSES = ("queued", "retry_wait", "running")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+"),
)
_ABSOLUTE_PATH = re.compile(r"(?:(?:/Users|/home)/[^\s,;]+|[A-Za-z]:\\Users\\[^\s,;]+)")
def _generated_at():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value, limit=500, fallback=""):
    text = " ".join(str(value or "").replace("\x00", " ").split())
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "[本地目录]")
    text = _ABSOLUTE_PATH.sub("[本地路径]", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[已隐藏]", text)
    return (text[:limit] if text else fallback)


def _platform_name():
    if platform.system() == "Darwin":
        return "macOS"
    if platform.system() == "Windows":
        return "Windows"
    return platform.system() or "Desktop"


def _status_label(status):
    return {
        "idle": "待运行",
        "ready": "队列中",
        "queued": "队列中",
        "waiting_retry": "等待重试",
        "retry_wait": "等待重试",
        "running": "运行中",
        "waiting": "等待处理",
        "needs_human": "等待回复",
        "needs_input": "等待回复",
        "blocked": "阻塞",
        "completed": "已完成",
        "succeeded": "已完成",
        "done": "已完成",
        "failed": "失败",
        "canceled": "已终止",
        "cancelled": "已终止",
        "interrupted": "已中断",
    }.get(status, "状态已更新")


def _record_kind(status):
    if status in ("completed", "succeeded", "done"):
        return "delivery"
    if status in ("failed", "canceled", "cancelled", "interrupted", "rejected",
                  "protocol_error", "blocked"):
        return "warning"
    if status == "running":
        return "progress"
    return "system"


def _mobile_status(state):
    return {
        "ready": "queued",
        "waiting_retry": "retry_wait",
        "needs_human": "needs_input",
        "completed": "succeeded",
        "canceled": "cancelled",
    }.get(state, state or "idle")


def _positions(workflow):
    definition = (workflow.get("snapshot_json") or {}).get("definition") or {}
    positions = definition.get("positions") or []
    try:
        order = pipeline_order(definition)
    except (TypeError, ValueError):
        order = [str(item.get("key")) for item in positions if item.get("key")]
    return positions, order


def _position(workflow, key):
    positions, _order = _positions(workflow)
    return next((item for item in positions if item.get("key") == key), {})


def _current_employee_runs(workflow):
    floor = 0
    for event in workflow.get("events") or []:
        if event.get("type") != "workflow.task_recompiled":
            continue
        data = event.get("data_json") or {}
        floor = max(floor, int(data.get("after_employee_run_id") or 0))
    return [item for item in workflow.get("employee_runs") or []
            if int(item.get("id") or 0) > floor]


def _current_position_key(workflow):
    positions, order = _positions(workflow)
    if not order:
        return "current"
    employee_runs = _current_employee_runs(workflow)
    if employee_runs:
        latest = employee_runs[-1]
        if latest.get("state") != "completed" or workflow.get("state") in (
                "completed", "canceled", "failed", "blocked", "needs_human"):
            return latest.get("position_key") or order[0]
    completed = {item.get("position_key") for item in employee_runs
                 if item.get("state") == "completed"}
    return next((key for key in order if key not in completed), order[-1])


def _position_labels(workflow, position_key=None):
    position = _position(workflow, position_key or _current_position_key(workflow))
    employee = position.get("employee") or {}
    return (
        _safe_text(RunTeamsCore.position_display_name(position), 120, "当前岗位"),
        _safe_text(employee.get("name"), 120, "RunTeams 员工"),
    )


def _workflow_progress(workflow):
    _positions_value, order = _positions(workflow)
    if not order:
        return None
    if workflow.get("state") == "completed":
        return 1.0
    completed = {item.get("position_key") for item in _current_employee_runs(workflow)
                 if item.get("state") == "completed"}
    return min(1.0, len(completed) / len(order))


def _result_detail(employee_run):
    output = employee_run.get("output_json") or {}
    if employee_run.get("state") in ("failed", "interrupted", "blocked"):
        return "运行未完成；详细错误仅保留在桌面端。"
    summary = output.get("summary")
    if summary:
        return _safe_text(summary, 500)
    issues = output.get("issues") if isinstance(output.get("issues"), list) else []
    if issues:
        return _safe_text("；".join(str(item) for item in issues if item), 500)
    return "岗位状态已更新，详细内容保留在桌面端。"


def _document_suffix(artifact):
    """Derive the kind from the artifact's own file name; never expose its path."""
    meta = artifact.get("meta_json") if isinstance(artifact.get("meta_json"), dict) else {}
    name = str(meta.get("path") or artifact.get("name") or "")
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


def _workflow_documents(workflow):
    """Metadata only. Bodies are fetched one at a time through a signed command."""
    documents = []
    superseded = set()
    for employee_run in workflow.get("employee_runs") or []:
        for artifact in employee_run.get("artifacts") or []:
            meta = (artifact.get("meta_json")
                    if isinstance(artifact.get("meta_json"), dict) else {})
            root = meta.get("revision_of")
            if root is not None and int(root) != int(artifact["id"]):
                superseded.add(int(root))
    for employee_run in workflow.get("employee_runs") or []:
        stage, employee = _position_labels(workflow, employee_run.get("position_key"))
        for artifact in employee_run.get("artifacts") or []:
            meta = (artifact.get("meta_json")
                    if isinstance(artifact.get("meta_json"), dict) else {})
            if int(artifact["id"]) in superseded:
                continue   # 旧版本不投给手机，审批只看当前版本
            suffix = _document_suffix(artifact)
            documents.append({
                "id": "artifact:{}".format(int(artifact["id"])),
                "name": _safe_text(artifact.get("name"), 200, "产物"),
                "kind": _DOCUMENT_KIND_LABELS.get(suffix, "文件"),
                "readable": suffix in _DOCUMENT_READABLE_SUFFIXES,
                "size": int(meta.get("size") or 0),
                "position_name": stage,
                "employee_name": employee,
                "revision": int(meta.get("revision") or 1),
                "revised_by_human": str(meta.get("author") or "") == "human",
                "created_at": artifact.get("created_at"),
            })
    return documents[:MAX_DOCUMENTS_PER_CARD]


def _work_records(workflow):
    records = []
    for employee_run in reversed((workflow.get("employee_runs") or [])[-MAX_RECORDS_PER_CARD:]):
        stage, employee = _position_labels(workflow, employee_run.get("position_key"))
        status = _mobile_status(employee_run.get("state"))
        records.append({
            "id": "employee-run:{}".format(employee_run["id"]),
            "position_name": stage,
            "employee_name": employee,
            "title": _status_label(status),
            "detail": _result_detail(employee_run),
            "timestamp": employee_run.get("updated_at") or employee_run.get("created_at"),
            "kind": _record_kind(status),
            "artifact_count": len(employee_run.get("artifacts") or []),
        })
    return records


def _workflow_recent_update(workflow):
    employee_runs = workflow.get("employee_runs") or []
    if employee_runs:
        return _result_detail(employee_runs[-1])
    return _status_label(_mobile_status(workflow.get("state")))


def _workflow_task(workflow):
    snapshot = workflow.get("snapshot_json") or {}
    task = snapshot.get("task") or {}
    return {
        "id": "workflow:{}".format(workflow["id"]),
        "title": _safe_text(task.get("title"), 200, "未命名任务"),
        "summary": _workflow_recent_update(workflow),
        "status": _mobile_status(workflow.get("state")),
        "progress": _workflow_progress(workflow),
        "updated_at": workflow.get("updated_at") or workflow.get("created_at"),
        "artifact_count": sum(len(item.get("artifacts") or [])
                              for item in workflow.get("employee_runs") or []),
        "documents": _workflow_documents(workflow),
        "records": _work_records(workflow),
    }


def _pipelines(core, workflows, snapshot_version):
    employees = {item["id"]: item for item in core.employee_catalog()}
    workflows_by_pipeline = {}
    for workflow in workflows:
        pipeline_id = int((workflow.get("snapshot_json") or {}).get("pipeline_id") or 0)
        workflows_by_pipeline.setdefault(pipeline_id, []).append(workflow)
    result = []
    for item in core.pipeline_catalog()[:MAX_PIPELINES]:
        definition = item.get("definition_json") or {}
        tasks_by_position = {position.get("key"): []
                             for position in definition.get("positions") or []}
        for workflow in workflows_by_pipeline.get(int(item["id"]), [])[:MAX_TASKS_PER_PIPELINE]:
            key = _current_position_key(workflow)
            if key not in tasks_by_position and tasks_by_position:
                key = next(iter(tasks_by_position))
            tasks_by_position.setdefault(key, []).append(_workflow_task(workflow))
        positions = []
        for position in definition.get("positions") or []:
            employee = employees.get(position.get("employee_id")) or {}
            draft = employee.get("draft_json") or {}
            positions.append({
                "id": "position:{}:{}".format(item["id"], position.get("key")),
                "name": _safe_text(RunTeamsCore.position_display_name(position), 120, "未命名岗位"),
                "employee_name": _safe_text(employee.get("name"), 120, "RunTeams 员工"),
                "summary": _safe_text(draft.get("role"), 200, "由已发布员工处理当前阶段"),
                "tasks": tasks_by_position.get(position.get("key"), []),
            })
        result.append({
            "id": "pipeline:{}".format(item["id"]),
            "name": _safe_text(item.get("name"), 160, "未命名流水线"),
            "revision": "snapshot-{}".format(snapshot_version),
            "access": "read_only",
            "positions": positions,
        })
    return result


def _run_events(workflow):
    events = []
    for employee_run in (workflow.get("employee_runs") or [])[-MAX_RECORDS_PER_CARD:]:
        stage, employee = _position_labels(workflow, employee_run.get("position_key"))
        status = _mobile_status(employee_run.get("state"))
        events.append({
            "id": "employee-run:{}".format(employee_run["id"]),
            "title": _status_label(status),
            "detail": "{} · {}".format(employee, stage),
            "timestamp": employee_run.get("updated_at") or employee_run.get("created_at"),
            "kind": _record_kind(status),
        })
    if not events:
        stage, employee = _position_labels(workflow)
        status = _mobile_status(workflow.get("state"))
        events.append({
            "id": "workflow:{}:{}".format(workflow["id"], status),
            "title": _status_label(status),
            "detail": "{} · {}".format(employee, stage),
            "timestamp": workflow.get("updated_at") or workflow.get("created_at"),
            "kind": _record_kind(status),
        })
    return events


def _workflows(workflows):
    result = []
    for workflow in workflows[:MAX_WORKFLOWS]:
        snapshot = workflow.get("snapshot_json") or {}
        task = snapshot.get("task") or {}
        position_key = _current_position_key(workflow)
        stage, employee = _position_labels(workflow, position_key)
        status = _mobile_status(workflow.get("state"))
        terminal = status in ("succeeded", "failed", "cancelled", "blocked")
        result.append({
            "id": "workflow:{}".format(workflow["id"]),
            "position_id": "{}:{}".format(snapshot.get("pipeline_id") or 0, position_key),
            "task_title": _safe_text(task.get("title"), 200, "未命名任务"),
            "pipeline_name": _safe_text(snapshot.get("pipeline_name"), 160, "未命名流水线"),
            "employee_name": employee,
            "position_name": stage,
            "status": status,
            "progress": _workflow_progress(workflow),
            "recent_update": _workflow_recent_update(workflow),
            "started_at": workflow.get("created_at") or workflow.get("updated_at"),
            "finished_at": workflow.get("updated_at") if terminal else None,
            "artifact_count": sum(len(item.get("artifacts") or [])
                                  for item in workflow.get("employee_runs") or []),
            "events": _run_events(workflow),
        })
    return result


def _interventions(core, workflows=None):
    documents_by_workflow = {}
    for workflow in workflows or []:
        documents_by_workflow[int(workflow["id"])] = _workflow_documents(workflow)
    result = []
    for item in attention.catalog(core=core, limit=MAX_INTERVENTIONS):
        actions = [
            {"id": action["id"], "label": _safe_text(action["label"], 80), "style": action["style"]}
            for action in item.get("actions", [])
            if action.get("id") != "edit_continue"
        ]
        result.append(
            {
                "id": str(item["id"]),
                "automation_id": (int(item["automation_id"])
                                  if item.get("automation_id") is not None else None),
                "workflow_id": (int(item["workflow_id"])
                                if item.get("workflow_id") is not None else None),
                "pipeline_id": (int(item["pipeline_id"])
                                if item.get("pipeline_id") is not None else None),
                "target_type": item["target_type"],
                "kind": item["kind"],
                "title": _safe_text(item["title"], 160, "待你处理"),
                "reason": _safe_text(item["reason"], 500, "任务需要人工处理。"),
                "context": _safe_text(item["context"], 800),
                "recovery": _safe_text(item["recovery"], 500),
                "pipeline_name": _safe_text(item["pipeline_name"], 160, "未命名流水线"),
                "position_name": _safe_text(item["node_name"], 120, "当前岗位"),
                "task_title": _safe_text(item["card_title"], 200, "未命名任务"),
                "attempt_count": item.get("attempt_count"),
                "artifact_count": int(item.get("artifact_count") or 0),
                "documents": documents_by_workflow.get(
                    int(item["workflow_id"]) if item.get("workflow_id") is not None else 0, []),
                "created_at": item["created_at"],
                "actions": actions,
            }
        )
    return result


def _activity(workflows):
    rows = []
    for workflow in workflows:
        snapshot = workflow.get("snapshot_json") or {}
        task = snapshot.get("task") or {}
        employee_runs = workflow.get("employee_runs") or []
        latest = employee_runs[-1] if employee_runs else None
        position_key = ((latest or {}).get("position_key") or
                        _current_position_key(workflow))
        stage, employee = _position_labels(workflow, position_key)
        status = _mobile_status((latest or {}).get("state") or workflow.get("state"))
        rows.append({
            "id": "activity:workflow:{}".format(workflow["id"]),
            "title": "{} · {}".format(employee, _status_label(status)),
            "detail": "{} · {}".format(
                _safe_text(task.get("title"), 200, "未命名任务"), stage),
            "pipeline_name": _safe_text(snapshot.get("pipeline_name"), 160, "未命名流水线"),
            "timestamp": ((latest or {}).get("updated_at") or workflow.get("updated_at")
                          or workflow.get("created_at")),
            "kind": _record_kind(status),
        })
    rows.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return rows[:MAX_ACTIVITY]


def build_dashboard_snapshot(app_version="开发版", generated_at=None, snapshot_version=None,
                             account=None, host=None):
    """Return a mobile_dashboard_v1 object containing only approved fields."""
    generated_at = generated_at or _generated_at()
    snapshot_version = int(snapshot_version if snapshot_version is not None else time.time() * 1000)
    safe_account = {
        "name": _safe_text((account or {}).get("name"), 120, "RunTeams 用户"),
        "email": _safe_text((account or {}).get("email"), 200),
        "plan": _safe_text((account or {}).get("plan"), 40, "local"),
    }
    entitlement = (account or {}).get("entitlements") or {}
    if entitlement:
        safe_account["entitlements"] = {
            "schema_version": int(entitlement.get("schema_version") or 1),
            "revision": max(0, int(entitlement.get("revision") or 0)),
            "plan": _safe_text(entitlement.get("plan"), 20, "free"),
            "granted_plan": _safe_text(entitlement.get("granted_plan"), 20, "free"),
            "display_name": _safe_text(entitlement.get("display_name"), 40, "Free"),
            "status": _safe_text(entitlement.get("status"), 20, "active"),
            "source": _safe_text(entitlement.get("source"), 20, "default"),
            "is_active": bool(entitlement.get("is_active")),
            "starts_at": entitlement.get("starts_at"),
            "expires_at": entitlement.get("expires_at"),
            "updated_at": entitlement.get("updated_at") or generated_at,
            "features": {
                key: bool((entitlement.get("features") or {}).get(key, False))
                for key in _MOBILE_ENTITLEMENT_FEATURES
            },
            "limits": {
                key: max(0, int((entitlement.get("limits") or {}).get(key, 0)))
                for key in _MOBILE_ENTITLEMENT_LIMITS
            },
        }
    safe_host = {
        "name": _safe_text((host or {}).get("name"), 120, "这台电脑"),
        "platform": _safe_text((host or {}).get("platform"), 40, _platform_name()),
        "is_online": bool((host or {}).get("is_online", True)),
        "last_seen_at": (host or {}).get("last_seen_at") or generated_at,
        "version": _safe_text((host or {}).get("version"), 40, app_version),
    }
    core = RunTeamsCore(store.core_data_root())
    workflows = core.workflow_catalog(max(MAX_WORKFLOWS, MAX_TASKS_PER_PIPELINE))
    pipelines = _pipelines(core, workflows, snapshot_version)
    projected_workflows = _workflows(workflows)
    activity = _activity(workflows)
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_version": snapshot_version,
        "account": safe_account,
        "host": safe_host,
        "interventions": _interventions(core, workflows),
        "workflows": projected_workflows,
        "pipelines": pipelines,
        "activity": activity,
        "synced_at": generated_at,
    }


def snapshot_content_hash(snapshot):
    """Hash the user-visible read model while ignoring transport-only timestamps.

    A newly generated snapshot gets a fresh version and sync timestamp even when
    no pipeline state changed. Those fields (and the derived pipeline revision)
    must not turn an idle desktop into a new ciphertext upload every interval.
    """
    semantic = copy.deepcopy(snapshot)
    semantic.pop("snapshot_version", None)
    semantic.pop("synced_at", None)
    semantic.get("host", {}).pop("last_seen_at", None)
    for pipeline in semantic.get("pipelines", []):
        pipeline.pop("revision", None)
    canonical = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_push_state(snapshot):
    """Return local-only opaque IDs needed to detect important transitions."""
    return {
        "attention": sorted(
            str(item["id"]) for item in snapshot.get("interventions", [])
        ),
        "completed": sorted(
            str(item["id"]) for item in snapshot.get("workflows", []) if item.get("status") == "succeeded"
        ),
        "failed": sorted(
            str(item["id"]) for item in snapshot.get("workflows", []) if item.get("status") == "failed"
        ),
        "live_schema": 3,
        "live": {
            str(item["id"]): {
                "status": str(item.get("status") or "running"),
                "started_at": _epoch_seconds(item.get("started_at")),
                "position_id": str(item.get("position_id") or "unknown"),
                "pipeline_name": str(item.get("pipeline_name") or ""),
                "position_name": str(item.get("position_name") or ""),
            }
            for item in snapshot.get("workflows", [])
            if item.get("status") in _ACTIVE_CHAIN_STATUSES
        },
    }


def encode_push_state(state):
    return json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def new_push_events(previous_json, current_state):
    """Coalesce new noteworthy objects into at most one event per kind."""
    if not previous_json:
        return []
    try:
        previous = json.loads(previous_json)
    except (TypeError, ValueError):
        return []
    events = []
    for kind in ("attention", "failed", "completed"):
        new_ids = sorted(set(current_state.get(kind, [])) - set(previous.get(kind, [])))
        if new_ids:
            events.append({"kind": kind, "object_ids": new_ids})
    return events


def new_live_activity_events(previous_json, current_state, snapshot):
    """Return one host overview transition; plaintext rows stay local until encryption."""
    if not previous_json:
        return []
    try:
        previous = json.loads(previous_json)
    except (TypeError, ValueError):
        return []
    before = previous.get("live") or {}
    after = current_state.get("live") or {}
    runs = {str(item.get("id")): item for item in snapshot.get("workflows", [])}
    upgraded = int(previous.get("live_schema") or 1) < 3
    if not upgraded and before == after:
        return []

    active_ids = set(after)
    newly_terminal_ids = set(before) - active_ids
    priority = {
        "attention": 0, "failed": 1, "running": 2, "queued": 3,
        "retry_wait": 4, "completed": 5, "cancelled": 6,
    }
    working_statuses = {"running"}
    position_items = {}
    for object_id in sorted(active_ids):
        run = runs.get(object_id) or {}
        raw_status = str(run.get("status") or (after.get(object_id) or {}).get("status") or "cancelled")
        if raw_status not in working_statuses:
            continue
        position_id = str(run.get("position_id") or "unknown")
        group_key = position_id
        updated_at = _epoch_seconds(
            ((run.get("events") or [{}])[0]).get("timestamp")
            or run.get("finished_at") or run.get("started_at")
        )
        existing = position_items.get(group_key)
        if existing:
            existing["task_count"] += 1
            existing["updated_at"] = max(existing["updated_at"], updated_at)
            if priority.get(raw_status, 10) < priority.get(existing["status"], 10):
                existing["status"] = raw_status
            continue
        position_items[group_key] = {
            "object_id": "position:{}".format(position_id),
            "kind": "position",
            "status": raw_status,
            "pipeline_name": _safe_text(run.get("pipeline_name"), 40, "未命名流水线"),
            "position_name": _safe_text(run.get("position_name"), 40, "当前岗位"),
            "task_count": 1,
            "updated_at": updated_at,
        }

    terminal_items = []
    for object_id in sorted(newly_terminal_ids):
        run = runs.get(object_id) or {}
        raw_status = str(run.get("status") or "cancelled")
        if raw_status == "succeeded":
            status = "completed"
        elif raw_status in ("failed", "blocked"):
            status = "failed"
        else:
            status = "cancelled"
        terminal_items.append({
            "object_id": "terminal:{}".format(object_id),
            "kind": "terminal",
            "status": status,
            "updated_at": _epoch_seconds(
                ((run.get("events") or [{}])[0]).get("timestamp")
                or run.get("finished_at") or run.get("started_at")
            ),
        })

    items = list(position_items.values()) + terminal_items
    items.sort(key=lambda item: (priority.get(item["status"], 10), -item["updated_at"]))
    active_statuses = [str(value.get("status") or "running") for value in after.values()]
    overall = (
        min(active_statuses, key=lambda value: priority.get(value, 10))
        if active_statuses else (items[0]["status"] if items else "cancelled")
    )
    started = min(
        [int(value.get("started_at") or time.time()) for value in after.values()]
        or [int(time.time())]
    )
    return [{
        "operation": "start" if not before and bool(after) else "update",
        "object_id": "overview-v2",
        "status": overall,
        "started_at": started,
        "items": items,
        "active_count": len(active_ids),
    }]


def _epoch_seconds(value):
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if text:
        normalized = text.rstrip("Z").split(".")[0]
        pattern = "%Y-%m-%dT%H:%M:%S" if "T" in normalized else "%Y-%m-%d %H:%M:%S"
        try:
            return int(calendar.timegm(time.strptime(normalized, pattern)))
        except (TypeError, ValueError, OverflowError):
            pass
    return int(time.time())


def notification_target_ref(host_id, kind, object_id):
    """Return an opaque route reference that mobile can recompute after decrypting.

    Host ID scopes local object identifiers so APNs and the relay never receive
    the plaintext intervention/run ID used inside a desktop database.
    """
    identity = "{}|{}|{}".format(host_id, kind, object_id)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
