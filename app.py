#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RunTeams.ai 本地服务 —— 有向图模型 + 数据驱动路由 + 按需自动流转。

启动:  python3 app.py   →  http://127.0.0.1:8791
"""
import json
import io
import mimetypes
import os
import re
import runpy
import signal
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import sys

import account_auth
import agent_stream
import app_update
import employee_sessions
import chat
import chat_attachments
import codex_threads
import core_api
import worker_avatars
import attention
import automation_store as automations
import bot_context
import model_channels
import mobile_commands
import mobile_projection
import local_database
import runtime_capabilities
import run_statistics
import relay_sync
import scheduler
from errors import Cancelled
import product_store as store
import app_secrets

# 只读资源(web/):打包后在 _MEIPASS,开发时在代码旁。
RES = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RES, "web")
PORT = int(os.environ.get("RUNTEAMS_PORT", "8791"))
def _app_version():
    configured = (os.environ.get("RUNTEAMS_VERSION") or "").strip()
    if configured:
        return configured
    try:
        with open(os.path.join(RES, "VERSION"), encoding="utf-8") as version_file:
            bundled = version_file.read().strip()
            if bundled:
                return bundled
    except OSError:
        pass
    return "0.1.0"


APP_VERSION = _app_version()
API_COMPAT_VERSION = 14
_CHAT_TURN_LOCK = threading.Lock()
_CHAT_TURN_CANCELS = {}
_CORE_CONTROLLER = None
_CHAT_TRACE_MAX_BYTES = 256 * 1024
_CHAT_TRACE_MAX_EVENTS = 800


def core_controller():
    global _CORE_CONTROLLER
    root = store.core_data_root()
    if _CORE_CONTROLLER is None or str(_CORE_CONTROLLER.root) != root:
        if _CORE_CONTROLLER is not None:
            _CORE_CONTROLLER.stop()
        def resolve_channel(provider):
            return next((item for item in store.list_channels()
                         if item.get("provider") == provider), None)

        def resolve_native_dependency(provider, plugin_id, refresh=False):
            channel = resolve_channel(provider)
            if channel is None:
                raise ValueError("模型渠道不存在")
            return runtime_capabilities.plugin_dependency(
                channel, plugin_id, refresh=refresh)

        _CORE_CONTROLLER = core_api.CoreController(
            root, credential_names_provider=app_secrets.names,
            credential_vault_path=app_secrets.vault_path(),
            channel_resolver=resolve_channel,
            native_dependency_resolver=resolve_native_dependency)
    return _CORE_CONTROLLER


def _is_formal_chat(session):
    """Only expose conversation kinds owned by the current product model."""
    if not session:
        return False
    if session.get("kind", "general") == "general":
        return True
    return session.get("kind") == employee_sessions.SESSION_KIND


def _formal_chat_summaries():
    with _CHAT_TURN_LOCK:
        awaiting_reply_ids = set(_CHAT_TURN_CANCELS)
    items = []
    for summary in store.list_chats():
        summary = dict(summary)
        summary["awaiting_reply"] = int(summary.get("id") or 0) in awaiting_reply_ids
        try:
            context = json.loads(summary.pop("context_json", "{}") or "{}")
        except (TypeError, ValueError):
            context = {}
        summary["context"] = context if isinstance(context, dict) else {}
        if summary.get("kind", "general") == "general":
            items.append(summary)
            continue
        if _is_formal_chat(store.get_chat(summary.get("id"))):
            items.append(summary)
    return items


def _bot_conversation_summaries():
    """Return one authoritative conversation summary for every active Bot."""
    employees = core_controller().core.employee_catalog()
    latest = {}
    for chat_summary in _formal_chat_summaries():
        if chat_summary.get("kind", "general") != "general":
            continue
        context = chat_summary.get("context") or {}
        intent = str(context.get("intent") or "")
        if intent not in {"chat", "work"} and chat_summary.get("subject_type") != "employee":
            continue
        try:
            employee_id = int(chat_summary.get("employee_id") or
                              context.get("target_employee_id") or
                              context.get("target_worker_id") or
                              context.get("worker_id") or 0)
        except (TypeError, ValueError):
            employee_id = 0
        if not employee_id or employee_id in latest:
            continue
        latest[employee_id] = chat_summary

    bots = []
    for employee in employees:
        employee_id = int(employee.get("id") or 0)
        chat = latest.get(employee_id)
        last_text = ""
        last_at = ""
        if chat:
            last_text = (chat.get("last_bot_message_text") or
                         chat.get("last_message_text") or "")
            last_at = (chat.get("last_bot_message_at") or
                       chat.get("last_message_at") or "")
        bots.append({
            "employee_id": employee_id,
            "name": employee.get("name") or "未命名员工",
            "avatar": employee.get("avatar") or "",
            "conversation_id": chat.get("id") if chat else None,
            "last_message": last_text,
            "last_message_at": last_at,
            "has_conversation": bool(chat),
            "release_id": (chat.get("employee_release_id") if chat else
                            (employee.get("active_release") or {}).get("id")),
            "release_digest": (chat.get("employee_release_digest") if chat else
                                (employee.get("active_release") or {}).get("digest", "")),
        })
    return {"bots": bots}


def _core_pipeline_exists(pipeline_id):
    return core_controller().core.pipeline(pipeline_id) is not None


def _begin_chat_turn(chat_id):
    cancel_event = threading.Event()
    with _CHAT_TURN_LOCK:
        if int(chat_id) in _CHAT_TURN_CANCELS:
            return None
        _CHAT_TURN_CANCELS[int(chat_id)] = cancel_event
    return cancel_event


def _end_chat_turn(chat_id, cancel_event):
    with _CHAT_TURN_LOCK:
        if _CHAT_TURN_CANCELS.get(int(chat_id)) is cancel_event:
            _CHAT_TURN_CANCELS.pop(int(chat_id), None)


def _cancel_chat_turn(chat_id):
    with _CHAT_TURN_LOCK:
        cancel_event = _CHAT_TURN_CANCELS.get(int(chat_id))
    if cancel_event is None:
        return False
    cancel_event.set()
    return True


def _new_chat_trace_record():
    return {"started": time.monotonic(), "events": [], "size": 0, "truncated": False}


def _record_chat_trace(record, event_type, payload):
    """Keep the visible Agent work stream small enough to persist with the reply."""
    if not record or not isinstance(payload, dict):
        return
    if event_type == "agent_event" and payload.get("kind") in (
            "reply_delta", "reasoning_delta", "plan_delta"):
        return
    item = {"type": event_type}
    if event_type == "agent_event":
        item["event"] = payload
    else:
        item.update(payload)
    try:
        encoded = json.dumps(item, ensure_ascii=False)
    except (TypeError, ValueError):
        return
    if len(encoded) > 32768:
        item = json.loads(encoded)
        target = item.get("event") if event_type == "agent_event" else item
        for key in ("delta", "output", "detail", "message"):
            if isinstance(target.get(key), str) and len(target[key]) > 16000:
                target[key] = target[key][-16000:]
        encoded = json.dumps(item, ensure_ascii=False)
    size = len(encoded.encode("utf-8"))
    if (len(record["events"]) >= _CHAT_TRACE_MAX_EVENTS or
            record["size"] + size > _CHAT_TRACE_MAX_BYTES):
        record["truncated"] = True
        return
    record["events"].append(item)
    record["size"] += size


def _chat_message_metadata(record, status="completed", result=None):
    result = result if isinstance(result, dict) else {}
    trace = {
        "version": 1,
        "events": list((record or {}).get("events") or []),
        "duration_sec": max(0, round(time.monotonic() - (record or {}).get(
            "started", time.monotonic()))),
        "complete": True,
        "cancelled": status == "cancelled",
        "failed": status == "failed",
        "truncated": bool((record or {}).get("truncated")),
    }
    metadata = {"trace": trace}
    if result.get("options"):
        metadata["options"] = result["options"]
    if result.get("pending") and result.get("plan"):
        metadata["pending"] = True
        metadata["plan"] = result["plan"]
    if isinstance(result.get("health"), dict):
        metadata["health"] = result["health"]
    if isinstance(result.get("employee_bot_release"), dict):
        metadata["employee_bot_release"] = result["employee_bot_release"]
    if result.get("context_refs"):
        metadata["context_refs"] = [str(item)[:160] for item in result["context_refs"][:50]]
    if status == "failed":
        metadata["failed"] = True
    if status == "cancelled":
        metadata["stopped"] = True
    return metadata


# 职务说明解析固定用的模型:Codex 高思考(要换改这两行即可)
PARSE_MODEL = "gpt-5.6-sol"
PARSE_EFFORT = "high"
# 返工循环熔断:同一落点节点累计被"打回"(kind=back)超过这个次数,停卡转人工,
# 不再自动往返。审查↔编码这类循环若不设上限会无限 ping-pong(实测曾 40 次/3 天)。
# 验收失败(delivery_status='rejected')另有 2 轮上限,二者独立。
MAX_BACK_ROUTES = 6
# 内置工具目录:有限、由 RunTeams 映射到各 Agent 运行时的原生工具(见 collaboration.runtime_args)。
# 无穷扩展走 MCP 服务与技能——它们是数据,不进这张表。
BUILTIN_TOOL_CATALOG = [
    {"id": "联网搜索", "note": "在公开网络检索资料（WebSearch）"},
    {"id": "取网页", "note": "打开并读取指定网址的内容（WebFetch）"},
    {"id": "跑脚本", "note": "在隔离工作区内执行命令与脚本（Bash）"},
    {"id": "写文件", "note": "在工作区创建或修改文件（需同时开启“可修改”）"},
]
RELAY_SYNC = relay_sync.RelaySyncWorker(APP_VERSION)
UPDATES = app_update.UpdateManager(APP_VERSION, store.data_dir())
runtime_capabilities.configure_plugin_icon_cache(store.data_dir())


def _task_tool_entry_path(raw):
    root = os.path.realpath(os.environ.get("RUNTEAMS_TASK_TOOL_ROOT") or "")
    entry = os.path.realpath(raw)
    if not root or os.path.commonpath((root, entry)) != root or not os.path.isfile(entry):
        raise SystemExit("受控任务工具入口无效")
    return entry


def _task_tool_sys_path():
    for path in reversed((os.environ.get("RUNTEAMS_TASK_TOOL_PATHS") or "").split(os.pathsep)):
        path = os.path.realpath(path)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def _run_frozen_task_tool():
    if len(sys.argv) < 3:
        raise SystemExit("受控任务工具启动参数不足")
    entry = _task_tool_entry_path(sys.argv[2])
    _task_tool_sys_path()
    sys.argv = [entry] + sys.argv[3:]
    runpy.run_path(entry, run_name="__main__")


def _run_frozen_caption_fit():
    if len(sys.argv) < 4:
        raise SystemExit("受控任务工具启动参数不足")
    browser, entry = sys.argv[2], _task_tool_entry_path(sys.argv[3])
    _task_tool_sys_path()
    import poster_render as render
    import caption_fit
    render.CHROME = browser
    sys.argv = [entry] + sys.argv[4:]
    raise SystemExit(caption_fit.main())


def reset_workspace_data(confirmation):
    """Guarded destructive reset used by the local settings flow and tests."""
    if confirmation != "清空工作区":
        raise ValueError("确认文本不匹配")
    controller = core_controller()
    was_running = controller.running
    controller.stop()
    try:
        try:
            counts = controller.core.reset_workspace()
        except Exception as exc:
            if "仍有运行中的任务" in str(exc):
                raise RuntimeError(str(exc))
            raise
        removed_chat_ids = store.reset_core_chat_context()
        for chat_id in removed_chat_ids:
            chat_attachments.remove_chat(chat_id)
    finally:
        if was_running:
            controller.start()
    return {"ok": True, "removed": counts,
            "employee_conversations": len(removed_chat_ids)}


def _purge_expired_trash():
    employee_ids = core_controller().core.purge_expired_employees()
    removed_chat_ids = []
    for employee_id in employee_ids:
        removed_chat_ids.extend(store.delete_employee_chats(employee_id))
    for chat_id in removed_chat_ids:
        chat_attachments.remove_chat(chat_id)
    return {
        "automations": automations.purge_expired_automations(),
        "pipelines": core_controller().core.purge_expired_pipelines(),
        "positions": core_controller().core.purge_expired_pipeline_positions(),
        "employees": len(employee_ids),
        "tasks": core_controller().core.purge_expired_tasks(),
        "documents": core_controller().core.purge_expired_documents(),
    }


def secret_vault_payload():
    """Return masked credentials with usage derived from immutable core facts."""
    masked = app_secrets.list_masked()
    entries = store.list_credential_entries()
    entry_by_name = {entry["name"]: entry for entry in entries}
    stored_order = [entry["name"] for entry in entries]
    usage = {}
    try:
        core = core_controller().core
        packages = {item["id"]: item for item in core.package_catalog()}
        pipelines = core.pipeline_catalog()
        for employee in core.employee_catalog():
            active_names = set(core.required_credentials(
                (employee.get("active_release") or {}).get("snapshot_json") or {}))
            draft_names = set()
            for reference in (employee.get("draft_json") or {}).get("capabilities") or []:
                package = packages.get(reference.get("package_id")) or {}
                for capability in ((package.get("manifest_json") or {}).get(
                        "capabilities") or []):
                    draft_names.update(capability.get("credentials") or [])
            pending_names = (draft_names - active_names) if employee.get("has_unpublished_changes") else set()
            positions = []
            for pipeline in pipelines:
                for position in (pipeline.get("definition_json") or {}).get("positions") or []:
                    if int(position.get("employee_id") or 0) == int(employee["id"]):
                        positions.append({"employee_id": employee["id"],
                                          "employee_name": employee["name"],
                                          "pipeline_id": pipeline["id"],
                                          "pipeline_name": pipeline["name"],
                                          "position_name": position.get("name") or position.get("key")})
            person = {"employee_id": employee["id"], "employee_name": employee["name"]}
            for name in active_names:
                target = usage.setdefault(name, {"used_by": [], "pending_by": [],
                                                  "used_by_positions": [],
                                                  "pending_by_positions": []})
                target["used_by"].append(person)
                target["used_by_positions"].extend(positions)
            for name in pending_names:
                target = usage.setdefault(name, {"used_by": [], "pending_by": [],
                                                  "used_by_positions": [],
                                                  "pending_by_positions": []})
                target["pending_by"].append(dict(person, pending=True))
                target["pending_by_positions"].extend(
                    [dict(position, pending=True) for position in positions])
    except (OSError, TypeError, ValueError):
        usage = {}
    names = set(masked) | set(stored_order) | set(usage)

    def credential(name):
        state = masked.get(name) or {"set": False, "masked": ""}
        entry = entry_by_name.get(name, {})
        binding = usage.get(name) or {}
        used_by = binding.get("used_by") or []
        pending_by = binding.get("pending_by") or []
        return {"name": name, "label": "", "note": "",
                "input": "secret", "accept": [],
                "source_name": entry.get("source_name", ""),
                "used_by": used_by, "pending_by": pending_by,
                "used_by_positions": binding.get("used_by_positions") or [],
                "pending_by_positions": binding.get("pending_by_positions") or [],
                "used_by_count": len(used_by), "pending_by_count": len(pending_by), **state}

    ordered_names = [name for name in stored_order if name in names]
    ordered_names.extend(sorted(names - set(ordered_names)))
    return {"credentials": [credential(name) for name in ordered_names]}


def is_spa_route(path):
    """Return whether a browser route should load the single-page app shell."""
    normalized = (path or "/").rstrip("/") or "/"
    return bool(
        normalized == "/chat/new"
        or re.fullmatch(r"/chat/\d+", normalized)
        or normalized == "/pipelines/new"
        or re.fullmatch(r"/pipelines/\d+", normalized)
        or re.fullmatch(r"/pipelines/\d+/workflows/\d+/runs/\d+", normalized)
        or normalized == "/automations"
        or normalized == "/design-system"
        or normalized == "/docs"
        or normalized == "/team"
        or normalized == "/extensions"
        or normalized == "/skills"
        or re.fullmatch(r"/skills/\d+", normalized)
        or normalized == "/extensions/packages"
        or re.fullmatch(r"/extensions/package/\d+", normalized)
        or normalized == "/trash"
        or normalized == "/extensions/local"
        or re.fullmatch(r"/extensions/(?:plugin|skill|mcp|package)/[^/]+/[^/]+", normalized)
    )


def _env_concurrency():
    try:
        return max(1, min(32, int(os.environ.get("RUNTEAMS_MAX_CONCURRENCY", "10"))))
    except (TypeError, ValueError):
        return 4


def _save_chat_attachments(chat_id, data):
    """合并浏览器上传与原生选择令牌，并保证失败时不遗留半成品。"""
    uploaded = []
    try:
        uploaded = chat_attachments.save(chat_id, data.get("attachments") or [])
        remaining = chat_attachments.MAX_TOTAL_BYTES - sum(int(item.get("size") or 0)
                                                            for item in uploaded)
        picked = chat_attachments.consume_native(
            chat_id, data.get("attachment_tokens") or [], max_total_bytes=remaining)
        return uploaded + picked
    except Exception:
        chat_attachments.discard(chat_id, uploaded)
        raise


def _open_local_path(path):
    path = os.path.abspath(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _export_local_file(path, filename):
    """Copy one managed artifact through the operating system's Save dialog."""
    if sys.platform != "darwin":
        raise RuntimeError("当前系统暂不支持原生导出")
    script = """on run argv
set exportName to item 1 of argv
set chosenFile to choose file name with prompt "导出产物" default name exportName
return POSIX path of chosenFile
end run"""
    result = subprocess.run(
        ["osascript", "-e", script, "--", str(filename or "artifact")],
        capture_output=True, text=True, timeout=300, check=False)
    if result.returncode != 0:
        if "User canceled" in (result.stderr or "") or "(-128)" in (result.stderr or ""):
            return ""
        raise RuntimeError("没有打开导出窗口")
    destination = os.path.abspath((result.stdout or "").strip())
    if not destination:
        return ""
    if os.path.realpath(destination) == os.path.realpath(path):
        raise RuntimeError("请选择产物原文件以外的位置")
    shutil.copy2(path, destination)
    return destination


