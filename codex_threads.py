# -*- coding: utf-8 -*-
"""Codex App Server 持久对话客户端。

这里只服务 RunTeams 顶层对话。流水线岗位继续使用一次性 ``codex exec``，保持
既有的隔离、工作区与进程治理语义。
"""
import json
import os
import queue
import signal
import subprocess
import threading
import time

from adapter_codex import CodexAdapter
import model_channels
from adapter_base import (AGENT_AUTHORITY_PROFILES, EXECUTION_INTERNAL_ANALYSIS,
                          validate_execution_profile)
import agent_stream
import agent_tool_registry
from errors import Cancelled


class CodexThreadError(RuntimeError):
    pass


def _agent_text_from_turn(turn):
    """Return the final assistant text embedded in a completed turn.

    Recent Codex app-server builds may deliver ``turn/completed`` before the
    separate ``item/completed`` notification.  The completed turn already
    contains its items, so treating the item notification as the only source
    of the final answer creates a false "no reply" failure despite a successful
    model turn.
    """
    final_text = ""
    for item in (turn or {}).get("items") or []:
        if item.get("type") != "agentMessage" or not item.get("text"):
            continue
        if item.get("phase") == "final_answer":
            final_text = str(item.get("text"))
    return final_text


def _server_argv(executable, extensions_enabled):
    argv = [executable, "app-server", "--listen", "stdio://"]
    features = ("plugins", "remote_plugin", "apps")
    flag = "--enable" if extensions_enabled else "--disable"
    for feature in features:
        argv += [flag, feature]
    return argv


def _item_type(value):
    return str(value or "").replace("_", "").replace("-", "").lower()


def _is_protocol_item(value):
    """Conversation framing is not user-visible tool work."""
    return _item_type(value) in ("usermessage", "reasoning", "plan")


def _stop_process(process):
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=1)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:
                process.kill()
        except Exception:
            pass


def _sandbox_settings(execution_profile, cwd):
    """Translate RunTeams' explicit execution profile to App Server settings."""
    execution_profile = validate_execution_profile(execution_profile)
    if execution_profile in AGENT_AUTHORITY_PROFILES:
        return "danger-full-access", {"type": "dangerFullAccess"}
    if execution_profile == EXECUTION_INTERNAL_ANALYSIS:
        return "read-only", {"type": "readOnly"}
    raise ValueError("无法映射 Agent 执行策略：{}".format(execution_profile))


