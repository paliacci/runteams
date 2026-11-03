"""Personal document tools reuse the device catalog and reviewed proposals."""
from copy import deepcopy


def dispatch(name, arguments, context):
    if name not in {'runteams_list_documents', 'runteams_get_document', 'runteams_propose_document'}:
        return None
    from runteams_core import agent_tool_registry as registry
    from runteams_core import product_store as store
    from runteams_core import device_data
    if not device_data.enabled():
        return None
    if not device_data.personal():
        raise registry.AgentToolError('请从个人工作区查看本机文档。')
    chat_id = context.get('chat_id')
    if chat_id and not store.device_chat(chat_id):
        raise registry.AgentToolError('原本机对话不存在，请重新打开。')
    session = store.get_chat(chat_id, include_messages=False) if chat_id else None
    if chat_id and (not session or session.get('kind') != 'general'):
        raise registry.AgentToolError('请从个人工作对话处理本机文档。')
    saved = (session or {}).get('context') or {}
    if (session or {}).get('scope_pipeline_id') or saved.get('scope_type') not in (None, '', 'global'):
        raise registry.AgentToolError('请从个人工作区查看本机文档。')
    expected = device_data.identity()
    local = expected.get('storage_kind') == 'local'
    actor = expected['library_id'] if local else expected['account_id']
    if (context.get('library_id') if local else context.get('actor_id')) != actor:
        raise PermissionError('账户已变化，请重新打开本机文档。')
    values = deepcopy(arguments)
    if values.get('data_view'):
        raise registry.AgentToolError('共享业务视图请从原业务入口处理。')
    if local:
        from runteams_core.local_documents import LocalDocuments
        work = LocalDocuments()
        if name == 'runteams_propose_document' and values.get('operation') == 'update' and type(values.get('base_revision')) is not int:
            raise registry.AgentToolError('请先读取当前文档并提供 base_revision。')
    else:
        from runteams_core.device_work_services import current as device_work_service
        work = device_work_service(channel_resolver=store.get_channel)
    with work.repository.audit_context(actor_id=actor, source='agent_tool'):
        work._actor()
        ctx = {**context, 'conversation_context':saved}
        if name == 'runteams_propose_document':
            result = registry._propose_document(values, ctx)
        else:
            handler = registry._list_documents if name == 'runteams_list_documents' else registry._get_document
            result = handler(values, ctx, core=work)
        device_data.check(expected)
        return result
