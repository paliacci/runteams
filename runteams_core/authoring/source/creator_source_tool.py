"""The product authoring entry: SDK source, never a parallel employee definition.

New drafts and fully submitted projects share LocalSources/Revisions with imports.
Existing definitions are historical data, not permission to invent SDK provenance.
"""
import json
import uuid

from runteams_core.storage import device_data
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, decode_files, digest, strict_json
from runteams_core.authoring.source.creator_local_source import current_store


def _workspace(session):
    from runteams_core.storage import product_store as product
    if (not session or not product.device_chat(session['id']) or session.get('kind') != 'general'
            or session.get('subject_type') != 'workspace' or session.get('scope_pipeline_id')
            or (session.get('context') or {}).get('context_type', 'general') != 'general'):
        raise ValueError('请在个人对话中创建员工；已有员工请继续其原 SDK 源码。')
    scope = device_data.identity()
    if scope.get('organization_id'):
        raise PermissionError('请在个人工作区创作员工。')
    return scope


def bind(session_id, original, scope, *, request_sha256):
    """Adopt the same chat atomically; keep messages, public ID and attachments."""
    from runteams_core.storage import product_store as product
    with product.chat_lock(session_id):
        session = product.get_chat(session_id, include_messages=False)
        context = (session or {}).get('context') or {}
        if context.get('creator_local_source_id'):
            if (context.get('creator_local_scope') != scope['cache_scope'] or
                    context.get('creator_submission_sha256') != request_sha256):
                raise ValueError('本对话已绑定另一份源码，请继续编辑原工程。')
            return session
        _workspace(session)
        context = {'context_type':'worker', 'intent':'create', 'phase':'design',
            'label':original['project']['name'], 'creator_authoring':True,
            'creator_local_source_id':original['id'], 'creator_local_scope':scope['cache_scope'],
            'creator_submission_sha256':request_sha256}
        with device_data.connect() as connection:
            device_data.check(scope)
            changed = connection.execute("UPDATE chats SET kind='employee_design',context_json=?,"
                "status='active',updated_at=? WHERE id=? AND kind='general' AND subject_type='workspace'",
                (json.dumps(context,ensure_ascii=False),product.now(),session_id)).rowcount
            if changed != 1:
                raise ValueError('对话已变化，请重新打开。')
            from runteams_core.storage.device_runtime_links import reset
            reset(connection, session_id)
        return product.get_chat(session_id, include_messages=False)


def attachment_source(session, attachment_id):
    """Resolve only a saved user folder in this chat, never an Agent-supplied path."""
    import re
    from runteams_core.conversations import chat_attachments
    from runteams_core.storage import product_store as product
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError
    from runteams_core.authoring.creator_contracts import read_folder
    if not isinstance(attachment_id,str) or not re.fullmatch('[a-f0-9]{24}',attachment_id):
        raise AgentToolError('请选择当前对话中的文件夹附件；本次未执行导入。')
    messages=product.get_chat(session['id'])['messages']
    items=[item for message in messages if message.get('role')=='user'
        for item in message.get('attachments') or [] if item.get('id')==attachment_id]
    if not items or any(item.get('kind')!='folder' for item in items):
        raise AgentToolError('当前对话中没有这份文件夹附件；本次未执行导入。')
    item=items[-1]
    try:
        inputs=chat_attachments._normalized_inputs(session['id'],item)
    except ValueError as exc:
        raise AgentToolError('文件夹附件快照不可用，请重新添加；本次未执行导入。') from exc
    if len(inputs)!=1 or inputs[0][0].get('kind')!='folder':
        raise AgentToolError('文件夹附件快照无效，请重新添加；本次未执行导入。')
    return read_folder(inputs[0][1])