def run_turn(channel, thread_id, message, developer_instructions, *, model="", effort="",
             cwd=None, image_paths=None, extensions_enabled=False, timeout=180,
             on_activity=None, on_thread=None, on_title=None, execution_profile,
             cancel_event=None, tool_context=None, tool_names=None,
             require_final_text=True):
    """开始或恢复官方 Codex thread，并等待一轮完成。"""
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled("运行已停止")
    executable = model_channels.resolve_channel_executable(channel)
    env = model_channels._probe_env(channel)
    process = subprocess.Popen(
        _server_argv(executable, extensions_enabled),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, cwd=cwd, bufsize=1,
        start_new_session=(os.name != "nt"))
    lines, stderr = queue.Queue(), []

    def read_stdout():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    def read_stderr():
        try:
            for line in process.stderr:
                stderr.append(line)
        except Exception:
            pass

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()
    next_id = 0
    responses, notifications, user_input_requests, native_tool_results = {}, [], [], []
    deadline = time.monotonic() + timeout
    active_thread_id = thread_id or ""
    official_title = ""
    # Persistent user-facing conversations now return ordinary text. Product
    # interactions travel through native tool calls instead of a JSON wrapper.
    reply_stream = agent_stream.ReplyDeltaStream(on_activity)
    agent_message_phases, work_buffers = {}, {}

    def emit_work(item_id, value, complete=False):
        key = str(item_id or "commentary")
        text = str(value or "")
        previous = work_buffers.get(key, "")
        delta = text[len(previous):] if complete and text.startswith(previous) else text
        if not delta:
            return
        work_buffers[key] = text if complete else previous + delta
        agent_stream.emit(on_activity, {"kind": "work_delta", "id": key, "delta": delta})

    def send(payload):
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def request(method, params):
        nonlocal next_id
        next_id += 1
        request_id = next_id
        send({"method": method, "id": request_id, "params": params})
        return request_id

    def handle(message_data):
        nonlocal official_title
        if message_data.get("id") is not None and not message_data.get("method"):
            responses[message_data.get("id")] = message_data
            return
        method = message_data.get("method") or ""
        params = message_data.get("params") or {}
        if method == "thread/name/updated":
            title = str(params.get("threadName") or "").strip()
            if title:
                official_title = title
                if on_title:
                    on_title(title)
        elif method == "item/tool/requestUserInput" and message_data.get("id") is not None:
            questions = params.get("questions") or []
            request = {
                "thread_id": str(params.get("threadId") or ""),
                "turn_id": str(params.get("turnId") or ""),
                "item_id": str(params.get("itemId") or "request_user_input"),
                "questions": questions if isinstance(questions, list) else [],
            }
            user_input_requests.append(request)
            step_id = request["item_id"] or "request_user_input"
            question_text = next((str(item.get("question") or "").strip()
                                  for item in request["questions"]
                                  if isinstance(item, dict) and item.get("question")), "")
            agent_stream.emit(on_activity, {
                "kind": "step", "id": step_id, "step_kind": "tool",
                "label": "request_user_input", "status": "running",
                "detail": question_text, "output": "", "meta": {}})
            # RunTeams renders the captured request as its own choice card. Resolve the
            # app-server request with an empty answer so this transport turn can finish;
            # the user's selected label is sent as the next official conversation turn.
            answers = {str(item.get("id")): {"answers": []}
                       for item in request["questions"]
                       if isinstance(item, dict) and item.get("id")}
            send({"id": message_data["id"], "result": {"answers": answers}})
            agent_stream.emit(on_activity, {
                "kind": "step", "id": step_id, "step_kind": "tool",
                "label": "request_user_input", "status": "completed",
                "detail": question_text, "output": "", "meta": {}})
        elif method == "item/tool/call" and message_data.get("id") is not None:
            tool = str(params.get("tool") or "")
            try:
                call_context = dict(tool_context or {})
                call_context.update({
                    "thread_id": str(params.get("threadId") or ""),
                    "turn_id": str(params.get("turnId") or ""),
                    "call_id": str(params.get("callId") or tool),
                })
                result = agent_tool_registry.dispatch(
                    tool, params.get("arguments") or {}, call_context)
            except agent_tool_registry.AgentToolError as exc:
                send({"id": message_data["id"], "error": {
                    "code": -32602, "message": str(exc)}})
                return
            if result.kind == "choice":
                request = {
                    "thread_id": str(params.get("threadId") or ""),
                    "turn_id": str(params.get("turnId") or ""),
                    "item_id": str(params.get("callId") or tool),
                    "questions": result.data.get("questions") or [],
                }
                user_input_requests.append(request)
            if result.kind in ("choice", "change_proposal", "employee_draft"):
                native_tool_results.append(result.envelope())
            send({"id": message_data["id"],
                  "result": agent_tool_registry.codex_call_result(result)})
        elif message_data.get("id") is not None:
            # 审批等尚未接入的服务端请求必须明确拒绝，避免整轮对话挂死。
            send({"id": message_data["id"], "error": {
                "code": -32000, "message": "RunTeams 当前无法处理这个交互请求"}})
        else:
            notifications.append(message_data)

    def read_one(wait=None):
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled("运行已停止")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexThreadError("Codex 对话超时 {}s".format(timeout))
        poll = min(remaining, wait) if wait else remaining
        if cancel_event is not None:
            poll = min(poll, 0.1)
        try:
            line = lines.get(timeout=poll)
        except queue.Empty:
            if cancel_event is not None and cancel_event.is_set():
                raise Cancelled("运行已停止")
            return False
        if line is None:
            raise CodexThreadError("Codex App Server 意外退出")
        try:
            handle(json.loads(line))
        except json.JSONDecodeError:
            pass
        return True

    def wait_response(request_id):
        while request_id not in responses:
            read_one()
        response = responses.pop(request_id)
        if response.get("error"):
            error = response.get("error") or {}
            raise CodexThreadError(error.get("message") or "Codex App Server 请求失败")
        return response.get("result") or {}

    try:
        init_id = request("initialize", {
            "clientInfo": {
                "name": "runteams", "title": "RunTeams.ai", "version": "0.1",
            },
            # Dynamic tools are negotiated behind the App Server experimental API
            # capability. Without this declaration thread/start rejects dynamicTools.
            "capabilities": {"experimentalApi": True},
        })
        wait_response(init_id)
        send({"method": "initialized", "params": {}})

        sandbox_mode, sandbox_policy = _sandbox_settings(execution_profile, cwd)
        thread_params = {
            "model": model or None,
            "cwd": cwd or None,
            "approvalPolicy": "never",
            "sandbox": sandbox_mode,
            "developerInstructions": developer_instructions,
        }
        if active_thread_id:
            thread_params["threadId"] = active_thread_id
            thread_result = wait_response(request("thread/resume", thread_params))
        else:
            thread_params["ephemeral"] = False
            thread_params["serviceName"] = "runteams"
            thread_params["threadSource"] = "runteams"
            thread_params["dynamicTools"] = agent_tool_registry.codex_dynamic_definitions(
                tool_names)
            thread_result = wait_response(request("thread/start", thread_params))
        thread = thread_result.get("thread") or {}
        active_thread_id = str(thread.get("id") or active_thread_id).strip()
        if not active_thread_id:
            raise CodexThreadError("Codex App Server 没有返回会话 ID")
        official_title = str(thread.get("name") or "").strip()
        if on_thread:
            on_thread(active_thread_id, official_title)
        if official_title and on_title:
            on_title(official_title)

        inputs = [{"type": "text", "text": message}]
        for path in image_paths or []:
            inputs.append({"type": "localImage", "path": path})
        turn_params = {
            "threadId": active_thread_id,
            "input": inputs,
            "cwd": cwd or None,
            "approvalPolicy": "never",
            "sandboxPolicy": sandbox_policy,
            "model": model or None,
            "effort": effort or None,
        }
        turn_result = wait_response(request("turn/start", turn_params))
        turn_id = str((turn_result.get("turn") or {}).get("id") or "")
        final_text, turn_error, usage = "", "", {}
        completed = False
        while not completed:
            if notifications:
                event = notifications.pop(0)
            else:
                read_one()
                continue
            method, params = event.get("method") or "", event.get("params") or {}
            event_turn = params.get("turn") or {}
            if method == "item/started":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage":
                    agent_message_phases[str(item.get("id") or "commentary")] = item.get("phase")
                elif not _is_protocol_item(item.get("type")):
                    agent_stream.emit(on_activity, agent_stream.step_event(item, "running"))
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("text"):
                    item_id = str(item.get("id") or "commentary")
                    phase = item.get("phase") or agent_message_phases.get(item_id)
                    if phase == "commentary":
                        emit_work(item_id, item.get("text"), complete=True)
                    else:
                        reply_stream.feed(item.get("text"), complete=True)
                    if phase == "final_answer":
                        final_text = str(item.get("text"))
                elif not _is_protocol_item(item.get("type")):
                    agent_stream.emit(on_activity, agent_stream.step_event(
                        item, "failed" if item.get("status") == "failed" else "completed",
                        output=item.get("aggregatedOutput") or item.get("output") or ""))
            elif method == "item/agentMessage/delta":
                item_id = str(params.get("itemId") or params.get("item_id") or "commentary")
                delta = params.get("delta") or params.get("text") or ""
                if agent_message_phases.get(item_id) == "commentary":
                    emit_work(item_id, delta)
                else:
                    reply_stream.feed(delta)
            elif method == "item/reasoning/summaryTextDelta":
                agent_stream.emit(on_activity, {
                    "kind": "reasoning_delta", "delta": str(params.get("delta") or "")})
            elif method == "item/plan/delta":
                agent_stream.emit(on_activity, {
                    "kind": "plan_delta", "delta": str(params.get("delta") or "")})
            elif method == "item/commandExecution/outputDelta":
                agent_stream.emit(on_activity, {
                    "kind": "step_output", "id": str(params.get("itemId") or
                                                         params.get("item_id") or "command"),
                    "delta": str(params.get("delta") or "")[-2000:]})
            elif method == "error":
                error = params.get("error") or {}
                turn_error = str(error.get("message") or params.get("message") or "Codex 运行失败")
            elif method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage") or params.get("usage") or usage
            elif method == "turn/completed" and (not turn_id or event_turn.get("id") == turn_id):
                status = event_turn.get("status")
                if status != "completed":
                    error = event_turn.get("error") or {}
                    turn_error = str(error.get("message") or turn_error or "Codex 对话未完成")
                if not final_text:
                    final_text = _agent_text_from_turn(event_turn)
                completed = True

        # turn 完成后从官方 thread 再读一次标题。标题事件若已到达，也会在等待
        # response 的过程中被 handle() 同步处理。
        read_result = wait_response(request(
            "thread/read", {"threadId": active_thread_id,
                            "includeTurns": not bool(final_text)}))
        read_thread = read_result.get("thread") or {}
        title = str(read_thread.get("name") or "").strip()
        if title:
            official_title = title
            if on_title:
                on_title(title)

        # Final fallback for app-server notification ordering/version changes.
        # The official thread is authoritative and the current turn id keeps us
        # from accidentally returning an earlier assistant response.
        if not final_text:
            turns = read_thread.get("turns") or []
            current_turn = next((item for item in reversed(turns)
                                 if not turn_id or item.get("id") == turn_id), None)
            final_text = _agent_text_from_turn(current_turn)

        if turn_error:
            raise CodexThreadError(turn_error)
        if not final_text and require_final_text:
            raise CodexThreadError("Codex 没有返回最终回复")
        return {"text": final_text, "thread_id": active_thread_id,
                "title": official_title, "meta": usage,
                "user_input_requests": user_input_requests,
                "native_tool_results": native_tool_results}
    except CodexThreadError as exc:
        blob = str(exc) + "\n" + "".join(stderr)
        # 复用既有订阅渠道的限流/网络错误分类。
        CodexAdapter().classify_error(blob, True, process.poll() or 1)
        raise
    finally:
        _stop_process(process)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except Exception:
                pass


def _single_thread_request(channel, method, params, timeout=8):
    executable = model_channels.resolve_channel_executable(channel)
    return model_channels._codex_app_server_request(
        executable, model_channels._probe_env(channel), method, params, timeout)


def set_name(channel, thread_id, title):
    return _single_thread_request(channel, "thread/name/set", {
        "threadId": thread_id, "name": title})


def delete_thread(channel, thread_id):
    return _single_thread_request(channel, "thread/delete", {"threadId": thread_id})
