"""Read original messages in direct conversations owned by one local asset."""
import json

from runteams_core.storage import device_data

PAGE = 8
PREVIEW = 1200
CHUNK = 4000


def _conversations(binding, caller):
    ref = binding['reference']
    base = ("SELECT c.id,c.context_json FROM chats c JOIN device_chat_index i ON i.chat_id=c.id "
            "WHERE i.deleted=0 AND c.kind='general' AND c.scope_type='global' ")
    if 'pipeline_source' in ref:
        with device_data.connect(readonly=True) as connection:
            rows = connection.execute(
                base + "AND c.subject_type='workspace' "
                "AND json_extract(c.context_json,'$.source_pipeline_workspace.source_id')=?",
                (ref['source_id'],)).fetchall()
        return [r['id'] for r in rows if json.loads(r['context_json']).get('source_pipeline_workspace') == ref]

    # Check the authoritative employee binding as well as the candidate identity.
    # Old installed employees may have only their device employee ID on the chat.
    from runteams_core.conversations import asset_memory
    from runteams_core.foundation.contracts import ContractError
    with device_data.connect(readonly=True) as connection:
        rows = connection.execute(
            base + "AND c.subject_type='employee' "
            "AND json_extract(c.context_json,'$.pipeline_work') IS NULL "
            "AND json_extract(c.context_json,'$.employee_work') IS NULL AND "
            "(json_extract(c.context_json,'$.source_employee.source_id')=? OR "
            "json_extract(c.context_json,'$.employee_reference.source_id')=? OR "
            "json_extract(c.context_json,'$.employee_reference.id')=? OR "
            "c.employee_id=(SELECT employee_id FROM chats WHERE id=?))",
            (ref.get('source_id'), ref.get('source_id'), ref.get('id'), caller)).fetchall()
    ids = []
    for row in rows:
        try:
            owner = asset_memory._binding(row['id'])
        except (ContractError, PermissionError, FileNotFoundError):
            continue
        if owner and owner['writable'] and owner['bank'] == binding['bank']:
            ids.append(row['id'])
    return ids


def _number(args, key, default=None, minimum=1):
    value = args.get(key, default)
    if type(value) is not int or not minimum <= value < 2**63 - 1:
        raise ValueError('历史消息编号或读取位置无效。')
    return value


def query(args, binding, caller):
    detail = args['action'] == 'history_message'
    allowed = {'action', 'message', 'offset'} if detail else {'action', 'chat', 'before'}
    if set(args) - allowed:
        raise ValueError('历史查询参数无效。history 仅接受 chat、before；history_message 接受 message、offset。')
    identity = device_data.identity()
    ids = _conversations(binding, caller)
    with device_data.connect(readonly=True) as connection:
        device_data.check(identity)
        if 'chat' in args:
            selected = _number(args, 'chat')
            ids = [selected] if selected in ids else []
        scope = (" FROM chat_messages m JOIN chats c ON c.id=m.chat_id JOIN device_chat_index i ON i.chat_id=c.id "
                 "WHERE i.deleted=0 AND m.chat_id IN (SELECT value FROM json_each(?)) "
                 "AND m.role IN ('user','bot') AND m.text<>''")
        params = [json.dumps(ids)]
        if detail:
            scope += ' AND m.id=?'
            params.append(_number(args, 'message'))
        elif 'before' in args:
            prior = connection.execute('SELECT m.ts,m.id' + scope + ' AND m.id=?',
                                       (*params, _number(args, 'before'))).fetchone()
            if not prior:
                raise ValueError('历史记录已变化，请重新查询。')
            scope += ' AND (m.ts,m.id)<(?,?)'
            params.extend(prior)
        offset = _number(args, 'offset', 0, minimum=0) if detail else 0
        size = CHUNK if detail else PREVIEW
        rows = connection.execute(
            'SELECT m.id AS message,c.id AS chat,i.identity,c.context_json,c.title,m.ts,m.role,substr(m.text,?,?) AS text,'
            'length(m.text) AS length' + scope + ' ORDER BY m.ts DESC,m.id DESC LIMIT ?',
            (offset + 1, size, *params, 1 if detail else PAGE + 1)).fetchall()
    if detail and (not rows or rows[0]['length'] < offset):
        raise ValueError('当前资产内无此消息或原文位置无效。')
    from runteams_core.conversations.page_paths import chat_owner_paths, chat_key, short_ids
    messages = [dict(row) for row in rows[:PAGE]]
    owners = chat_owner_paths(json.loads(item.pop('context_json')) for item in messages)
    keys = [chat_key(item.pop('identity')) for item in messages]
    ids = short_ids(keys)
    for item, owner, key in zip(messages, owners, keys, strict=True):
        item['next_offset'] = offset + size if offset + size < item.pop('length') else None
        item['conversation_url'] = owner + '/chats/' + ids[key]
    if detail:
        return messages[0]
    return {'messages': messages, 'next_before': messages[-1]['message'] if len(rows) > PAGE else None}