def _team_files(session_id, name):
    key = 'team-' + digest([session_id, name])[:24]
    path = 'pipelines/team.json'
    return {
        'project.json': canonical({'schema': 'runteams.creator-project/2', 'key': key, 'name': name,
            'version': '1.0.0', 'sdk': 'mcp-apps/1-dev', 'entrypoints': {'employees': [], 'pipelines': [path]},
            'dependency_lock': 'dependencies.lock.json', 'source_access': {'default': 'author', 'public_files': []}}),
        'dependencies.lock.json': canonical({'schema': 'runteams.dependencies/2', 'root': key,
            'runtime': {'protocol': 'mcp', 'managed_node': '24'}, 'dependencies': []}),
        path: canonical({'schema': 'runteams.pipeline-source/3', 'key': key, 'employees': [],
            'pipeline': {'name': name, 'positions': [], 'edges': []}})}


def _save_team(session_id, scope, files, raw, report):
    from runteams_core.foundation import file_locks
    from runteams_core.pipelines.pipeline_references import reference
    from runteams_core.storage import product_store as product
    from runteams_core.storage.device_runtime_links import reset
    from runteams_core.authoring.source.creator_source_import import inspect_source

    store = current_store(scope['cache_scope'])
    path, = strict_json(files['project.json'])['entrypoints']['pipelines']
    ref = reference(report['source']['sha256'], path)
    with file_locks.held(store.root / f'.team-chat-{int(session_id)}.lock'):
        session = product.get_chat(session_id, include_messages=False)
        _workspace(session)
        context = session['context']
        bound = context.get('source_pipeline_workspace')
        if (bound and bound != ref) or context.get('creator_local_source_id'):
            raise ValueError('对话已绑定其他作品，请从新对话创建。')
        original = store.save(raw, report['source']['sha256'], inspect_source)
        if original['id'] != ref['source_id']:
            raise ValueError('智能体团队源码回执不匹配。')
        if not bound:
            updated = {'context_type': 'general', 'intent': 'general', 'source_pipeline_workspace': ref,
                       'source_pipeline_discussion': str(uuid.uuid5(uuid.NAMESPACE_URL, f'runteams:chat:{session_id}'))}
            with device_data.connect() as connection:
                device_data.check(scope)
                changed = connection.execute("UPDATE chats SET context_json=?,updated_at=? WHERE id=? "
                    "AND kind='general' AND subject_type='workspace' AND json_extract(context_json,"
                    "'$.source_pipeline_workspace') IS NULL AND json_extract(context_json,'$.creator_local_source_id') IS NULL",
                    (json.dumps(updated), product.now(), session_id)).rowcount
                if changed != 1:
                    raise ValueError('对话已变化，请重新打开。')
                reset(connection, session_id)
    return {'state': 'saved', 'reference': ref, 'session_id': session_id,
            'name': strict_json(files[path])['pipeline']['name'], 'published': False}


def _validate_arguments(arguments):
    """Reject malformed calls before any SDK read/write, with a model-visible result."""
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError
    if not isinstance(arguments, dict):
        raise AgentToolError('SDK 工具参数必须是对象。')
    action = arguments.get('action')
    if action == 'create_pipeline':
        if (set(arguments) != {'action', 'name'} or not isinstance(arguments['name'], str)
                or not 1 <= len(arguments['name'].strip()) <= 80):
            raise AgentToolError('创建智能体团队需要 1 至 80 字的名称。')
    elif action in ('schema', 'reference'):
        kinds = ('employee', 'pipeline', 'skill') if action == 'schema' else ('project', 'dependencies', 'authoring')
        if set(arguments) != {'action', 'kind'} or arguments.get('kind') not in kinds:
            raise AgentToolError('{} 必须且只能提供 action、kind；kind 可选 {}。例如 {{"action":"{}","kind":"{}"}}。'
                .format(action, ' / '.join(kinds), action, kinds[0]))
    elif action in ('submit', 'import'):
        field = 'files' if action == 'submit' else 'attachment_id'
        if set(arguments) != {'action', field}:
            raise AgentToolError('{} 必须且只能提供 action、{}；未执行保存。'.format(action, field))
        if action == 'submit' and (not isinstance(arguments['files'], dict) or not arguments['files']):
            raise AgentToolError('submit 的 files 必须是非空的相对路径到 base64 字节映射；未执行保存。')
        if action == 'import':
            import re
            if not isinstance(arguments[field], str) or not re.fullmatch('[a-f0-9]{24}', arguments[field]):
                raise AgentToolError('import 的 attachment_id 必须是当前对话已保存的24位文件夹附件编号；未执行保存。')
    else:
        raise AgentToolError('SDK action 可选 schema、reference、submit、import；创建员工先读取合同，再提交完整源码。')


