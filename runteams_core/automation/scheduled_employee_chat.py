"""Background consumer of the *same* employee Chat handler for SDK programs.

The original handler owns native runtime, MCP enablement/approvals, messages,
questions and turn diagnostics. This adapter only consumes its normal events.
No alternate model client, tool executor or automatic approval is introduced.
"""
import json
import sqlite3
import threading

from runteams_core.storage import device_data
from runteams_core.foundation.contracts import ContractError


FAILURE_IN_CHAT = '请查看原工作对话。'


def _failure_notice(metadata):
    notice = metadata.get('system_notice') or {}
    if not isinstance(notice, dict) or notice.get('kind') not in ('error', 'runtime_interrupted'):
        return ''
    text = notice.get('execution_reason') or notice.get('text')
    return text.strip()[:500] if isinstance(text, str) else ''


def recorded_failure_reason(chat_id, started_at, ended_at):
    """Read an older failure from the exact device chat and execution window."""
    if type(chat_id) is not int or chat_id < device_data.LOCAL_CHAT_ID_MIN or not started_at or not ended_at:
        return ''
    try:
        with device_data.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT metadata FROM chat_messages WHERE chat_id=? AND role IN ('bot','assistant') "
                "AND julianday(ts) BETWEEN julianday(?) AND julianday(?) "
                "AND (json_extract(metadata,'$.trace.failed')=1 OR json_extract(metadata,'$.incomplete')=1) "
                "LIMIT 2", (chat_id, started_at, ended_at)).fetchall()
        return _failure_notice(json.loads(rows[0][0])) if len(rows) == 1 else ''
    except (OSError, sqlite3.Error, ValueError):
        return ''


def outcome(chat_id,after_message_id=None,*,response_message_id=None):
    """Read a turn's status and return its reply only for a confirmed response ID."""
    from runteams_core.storage import product_store as store
    session = store.get_chat(chat_id)
    if not session:
        return 'interrupted', '原工作对话需要核对，不会自动重做。'
    messages = session.get('messages') or []
    if after_message_id is not None:
        current = []
        for message in messages:
            if message['id'] <= after_message_id:
                continue
            if message['role'] == 'user':
                metadata = message.get('metadata') or {}
                if not (metadata.get('question_request_id') or metadata.get('steer_request_id')):
                    break
            current.append(message)
        messages = current
    bot = next((m for m in reversed(messages) if m['role'] in ('bot', 'assistant') and
                (response_message_id is None or m['id'] == response_message_id)), None)
    if bot:
        metadata = bot.get('metadata') or {}
        trace = metadata.get('trace') or {}
        if metadata.get('pending'):
            return 'blocked', '工作需要确认，请查看原对话。'
        if trace.get('cancelled'):
            return 'cancelled', (metadata.get('system_notice') or {}).get('text') or FAILURE_IN_CHAT
        if trace.get('failed') or metadata.get('incomplete'):
            return 'failed', _failure_notice(metadata) or FAILURE_IN_CHAT
        if trace.get('complete'):
            if response_message_id is not None and not metadata.get('system_notice'):
                return 'completed', bot.get('text') or ''
            return 'completed', ''
    return 'interrupted', '原工作未确认完成，请查看对话，不会自动重做。'


def execute(host, backend, job, asset, cancel_event=None):
    from runteams_core.storage import product_store as store
    device_data.check(backend.scope)
    from runteams_core.employees.employee_context import current
    if not current().scheduled_host_ready(host):
        raise ContractError('员工程序的原生工作宿主尚未就绪。')
    snapshot = json.loads(job['snapshot'])
    payload = json.loads(snapshot['payload'])
    # Persist the dedicated normal employee conversation before spending a turn.
    # A pre-existing admission is inspected, never sent again.
    with backend.connection(write=True) as c:
        prior = c.execute('SELECT chat_id,status FROM occurrences WHERE id=?', (job['id'],)).fetchone()
        if prior is None or prior['chat_id'] or prior['status'] not in ('queued','running'):
            return
        if asset.get('local_package'):
            from runteams_core.employees.source_employee_runtime import create_chat
            chat_id = create_chat(asset['local_package'],title=snapshot['name'],preferred_skill=payload['skill_key'])
        else:
            chat_id = current().scheduled_downloaded_chat(backend,asset,snapshot,payload,job)
        c.execute('UPDATE occurrences SET chat_id=? WHERE id=?', (chat_id, job['id']))

    return consume(host,backend,job,chat_id,payload,cancel_event)




def consume(host,backend,job,chat_id,payload,cancel_event=None):
    prompt=('这是一项已授权的定时工作，请现在完成并交付结果。需要人工决定时使用原有提问流程；'
            '不得重做结果未知的外部操作。\n\n'+payload['objective'])
    if payload['parameters']:prompt+='\n\n任务信息：\n'+json.dumps(payload['parameters'],ensure_ascii=False)
    from runteams_core.employees.employee_context import current
    status,reason=current().scheduled_turn(host,backend.scope,job['operation_id'],chat_id,prompt,cancel_event)
    with backend.connection(write=True) as c:
        c.execute("UPDATE occurrences SET status=?,reason=? WHERE id=? AND status NOT IN ('cancelled','canceled')",(status,'' if status == 'completed' else reason,job['id']))


