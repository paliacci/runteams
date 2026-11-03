"""Canonical account-free SDK source operations, shared by product hosts."""
from dataclasses import dataclass
from runteams_core.authoring.creator_authoring import file_payload
from runteams_core.authoring.creator_contracts import relative
from runteams_core.authoring.source.creator_source_revisions import Revisions

ACTIONS = frozenset({'', '/file', '/workspace', '/history', '/receipt', '/edit', '/restore', '/build', '/session', '/recovery', '/export','/configuration','/identity'})

@dataclass(frozen=True)
class SourceDownload:
    raw: bytes
    identity: str
    revision: str


def read(store, identity, file, query):
    if file == '/identity' and set(query) == {'employee_source'} and len(query['employee_source']) == 1:
        from runteams_core.employees.employee_avatars import identity as employee_identity
        from runteams_core.authoring.creator_contracts import strict_json
        files = Revisions(store, identity).files()
        path = query['employee_source'][0]
        if path not in strict_json(files['project.json'])['entrypoints']['employees']:
            raise PermissionError('员工不属于当前工程。')
        value = employee_identity(strict_json(files[path]), files=files)
    elif file=='/configuration' and set(query) in ({'employee_source'},{'employee_source','operation_id'}) and all(len(v)==1 for v in query.values()):
        from runteams_core.employees.source_employee_runtime import reference
        from runteams_core.configuration.employee_configuration import for_source, source_receipt
        ref=reference(identity,query['employee_source'][0])
        if 'operation_id' in query:value=source_receipt(ref,query['operation_id'][0])
        else:
            with for_source(ref) as config:value=config.read()
    elif file == '/export' and set(query)=={'revision'} and len(query['revision'])==1:
        return SourceDownload(Revisions(store,identity).export(query['revision'][0]), identity, query['revision'][0])
    elif file == '/build' and (not query or set(query)=={'operation_key'} and len(query['operation_key'])==1):
        from runteams_core.authoring.compilation.creator_local_build import LocalBuilds
        builds = LocalBuilds(store,identity)
        value = builds.status()
        if query:value['latest']=builds.read(query['operation_key'][0])
    elif file == '/file' and set(query) == {'path'} and len(query['path']) == 1:
        path = relative(query['path'][0])
        files = Revisions(store, identity).files()
        if path not in files:
            raise FileNotFoundError()
        value = file_payload(path, files[path])
    elif file == '/workspace' and not query:
        value = Revisions(store, identity).current()
        from runteams_core.authoring.compilation.creator_local_build import LocalBuilds
        value['build'] = LocalBuilds(store,identity).status()
        from runteams_core.authoring.creator_local_authoring import pending_changes
        value['pending_authoring'] = pending_changes(store, identity)
    elif file == '/history' and not query:
        value = Revisions(store, identity).history()
    elif file == '/receipt' and set(query) == {'operation_key'} and len(query['operation_key']) == 1:
        value = Revisions(store, identity).receipt(query['operation_key'][0])
    elif not file and not query:
        value = store.describe(identity)
    else:
        raise ValueError('源码查询参数无效。')
    store.check_scope()
    return value


def write(store, identity, file, body, scope, serialize):
    if file=='/configuration' and isinstance(body,dict) and set(body)=={'employee_source','action','field','definition_sha256','value'} and body['action']=='credential':
        from runteams_core.employees.source_employee_runtime import reference
        from runteams_core.configuration.employee_configuration import for_source
        with for_source(reference(identity,body['employee_source'])) as config:
            value=config.credential(**{k:v for k,v in body.items() if k not in ('employee_source','action')})
    elif file=='/configuration':
        if not isinstance(body,dict) or set(body) not in ({'employee_source','operation_id','expected_revision','definition_sha256','values'},{'employee_source','operation_id','expected_revision','definition_sha256','values','bindings'}):raise ValueError('配置保存参数无效。')
        from runteams_core.employees.source_employee_runtime import reference
        from runteams_core.configuration.employee_configuration import for_source
        with for_source(reference(identity,body['employee_source'])) as config:
            value=config.save(**{k:v for k,v in body.items() if k!='employee_source'})
    elif file == '/build':
        from runteams_core.authoring.compilation.creator_local_build import LocalBuilds
        builds = LocalBuilds(store,identity)
        if isinstance(body,dict) and set(body)=={'action','base_revision','operation_key'} and body['action']=='start':
            value = builds.start(body['base_revision'],body['operation_key'])
        elif isinstance(body,dict) and set(body)=={'action','operation_key'} and body['action']=='cancel':
            value = builds.cancel(body['operation_key'])
        else:raise ValueError('构建参数无效。')
    elif file == '/recovery':
        from runteams_core.storage.device_data import LOCAL_CHAT_ID_MIN
        if (not isinstance(body, dict) or set(body) != {'session_id','base_revision'} or
                type(body['session_id']) is not int or body['session_id'] < LOCAL_CHAT_ID_MIN):
            raise ValueError('恢复会话无效。')
        from runteams_core.storage import product_store
        session = product_store.get_chat(body['session_id'])
        if not session or (session.get('context') or {}).get('creator_local_source_id') != identity:
            raise PermissionError('恢复会话与这份源码不匹配。')
        from runteams_core.authoring.creator_local_authoring import recover
        value = recover(session,body['base_revision'])
    elif file == '/session':
        if not isinstance(body, dict) or set(body) != {'runtime'} or not isinstance(body['runtime'], dict):
            raise ValueError('创作会话参数无效。')
        from runteams_core.authoring.creator_local_authoring import session_for
        value = {'session': serialize(session_for(store, identity,
            scope, body['runtime']))}
    elif file == '/identity':
        from runteams_core.employees.employee_avatars import edit
        value = edit(store, identity, body)
    elif file in ('/edit', '/restore'):
        # Reuse the bounded upload reader. A single edit is capped at 2 MiB;
        # complete snapshots remain capped by the common source contract.
        restore = file == '/restore'
        if not isinstance(body, dict) or set(body) != {'base_revision', 'operation_key', 'revision' if restore else 'changes'}:
            raise ValueError('源码保存参数无效。')
        revisions = Revisions(store, identity)
        files = revisions.files_at(body['revision'] if restore else body['base_revision'])
        import base64
        changes = [] if restore else body['changes']
        if not restore and (not isinstance(changes, list) or not 1 <= len(changes) <= 500):
            raise ValueError('请选择要保存的文件。')
        seen = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {'path', 'content_base64'}:
                raise ValueError('文件修改格式无效。')
            path = relative(change['path'])
            if path in seen:
                raise ValueError('同一文件不能重复修改。')
            seen.add(path)
            if change['content_base64'] is None:
                files.pop(path, None)
            else:
                if not isinstance(change['content_base64'], str):
                    raise ValueError('文件内容格式无效。')
                raw = base64.b64decode(change['content_base64'], validate=True)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError('本机单次编辑暂限 2 MB。')
                files[path] = raw
        value = revisions.commit(files, body['base_revision'], body['operation_key'])
    else:
        raise ValueError('源码操作无效。')
    store.check_scope()
    return value