def _core_artifact_file(artifact_id):
    artifact = core_controller().core.artifact(int(artifact_id))
    if not artifact:
        return None, None
    path = os.path.realpath(artifact.get("ref") or "")
    root = os.path.realpath(os.path.join(str(core_controller().root), "artifacts"))
    try:
        safe = os.path.commonpath((root, path)) == root
    except ValueError:
        safe = False
    return (artifact, path) if safe and os.path.isfile(path) else (artifact, None)


def _artifact_filename(artifact, path):
    name = str(artifact.get("name") or "artifact")
    source_name = os.path.basename(str((artifact.get("meta_json") or {}).get("path") or path))
    if not os.path.splitext(name)[1] and os.path.splitext(source_name)[1]:
        name += os.path.splitext(source_name)[1]
    return name


def _artifact_content_type(artifact, path):
    hint = str((artifact.get("meta_json") or {}).get("path") or
               artifact.get("name") or path)
    content_type = mimetypes.guess_type(hint)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in (
            "application/json", "application/javascript", "application/xml"):
        content_type += "; charset=utf-8"
    return content_type


def _pick_local_directory():
    """Open the operating system folder picker without granting browser-wide file access."""
    if sys.platform != "darwin":
        raise RuntimeError("当前系统暂不支持原生文件夹选择")
    result = subprocess.run(
        ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择本地能力所在的文件夹")'],
        capture_output=True, text=True, timeout=300, check=False)
    if result.returncode:
        if "User canceled" in (result.stderr or ""):
            return None
        raise RuntimeError((result.stderr or "无法打开文件夹选择器").strip())
    path = (result.stdout or "").strip().rstrip("/")
    if not path or not os.path.isdir(path):
        raise RuntimeError("没有选择有效的文件夹")
    return os.path.realpath(path)

