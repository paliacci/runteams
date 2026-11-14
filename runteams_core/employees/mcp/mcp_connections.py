"""Device-local MCP connections and explicit tool tests."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from urllib.parse import urlsplit
import uuid

from runteams_core.configuration.credentials import app_secrets
from runteams_core.configuration.credentials.credential_redaction import redact_value
from runteams_core.employees.mcp.employee_mcp import MCPError, _environment
from runteams_core.foundation.local_json import strict_json
from runteams_core.storage import device_data, local_database
from runteams_core.storage.local_library import private_directory


PRESETS = (
    {'id': 'composio', 'name': 'Composio', 'kind': 'composio'},
    {'id': 'sample', 'name': 'RunTeams 示例', 'kind': 'sample'},
    {'id': 'slack', 'name': 'Slack', 'kind': 'preset', 'url': 'https://mcp.slack.com/mcp'},
)
EXAMPLES = {'echo': {'text': 'Hello, RunTeams!'}, 'calculate': {'a': 7, 'b': 8}}
ERRORS = {
    'authentication': '服务要求授权，或当前令牌权限不足。请检查连接凭据。',
    'connection': '无法读取 MCP 服务。请检查地址和凭据后重试。',
    'outcome_unknown': '服务没有确认结果。请先到原服务核对，再决定是否重试。',
    'tool_error': 'MCP 服务拒绝了此次调用，请检查参数和权限。',
    'response_too_large': '工具返回的内容太长，无法在此显示。请在原服务核对结果。',
}


def _endpoint(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s\\\x00-\x1f\x7f]', value):
        raise ValueError('请输入有效的 MCP 服务地址。')
    try:
        url = urlsplit(value)
        loopback = url.hostname in ('127.0.0.1', '::1', 'localhost')
        if (not url.hostname or url.username is not None or url.password is not None or url.fragment
                or url.query or '?' in value or '#' in value or url.port == 0
                or (url.scheme != 'https' and not (url.scheme == 'http' and loopback))):
            raise ValueError()
    except ValueError:
        raise ValueError('请输入 HTTPS 地址，或本机 HTTP 地址。令牌请填在单独的输入框。') from None
    return url.geturl()


def _run(runtime, request):
    try:
        node, worker = runtime().verify()
    except (MCPError, OSError, ValueError, AttributeError):
        return {'error': '此安装缺少可用的 MCP 运行资源。', 'code': 'runtime_unavailable'}
    try:
        with tempfile.TemporaryDirectory(prefix='runteams-mcp-test-') as temp:
            process = subprocess.run(
                [str(node), str(worker), '--test-connection'],
                input=json.dumps(request, allow_nan=False).encode() + b'\n', stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, cwd=temp, env=_environment(node, Path(temp)), timeout=24,
            )
            reply = strict_json(process.stdout) if process.returncode == 0 else {}
    except (ValueError, OSError, subprocess.TimeoutExpired):
        reply = {}
    if isinstance(reply, dict) and isinstance(reply.get('result'), dict):
        return {'result': redact_value(reply['result'], {'token': request.get('token')})}
    code = reply.get('error') if isinstance(reply, dict) else None
    if not isinstance(code, str) or code not in ERRORS:
        code = 'outcome_unknown' if request.get('tool') else 'connection'
    return {'error': ERRORS[code], 'code': code}


def dispatch(method, data, runtime):
    if not device_data.personal():
        raise PermissionError('请在本机个人工作区管理 MCP 连接。')
    if not isinstance(data, dict):
        raise ValueError('MCP 请求格式无效。')
    if method == 'POST' and str(data.get('action', '')).startswith('employee-apps-'):
        from runteams_core.employees.mcp.employee_applications import bindings
        return bindings(data)
    identity = device_data.identity()
    scope = identity['cache_scope']
    if not re.fullmatch(r'[a-f0-9]{64}', scope):
        raise PermissionError('本机资料身份无效。')
    base = Path(local_database.DB_PATH).resolve().parent
    root = private_directory(private_directory(base / 'host-credentials') / 'mcp-connections')
    db = root / (scope + '.sqlite3')
    vault = root / (scope + '.secrets.json')
    if db.is_symlink() or vault.is_symlink():
        raise ValueError('本机 MCP 连接目录无效。')
    with closing(sqlite3.connect(db, timeout=45)) as connection, connection, app_secrets.vault_scope(vault):
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE IF NOT EXISTS connections (id TEXT PRIMARY KEY, name TEXT, url TEXT)')
        if method == 'POST' and data.get('id') != 'composio' and data.get('action') in ('save', 'remove'):
            connection.execute('BEGIN IMMEDIATE')
        if method == 'GET' and not data:
            names = app_secrets.names()
            custom = [dict(row, kind='custom') for row in
                      connection.execute('SELECT id, name, url FROM connections ORDER BY rowid')]
            return {'connections': [dict(row, has_token=row['id'] in names) for row in (*PRESETS, *custom)]}
        if method != 'POST':
            raise ValueError('MCP 请求格式无效。')
        if data.get('id') == 'composio':
            from runteams_core.employees.mcp.composio_connections import dispatch as composio_dispatch
            return composio_dispatch(connection, data)
        action, key = data.get('action'), data.get('id')
        if action == 'save' and key is None and set(data) == {'action','name','url','token'}:
            name = data['name']
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError('请输入 1 到 80 个字符的连接名称。')
            row = {'id': uuid.uuid4().hex, 'name': name.strip(), 'url': _endpoint(data['url']), 'kind':'custom'}
            connection.execute('INSERT INTO connections (id, name, url) VALUES (?, ?, ?)',
                               (row['id'], row['name'], row['url']))
            _save_token(row['id'], data['token'])
            return {'connection': dict(row, has_token=bool(data['token']))}
        if not isinstance(key, str) or not re.fullmatch(r'(?:sample|slack|[a-f0-9]{32})', key):
            raise ValueError('请选择 MCP 连接。')
        row = next((preset for preset in PRESETS if preset['id'] == key), None)
        if row is None:
            record = connection.execute('SELECT id, name, url FROM connections WHERE id=?', (key,)).fetchone()
            if record is None:
                raise ValueError('此连接已移除，请刷新列表。')
            row = dict(record, kind='custom')
        if action == 'save' and row['kind'] != 'sample' and set(data) == {'action','id','token'}:
            _save_token(key, data['token'])
            return {'connection': dict(row, has_token=bool(data['token']))}
        if action == 'remove' and row['kind'] == 'custom' and set(data) == {'action','id'}:
            connection.execute('DELETE FROM connections WHERE id=?', (key,))
            _save_token(key, '')
            return {'removed': True}
        token = app_secrets.resolve([key]).get(key, '')
    request = {'url': row.get('url', ''), 'token': token}
    if action == 'test' and set(data) == {'action','id','tool','arguments'}:
        tool, arguments = data['tool'], data['arguments']
        if (not isinstance(tool, str) or not 1 <= len(tool) <= 256 or not isinstance(arguments, dict)
                or len(json.dumps(arguments, allow_nan=False).encode()) > 65536):
            raise ValueError('请提供有效的工具名称和 JSON 对象参数。')
        request.update(tool=tool, arguments=arguments)
    elif action != 'inspect' or set(data) != {'action','id'}:
        raise ValueError('MCP 请求格式无效。')
    device_data.check(identity)
    result = _run(runtime, request)
    device_data.check(identity)
    if action == 'inspect' and key == 'sample' and 'result' in result:
        for tool in result['result']['tools']:
            tool['example'] = EXAMPLES.get(tool['name'], {})
    return result


def _save_token(key, token):
    if not isinstance(token, str) or len(token) > 8192 or not re.fullmatch(r'[\x21-\x7e]*', token):
        raise ValueError('访问令牌格式无效。')
    app_secrets.set_secret(key, token)
