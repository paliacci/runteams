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
import uuid

from runteams_core.agents.adapters.adapter_codex import CodexAdapter
from runteams_core.agents.models import model_channels
from runteams_core.agents.adapters.adapter_base import AGENT_AUTHORITY_PROFILES, EXECUTION_INTERNAL_ANALYSIS, validate_execution_profile
from runteams_core.agents import agent_stream
from runteams_core.agents.tools import agent_tool_registry
from runteams_core.agents import codex_processes
from runteams_core.foundation.errors import Cancelled

# Process-local native provider definition: same OpenAI authentication/default
# endpoint and provider semantics, HTTP Responses streaming instead of WebSocket.
# A random private id avoids replacing any user-owned provider definition.
_HTTP_PROVIDER = 'runteams_http_' + uuid.uuid4().hex


class CodexThreadError(RuntimeError):
    pass


class TurnControl:
    """Forward steering on the existing app-server connection, never a new turn."""
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = queue.Queue()
        self.requests = {}
        self.ready = False
        self.closed = False

    def activate(self):
        with self.lock:
            if not self.closed:
                self.ready = True

    def deactivate(self):
        with self.lock:
            self.ready = False

    def submit(self, key, text, accept):
        with self.lock:
            previous = self.requests.get(key)
            if previous:
                if previous['text'] != text:
                    raise ValueError("这次补充的内容已改变，请重新发送")
                return previous
            if not self.ready or self.closed:
                raise ValueError("当前工作已结束或尚未准备好，请保留输入后重新发送")
            command = {'key': key, 'text': text, 'accept': accept,
                       'done': threading.Event(), 'result': None, 'error': '', 'native_accepted': False}
            self.requests[key] = command
            self.pending.put(command)
            return command

    def resolve(self, command, response, turn_id):
        with self.lock:
            if command['done'].is_set():
                return
            result = response.get('result') or {}
            if response.get('error') or result.get('turnId') != turn_id:
                command['error'] = ((response.get('error') or {}).get('message') or
                                    "当前工作已结束，请保留输入后重新发送")
            else:
                # Persist only after the official server has accepted the input.
                command['native_accepted'] = True
                try:
                    command['result'] = command['accept'](turn_id)
                except Exception:
                    command['error'] = "补充已交给助手，但记录未保存，请重新载入对话核对"
            command['done'].set()

    def close(self):
        with self.lock:
            self.ready = False
            self.closed = True
            for command in self.requests.values():
                if not command['done'].is_set():
                    command['error'] = "当前工作已结束，请保留输入后重新发送"
                    command['done'].set()


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
        if item.get("phase") == "final_answer" and item.get("delivery") != "async":
            final_text = str(item.get("text"))
    return final_text


def _server_argv(executable, extensions_enabled):
    argv = [executable, "app-server", "--listen", "stdio://"]
    features = ("plugins", "remote_plugin", "apps")
    flag = "--enable"  # Selections are preferences, never a native capability gate.
    for feature in features:
        argv += [flag, feature]
    return argv


def _item_type(value):
    return str(value or "").replace("_", "").replace("-", "").lower()