def _automation_execution_config(item):
    """Resolve only the Agent configuration frozen on the automation itself."""
    if not item:
        raise ValueError("自动化不存在")
    channel_id = item.get("channel_id")
    channel = store.get_channel(channel_id) if channel_id else None
    if not channel or not channel.get("enabled"):
        raise ValueError("自动化保存的 Agent 渠道不可用，请重新选择")
    model = str(item.get("model") or "").strip()
    if not model:
        raise ValueError("自动化保存的模型不可用，请重新选择")
    effort = str(item.get("reasoning_effort") or "").strip()
    return channel, model, effort


def _execute_automation(job, cancel_event=None):
    """Execute one authorized schedule through the ordinary Agent chat path."""
    channel, model, effort = _automation_execution_config(job)
    config = {"channel_id": channel["id"], "model": model,
              "reasoning_effort": effort,
              "scope_pipeline_id": None, "extensions_enabled": False,
              "title": job.get("name") or "自动化", "title_source": "channel"}
    cid = store.create_chat(channel_id=channel["id"], model=config["model"],
                            reasoning_effort=config["reasoning_effort"], kind="automation",
                            context={"context_type": "automation", "intent": "run",
                                     "automation_id": job.get("automation_id"),
                                     "automation_run_id": job.get("id"),
                                     "automation_name": job.get("name") or "自动化",
                                     "label": job.get("name") or "自动化"})
    store.set_chat_channel_title(cid, job.get("name") or "自动化")
    automations.set_automation_run_chat(job["id"], cid)
    prompt = str(job.get("prompt") or "").strip()
    store.add_chat_message(cid, "user", prompt)

    class Activity:
        def on_event(self, event):
            automations.add_automation_run_event(job["id"], "agent_event", event)
    try:
        result = chat.run_chat(
            prompt, [], config, chat_id=cid, auto_apply=True,
            cancel_event=cancel_event,
            action_context={"automation_id": job["automation_id"],
                            "automation_run_id": job["id"]},
            on_activity=Activity())
        store.add_chat_message(cid, "assistant", result.get("reply") or "(无回复)",
                               result.get("applied") or [])
        applied = result.get("applied") or []
        if applied:
            automations.add_automation_run_event(job["id"], "actions", {"items": applied})
        failed_actions = [str(item) for item in applied if str(item).startswith("✗")]
        if failed_actions:
            raise RuntimeError("；".join(failed_actions)[:1000])
        automations.finish_automation_run(job["id"], "completed", result.get("reply") or "")
        automations.add_automation_run_event(job["id"], "system", {"message": "自动化已完成"})
    except Cancelled as exc:
        message = str(exc) or "运行已取消"
        if store.get_chat(cid):
            store.add_chat_message(cid, "assistant", message)
        automations.finish_automation_run(job["id"], "cancelled", message)
    except Exception as exc:
        message = "运行失败：{}".format(str(exc)[:500])
        store.add_chat_message(cid, "assistant", message)
        automations.finish_automation_run(job["id"], "failed", message)
        raise


def _automation_has_open_core_work(automation_id):
    return core_controller().core.automation_has_open_work(automation_id)


def _perform_automation_attention(run_id, action):
    """Revalidate and perform one action against a derived automation failure."""
    item = automations.get_automation_attention(run_id)
    if not item:
        raise ValueError("这条待处理事项已经完成")
    action = str(action or "").strip()
    allowed = {value["id"] for value in item.get("actions") or []}
    if action not in allowed:
        raise ValueError("此事项不支持这个操作")
    automation_id = int(item["automation_id"])
    if action == "retry":
        _automation_execution_config(automations.get_automation(automation_id))
        occurrence = automations.run_automation_now(
            automation_id, has_open_work=_automation_has_open_core_work)
        AUTOMATION_SCHEDULER.wake()
        return {"ok": True, "automation_run_id": occurrence["id"],
                "run_id": "automation:{}".format(occurrence["id"])}
    if not automations.pause_automation(automation_id):
        raise ValueError("自动化状态已经变化")
    return {"ok": True, "paused": True}


AUTOMATION_SCHEDULER = scheduler.AutomationScheduler(
    _execute_automation, max_concurrency=max(1, min(2, _env_concurrency())),
    on_state_change=RELAY_SYNC.wake,
    has_open_work=_automation_has_open_core_work)


MOBILE_DOCUMENT_MAX_CHARS = 60000
MOBILE_DOCUMENT_READABLE_SUFFIXES = (
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".log", ".yaml", ".yml", ".xml")


def _mobile_document_id(target_id):
    if not target_id.startswith("artifact:"):
        raise mobile_commands.CommandRejected("文档不存在")
    try:
        return int(target_id.split(":", 1)[1])
    except (TypeError, ValueError):
        raise mobile_commands.CommandRejected("文档不存在")


def _mobile_document_text(artifact_id):
    """Read one managed document as text, bounded so a report cannot flood the relay."""
    artifact, path = _core_artifact_file(artifact_id)
    if not artifact:
        raise mobile_commands.CommandRejected("文档不存在")
    if not path:
        raise mobile_commands.CommandRejected("文档文件不可用")
    hint = str((artifact.get("meta_json") or {}).get("path") or artifact.get("name") or "")
    suffix = hint[hint.rfind("."):].lower() if "." in hint else ""
    if suffix not in MOBILE_DOCUMENT_READABLE_SUFFIXES:
        raise mobile_commands.CommandRejected("这类文件只能在电脑上打开")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(MOBILE_DOCUMENT_MAX_CHARS + 1)
    except OSError as exc:
        raise mobile_commands.CommandRejected(str(exc) or "文档没有读到")
    truncated = len(content) > MOBILE_DOCUMENT_MAX_CHARS
    return artifact, content[:MOBILE_DOCUMENT_MAX_CHARS], truncated


