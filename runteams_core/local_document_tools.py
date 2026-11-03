"""Apply completed personal-document submissions once in the existing ledger."""
import json
from . import device_data
from .contracts import ContractError, digest
from .local_documents import LocalDocuments
from .document_actions import apply_document_action


def _stream(chat_id, message):
    return 'device-chat-action:'+device_data.epoch(chat_id)+':'+str(message['id'])


def receipt(chat_id, operation):
    import product_store as store
    session=store.get_chat(chat_id)
    message=next((m for m in (session or {}).get('messages',[])
                  if m['role']=='user' and m.get('metadata',{}).get('local_turn_id')==operation),None)
    if not message:return None
    core=LocalDocuments()
    with core.repository.connect() as c:
        row=c.execute("SELECT data_json FROM events WHERE stream=? AND type='chat.actions_applied' ORDER BY id DESC LIMIT 1",
                      (_stream(chat_id,message),)).fetchone()
    return json.loads(row[0]) if row else None


def apply_submissions(chat_id, submissions, cancel):
    from agent_tool_registry import PROTOCOL
    actions=[action for item in submissions or [] if isinstance(item,dict)
             and item.get('protocol')==PROTOCOL and item.get('kind')=='change_proposal'
             for action in item.get('data',{}).get('actions',[])]
    if not actions:return {}
    if any(not isinstance(a,dict) or a.get('op') not in ('create_document','update_document') or a.get('data_view') for a in actions):
        raise ContractError('此入口只处理个人文档。')
    import product_store as store
    session=store.get_chat(chat_id)
    if not session or session.get('kind')!='general' or session.get('scope_pipeline_id'):
        raise ContractError('请在个人对话处理文档。')
    message=next((m for m in reversed(session['messages']) if m['role']=='user'),None)
    if not message:raise ContractError('原用户请求不存在。')
    core=LocalDocuments();action_digest=digest(actions)
    with core.repository.audit_context(actor_id=core._actor(),source='agent_tool'), core.repository.definition_lock(), core.repository.connect() as c:
        core._actor()
        row=c.execute("SELECT data_json FROM events WHERE stream=? AND type='chat.actions_applied' ORDER BY id DESC LIMIT 1",
                      (_stream(chat_id,message),)).fetchone()
        if row:
            result=json.loads(row[0])
            if result['actions_digest']!=action_digest:raise ContractError('本轮已执行其他内容，请核对原文档。')
            return result
        applied=[]
        for action in actions:
            if cancel.is_set():
                from errors import Cancelled
                raise Cancelled('运行已停止')
            if action['op']=='update_document' and type(action.get('base_revision')) is not int:
                raise ContractError('请重新读取文档并提供 base_revision。')
            if action['op']=='create_document' and action.get('document') is None:
                from .document_service import _normalize_agent_document_key
                key=_normalize_agent_document_key(action.get('document_key'),action.get('name'))
                if core._find_agent_document(c,key):
                    raise ContractError('文档已存在，请先读取后按当前版本更新。')
            summary,effect=apply_document_action(core,action)
            if not effect.get('document_id'):raise ContractError('文档没有保存。')
            applied.append(summary)
        result={'ok':True,'applied':applied,'run_cards':[],'focus_pid':None,'device_only':True,'actions_digest':action_digest}
        core.repository.event(_stream(chat_id,message),'chat.actions_applied',result,connection=c,source='agent_tool')
        if cancel.is_set():
            from errors import Cancelled
            raise Cancelled('运行已停止')
        core._actor()
        return result
