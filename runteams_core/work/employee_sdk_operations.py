"""Employee SDK operations over the host-selected employee and active MCP call."""
import hashlib
import re
import uuid

from runteams_core.assets.collections.local_collections import Collections
from runteams_core.configuration.configuration_schema import managed_fields
from runteams_core.employees.managed_employee_data import provision
from runteams_core.employees.mcp.employee_applications import AccountRequired, ApplicationTurn, storage_key
from runteams_core.storage import device_data
from runteams_core.storage.storage_contracts import BusinessCloudUnknown


def collections(config, method, params, release, guard):
    field = next((field for field in managed_fields(config.definition)
                  if field['key'] == params['collection']), None)
    if field is None:
        raise PermissionError('员工未声明此托管集合。')
    store = Collections()
    if method == 'data.query':
        if params.get('filter'):
            raise ValueError('本机托管集合暂不支持过滤条件。')
        guard()
        page = store.query(field, provision(config, field), limit=params['limit'], cursor=params.get('cursor') or '')
        guard()
        return {'items': [{'id': row['key'], 'revision': str(row['revision']), 'value': row['value']}
                          for row in page['items']], 'next_cursor': page['next_cursor']}
    records = []
    for mutation in params['mutations']:
        revision = mutation['base_revision']
        if mutation['value'] is None or (revision is not None and not re.fullmatch(r'[1-9][0-9]{0,17}', revision)):
            raise ValueError('托管集合写入需要记录内容和有效版本。')
        records.append({'key': mutation['id'], 'value': mutation['value'],
                        'expected_revision': 0 if revision is None else int(revision)})
    key = params['operation_key']
    selected = provision(config, field)
    with device_data.connect():
        guard()
        result = store.upsert_many(field, selected, records=records,
            operation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, selected['collection_id']+':sdk:'+key)),
            provenance={'source':'employee-sdk','employee_reference':config.reference})
        guard()
    return {'state':'confirmed','operation_key':key,'release_digest':release,
            'result': {'ok': result['ok'], 'records': result.get('records', [])}}


def applications(config, method, params, guard, cancel):
    identifier = params['application']
    turn = ApplicationTurn(storage_key(config.reference), device_data.identity(), None, cancel)
    row = turn.bindings().get(identifier)
    account = (row or {}).get('account')
    # Do not expose the provider account ID. The stable opaque value can
    # partition an employee's own data when they change selected accounts.
    connected = account is not None
    if method == 'application.status':
        return {'connected':connected,'binding_key': hashlib.sha256(
            (account.get('id') or identifier).encode()).hexdigest() if connected else None}
    if not connected:
        raise AccountRequired('请在员工设置中连接应用。')
    args = {'operation':'call','application':identifier,'tool':params['tool'],'arguments':params['arguments']}
    if row['provider'] == 'composio':
        args['version'] = turn.tool_definition(row,params['tool'])['version']
    operation = str(uuid.uuid5(uuid.NAMESPACE_URL,turn.key+':'+identifier+':'+params['operation_key']))
    guard()
    turn.check_connection(identifier,row)
    result = turn.execute(args,{'sdk_operation_id':operation,'sdk_binding':row})
    try:
        turn.check_connection(identifier,row)
        guard()
    except (AccountRequired,PermissionError) as error:
        raise BusinessCloudUnknown(operation) from error
    return result
