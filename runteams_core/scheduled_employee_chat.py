"""Background consumer of the *same* employee Chat handler for SDK programs.

The original handler owns native runtime, MCP enablement/approvals, messages,
questions and turn diagnostics. This adapter only consumes its normal events.
No alternate model client, tool executor or automatic approval is introduced.
"""
import json
import threading

from . import device_data
from .contracts import ContractError


def outcome(chat_id,after_message_id=None):
    import product_store as store
    session = store.get_chat(chat_id)
    if not session:
        return 'interrupted', '原工作对话需要核对，不会自动重做。'
    bot = next((m for m in reversed(session.get('messages') or [])
        if m['role'] in ('bot', 'assistant') and
        (after_message_id is None or m['id']>after_message_id)), None)
    if bot:
        metadata = bot.get('metadata') or {}
        trace = metadata.get('trace') or {}
        if metadata.get('pending'):
            return 'blocked', '工作需要确认，请查看原对话。'
        if trace.get('cancelled'):
            return 'cancelled', '请查看原工作对话。'
        if trace.get('failed') or metadata.get('incomplete'):
            return 'failed', '请查看原工作对话。'
        if trace.get('complete'):
            return 'completed', ''
    return 'interrupted', '原工作未确认完成，请查看对话，不会自动重做。'


def execute(host, backend, job, asset, cancel_event=None):
    import product_store as store
    device_data.check(backend.scope)
    from .employee_context import current
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
            from .source_employee_runtime import create_chat
            chat_id = create_chat(asset['local_package'],title=snapshot['name'],preferred_skill=payload['skill_key'])
        else:
            chat_id = current().scheduled_downloaded_chat(backend,asset,snapshot,payload,job)
        c.execute('UPDATE occurrences SET chat_id=? WHERE id=?', (chat_id, job['id']))

    return consume(host,backend,job,chat_id,payload,cancel_event)




def consume(host,backend,job,chat_id,payload,cancel_event=None):
    prompt=('这是一项已授权的定时工作，请现在完成并交付结果。需要人工决定时使用原有提问流程；'
            '不得重做结果未知的外部操作。\n\n'+payload['objective'])
    if payload['parameters']:prompt+='\n\n任务信息：\n'+json.dumps(payload['parameters'],ensure_ascii=False)
    from .employee_context import current
    status,reason=current().scheduled_turn(host,backend.scope,job['operation_id'],chat_id,prompt,cancel_event)
    with backend.connection(write=True) as c:
        c.execute('UPDATE occurrences SET status=?,reason=? WHERE id=?',(status,reason,job['id']))