def _execute_mobile_command(payload, device_id):
    """Execute one verified command against current core or automation facts."""
    del device_id
    action = payload.get("action")
    target_id = str(payload.get("target_id") or "")
    action_id = str(payload.get("action_id") or "")
    if action == "intervention.perform":
        if target_id.startswith("workflow:"):
            try:
                workflow_id = int(target_id.split(":", 1)[1])
            except (TypeError, ValueError):
                raise mobile_commands.CommandRejected("待处理事项无效")
            item = next((value for value in core_controller().core.attention_catalog()
                         if value["id"] == target_id), None)
            if not item:
                raise mobile_commands.CommandRejected("这条待处理事项已经完成")
            if action_id not in {value["id"] for value in item.get("actions") or []}:
                raise mobile_commands.CommandRejected("此事项不支持这个操作")
            try:
                if action_id == "respond":
                    workflow = core_controller().core.respond_to_human(
                        workflow_id, payload.get("response"))
                    core_controller().wake()
                    return {"ok": True, "message": "回复已提交，任务将继续",
                            "run_id": "workflow:{}".format(workflow["id"])}
                if action_id == "retry":
                    workflow = core_controller().core.retry_workflow(workflow_id)
                    core_controller().wake()
                    return {"ok": True, "message": "任务已重新进入队列",
                            "run_id": "workflow:{}".format(workflow["id"])}
                if action_id == "terminate":
                    core_controller().core.cancel_workflow(workflow_id)
                    return {"ok": True, "message": "任务已终止"}
            except (core_api.ContractError, OSError, TypeError, ValueError) as exc:
                raise mobile_commands.CommandRejected(str(exc))
        if target_id.startswith("automation-intervention:"):
            try:
                automation_run_id = int(target_id.split(":", 1)[1])
                result = _perform_automation_attention(automation_run_id, action_id)
            except (TypeError, ValueError) as exc:
                raise mobile_commands.CommandRejected(str(exc) or "待处理事项无效")
            if action_id == "retry":
                return {"ok": True, "message": "自动化已重新开始",
                        "run_id": result["run_id"]}
            return {"ok": True, "message": "自动化已暂停"}
        raise mobile_commands.CommandRejected("待处理事项无效")

    if action == "run.control":
        if not target_id.startswith("workflow:"):
            raise mobile_commands.CommandRejected("运行不存在")
        if action_id != "cancel":
            raise mobile_commands.CommandRejected("此运行不支持这个操作")
        try:
            workflow_id = int(target_id.split(":", 1)[1])
            workflow = core_controller().core.workflow(workflow_id)
            if not workflow:
                raise mobile_commands.CommandRejected("运行不存在")
            if workflow.get("state") in ("completed", "canceled", "failed", "blocked"):
                raise mobile_commands.CommandRejected("运行已经结束")
            core_controller().core.cancel_workflow(workflow_id)
        except mobile_commands.CommandRejected:
            raise
        except (core_api.ContractError, OSError, TypeError, ValueError) as exc:
            raise mobile_commands.CommandRejected(str(exc))
        return {"ok": True, "message": "任务已终止"}

    if action == "document.read":
        artifact_id = _mobile_document_id(target_id)
        artifact, content, truncated = _mobile_document_text(artifact_id)
        return {"ok": True, "name": str(artifact.get("name") or "产物"),
                "content": content, "truncated": truncated,
                "message": ("文档较长，手机上只显示前 {} 字，完整内容请在电脑上看".format(
                    MOBILE_DOCUMENT_MAX_CHARS) if truncated else "")}

    raise mobile_commands.CommandRejected("不支持的远程操作")