def _is_protocol_item(value):
    """Conversation framing is not user-visible tool work."""
    return _item_type(value) in ("usermessage", "reasoning", "plan", "contextcompaction")


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
             cwd=None, image_paths=None, extensions_enabled=True, timeout=180,
             on_activity=None, on_thread=None, on_title=None, execution_profile,
             cancel_event=None, tool_context=None, tool_names=None,
             require_final_text=True, preserve_tool_submissions=False,
             on_runtime=None, initialize_session=None, employee_mcp=None, runtime_owner=None,
             context_root=None):
    """开始或恢复官方 Codex thread，并等待一轮完成。"""
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled("运行已停止")
    executable = model_channels.resolve_channel_executable(channel)
    env = model_channels._probe_env(channel)
    from runteams_core.agents.environment import agent_environment
    env = agent_environment.execution_env(env, cwd,
        ((tool_context or {}).get('runtime') or {}).get('workspace_environment'))
    argv = _server_argv(executable, extensions_enabled)
    if context_root is not None:
        if (not cwd or os.path.realpath(context_root) != os.path.realpath(cwd)
                or initialize_session is not None or employee_mcp is not None):
            raise ValueError('托管对话上下文边界必须是当前工作目录')
        # Product-owned scratch space is its own project, even when a source
        # checkout hosts development data. Native global/workspace rules,
        # workspace config and skills still load normally inside this boundary.
        argv += ['-c', 'project_root_markers=[]']
    pooled = bool(runtime_owner and initialize_session is None and employee_mcp is None)
    if pooled:
        prefix = 'model_providers.' + _HTTP_PROVIDER + '.'
        for key, value in (('name', 'OpenAI'), ('wire_api', 'responses'),
                           ('requires_openai_auth', True), ('supports_websockets', False)):
            argv += ['-c', prefix + key + '=' + json.dumps(value)]
    if employee_mcp:
        if not callable(employee_mcp.get('on_approval')): raise ValueError('Employee approval route required')
        # Per-process config only; all existing native skills/plugins/MCP stay.
        # No write to the user's official Runtime profile or auth files.
        for name, config in employee_mcp['mcp_servers'].items():
            for key, value in config.items():
                if isinstance(value,dict):
                    for child, scalar in value.items():
                        argv += ['-c','mcp_servers.'+name+'.'+key+'.'+child+'='+json.dumps(scalar)]
                else:
                    argv += ['-c', 'mcp_servers.'+name+'.'+key+'='+json.dumps(value)]
    started = time.monotonic()
    timings = {}
    start_process = lambda: subprocess.Popen(
        argv,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, cwd=cwd, bufsize=1,
        start_new_session=(os.name != "nt"))
    # External session credentials and per-turn employee MCP bridges have their
    # own lifetime; do not keep those processes beyond their original scope.
    owner = tuple(runtime_owner) if pooled else None
    if pooled:
        signature = codex_processes.configuration_stamp(executable, argv, env, cwd, execution_profile,
                                                        **({'context_root': context_root} if context_root is not None else {}))
        connection, reused = codex_processes.POOL.acquire(owner, signature, thread_id, start_process, _stop_process)
    else:
        connection, reused = codex_processes.Connection(start_process, _stop_process), False
    process, lines, stderr = connection.process, connection.lines, connection.stderr
    timings.update(process_reused=reused, process_acquire_ms=round((time.monotonic()-started)*1000))
    healthy = False
    responses, notifications, user_input_requests, native_tool_results = {}, [], [], []
    early_requests = []
    deadline = time.monotonic() + timeout
    active_thread_id = thread_id or ""
    turn_id = ""
    interrupt_sent = False
    interrupt_deadline = None
    control = getattr(cancel_event, 'turn_control', None)
    if control is None and callable(getattr(on_activity, 'request_user_input_async', None)):
        control = TurnControl()
    steer_requests = {}
    deferred_questions = {}
    blocking_questions = {}
    native_idle = False
    async_question_items = {}
    official_title = ""
    final_text, usage = "", {}
    # Persistent user-facing conversations now return ordinary text. Product
    # interactions travel through native tool calls instead of a JSON wrapper.
    reply_stream = agent_stream.ReplyDeltaStream(on_activity)
    agent_message_phases, work_buffers = {}, {}
    tool_failures = {}

    class DeferredQuestion(Exception):
        pass

    def defer_question(native_id, questions, dynamic=False):
        from runteams_core.agents.agent_interaction import questions as normalize_questions
        questions = normalize_questions(questions)
        key = on_activity.request_user_input_deferred(questions)
        blocking_questions[native_id] = {'key': key, 'questions': questions,
                                         'dynamic': dynamic, 'turn_id': turn_id}

    def question_reply(rows):
        return '用户已回答提问，请依据答案继续原工作。\n' + json.dumps([
            {'question': q.get('question') or q.get('title'),
             'answer': answer['answers'].get(q['id'], {}).get('answers', [])}
            for entry, answer in rows for q in entry['questions']], ensure_ascii=False)

    def question_result(entry, answer):
        return agent_tool_registry.codex_call_result(agent_tool_registry.AgentToolResult(
            'user_input', '用户已回答，请依据这些答案继续当前工作。', answer)) if entry['dynamic'] else answer

    def emit_work(item_id, value, complete=False):
        key = str(item_id or "commentary")
        text = str(value or "")
        previous = work_buffers.get(key, "")
        delta = text[len(previous):] if complete and text.startswith(previous) else text
        if not delta:
            return
        timings.setdefault('first_output_ms', round((time.monotonic()-started)*1000))
        work_buffers[key] = text if complete else previous + delta
        agent_stream.emit(on_activity, {"kind": "work_delta", "id": key, "delta": delta})

    def send(payload):
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def request(method, params):
        connection.next_id += 1
        request_id = connection.next_id
        send({"method": method, "id": request_id, "params": params})
        return request_id

    def ask_user(questions):
        nonlocal deadline
        ask = getattr(on_activity, 'request_user_input', None)
        if not callable(ask):
            raise agent_tool_registry.AgentToolError('当前运行没有可回答问题的界面')
        started_wait = time.monotonic()
        try:
            return ask(questions)
        finally:
            deadline += time.monotonic() - started_wait

    def async_question(item):
        item_id = str(item.get('id') or '')
        if item_id in async_question_items:
            return
        ask = getattr(on_activity, 'request_user_input_async', None)
        if not item_id:
            raise CodexThreadError('异步提问缺少原问题编号')
        questions = [dict(q, id=json.dumps(['request_user_input_async', item_id, index],
                                           ensure_ascii=False, separators=(',', ':')))
                     for index, q in enumerate(item['questions'])]
        if not callable(ask) or not control:
            # Background/non-chat owners may consume the structured request from
            # the result. An optional question must not abort independent work or
            # become a fabricated final answer when there is no live chat UI.
            from runteams_core.agents.agent_interaction import questions as normalize_questions
            user_input_requests.append({'thread_id': active_thread_id, 'turn_id': turn_id,
                'item_id': item_id, 'questions': normalize_questions(questions), 'is_blocking': False})
            async_question_items[item_id] = None
            return
        # Same-turn user input is the official async-answer path. Native async
        # agentMessage items are not requestUserInput RPCs and need no empty reply.
        from hashlib import sha256
        client_id = 'question-' + sha256((active_thread_id + turn_id + item_id).encode()).hexdigest()
        def submit(answers, accept):
            rows = [{'questionItemId': q['id'], 'question': q.get('title') or q.get('question'),
                     'answer': '、'.join(answers[q['id']]['answers'])} for q in questions]
            text = '<send_user_message_question_reply>\n' + json.dumps(rows, ensure_ascii=False) + '\n</send_user_message_question_reply>'
            return control.submit(client_id, text, accept)
        async_question_items[item_id] = ask(questions, submit=submit)

    def handle(message_data):
        nonlocal official_title, deadline
        if message_data.get("id") is not None and not message_data.get("method"):
            command = steer_requests.pop(message_data.get('id'), None)
            if command is not None:
                control.resolve(command, message_data, turn_id)
                return
            responses[message_data.get("id")] = message_data
            return
        method = message_data.get("method") or ""
        params = message_data.get("params") or {}
        # Late notifications/RPCs from a finished turn must never enter the next
        # turn's trace, input broker or business tools on this warm connection.
        event_thread = params.get('threadId') or params.get('thread_id')
        event_turn = params.get('turnId') or params.get('turn_id') or (params.get('turn') or {}).get('id')
        if (pooled or native_idle or timings.get('question_continuations')) and ((event_thread and active_thread_id and event_thread != active_thread_id) or
                       event_turn in connection.finished_turns or
                       (event_turn and turn_id and event_turn != turn_id)):
            if message_data.get('id') is not None:
                send({'id':message_data['id'],'error':{'code':-32000,'message':'This turn is no longer active'}})
            return
        if (pooled or native_idle or timings.get('question_continuations')) and message_data.get('id') is not None and method and not turn_id:
            early_requests.append(message_data)
            return
        if method=='account/chatgptAuthTokens/refresh' and message_data.get('id') is not None and initialize_session is not None:
            # The temporary external-token session must not read/refresh another
            # app's credentials. Its owner can establish a new session explicitly.
            send({'id':message_data['id'],'error':{'code':-32000,'message':'External session credentials are not renewable here'}})
        elif method == "thread/name/updated":
            title = str(params.get("threadName") or "").strip()
            if title:
                official_title = title
                if on_title:
                    on_title(title)
        elif (method in ('item/tool/requestUserInput', 'tool/requestUserInput') and
              message_data.get('id') is not None and params.get('isBlocking') is False and
              callable(getattr(on_activity, 'request_user_input_async', None))):
            if (params.get('threadId') != active_thread_id or
                    turn_id and params.get('turnId') != turn_id):
                raise CodexThreadError('提问不属于当前工作')
            key = on_activity.request_user_input_async(params.get('questions') or [])
            deferred_questions[message_data['id']] = key
        elif method == 'serverRequest/resolved':
            if params.get('threadId') in (None, active_thread_id):
                entry = blocking_questions.get(params.get('requestId'))
                if entry:
                    entry['native_resolved'] = True
                key = deferred_questions.pop(params.get('requestId'), None)
                broker = getattr(cancel_event, 'questions', None)
                if key and broker:
                    broker.expire(key)
        elif (method in ('item/tool/requestUserInput', 'tool/requestUserInput') and
              message_data.get('id') is not None and
              on_runtime is None and
              callable(getattr(on_activity, 'request_user_input_deferred', None))):
            if params.get('threadId') not in (None, active_thread_id) or params.get('turnId') not in (None, turn_id):
                raise CodexThreadError('提问不属于当前工作')
            defer_question(message_data['id'], params.get('questions') or [])
        elif employee_mcp and message_data.get('id') is not None and method in (
                'item/commandExecution/requestApproval','item/fileChange/requestApproval',
                'mcpServer/elicitation/request','tool/requestUserInput','item/tool/requestUserInput'):
            try:
                if active_thread_id and params.get('threadId') not in (None,active_thread_id):
                    raise PermissionError('Official approval thread changed')
                answer = employee_mcp['on_approval'](method,params)
                send({'id':message_data['id'],'result':answer})
            except Exception:
                send({'id':message_data['id'],'error':{'code':-32000,'message':'Approval was not granted by the current work owner'}})
        elif method in ("item/tool/requestUserInput", "tool/requestUserInput") and message_data.get("id") is not None:
            ask = getattr(on_activity, 'request_user_input', None)
            if callable(ask):
                if (params.get('threadId') not in (None, active_thread_id) or
                        turn_id and params.get('turnId') not in (None, turn_id)):
                    raise CodexThreadError('提问不属于当前工作')
                answer = ask_user(params.get('questions') or [])
                send({'id': message_data['id'], 'result': answer})
                return
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
            call_id = str(params.get("callId") or tool)
            tool_failures.pop(call_id, None)
            try:
                if params.get('threadId') not in (None, active_thread_id) or params.get('turnId') not in (None, turn_id):
                    raise agent_tool_registry.AgentToolError('工具请求不属于当前工作')
                if tool_names is not None and tool not in tool_names:
                    raise agent_tool_registry.AgentToolError('当前会话未启用此工具，请使用本轮提供的工具。')
                call_context = dict(tool_context or {})
                # A bound business execution attests one exact native turn.
                # Keep its original protocol rather than changing that identity.
                if on_runtime is None and callable(getattr(on_activity, 'request_user_input_deferred', None)):
                    def deferred(questions):
                        defer_question(message_data['id'], questions, dynamic=True)
                        raise DeferredQuestion()
                    call_context['request_user_input'] = deferred
                elif callable(getattr(on_activity, 'request_user_input', None)):
                    call_context['request_user_input'] = ask_user
                call_context.update({
                    "thread_id": str(params.get("threadId") or ""),
                    "turn_id": str(params.get("turnId") or ""),
                    "call_id": call_id,
                })
                result = agent_tool_registry.dispatch(
                    tool, params.get("arguments"), call_context)
            except DeferredQuestion:
                return
            except agent_tool_registry.AgentToolError as exc:
                tool_failures[call_id] = str(exc)
                agent_stream.emit(on_activity, agent_stream.step_event({
                    "type": "dynamicToolCall", "id": call_id, "tool": tool,
                    "namespace": params.get("namespace") or "",
                    "arguments": params.get("arguments") or {},
                }, "failed", output=str(exc)))
                # A handled validation failure is a tool result, not a broken
                # RPC. Codex otherwise replaces the actionable message with
                # "dynamic tool request failed", preventing self-correction.
                send({"id": message_data["id"], "result": {
                    "success": False,
                    "contentItems": [{"type": "inputText", "text": str(exc)}]}})
                return
            if result.kind == "choice":
                request = {
                    "thread_id": str(params.get("threadId") or ""),
                    "turn_id": str(params.get("turnId") or ""),
                    "item_id": str(params.get("callId") or tool),
                    "questions": result.data.get("questions") or [],
                }
                user_input_requests.append(request)
            if result.kind in ("choice", "change_proposal", "creator_source"):
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
        nonlocal interrupt_sent, interrupt_deadline, deadline
        if cancel_event is not None and cancel_event.is_set():
            if not turn_id or native_idle:
                raise Cancelled("运行已停止")
            if not interrupt_sent:
                request('turn/interrupt', {'threadId': active_thread_id, 'turnId': turn_id})
                interrupt_sent = True
                interrupt_deadline = time.monotonic() + 5
            if time.monotonic() >= interrupt_deadline:
                # If the server stops acknowledging, finally terminates its
                # process group so a cancellation cannot leave it working.
                raise Cancelled("运行已停止")
        if control and control.ready and turn_id and not interrupt_sent:
            while True:
                try:
                    command = control.pending.get_nowait()
                except queue.Empty:
                    break
                if command['done'].is_set():
                    continue
                steer_id = request('turn/steer', {
                    'threadId': active_thread_id, 'expectedTurnId': turn_id,
                    'clientUserMessageId': command['key'],
                    'input': [{'type': 'text', 'text': command['text']}],
                })
                steer_requests[steer_id] = command
        # Never wait for a non-blocking question in the stdout reader. Independent
        # work and cancellation continue; a real answer replies on its original RPC.
        broker = getattr(cancel_event, 'questions', None)
        for native_id, key in list(deferred_questions.items()):
            answer = broker.response(key) if broker else None
            if answer is not None:
                send({'id': native_id, 'result': answer})
                deferred_questions.pop(native_id, None)
        for native_id, entry in list(blocking_questions.items()):
            answer = broker.response(entry['key']) if broker else None
            if answer is not None and not entry.get('native_resolved') and not native_idle and entry['turn_id'] == turn_id and not notifications and lines.empty():
                send({'id': native_id, 'result': question_result(entry, answer)})
                blocking_questions.pop(native_id, None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexThreadError("Codex 对话超时 {}s".format(timeout))
        poll = min(remaining, wait) if wait else remaining
        if cancel_event is not None or deferred_questions:
            poll = min(poll, 0.1)
        poll_started = time.monotonic()
        try:
            line = lines.get(timeout=poll)
        except queue.Empty:
            if blocking_questions:
                deadline += time.monotonic() - poll_started
            if cancel_event is not None and cancel_event.is_set() and not turn_id:
                raise Cancelled("运行已停止")
            return False
        if blocking_questions:
            deadline += time.monotonic() - poll_started
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
            error_event = (agent_stream.provider_error_event(error) or
                           agent_stream.provider_error_event(error.get('data')))
            if error_event:
                agent_stream.emit(on_activity, error_event)
            raise CodexThreadError(error.get("message") or "Codex App Server 请求失败")
        return response.get("result") or {}

    try:
        phase_started = time.monotonic()
        if not connection.initialized:
            init_id = request("initialize", {
                "clientInfo": {
                    "name": "runteams", "title": "RunTeams.ai", "version": "0.1",
                },
                # Dynamic tools are negotiated behind the experimental API.
                "capabilities": {"experimentalApi": True},
            })
            wait_response(init_id)
            send({"method": "initialized", "params": {}})
            connection.initialized = True
        timings['initialize_ms'] = round((time.monotonic()-phase_started)*1000)
        if pooled:
            if not connection.provider_selected:
                # Read the effective native layers, not a separate scan or a
                # hand-parsed profile. Respect explicitly configured providers,
                # endpoints and managed configuration; native policy still
                # validates thread/start/resume and every tool invocation.
                config_result = wait_response(request('config/read', {'includeLayers': False}))
                config = config_result.get('config')
                if (isinstance(config, dict) and config.get('model_provider') in (None, '', 'openai')
                        and not config.get('openai_base_url')
                        and str(config.get('chatgpt_base_url') or '').rstrip('/') in
                            ('', 'https://chatgpt.com/backend-api')):
                    connection.model_provider = _HTTP_PROVIDER
                connection.provider_selected = True
            timings['transport'] = 'responses_http' if connection.model_provider else 'native_configured'
        if initialize_session is not None:
            # Trusted host callback, never serialized as model input, channel
            # configuration or a tool. Allows an independently owned official
            # in-memory session without editing another profile's credentials.
            initialize_session(lambda method,params:wait_response(request(method,params)))

        sandbox_mode, sandbox_policy = _sandbox_settings(execution_profile, cwd)
        thread_params = {
            "model": model or None,
            "cwd": cwd or None,
            "approvalPolicy": "never",
            "sandbox": sandbox_mode,
            "developerInstructions": developer_instructions,
        }
        if pooled and connection.model_provider:
            thread_params['modelProvider'] = connection.model_provider
            # A failed optional login-shell snapshot was another cold-start
            # wait. Keep command execution and native environment/login policy;
            # disable only its startup cache on this standard HTTP chat route.
            thread_params['config'] = {'features.shell_snapshot': False}
        if employee_mcp:
            # Use the official user's/organization's effective approval and
            # sandbox configuration. Never apply the legacy all-access profile.
            thread_params.pop('approvalPolicy'); thread_params.pop('sandbox')
        thread_signature = json.dumps([thread_params, list(tool_names or [])], sort_keys=True)
        phase_started = time.monotonic()
        if reused and connection.thread_id == active_thread_id and connection.thread_signature == thread_signature:
            thread_result = {'thread': {'id': active_thread_id}}
        elif active_thread_id:
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
        connection.thread_id = active_thread_id
        connection.thread_signature = thread_signature
        timings['thread_setup_ms'] = round((time.monotonic()-phase_started)*1000)
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
        if employee_mcp:
            turn_params.pop('approvalPolicy'); turn_params.pop('sandboxPolicy')
        phase_started = time.monotonic()
        turn_result = wait_response(request("turn/start", turn_params))
        timings['turn_start_ms'] = round((time.monotonic()-phase_started)*1000)
        turn_id = str((turn_result.get("turn") or {}).get("id") or "")
        for pending_request in early_requests:
            handle(pending_request)
        early_requests.clear()
        if on_runtime is not None:
            if not turn_id:raise CodexThreadError('Codex App Server 没有返回本轮运行 ID')
            on_runtime({'provider':'codex','thread_id':active_thread_id,'native_turn_id':turn_id,'phase':'started'})
        if control and turn_id:
            control.activate()
            agent_stream.emit(on_activity, {'kind': 'turn_control', 'can_steer': True})
        final_text, turn_error, usage = "", "", {}
        completed = False
        while not completed:
            if native_idle:
                broker = getattr(cancel_event, 'questions', None)
                ready = [(native_id, entry, broker.response(entry['key'])) for native_id, entry in blocking_questions.items()]
                ready = [(native_id, entry, answer) for native_id, entry, answer in ready if answer is not None]
                if ready:
                    if cancel_event is not None and cancel_event.is_set():
                        raise Cancelled('运行已停止')
                    continuation = dict(turn_params, input=[{'type': 'text', 'text': question_reply([(entry, answer) for _, entry, answer in ready])}])
                    for native_id, entry, answer in ready:
                        if not entry.get('native_resolved'):
                            send({'id': native_id, 'result': question_result(entry, answer)})
                        blocking_questions.pop(native_id, None)
                    if cancel_event is not None and cancel_event.is_set():
                        raise Cancelled('运行已停止')
                    turn_id = ''
                    deadline = time.monotonic() + timeout
                    if control:
                        control = TurnControl()
                        if cancel_event is not None:
                            cancel_event.turn_control = control
                    resumed = wait_response(request('turn/start', continuation))
                    turn_id = str((resumed.get('turn') or {}).get('id') or '')
                    if not turn_id:
                        raise CodexThreadError('Codex 没有确认提问后的继续处理，请勿重复提交答案')
                    native_idle = False
                    timings['question_continuations'] = timings.get('question_continuations', 0) + 1
                    final_text, turn_error = '', ''
                    reply_stream = agent_stream.ReplyDeltaStream(on_activity)
                    agent_stream.emit(on_activity, {'kind': 'reply_reset', 'text': ''})
                    for pending_request in early_requests:
                        handle(pending_request)
                    early_requests.clear()
                    if control:
                        control.activate()
                    agent_stream.emit(on_activity, {'kind':'turn_control','can_steer':True})
            if notifications:
                event = notifications.pop(0)
            else:
                read_one()
                continue
            method, params = event.get("method") or "", event.get("params") or {}
            event_turn = params.get("turn") or {}
            # Events received before turn/start's response were buffered before
            # the current id was known. Check them again when consuming them.
            event_thread_id = params.get('threadId') or params.get('thread_id')
            event_turn_id = params.get('turnId') or params.get('turn_id') or event_turn.get('id')
            if (pooled or native_idle or timings.get('question_continuations')) and ((event_thread_id and event_thread_id != active_thread_id) or
                           (event_turn_id and event_turn_id != turn_id)):
                continue
            if method == "item/started":
                item = params.get("item") or {}
                phase_event = agent_stream.runtime_item_event(item, True)
                if phase_event:
                    agent_stream.emit(on_activity, phase_event)
                if item.get("type") == "agentMessage":
                    agent_message_phases[str(item.get("id") or "commentary")] = "async" if item.get("delivery") == "async" else item.get("phase")
                elif not _is_protocol_item(item.get("type")):
                    agent_stream.emit(on_activity, agent_stream.step_event(item, "running"))
            elif method == "item/completed":
                item = params.get("item") or {}
                phase_event = agent_stream.runtime_item_event(item, False)
                if phase_event:
                    agent_stream.emit(on_activity, phase_event)
                if item.get('type') == 'agentMessage' and item.get('delivery') == 'async':
                    if item.get('questions'):
                        if params.get('threadId') != active_thread_id or params.get('turnId') != turn_id:
                            raise CodexThreadError('异步提问不属于当前工作')
                        async_question(item)
                    elif item.get('text'):
                        emit_work(item.get('id'), item['text'], complete=True)
                    continue
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
                    tool_error = tool_failures.get(str(item.get("id") or ""), "")
                    agent_stream.emit(on_activity, agent_stream.step_event(
                        item, "failed" if tool_error or item.get("status") == "failed" else "completed",
                        output=item.get("aggregatedOutput") or item.get("output") or
                               item.get("result") or item.get("error") or tool_error))
            elif method == "item/agentMessage/delta":
                item_id = str(params.get("itemId") or params.get("item_id") or "commentary")
                delta = params.get("delta") or params.get("text") or ""
                if delta:
                    timings.setdefault('first_output_ms', round((time.monotonic()-started)*1000))
                if agent_message_phases.get(item_id) == "async":
                    continue
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
            elif method == "account/rateLimits/updated":
                agent_stream.emit(on_activity, agent_stream.rate_limits_event(params.get('rateLimits')))
            elif method == "error":
                error = params.get("error") or {}
                error_event = agent_stream.provider_error_event(error, params.get('willRetry'))
                if error_event:
                    agent_stream.emit(on_activity, error_event)
                if params.get('willRetry') is True:
                    # A native reconnect notice is not this turn's outcome.
                    # The same native turn continues; never replay it here.
                    timings['native_retry_count'] = timings.get('native_retry_count', 0) + 1
                else:
                    turn_error = str(error.get("message") or params.get("message") or "Codex 运行失败")
            elif method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage") or params.get("usage") or usage
            elif method == "turn/completed" and (not turn_id or event_turn.get("id") == turn_id):
                status = event_turn.get("status")
                broker = getattr(cancel_event, 'questions', None)
                if status == 'completed' and blocking_questions:
                    # Native exec cells may yield, then finish the model turn while
                    # their question is still pending. Keep the product interaction
                    # alive; a later answer starts a continuation on this same thread.
                    native_idle = True
                    connection.finished_turns.append(turn_id)
                    if control:
                        control.close()
                    if broker:
                        for key in [*deferred_questions.values(), *async_question_items.values()]:
                            broker.expire(key)
                    deferred_questions.clear()
                    async_question_items.clear()
                    agent_stream.emit(on_activity, {'kind':'turn_control','can_steer':False})
                    continue
                for native_id, key in list(deferred_questions.items()):
                    answer = broker.response(key) if broker else None
                    if answer is not None:
                        send({'id': native_id, 'result': answer})
                    elif broker:
                        broker.expire(key)
                    deferred_questions.pop(native_id, None)
                if status == 'interrupted' and cancel_event is not None and cancel_event.is_set():
                    raise Cancelled("运行已停止")
                if control:
                    control.deactivate()
                    # Notifications and RPC responses may arrive out of order.
                    # Resolve already submitted inputs before saving the reply.
                    receipt_deadline = time.monotonic() + 2
                    while steer_requests and time.monotonic() < receipt_deadline:
                        read_one(wait=0.1)
                    control.close()
                if broker:
                    for key in async_question_items.values():
                        broker.expire(key)
                if status == "completed":
                    agent_stream.emit(on_activity, {'kind': 'provider_error_cleared'})
                if status != "completed":
                    error = event_turn.get("error") or {}
                    error_event = agent_stream.provider_error_event(error)
                    if error_event:
                        agent_stream.emit(on_activity, error_event)
                    turn_error = str(error.get("message") or turn_error or "Codex 对话未完成")
                if not final_text:
                    final_text = _agent_text_from_turn(event_turn)
                completed = True

        # turn 完成后从官方 thread 再读一次标题。标题事件若已到达，也会在等待
        # response 的过程中被 handle() 同步处理。
        optional_read = bool(final_text) and not turn_error and on_runtime is None and status == 'completed'
        read_failed = False
        original_deadline = deadline
        try:
            if optional_read:
                deadline = min(deadline, time.monotonic() + 2)
            read_result = wait_response(request(
                "thread/read", {"threadId": active_thread_id,
                                "includeTurns": bool(on_runtime) or not bool(final_text)}))
        except (CodexThreadError, BrokenPipeError, ConnectionError):
            if not optional_read:
                raise
            # Completed prose is already authoritative for an ordinary chat.
            # An optional title read cannot invalidate it. Discard the damaged
            # connection so a late response never leaks into another turn.
            read_result = {}
            read_failed = True
            timings['optional_thread_read_failed'] = True
        finally:
            deadline = original_deadline
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
        runtime_observation=None
        if on_runtime is not None:
            # A model's text or an earlier streamed completion cannot attest to
            # this exact turn. Confirm it with a read from the same native server.
            verified=next((item for item in read_thread.get('turns') or [] if item.get('id')==turn_id),None)
            if read_thread.get('id')!=active_thread_id or verified is None or verified.get('status')!='completed':
                raise CodexThreadError('本轮官方运行结果尚未核实')
            verified_text=_agent_text_from_turn(verified)
            if verified_text!=final_text:raise CodexThreadError('本轮官方运行正文与回执不一致')
            from hashlib import sha256
            runtime_observation={'provider':'codex','thread_id':active_thread_id,'native_turn_id':turn_id,
                'phase':'completed','output_sha256':sha256(final_text.encode()).hexdigest()}
            on_runtime(runtime_observation)
        healthy = not read_failed
        connection.finished_turns.append(turn_id)
        timings['total_ms'] = round((time.monotonic()-started)*1000)
        return {"text": final_text, "thread_id": active_thread_id,'turn_id':turn_id,
                'runtime_timings': timings,
                "title": official_title, "meta": usage,
                **({'runtime_observation':runtime_observation} if runtime_observation is not None else {}),
                "user_input_requests": user_input_requests,
                "native_tool_results": native_tool_results}
    except CodexThreadError as exc:
        # Keep complete, validated tool submissions if later prose is cut off.
        # The owning product path applies them using its durable receipt; a
        # transport interruption must never manufacture another approval card.
        if preserve_tool_submissions and any(
                item.get("kind") in ("creator_source", "change_proposal")
                for item in native_tool_results):
            return {"text": reply_stream.raw or final_text, "thread_id": active_thread_id,
                    "title": official_title, "meta": usage,
                    "incomplete": True,
                    "system_notice": {"kind": "runtime_interrupted", "text": "本轮回复未完成：" + str(exc)},
                    "user_input_requests": user_input_requests,
                    "native_tool_results": native_tool_results}
        blob = str(exc) + "\n" + "".join(stderr)
        # 复用既有订阅渠道的限流/网络错误分类。
        CodexAdapter().classify_error(blob, True, process.poll() or 1)
        raise
    finally:
        broker = getattr(cancel_event, 'questions', None)
        if broker:
            for key in [*deferred_questions.values(), *async_question_items.values(),
                        *(entry['key'] for entry in blocking_questions.values())]:
                broker.expire(key)
        if control:
            control.close()
        if pooled:
            codex_processes.POOL.release(owner, connection, healthy)
        else:
            connection.close()


def _single_thread_request(channel, method, params, timeout=8):
    executable = model_channels.resolve_channel_executable(channel)
    return model_channels._codex_app_server_request(
        executable, model_channels._probe_env(channel), method, params, timeout)


def set_name(channel, thread_id, title):
    return _single_thread_request(channel, "thread/name/set", {
        "threadId": thread_id, "name": title})


def delete_thread(channel, thread_id):
    codex_processes.POOL.close_thread(thread_id)
    return _single_thread_request(channel, "thread/delete", {"threadId": thread_id})
