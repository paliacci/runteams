"""Canonical atomic employee actions and their durable turn receipts."""
import json
from runteams_core import local_references
from contextlib import ExitStack
from . import device_data

def execute_actions(chat_id,actions,*,cancel_event=None):
    """Apply validated Agent actions once in the actual personal work ledger.

    The accepted user message identifies this turn. Receipt and effects share
    one transaction, so a lost reply reads the same result without another UI
    confirmation or a repeated task/document write.
    """
    from runteams_core import product_store as store
    from .contracts import digest
    from .device_work_services import current
    from .employee_context import current as employee_context
    from .work_identity import principal
    expected=device_data.identity()
    if not store.device_chat(chat_id):raise ValueError('本机对话不存在。')
    session=store.get_chat(chat_id)
    if not session or session.get('kind') not in ('general','employee_design'):
        raise ValueError('请在原工作对话继续。')
    allowed={'create_employee_task','create_pipeline_work','create_document','update_document'}
    if not actions or any(a.get('op') not in allowed for a in actions):
        raise ValueError('这项业务没有接通当前对话工具，未执行更改。')
    messages=session.get('messages') or []
    index=next((i for i in range(len(messages)-1,-1,-1) if messages[i].get('role')=='user'),None)
    if index is None:raise ValueError('原用户请求不存在，未执行更改。')
    source=messages[index]
    stream='device-chat-action:'+device_data.epoch(chat_id)+':'+str(source['id'])
    action_digest=digest(actions)
    work=current(channel_resolver=store.get_channel)
    from .employee_binding import document_owner
    with ExitStack() as owner, work.repository.audit_context(actor_id=principal(expected),source='agent_tool'),\
            work.repository.definition_lock(),work.repository.connect() as connection:
        work._actor()
        row=connection.execute("SELECT data_json FROM events WHERE stream=? AND type='chat.actions_applied' ORDER BY id DESC LIMIT 1",(stream,)).fetchone()
        if row:
            result=json.loads(row['data_json'])
            if result['actions_digest']!=action_digest:raise ValueError('本轮已执行其他内容，请核对原工作。')
            return result
        if not employee_context().allows_actions(work,session,actions):raise ValueError('请在绑定员工的个人工作对话中交办。')
        owner.enter_context(document_owner(session))
        authorization=work.repository.event('chat:'+str(chat_id),'task.dispatch_authorized',
            {'chat_id':chat_id,'message_id':source['id'],'device_chat_identity':device_data.epoch(chat_id)},
            source='agent_tool',connection=connection)
        context={'chat_id':chat_id,'conversation_context':session.get('context') or {},
            'dispatch_authorization_event_id':authorization,
            **local_references.conversation_source(source.get('attachments') or [],messages[:index])}
        applied,cards=[],[]
        for action in actions:
            if cancel_event is not None and cancel_event.is_set():
                from runteams_core.errors import Cancelled
                raise Cancelled('运行已停止')
            summary,effect=employee_context().apply_action(work,action,context)
            if action['op'] in ('create_document','update_document') and not (effect or {}).get('document_id'):
                raise ValueError('文档没有保存，请核对原操作。')
            applied.append(summary)
            if (effect or {}).get('run_card'):cards.append(effect['run_card'])
        result={'ok':True,'applied':applied,'run_cards':cards,'focus_pid':None,'device_only':True,
            'actions_digest':action_digest}
        work.repository.event(stream,'chat.actions_applied',result,source='agent_tool',connection=connection)
        if cancel_event is not None and cancel_event.is_set():
            from runteams_core.errors import Cancelled
            raise Cancelled('运行已停止')
        device_data.check(expected)
    return result