def _stop_active_runs():
    if _CORE_CONTROLLER is not None:
        _CORE_CONTROLLER.stop()
    AUTOMATION_SCHEDULER.stop()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream_file(self, path, ctype, filename, download=False):
        try:
            size = os.path.getsize(path)
            handle = open(path, "rb")
        except OSError:
            self.send_response(404); self.end_headers(); return
        disposition = "attachment" if download else "inline"
        fallback = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "artifact") or "artifact"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", "{}; filename=\"{}\"; filename*=UTF-8''{}".format(
            disposition, fallback, quote(filename or fallback)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
        self.end_headers()
        with handle:
            shutil.copyfileobj(handle, self.wfile)

    def _stream_bytes(self, body, ctype, filename, download=False):
        body = bytes(body or b"")
        disposition = "attachment" if download else "inline"
        fallback = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "download") or "download"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", "{}; filename=\"{}\"; filename*=UTF-8''{}".format(
            disposition, fallback, quote(filename or fallback)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "sandbox")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _chat_stream(self, cid, data):
        """统一发送所有持久会话；会话 kind 只决定后台处理策略。"""
        msg = (data.get("message") or "").strip()
        ui_test_state = str(data.get("ui_test_state") or "").strip()
        if ui_test_state not in {"waiting", "failed", "health_ok", "health_warn",
                                 "health_block"}:
            ui_test_state = ""
        # UI test overrides only belong to the built-in visual test prompts.  A normal
        # client cannot manufacture a health or failure state by posting this flag.
        if not (msg.startswith("这是 Agent Chat 的") and "UI 测试" in msg):
            ui_test_state = ""
        sess = store.get_chat(cid)
        if not _is_formal_chat(sess):
            return self._json({"error": "对话不存在"}, 404)
        rewind_message_id = data.get("rewind_message_id")
        rewind_source = None
        if rewind_message_id not in (None, ""):
            try:
                rewind_message_id = int(rewind_message_id)
            except (TypeError, ValueError):
                return self._json({"error": "要编辑的消息无效"}, 400)
            rewind_source = store.get_chat_message(cid, rewind_message_id)
            if not rewind_source or rewind_source.get("role") != "user":
                return self._json({"error": "要编辑的消息已经不存在"}, 409)
        reuse_ids = {str(item) for item in (data.get("reuse_attachment_ids") or []) if item}
        source_attachments = ((rewind_source.get("attachments") or [])
                              if rewind_source else [])
        source_attachment_ids = {str(item.get("id") or "") for item in source_attachments}
        if reuse_ids - source_attachment_ids:
            return self._json({"error": "原消息中的附件已经不可用，请重新添加"}, 409)
        try:
            uploaded_attachments = _save_chat_attachments(cid, data)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        reused_attachments = [item for item in source_attachments
                              if str(item.get("id") or "") in reuse_ids]
        attachments = reused_attachments + uploaded_attachments
        if not msg and not attachments:
            chat_attachments.discard(cid, uploaded_attachments)
            return self._json({"error": "请输入消息或添加附件"}, 400)

        cancel_event = _begin_chat_turn(cid)
        if cancel_event is None:
            chat_attachments.discard(cid, uploaded_attachments)
            return self._json({"error": "这段对话正在处理上一条消息"}, 409)

        capabilities = chat._normalize_capabilities(data.get("capabilities"))
        if rewind_source:
            old_runtime_provider = sess.get("runtime_provider")
            old_runtime_thread_id = sess.get("runtime_thread_id")
            try:
                store.rewind_chat(cid, rewind_message_id)
            except ValueError as exc:
                _end_chat_turn(cid, cancel_event)
                chat_attachments.discard(cid, uploaded_attachments)
                return self._json({"error": str(exc)}, 409)
            if old_runtime_provider == "codex" and old_runtime_thread_id:
                try:
                    codex_threads.delete_thread(
                        store.get_channel(sess.get("channel_id")), old_runtime_thread_id)
                except Exception:
                    # 本地回退已经完成；远端旧分支清理失败不能阻断用户继续编辑。
                    pass
            sess = store.get_chat(cid)
        history = sess.get("messages") or []
        user_message_id = store.add_chat_message(
            cid, "user", msg, attachments=attachments, capabilities=capabilities)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        connected = [True]
        trace_record = _new_chat_trace_record()

        def emit(kind, payload=None):
            if not connected[0]:
                return
            event = {"type": kind}
            if isinstance(payload, dict):
                event.update(payload)
            try:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            except Exception:
                connected[0] = False

        public_attachments = chat_attachments.public(attachments)
        emit("accepted", {"message_id": user_message_id,
                          "attachments": public_attachments,
                          "capabilities": capabilities})
        class Activity:
            def on_event(self, event):
                _record_chat_trace(trace_record, "agent_event", event)
                emit("agent_event", {"event": event})
        activity = Activity()
        try:
            if ui_test_state == "waiting":
                # Keep the accepted, pre-response state visible long enough for visual QA.
                time.sleep(3)
            if sess.get("kind", "general") == "general":
                out = chat.run_chat(
                    msg or "请查看并处理附件。", history, sess, attachments, cid,
                    on_activity=activity,
                    capabilities=capabilities,
                    view_context=data.get("view_context"),
                    cancel_event=cancel_event)
            else:
                out = employee_sessions.run_turn(
                    cid, msg, history, attachments, data.get("draft"),
                    on_activity=activity,
                    capabilities=capabilities,
                    cancel_event=cancel_event)
            if ui_test_state == "failed":
                raise RuntimeError("Agent UI 测试：模拟本地服务未返回结果")
            if ui_test_state == "health_ok":
                out["health"] = {"block": 0, "warn": 0, "issues": []}
            elif ui_test_state == "health_warn":
                out["health"] = {"block": 0, "warn": 1, "issues": [{
                    "sev": "warn", "msg": "「06 立项终审」还没有交付要求和完成标准"}]}
            elif ui_test_state == "health_block":
                out["health"] = {"block": 2, "warn": 0, "issues": [
                    {"sev": "block", "msg": "先为「06 立项终审」选择员工"},
                    {"sev": "block", "msg": "任务参数「bundleId」还没有指定填写岗位"},
                ]}
            bot_message_id = store.add_chat_message(
                cid, "bot", out.get("reply", ""), out.get("applied") or [],
                metadata=_chat_message_metadata(trace_record, "completed", out))
            out["message_id"] = bot_message_id
            out["attachments"] = public_attachments
            emit("result", out)
        except Cancelled:
            message = "已保留当前工作区和已经完成的检查结果。"
            store.add_chat_message(
                cid, "bot", message,
                metadata=_chat_message_metadata(trace_record, "cancelled"))
            emit("cancelled", {"message": "已停止"})
        except Exception as exc:
            message = chat.public_error(exc, sess)
            store.add_chat_message(
                cid, "bot", message,
                metadata=_chat_message_metadata(trace_record, "failed"))
            emit("error", {"message": message})
        finally:
            _end_chat_turn(cid, cancel_event)

    def _bearer_token(self):
        value = self.headers.get("Authorization", "")
        return value[7:].strip() if value.lower().startswith("bearer ") else ""

    def _core_audit_context(self):
        """Return request provenance without ever persisting the bearer token."""
        try:
            account = account_auth.session() or {}
        except Exception:
            account = {}
        return {
            "actor_id": account.get("user_id") or None,
            "correlation_id": self.headers.get("X-Request-ID") or uuid.uuid4().hex,
            "source": "http",
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path
        if p == "/api/health":
            return self._json({"app": "RunTeams.ai", "api_version": API_COMPAT_VERSION,
                               "version": APP_VERSION, "pid": os.getpid()})
        if p == "/api/failure-stats":
            return self._json(run_statistics.summary(core_controller().core))
        if p in ("/", "/index.html"):
            return self._file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
        if p == "/runteams.css":
            return self._file(os.path.join(WEB, "runteams.css"), "text/css; charset=utf-8")
        if p == "/favicon.svg":
            return self._file(os.path.join(WEB, "favicon.svg"), "image/svg+xml")
        if p == "/api/worker-avatars":
            return self._json({"presets": worker_avatars.preset_items()})
        m = re.match(r"^/api/worker-avatar/upload/([a-f0-9]{24}\.webp)$", p)
        if m:
            path = worker_avatars.upload_path(
                "upload:" + m.group(1), store.data_dir())
            if not path or not os.path.isfile(path):
                return self._json({"error": "头像不存在"}, 404)
            return self._file(path, "image/webp")
        m = re.match(r"^/api/core/artifacts/(\d+)/content$", p)
        if m:
            artifact, path = _core_artifact_file(int(m.group(1)))
            if not artifact:
                return self._json({"error": "产物不存在"}, 404)
            if not path:
                return self._json({"error": "产物文件不可用"}, 404)
            return self._stream_file(
                path, _artifact_content_type(artifact, path),
                _artifact_filename(artifact, path),
                parse_qs(parsed.query).get("download") == ["1"])
        m = re.match(r"^/api/core/workflows/(\d+)/inputs/([a-f0-9]{24})/content$", p)
        if m:
            try:
                item, path = core_controller().core.workflow_task_input_file(
                    int(m.group(1)), m.group(2))
            except (core_api.ContractError, OSError, TypeError, ValueError) as exc:
                return self._json({"error": str(exc)}, 404)
            if not path or not os.path.exists(path):
                return self._json({"error": "任务资料不可用"}, 404)
            download = parse_qs(parsed.query).get("download") == ["1"]
            name = str(item.get("name") or "附件")
            if os.path.isdir(path):
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                    for child in sorted(path.rglob("*")):
                        if child.is_file():
                            bundle.write(child, child.relative_to(path).as_posix())
                filename = name if name.lower().endswith(".zip") else name + ".zip"
                return self._stream_bytes(archive.getvalue(), "application/zip", filename, True)
            ctype = item.get("mime_type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
                ctype += "; charset=utf-8" if "charset=" not in ctype else ""
            return self._stream_file(path, ctype, name, download)
        if p.startswith("/api/core/"):
            result = core_api.safe_dispatch(
                core_api.get_payload, core_controller(), p, parse_qs(parsed.query), re,
                audit_context=self._core_audit_context())
            if result is not None:
                payload, status = result
                return self._json(payload, status)
        m = re.match(r"^/worker-avatars/bottts/([a-z0-9-]+)\.svg$", p)
        if m and m.group(1) in worker_avatars.PRESET_IDS:
            return self._file(
                os.path.join(WEB, "worker-avatars", "bottts", m.group(1) + ".svg"),
                "image/svg+xml",
            )
        m = re.match(r"^/api/environment/plugin-icon/([a-f0-9]{24})$", p)
        if m:
            icon = runtime_capabilities.plugin_icon(m.group(1))
            if not icon:
                return self._json({"error": "图标不存在"}, 404)
            return self._file(icon[0], icon[1])
        if p == "/api/environment/plugin-resources":
            query = parse_qs(parsed.query)
            try:
                channel_id = int(query.get("channel_id", [""])[0])
            except (TypeError, ValueError):
                return self._json({"error": "渠道标识无效"}, 400)
            channel = store.get_channel(channel_id)
            if not channel:
                return self._json({"error": "渠道不存在"}, 404)
            try:
                return self._json(runtime_capabilities.plugin_resources(
                    channel, query.get("plugin_id", [""])[0]))
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 503)
        m = re.match(r"^/api/environment/plugin-resource/([a-f0-9]{24})$", p)
        if m:
            try:
                return self._json(runtime_capabilities.plugin_resource_file(
                    m.group(1), parse_qs(parsed.query).get("path", [""])[0]))
            except ValueError as exc:
                return self._json({"error": str(exc)}, 404)
        m = re.match(r"^/vendor/([\w.\-]+\.(js|css))$", p)
        if m:
            ctype = "text/css; charset=utf-8" if p.endswith(".css") else "application/javascript; charset=utf-8"
            return self._file(os.path.join(WEB, "vendor", m.group(1)), ctype)
        m = re.match(r"^/fonts/([\w.\-]+\.woff2)$", p)
        if m:
            return self._file(os.path.join(WEB, "fonts", m.group(1)), "font/woff2")
        if p == "/api/trash":
            _purge_expired_trash()
            items = (core_controller().core.employee_trash_catalog() +
                     core_controller().core.pipeline_trash_catalog() +
                     core_controller().core.pipeline_position_trash_catalog() +
                     core_controller().core.task_trash_catalog() +
                     core_controller().core.document_trash_catalog() +
                     automations.list_trashed_automations())
            items.sort(key=lambda item: item.get("trashed_at") or "", reverse=True)
            return self._json({"items": items,
                               "retention_days": 30})
        if p == "/api/automations":
            return self._json({"automations": automations.list_automations()})
        m = re.match(r"^/api/automation/(\d+)$", p)
        if m:
            item = automations.get_automation(int(m.group(1)))
            return self._json(item or {"error": "自动化不存在"}, 200 if item else 404)
        m = re.match(r"^/api/automation-run/(\d+)$", p)
        if m:
            item = automations.get_automation_run(int(m.group(1)))
            return self._json(item or {"error": "自动化运行记录不存在"}, 200 if item else 404)
        if p == "/api/app-info":
            try:
                database_size = os.path.getsize(local_database.DB_PATH)
            except OSError:
                database_size = 0
            platform_name = "macOS" if sys.platform == "darwin" else ("Windows" if os.name == "nt" else "Linux")
            return self._json({"version": APP_VERSION, "platform": platform_name,
                               "data_dir": store.data_dir(), "database_size": database_size,
                               "port": PORT, "max_concurrency": _env_concurrency(),
                               "native_attachment_picker": chat_attachments.native_picker_available()})
        if p == "/api/app-update":
            return self._json(UPDATES.status())
        if p == "/api/account/session":
            return self._json(relay_sync.enrich_account(account_auth.session()))
        if p == "/api/billing/status":
            try:
                return self._json(relay_sync.billing_request("GET", "/v1/billing/status"))
            except relay_sync.RelaySyncError as exc:
                return self._json({"error": str(exc)}, exc.status or 503)
        if p == "/api/mobile-preview":
            return self._json(mobile_projection.build_dashboard_snapshot(
                app_version=APP_VERSION,
                account=relay_sync.enrich_account(account_auth.session()),
            ))
        if p == "/api/mobile-relay/status":
            return self._json(relay_sync.status())
        if p == "/api/mobile-relay/devices":
            try:
                return self._json({"devices": relay_sync.mobile_devices()})
            except relay_sync.RelaySyncError as exc:
                return self._json({"error": str(exc)}, exc.status or 503)
        if p == "/api/secret-vault":
            return self._json(secret_vault_payload())
        if p == "/api/channels":
            return self._json({
                "providers": model_channels.public_providers(),
                "channels": [model_channels.public_channel(c) for c in store.list_channels()],
            })
        if p == "/api/channel-usage":
            return self._json(model_channels.channels_usage(store.list_channels()))
        if p == "/api/environment":
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] in ("1", "true", "yes")
            return self._json(runtime_capabilities.environment_summary(
                store.list_channels(), refresh=refresh))
        m = re.match(r"^/api/channel/(\d+)/capabilities$", p)
        if m:
            channel = store.get_channel(int(m.group(1)))
            if not channel:
                return self._json({"error": "渠道不存在"}, 404)
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] in ("1", "true", "yes")
            return self._json(runtime_capabilities.inventory(channel, refresh=refresh))
        if p == "/api/model-catalog":
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] in ("1", "true", "yes")
            return self._json(model_channels.global_catalog(store.list_channels(), refresh=refresh))
        if p == "/api/interventions":
            items = attention.catalog(core_controller().core)
            return self._json({"items": items, "count": len(items)})
        m = re.match(r"^/api/bots/(\d+)/context$", p)
        if m:
            query = parse_qs(parsed.query)
            scope_type = (query.get("scope_type", ["global"])[0] or "global").strip()
            pipeline_id = (query.get("pipeline_id", [None])[0] or None)
            run_id = (query.get("run_id", [None])[0] or None)
            try:
                projection = bot_context.build(
                    core_controller().core, int(m.group(1)),
                    scope_type=scope_type, pipeline_id=pipeline_id, run_id=run_id)
            except (TypeError, ValueError) as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json(projection)
        if p == "/api/bots":
            return self._json(_bot_conversation_summaries())
        if p == "/api/chats":
            return self._json({"chats": _formal_chat_summaries()})
        m = re.match(r"^/api/chat/(\d+)$", p)
        if m:
            ch = store.get_chat(int(m.group(1)))
            if _is_formal_chat(ch):
                for message in ch.get("messages", []):
                    message["attachments"] = chat_attachments.public(message.get("attachments"))
                if ch.get("kind") == employee_sessions.SESSION_KIND:
                    ch = employee_sessions.public_session(ch)
            else:
                ch = None
            return self._json(ch or {"error": "对话不存在"}, 200 if ch else 404)
        m = re.match(r"^/api/chat/(\d+)/attachment/([a-f0-9]{24})$", p)
        if m:
            cid, attachment_id = int(m.group(1)), m.group(2)
            if not _is_formal_chat(store.get_chat(cid)):
                self.send_response(404); self.end_headers(); return
            item = store.find_chat_attachment(cid, attachment_id)
            if not item:
                self.send_response(404); self.end_headers(); return
            try:
                path = chat_attachments.path_for(cid, item)
            except ValueError:
                self.send_response(404); self.end_headers(); return
            return self._stream_file(path, item.get("mime_type") or "application/octet-stream",
                                     item.get("name") or "attachment", False)
        if is_spa_route(p):
            return self._file(os.path.join(WEB, "index.html"), "text/html; charset=utf-8")
        self.send_response(404); self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        d = self._body()
        if p == "/api/worker-avatar/upload":
            try:
                return self._json(
                    worker_avatars.save_upload(d, store.data_dir()), 201)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/worker-avatar/upload/discard":
            reference = str(d.get("avatar") or "")
            try:
                in_use = core_controller().core.employee_avatar_in_use(reference)
            except (TypeError, ValueError):
                return self._json({"error": "头像无效"}, 400)
            if not in_use:
                worker_avatars.remove_upload(reference, store.data_dir())
            return self._json({"ok": True, "in_use": in_use})
        artifact_action = re.match(r"^/api/core/artifacts/(\d+)/(open|export)$", p)
        if artifact_action:
            artifact, path = _core_artifact_file(int(artifact_action.group(1)))
            if not artifact:
                return self._json({"error": "产物不存在"}, 404)
            if not path:
                return self._json({"error": "产物文件不可用"}, 404)
            try:
                if artifact_action.group(2) == "open":
                    _open_local_path(path)
                    return self._json({"ok": True})
                destination = _export_local_file(path, _artifact_filename(artifact, path))
                return self._json({"ok": True, "cancelled": not bool(destination),
                                   "path": destination})
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                return self._json({"error": str(exc)}, 400)
        employee_delete = re.match(r"^/api/core/employees/(\d+)/delete$", p)
        if employee_delete:
            employee_id = int(employee_delete.group(1))
            employee = core_controller().core.employee(
                employee_id, include_trashed=True)
            result = core_api.safe_dispatch(
                core_api.post_payload, core_controller(), p, d, re,
                audit_context=self._core_audit_context())
            payload, status = result
            if status < 400:
                removed = store.delete_employee_chats(employee_id)
                for chat_id in removed:
                    chat_attachments.remove_chat(chat_id)
                payload["employee_conversations"] = len(removed)
                avatar = str((employee or {}).get("avatar") or "")
                if (avatar.startswith("upload:") and
                        not core_controller().core.employee_avatar_in_use(avatar)):
                    worker_avatars.remove_upload(avatar, store.data_dir())
            return self._json(payload, status)
        if p.startswith("/api/core/"):
            result = core_api.safe_dispatch(
                core_api.post_payload, core_controller(), p, d, re,
                audit_context=self._core_audit_context())
            if result is not None:
                payload, status = result
                return self._json(payload, status)
        if p == "/api/environment/plugin/install":
            try:
                channel_id = int(d.get("channel_id"))
            except (TypeError, ValueError):
                return self._json({"error": "模型渠道无效"}, 400)
            channel = store.get_channel(channel_id)
            if not channel:
                return self._json({"error": "模型渠道不存在"}, 404)
            try:
                result = runtime_capabilities.install_plugin(channel, d.get("plugin_id"))
                result["environment"] = runtime_capabilities.environment_summary(
                    store.list_channels(), refresh=True)
                result["ok"] = True
                return self._json(result, 200 if result.get("already_installed") else 201)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 409)
        if p == "/api/workspace/reset":
            try:
                return self._json(reset_workspace_data(d.get("user_confirmation") or d.get("confirmation")))
            except RuntimeError as exc:
                return self._json({"error": str(exc)}, 409)
            except Exception as exc:
                return self._json({"error": "本地数据清理失败：{}".format(str(exc)[:200])}, 400)
        if p == "/api/attachments/pick":
            origin = self.headers.get("Origin") or ""
            allowed = {"http://127.0.0.1:{}".format(PORT), "http://localhost:{}".format(PORT)}
            if origin and origin not in allowed:
                return self._json({"error": "不允许从其他页面打开本地文件选择器"}, 403)
            try:
                return self._json({"items": chat_attachments.pick_native()})
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/account/otp/request":
            try:
                return self._json(account_auth.request_otp(d.get("email")), 202)
            except account_auth.AuthError as exc:
                return self._json({"error": str(exc)}, exc.status if exc.status in (400, 429) else 503)
        if p == "/api/account/otp/verify":
            try:
                result = account_auth.verify_otp(d.get("email"), d.get("token"))
                RELAY_SYNC.wake()
                return self._json(result)
            except account_auth.AuthError as exc:
                return self._json({"error": str(exc)}, exc.status if exc.status in (400, 429) else 503)
        if p == "/api/account/logout":
            try:
                # Revoke the account-bound cloud identity before clearing the
                # access token. Local pipelines, chats and files are untouched.
                relay_sync.retire_account_host()
                result = account_auth.logout()
                RELAY_SYNC.wake()
                return self._json(result)
            except account_auth.AuthError as exc:
                return self._json({"error": str(exc)}, 503)
        if p == "/api/feedback":
            try:
                return self._json(relay_sync.feedback_request(d), 201)
            except relay_sync.RelaySyncError as exc:
                return self._json({"error": str(exc)}, exc.status or 503)
        if p in ("/api/billing/checkout", "/api/billing/portal"):
            remote_path = (
                "/v1/billing/checkout-session"
                if p.endswith("/checkout") else "/v1/billing/portal-session"
            )
            try:
                return self._json(relay_sync.billing_request("POST", remote_path))
            except relay_sync.RelaySyncError as exc:
                return self._json({"error": str(exc)}, exc.status or 503)
        if p == "/api/automations":
            try:
                item = automations.save_automation(d)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            AUTOMATION_SCHEDULER.wake()
            return self._json({"automation": item}, 201)
        m = re.match(r"^/api/automation/(\d+)/(update|run|cancel|delete)$", p)
        if m:
            automation_id, action = int(m.group(1)), m.group(2)
            try:
                if action == "update":
                    item = automations.save_automation(d, automation_id)
                    AUTOMATION_SCHEDULER.wake()
                    return self._json({"automation": item})
                if action == "run":
                    _automation_execution_config(automations.get_automation(automation_id))
                    occurrence = automations.run_automation_now(
                        automation_id, has_open_work=_automation_has_open_core_work)
                    AUTOMATION_SCHEDULER.wake()
                    return self._json({"ok": True, "run": occurrence,
                                       "automation": automations.get_automation(automation_id)})
                if action == "cancel":
                    if not AUTOMATION_SCHEDULER.cancel_automation(
                            automation_id, "本次运行已停止", wait_timeout=5):
                        return self._json({"error": "本次运行正在停止，请稍后再试"}, 409)
                    return self._json({"ok": True,
                                       "automation": automations.get_automation(automation_id)})
                if not AUTOMATION_SCHEDULER.cancel_automation(
                        automation_id, "自动化已删除", wait_timeout=5):
                    return self._json({"error": "自动化正在停止，请稍后再试"}, 409)
                if not automations.trash_automation(automation_id):
                    return self._json({"error": "自动化不存在"}, 404)
                return self._json({"ok": True, "trashed": True})
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
        if p == "/api/mobile-relay/sync":
            result = RELAY_SYNC.sync_now()
            return self._json(result, 200 if result.get("configured") else 409)
        if p == "/api/mobile-relay/device/revoke":
            try:
                result = relay_sync.revoke_mobile_device(d.get("device_id"))
                RELAY_SYNC.wake()
                return self._json(result)
            except relay_sync.RelaySyncError as exc:
                return self._json({"error": str(exc)}, exc.status or 503)
        if p == "/api/app/open-data-directory":
            try:
                _open_local_path(store.data_dir())
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/app/pick-directory":
            try:
                path = _pick_local_directory()
                return self._json({"path": path} if path else {"cancelled": True})
            except Exception as e:
                return self._json({"error": str(e)}, 400)
        if p == "/api/credential":
            name = str(d.get("name") or "").strip()
            try:
                entry = store.save_credential_entry(name)
                if "value" in d:
                    app_secrets.set_secret(name, d.get("value"))
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True, "credential": entry,
                               "vault": secret_vault_payload()})
        if p == "/api/credentials/reorder":
            current = secret_vault_payload()["credentials"]
            current_names = {item["name"] for item in current}
            order = d.get("order") or []
            if len(order) != len(current_names) or set(order) != current_names:
                return self._json({"error": "凭据顺序与当前列表不一致，请刷新后重试"}, 409)
            try:
                store.reorder_credential_entries(order)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True, "vault": secret_vault_payload()})
        if p == "/api/credentials/values":
            values = d.get("values")
            source_names = d.get("source_names") or {}
            order = d.get("order") or []
            current_names = {item["name"] for item in secret_vault_payload()["credentials"]}
            if (not isinstance(values, dict) or not set(values).issubset(current_names)
                    or not isinstance(source_names, dict)
                    or not set(source_names).issubset(set(values))):
                return self._json({"error": "凭据列表已变化，请刷新后重试"}, 409)
            if len(order) != len(current_names) or set(order) != current_names:
                return self._json({"error": "凭据顺序与当前列表不一致，请刷新后重试"}, 409)
            try:
                app_secrets.set_secrets(values)
                store.set_credential_source_names({
                    name: source_names.get(name, "") for name in values})
                store.reorder_credential_entries(order)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": True, "vault": secret_vault_payload()})
        if p == "/api/credential/delete":
            name = str(d.get("name") or "").strip()
            if not name:
                return self._json({"error": "凭据 Key 不能为空"}, 400)
            app_secrets.set_secret(name, "")
            store.delete_credential_entry(name)
            return self._json({"ok": True, "vault": secret_vault_payload()})
        m = re.match(r"^/api/automation-attention/(\d+)/action$", p)
        if m:
            try:
                return self._json(_perform_automation_attention(
                    int(m.group(1)), d.get("action")))
            except ValueError as exc:
                return self._json({"error": str(exc)}, 409)
        if p == "/api/conversations":
            kind = d.get("kind") or "general"
            try:
                if kind == "general":
                    channel = store.get_channel(d.get("channel_id")) or store.get_default_channel()
                    if not channel or not channel.get("enabled"):
                        return self._json({"error": "请选择可用的模型渠道"}, 400)
                    scope_pipeline_id = d.get("scope_pipeline_id") or None
                    if scope_pipeline_id is not None:
                        try:
                            scope_pipeline_id = int(scope_pipeline_id)
                        except (TypeError, ValueError):
                            return self._json({"error": "对话作用范围无效"}, 400)
                        if not _core_pipeline_exists(scope_pipeline_id):
                            return self._json({"error": "选择的流水线已不存在"}, 400)
                    model, effort = model_channels.normalize_selection(
                        channel, d.get("model"), d.get("reasoning_effort"))
                    context = d.get("context") if isinstance(d.get("context"), dict) else None
                    bot_context_value = context or {}
                    is_bot_chat = (str(bot_context_value.get("context_type") or "").strip() == "worker" and
                                   str(bot_context_value.get("intent") or "chat").strip() in {"chat", "work"})
                    if is_bot_chat:
                        try:
                            employee_id = int(d.get("employee_id") or
                                              bot_context_value.get("target_employee_id") or
                                              bot_context_value.get("target_worker_id") or
                                              bot_context_value.get("worker_id"))
                        except (TypeError, ValueError):
                            return self._json({"error": "员工 Bot 会话缺少有效员工"}, 400)
                        employee = core_controller().core.employee(employee_id)
                        if employee is None:
                            return self._json({"error": "员工不存在"}, 400)
                        release = employee.get("active_release") or {}
                        context = dict(context or {})
                        context.setdefault("target_employee_id", employee_id)
                        context.setdefault("worker_name", employee.get("name") or "当前员工 Bot")
                        context.setdefault("employee_release_id", release.get("id"))
                        context.setdefault("employee_release_digest", release.get("digest", ""))
                        scope_type = str(context.get("scope_type") or
                                         ("pipeline" if scope_pipeline_id else "global")).strip()
                        cid = store.create_chat(
                            channel["id"], model, effort, scope_pipeline_id,
                            bool(d.get("extensions_enabled")), context=context,
                            subject_type="employee", employee_id=employee_id,
                            employee_release_id=release.get("id"),
                            employee_release_digest=release.get("digest", ""),
                            scope_type=scope_type, scope_run_id=context.get("run_id"))
                    else:
                        cid = store.create_chat(channel["id"], model, effort,
                                                scope_pipeline_id,
                                                bool(d.get("extensions_enabled")),
                                                context=context)
                    session = store.get_chat(cid)
                elif kind == employee_sessions.SESSION_KIND:
                    session = employee_sessions.create_session(
                        d.get("runtime") or {}, d.get("employee_id"),
                        d.get("phase") or "design")
                else:
                    return self._json({"error": "不支持的会话类型"}, 400)
                return self._json({"session": employee_sessions.public_session(session)})
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:
                return self._json({"error": chat.public_error(exc, d.get("runtime") or {})}, 502)
        m = re.match(r"^/api/chat/(\d+)/cancel$", p)
        if m:
            cid = int(m.group(1))
            if not _is_formal_chat(store.get_chat(cid)):
                return self._json({"error": "对话不存在"}, 404)
            return self._json({"cancelled": _cancel_chat_turn(cid)})
        m = re.match(r"^/api/chat/(\d+)/stream$", p)
        if m:
            return self._chat_stream(int(m.group(1)), d)
        m = re.match(r"^/api/chat/(\d+)/draft-action$", p)
        if m:
            cid = int(m.group(1))
            session = store.get_chat(cid)
            if not (_is_formal_chat(session)
                    and session.get("kind") == employee_sessions.SESSION_KIND):
                return self._json({"error": "对话不存在"}, 404)
            try:
                action = str(d.get("action") or "").strip()
                if action == "apply":
                    result = employee_sessions.apply_ready_draft(cid, d.get("draft"))
                    store.add_chat_message(cid, "bot", result["reply"], result.get("applied"))
                elif action == "discard":
                    result = employee_sessions.discard_ready_draft(cid)
                else:
                    return self._json({"error": "不支持的草稿操作"}, 400)
                return self._json(result)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 409)
        m = re.match(r"^/api/chat/(\d+)/apply-plan$", p)
        if m:
            chat_id = int(m.group(1))
            session = store.get_chat(chat_id)
            if not (_is_formal_chat(session) and session.get("kind", "general") == "general"):
                return self._json({"error": "对话不存在"}, 404)
            try:
                message_id = int(d.get("message_id"))
            except (TypeError, ValueError):
                return self._json({"error": "待确认方案已经不存在"}, 409)
            message = store.get_chat_message(chat_id, message_id)
            metadata = (message or {}).get("metadata") or {}
            plan = metadata.get("plan") if metadata.get("pending") else None
            if not message or message.get("role") != "bot" or not isinstance(plan, dict):
                return self._json({"error": "这项方案已经处理"}, 409)
            actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
            # A confirmed plan still belongs to the conversation that produced
            # it. Preserve the bound Bot context so a direct handoff can carry
            # the bounded historical record into the frozen employee work order.
            applied, run_cards, focus_pid = chat.apply_actions(actions, action_context={
                "chat_id": chat_id,
                "conversation_context": session.get("context") or {},
            })
            try:
                store.resolve_chat_plan(chat_id, message_id, applied, "applied")
            except ValueError as exc:
                return self._json({"error": str(exc)}, 409)
            AUTOMATION_SCHEDULER.wake()
            return self._json({"ok": True, "applied": applied,
                               "run_cards": run_cards, "focus_pid": focus_pid})
        m = re.match(r"^/api/chat/(\d+)/dismiss-plan$", p)
        if m:
            chat_id = int(m.group(1))
            session = store.get_chat(chat_id)
            if not (_is_formal_chat(session) and session.get("kind", "general") == "general"):
                return self._json({"error": "对话不存在"}, 404)
            try:
                message_id = int(d.get("message_id"))
                store.resolve_chat_plan(chat_id, message_id, [], "cancelled")
            except (TypeError, ValueError) as exc:
                return self._json({"error": str(exc) or "待确认方案已经不存在"}, 409)
            return self._json({"ok": True})
        m = re.match(r"^/api/chat/(\d+)/config$", p)
        if m:
            session = store.get_chat(int(m.group(1)))
            if not _is_formal_chat(session):
                return self._json({"error": "对话不存在"}, 404)
            channel = store.get_channel(d.get("channel_id"))
            if not channel or not channel.get("enabled"):
                return self._json({"error": "请选择可用的模型渠道"}, 400)
            scope_pipeline_id = d.get("scope_pipeline_id") or None
            if scope_pipeline_id is not None:
                try:
                    scope_pipeline_id = int(scope_pipeline_id)
                except (TypeError, ValueError):
                    return self._json({"error": "对话作用范围无效"}, 400)
                if not _core_pipeline_exists(scope_pipeline_id):
                    return self._json({"error": "选择的流水线已不存在"}, 400)
            model, effort = model_channels.normalize_selection(
                channel, d.get("model"), d.get("reasoning_effort"))
            store.update_chat_config(int(m.group(1)), channel["id"],
                                     model, effort,
                                     scope_pipeline_id,
                                     bool(d.get("extensions_enabled")),
                                     context=d.get("context"))
            return self._json({"ok": True})
        m = re.match(r"^/api/chat/(\d+)/rename$", p)
        if m:
            cid = int(m.group(1))
            title = (d.get("title") or "").strip() or "新对话"
            sess = store.get_chat(cid)
            if not _is_formal_chat(sess):
                return self._json({"error": "对话不存在"}, 404)
            if sess.get("runtime_provider") == "codex" and sess.get("runtime_thread_id"):
                channel = store.get_channel(sess.get("channel_id"))
                try:
                    codex_threads.set_name(channel, sess["runtime_thread_id"], title)
                except Exception as exc:
                    return self._json({"error": chat.public_error(exc, sess)}, 502)
            store.rename_chat(cid, title)
            return self._json({"ok": True})
        m = re.match(r"^/api/chat/(\d+)/delete$", p)
        if m:
            cid = int(m.group(1))
            sess = store.get_chat(cid)
            if sess and sess.get("runtime_provider") == "codex" and sess.get("runtime_thread_id"):
                channel = store.get_channel(sess.get("channel_id"))
                try:
                    codex_threads.delete_thread(channel, sess["runtime_thread_id"])
                except Exception:
                    # 用户删除本地对话的意图优先；官方会话清理失败不阻断本地删除。
                    pass
            store.delete_chat(cid)
            chat_attachments.remove_chat(cid)
            return self._json({"ok": True})
        if p == "/api/channels":
            provider = (d.get("provider") if d.get("provider") in model_channels.PROVIDERS
                        else model_channels.DEFAULT_PROVIDER_ID)
            existing = store.get_channel(d.get("id")) if d.get("id") else None
            if existing:
                provider = existing["provider"]
            info = model_channels.provider_info(provider)
            fields = {
                "name": info["channel_name"],
                "provider": provider,
                "executable": "",
                "config_dir": "",
                "enabled": 1 if d.get("enabled", True) else 0,
                "is_default": 1 if d.get("is_default") else 0,
            }
            cid = store.upsert_channel(d.get("id"), fields)
            return self._json({"id": cid})
        m = re.match(r"^/api/channel/(\d+)/probe$", p)
        if m:
            channel = store.get_channel(int(m.group(1)))
            if not channel:
                return self._json({"error": "渠道不存在"}, 404)
            return self._json({"channel": model_channels.public_channel(channel, with_status=True)})
        m = re.match(r"^/api/channel/(\d+)/connect$", p)
        if m:
            cid = int(m.group(1))
            if not store.set_channel_enabled(cid, True):
                return self._json({"error": "渠道不存在"}, 404)
            channel = store.get_channel(cid)
            public = model_channels.public_channel(channel, with_status=True)
            status = public.get("probe") or {}
            return self._json({
                "channel": public,
                "requires_login": bool(
                    status.get("installed") and not status.get("authenticated")
                ),
            })
        m = re.match(r"^/api/channel/(\d+)/remove$", p)
        if m:
            cid = int(m.group(1))
            if not store.set_channel_enabled(cid, False):
                return self._json({"error": "渠道不存在"}, 404)
            return self._json({"channel": model_channels.public_channel(store.get_channel(cid))})
        m = re.match(r"^/api/channel/(\d+)/delete$", p)
        if m:
            ok, error = store.delete_channel(int(m.group(1)))
            return self._json({"ok": ok, "error": error}, 200 if ok else 400)
        m = re.match(r"^/api/trash/automation/(\d+)/restore$", p)
        if m:
            ok = automations.restore_automation(int(m.group(1)))
            return self._json({"ok": ok}, 200 if ok else 404)
        m = re.match(r"^/api/trash/automation/(\d+)/delete$", p)
        if m:
            ok = automations.delete_trashed_automation(int(m.group(1)))
            return self._json({"ok": ok}, 200 if ok else 404)
        self.send_response(404); self.end_headers()



