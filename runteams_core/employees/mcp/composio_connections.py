"""Composio's current REST sessions, scoped to the host's local credential vault.

Catalog and explicit tests share the same connection. No SDK, automatic retry,
provider credentials, client-supplied user IDs, or arbitrary proxy endpoints.
"""
import hashlib
import http.client
import json
import re
import time
from urllib.parse import urlencode, urlsplit
import uuid

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource
from runteams_core.configuration.credentials import app_secrets
from runteams_core.configuration.credentials.credential_redaction import redact_value
from runteams_core.foundation.local_json import strict_json

BASE = '/api/v3.1'
MAX_RESPONSE = 4 * 1024 * 1024
UNKNOWN = '服务未确认执行结果。请先到原应用核对，再决定是否重新测试。'


class ComposioError(Exception):
    def __init__(self, message, code='composio_error'):
        super().__init__(message)
        self.code = code


def request(key, method, path, *, query=None, body=None, execution=False):
    """One request, fixed TLS origin, bounded response, no redirect or retry."""
    connection = http.client.HTTPSConnection('backend.composio.dev', timeout=35)
    try:
        target = BASE + path + ('?' + urlencode(query, doseq=True) if query else '')
        connection.request(method, target, body=None if body is None else json.dumps(body, allow_nan=False).encode(),
                           headers={'x-api-key': key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ComposioError(UNKNOWN if execution else '返回内容过大，请缩小搜索范围。', 'outcome_unknown' if execution else 'response_too_large')
        if response.status in (401, 403):
            raise ComposioError('API Key 无效或权限不足，请检查 Composio 项目及 Key 的权限。', 'authentication')
        if response.status == 429:
            raise ComposioError('Composio 暂时限制了请求，请稍后重试。', 'rate_limited')
        if response.status >= 500 and execution:
            raise ComposioError(UNKNOWN, 'outcome_unknown')
        if not 200 <= response.status < 300:
            # Never echo upstream errors: they may include credentials or args.
            raise ComposioError('Composio 拒绝了请求（HTTP %s）。请检查账号授权、工具参数或项目配置。' % response.status)
        value = strict_json(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return redact_value(value, {'key': key})
    except (OSError, http.client.HTTPException, ValueError):
        raise ComposioError(UNKNOWN if execution else '无法读取 Composio，请检查网络后重试。',
                            'outcome_unknown' if execution else 'connection') from None
    finally:
        connection.close()


def text(value, limit=200, *, required=False, pattern=None):
    if not isinstance(value, str) or len(value) > limit or (required and not value) or (pattern and not re.fullmatch(pattern, value)):
        raise ValueError('Composio 请求参数无效。')
    return value


def slug(value):
    return text(value, 160, required=True, pattern=r'[A-Za-z0-9_-]+')


def page(value, transform):
    if not isinstance(value.get('items'), list):
        raise ComposioError('Composio 返回的目录格式不受支持。')
    return {'items': [transform(row) for row in value['items']],
            'next_cursor': value.get('next_cursor'), 'total_items': value.get('total_items')}


def toolkit_logo(value):
    if not isinstance(value, str) or len(value) > 512:
        return ''
    if re.fullmatch(
        r'https://(?:logos\.composio\.dev/api/[A-Za-z0-9_-]+|(?:assets\.composio\.dev/logos/|cdn\.jsdelivr\.net/gh/ComposioHQ/open-logos@[A-Za-z0-9_-]+/)'
        r'[A-Za-z0-9_.-]+\.(?:png|svg|webp|jpe?g))', value
    ):
        return value
    return ''


def toolkit(row):
    meta = row.get('meta') or {}
    return {'slug': slug(row['slug']), 'name': row.get('name') or row['slug'],
            'description': meta.get('description') or '', 'tools_count': meta.get('tools_count'),
            'logo': toolkit_logo(meta.get('logo')),
            'no_auth': row.get('no_auth') is True,
            'managed_auth': bool(row.get('composio_managed_auth_schemes'))}


def tool(row):
    return {'name': slug(row['slug']), 'title': row.get('name') or row['slug'],
            'description': row.get('description') or '', 'inputSchema': row.get('input_parameters') or {},
            'version': row.get('version'), 'no_auth': row.get('no_auth') is True,
            'tags': row.get('tags') or []}


def accounts(key, user, selected):
    result, cursor, seen = [], '', set()
    while True:
        value = request(key, 'GET', '/connected_accounts', query={
            'user_ids': user, 'toolkit_slugs': selected, 'limit': 100, **({'cursor': cursor} if cursor else {})})
        for row in value.get('items', []):
            if row.get('user_id') != user or row.get('toolkit', {}).get('slug') != selected:
                continue
            state = row.get('state')
            profile = state.get('val') if isinstance(state, dict) else None
            display = profile.get('displayName') if isinstance(profile, dict) else None
            name = display.strip() if isinstance(display, str) and 0 < len(display.strip()) <= 320 else ''
            result.append({'id': slug(row['id']), 'name': name or row.get('alias') or row.get('word_id') or row['id'],
                           'status': row.get('status'), 'disabled': bool(row.get('is_disabled'))})
        cursor = value.get('next_cursor')
        if not cursor:
            return result
        if cursor in seen or len(seen) >= 20:
            raise ComposioError('账号列表未完整返回，请稍后重新读取。')
        seen.add(cursor)


def _session(db, key, user, selected, revision):
    row = db.execute('SELECT session_id, created FROM composio_sessions WHERE toolkit=? AND revision=?', (selected, revision)).fetchone()
    if row and time.time() - row['created'] < 1800:
        return row['session_id']
    result = request(key, 'POST', '/tool_router/session', body={
        'user_id': user, 'toolkits': {'enable': [selected]},
        'multi_account': {'enable': True, 'require_explicit_selection': True},
        'workbench': {'enable': False}, 'instant': False,
        'manage_connections': {'enable': True, 'enable_connection_removal': False}})
    session = slug(result.get('session_id'))
    db.execute('INSERT OR REPLACE INTO composio_sessions VALUES (?,?,?,?)', (selected, revision, session, time.time()))
    return session


def authorization_url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'https' and parsed.hostname in ('connect.composio.dev', 'app.composio.dev')
                and parsed.path.startswith('/link/') and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and not re.search(r'[\s\\]', value)):
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    raise ValueError('Composio 返回了无法识别的授权地址。')


def _no_remote_ref(uri):
    raise NoSuchResource(ref=uri)


def dispatch(db, data):
    try:
        return _dispatch(db, data)
    except ComposioError as error:
        return {'error': str(error), 'code': error.code}


def _dispatch(db, data):
    action = data.get('action')
    fields = {
        'status': set(), 'save': {'token'}, 'remove': {'revision'},
        'catalog': {'revision', 'search', 'cursor'},
        'toolkit': {'revision', 'toolkit'},
        'tool': {'revision', 'toolkit', 'tool'},
        'tools': {'revision', 'toolkit', 'search', 'cursor'},
        'accounts': {'revision', 'toolkit'}, 'connect': {'revision', 'toolkit'},
        'test': {'revision', 'toolkit', 'tool', 'version', 'account', 'arguments', 'operation_id'},
    }
    if action not in fields or set(data) != {'id', 'action'} | fields[action]:
        raise ValueError('Composio 请求格式无效。')
    db.execute('CREATE TABLE IF NOT EXISTS composio_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS composio_sessions (toolkit TEXT PRIMARY KEY, revision TEXT, session_id TEXT, created REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS composio_tests (id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)')
    # Serialize key changes and admissions; never run a stale test on a new key.
    db.execute('BEGIN IMMEDIATE')
    settings = dict(db.execute('SELECT name,value FROM composio_settings'))
    user = settings.get('user_id') or 'runteams_' + uuid.uuid4().hex
    if 'user_id' not in settings:
        db.execute('INSERT INTO composio_settings VALUES (?,?)', ('user_id', user))
    key = app_secrets.resolve(['composio']).get('composio', '')
    revision = hashlib.sha256(key.encode()).hexdigest() if key else ''
    if action == 'status':
        return {'configured': bool(key), 'revision': revision}
    if action == 'save':
        candidate = text(data['token'], 8192, required=True)
        if re.search(r'[^\x21-\x7e]', candidate):
            raise ValueError('API Key 不能包含空白或非 ASCII 字符。')
        request(candidate, 'GET', '/toolkits', query={'limit': 1})
        app_secrets.set_secret('composio', candidate)
        db.execute('DELETE FROM composio_sessions')
        return {'configured': True, 'revision': hashlib.sha256(candidate.encode()).hexdigest()}
    if not key:
        raise ComposioError('请先设置 Composio API Key。', 'not_configured')
    if data['revision'] != revision:
        raise ComposioError('Composio 凭据已改变，请重新打开页面。', 'stale_connection')
    if action == 'remove':
        app_secrets.set_secret('composio', '')
        db.execute('DELETE FROM composio_sessions')
        return {'configured': False, 'revision': ''}
    if action in ('catalog', 'tools'):
        query = {'limit': 30, 'include_deprecated': 'false'}
        search = text(data['search'], 200)
        cursor = text(data['cursor'], 4096)
        if cursor: query['cursor'] = cursor
        if action == 'catalog':
            query.update(sort_by='usage', user_id=user)
            if search: query['search'] = search
            return page(request(key, 'GET', '/toolkits', query=query), toolkit)
        query.update(toolkit_slug=slug(data['toolkit']), toolkit_versions='latest')
        if search: query['query'] = search
        return page(request(key, 'GET', '/tools', query=query), tool)
    selected = slug(data['toolkit'])
    if action == 'toolkit':
        return toolkit(request(key, 'GET', '/toolkits/' + selected))
    if action == 'tool':
        definition = request(key, 'GET', '/tools/' + slug(data['tool']), query={'version': 'latest'})
        if definition.get('toolkit', {}).get('slug') != selected:
            raise ValueError('工具不属于所选应用。')
        return tool(definition)
    if action == 'accounts':
        return {'accounts': accounts(key, user, selected)}
    if action == 'connect':
        session = _session(db, key, user, selected, revision)
        value = request(key, 'POST', '/tool_router/session/' + session + '/link', body={'toolkit': selected})
        result = {'redirect_url': authorization_url(value.get('redirect_url', ''))}
        account = value.get('connected_account_id')
        if isinstance(account, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', account):
            result['connected_account_id'] = account
        return result
    tool_name, version = slug(data['tool']), slug(data['version'])
    account = text(data['account'], 200)
    args = data['arguments']
    operation = text(data['operation_id'], 36, pattern=r'[a-f0-9-]{36}')
    if not isinstance(args, dict) or len(json.dumps(args, allow_nan=False).encode()) > 128 * 1024:
        raise ValueError('测试参数必须是小于 128 KB 的 JSON 对象。')
    fingerprint = hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != 'operation_id'}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    previous = db.execute('SELECT fingerprint,result FROM composio_tests WHERE id=?', (operation,)).fetchone()
    if previous:
        if previous['fingerprint'] != fingerprint:
            raise ValueError('测试操作编号已用于其他参数，请重新打开测试。')
        return strict_json(previous['result'].encode()) if previous['result'] else {'error': UNKNOWN, 'code': 'outcome_unknown'}
    definition = request(key, 'GET', '/tools/' + tool_name, query={'version': 'latest'})
    if definition.get('version') != version:
        raise ValueError('工具版本已更新，请重新读取功能列表后测试。')
    if definition.get('toolkit', {}).get('slug') != selected:
        raise ValueError('工具不属于所选应用。')
    if definition.get('no_auth') is not True:
        valid = [row['id'] for row in accounts(key, user, selected) if row['status'] == 'ACTIVE' and not row['disabled']]
        if account not in valid:
            raise ValueError('请先连接并选择此应用的有效账号。')
    elif account:
        raise ValueError('无需账号的工具不接受账号参数。')
    schema = definition.get('input_parameters') or {'type': 'object'}
    try:
        validator = Draft202012Validator(schema, registry=Registry(retrieve=_no_remote_ref))
        error = next(validator.iter_errors(args), None)
        if error:
            # Do not echo argument values into persisted diagnostics.
            raise ComposioError('测试参数不符合工具要求，请检查必填字段及参数类型。', 'invalid_arguments')
    except ComposioError:
        raise
    except Exception:
        raise ComposioError('暂时无法校验此工具的参数定义。', 'invalid_schema') from None
    session = _session(db, key, user, selected, revision)
    # Persist admission before any external effect. Restart/replay never resends.
    db.execute('INSERT INTO composio_tests VALUES (?,?,NULL)', (operation, fingerprint))
    db.commit()
    started = time.monotonic()
    try:
        value = request(key, 'POST', '/tool_router/session/' + session + '/execute',
                        body={'tool_slug': tool_name, 'arguments': args, **({'account': account} if account else {})}, execution=True)
        result_type = value.get('result_type')
        if result_type not in ('completed', 'failed', 'blocked', 'input_required'):
            raise ComposioError(UNKNOWN, 'outcome_unknown')
        result = {'result': {'isError': result_type != 'completed', 'result_type': result_type,
                            'data': value.get('data'), 'error': value.get('error'), 'log_id': value.get('log_id'),
                            'elapsed_ms': round((time.monotonic() - started) * 1000)}}
    except ComposioError as error:
        result = {'error': str(error), 'code': error.code}
    result = redact_value(result, {'key': key})
    db.execute('UPDATE composio_tests SET result=? WHERE id=?', (json.dumps(result, allow_nan=False), operation))
    return result
