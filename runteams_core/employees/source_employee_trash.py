"""Recoverable roster removal, scoped to one device library and employee source."""
import json

from runteams_core.assets.source_links import source_key
from runteams_core.employees import employee_references
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data
from runteams_core.storage.repository import utc_now


SETTING = 'source-employee-trash/v1'


def _read(connection):
    row = connection.execute('SELECT value FROM device_settings WHERE key=?', (SETTING,)).fetchone()
    return json.loads(row['value']) if row else {'last_id': 0, 'items': {}}


def catalog():
    with device_data.connect(readonly=True) as connection:
        return [{'kind': 'employee', 'can_delete': False, **item} for item in _read(connection)['items'].values()]


def hidden_keys():
    with device_data.connect(readonly=True) as connection:
        return set(_read(connection)['items'])


def change(action, data):
    if action not in ('trash', 'restore') or not isinstance(data, dict) or set(data) != (
            {'reference', 'id'} if action == 'restore' else {'reference'}):
        raise ContractError('员工垃圾箱请求无效。')
    scope = device_data.identity()
    ref = employee_references.checked_reference(data['reference'])
    if ref.get('schema') != employee_references.SOURCE_SCHEMA:
        raise PermissionError('只能将本地员工移到垃圾箱。')
    key = source_key(ref['source_id'], ref['employee_source'])
    if action == 'trash':
        from runteams_core.employees.employee_directory import local_entries
        entries = local_entries(errors={})
        entry = next((row for row in entries if row['source']['reference'] == ref), None)
        if not entry:
            raise ContractError('找不到这名本地员工。')
        if entry.get('pipeline_groups'):
            raise ContractError('这名员工属于流水线，请在流水线菜单中操作。')
    elif type(data['id']) is not int or data['id'] <= 0:
        raise ContractError('员工垃圾箱记录无效。')
    with device_data.connect() as connection:
        device_data.check(scope)
        state = _read(connection)
        items = state['items']
        if action == 'trash':
            if key in items:
                return {'trashed': True, 'reference': ref}
            state['last_id'] += 1
            items[key] = {'id': state['last_id'], 'reference': ref, 'title': entry['record']['name'],
                          'trashed_at': utc_now()}
        else:
            if key not in items or items[key]['id'] != data['id']:
                raise ContractError('员工垃圾箱记录已变化，请重新读取。')
            del items[key]
        connection.execute('INSERT INTO device_settings(key,value) VALUES(?,?) '
                           'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (SETTING, json.dumps(state, ensure_ascii=False)))
    return {'trashed': action == 'trash', 'reference': ref}