class Server(ThreadingHTTPServer):
    daemon_threads = True
    def server_bind(self):
        # 跳过 HTTPServer.server_bind 里的 socket.getfqdn() 反向 DNS——
        # 冻结打包/无 DNS 环境下它会卡住(还会懒加载编码模块)。直接绑,手填 server_name。
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--runteams-apply-update":
        try:
            applied = app_update.apply_pending_update(sys.argv[2], store.data_dir())
        except app_update.UpdateError as exc:
            print("RunTeams 更新未应用：{}".format(exc), file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(10 if applied else 0)
    if len(sys.argv) >= 5 and sys.argv[1] == "--runteams-capability-launcher":
        import capability_launcher
        capability_launcher.main(sys.argv[2:])
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--runteams-task-tool":
        _run_frozen_task_tool()
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--runteams-caption-fit":
        _run_frozen_caption_fit()
        return
    if len(sys.argv) == 5 and sys.argv[1] == "--runteams-core-mcp":
        from runteams_core.protocol import main as run_core_protocol
        run_core_protocol(sys.argv[2], int(sys.argv[3]), sys.argv[4],
                          credential_resolver=app_secrets.resolve)
        return
    if len(sys.argv) == 2 and sys.argv[1] == "--runteams-agent-tools-mcp":
        from agent_tools_mcp import main as run_agent_tools_mcp
        run_agent_tools_mcp()
        return
    store.init_product_db()
    # 先取得 HTTP 监听端口，再触碰任何运行中状态。桌面端、误启动的第二实例或
    # 外部探测都可能短暂拉起同一可执行文件；若先 recover，它即使随后因端口
    # 占用退出，也会把真正主实例正在执行的任务错误标成 interrupted 并重新入队。
    srv = Server(("127.0.0.1", PORT), Handler)
    recovered_core = core_controller().start()
    _purge_expired_trash()
    runtime_capabilities.warm_plugin_icons(store.list_channels())
    recovered_automations = automations.recover_automation_runs()
    AUTOMATION_SCHEDULER.start()
    RELAY_SYNC.set_command_handler(_execute_mobile_command)
    RELAY_SYNC.start()
    UPDATES.start()
    print("RunTeams.ai 运行中 → http://127.0.0.1:{}".format(PORT))
    if recovered_automations:
        print("已恢复 {} 个意外中断的自动化".format(recovered_automations))
    if recovered_core:
        print("已恢复 {} 个新内核运行".format(len(recovered_core)))
    previous_term = signal.getsignal(signal.SIGTERM)

    def stop_server(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop_server)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_active_runs()
        RELAY_SYNC.stop()
        UPDATES.stop()
        srv.server_close()
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    main()