def tool(arguments, context):
    """General chat reads contracts, imports an attached folder or submits SDK bytes."""
    from runteams_core.storage import product_store as product
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    session = product.get_chat(context.get('chat_id'), include_messages=False)
    scope = device_data.identity()
    if scope.get('storage_kind') == 'local':
        if context.get('library_id') != scope['library_id']:
            raise PermissionError('本机资料库已变化，请重新打开对话。')
    elif context.get('actor_id') != scope['account_id']:
        raise PermissionError('账户已变化，请重新打开对话。')
    if not (session or {}).get('context', {}).get('creator_local_source_id'):
        _workspace(session)
    else:
        from runteams_core.authoring.creator_local_authoring import source
        source(session).current()
    _validate_arguments(arguments)
    action = arguments.get('action')
    if action == 'schema' and set(arguments) == {'action','kind'}:
        from runteams_core.authoring.creator_definitions import author_schema
        result = {'schema':author_schema(arguments['kind'])}
    elif action == 'reference' and set(arguments) == {'action','kind'}:
        from runteams_core.authoring.creator_authoring import reference
        result = reference(arguments['kind'])
    elif (action == 'create_pipeline' or action == 'submit' and set(arguments) == {'action','files'}
            or action == 'import' and set(arguments) == {'action','attachment_id'}):
        from runteams_core.authoring.source.creator_source_archive import pack
        from runteams_core.authoring.source.creator_source_import import inspect_source
        saved = session.get('context') or {}
        if saved.get('creator_local_source_id') and saved.get('creator_submission_sha256') != digest(arguments):
            raise AgentToolError('本对话已绑定原源码，请在原工程中编辑；本次未执行提交。')
        # Only rejected input validation is recoverable. Storage/binding failures
        # below may follow a write and must retain their original failure semantics.
        try:
            files = (_team_files(session['id'], arguments['name'].strip()) if action == 'create_pipeline' else
                attachment_source(session,arguments['attachment_id']) if action=='import'
                else decode_files(arguments['files']))
            raw = pack(files)
            report = inspect_source(raw)
            if report['pipelines'] == 1 and strict_json(files['project.json'])['schema'] == 'runteams.creator-project/2':
                result = _save_team(session['id'], scope, files, raw, report)
                device_data.check(scope)
                return AgentToolResult('creator_source', '智能体团队已创建。', result)
            if saved.get('source_pipeline_workspace'):
                raise AgentToolError('当前对话已经绑定智能体团队，请在新对话中创建其他作品。')
            if (strict_json(files['project.json'])['schema'] != 'runteams.creator-project/2'
                    or report['employees'] != 1 or report['pipelines']):
                raise CreatorContractError('invalid_employee_bundle', '员工须提交一份完整的当前 SDK 源码。')
            if action == 'submit' and not saved.get('creator_local_source_id'):
                from runteams_core.authoring.source.employee_starters import validate_submission
                try:
                    validate_submission(files)
                except ValueError as exc:
                    raise CreatorContractError('invalid_employee_starters', str(exc)) from exc
        except CreatorContractError as exc:
            raise AgentToolError('SDK 源码校验未通过（{}）：{} 本次未保存或绑定，请修正源码后重新提交。'
                .format(exc.code, str(exc))) from exc
        source_store = current_store(scope['cache_scope'])
        original = source_store.save(raw, report['source']['sha256'], inspect_source)
        adopted = bind(session['id'],original,scope,request_sha256=digest(arguments))
        result = {'state':'saved','source_id':original['id'],'session_id':adopted['id'],
            'published':False,'next':'本轮源码已保存。后续对话直接编辑本工程；可在资源中查看、编辑和构建源码。'}
    else:
        raise ValueError('创建员工请读取 SDK 合同后 submit 完整源码，或 import 当前对话的文件夹附件；后续在原工程中编辑。')
    device_data.check(scope)
    return AgentToolResult('creator_source','SDK 源码操作已完成。',result)

