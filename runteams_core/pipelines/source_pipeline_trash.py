"""Recoverable removal of one authored pipeline, without changing its source."""
import json
from pathlib import Path

from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_references
from runteams_core.storage.repository import utc_now


PREFIX = 'source-pipeline-trash:'
EVENT = 'pipeline.trash_state'


def _stream(ref):
    return PREFIX + ref['source_id'] + ':' + ref['pipeline_source']


def _state(connection, ref):
    return connection.execute('SELECT id,data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
                              (_stream(ref), EVENT)).fetchone()


def check_available(core, ref, connection=None):
    if not isinstance(ref, dict) or ref.get('schema') != pipeline_references.REFERENCE:
        return
    if connection is None:
        if not Path(core.repository.path).is_file():
            return
        with core.repository.read_snapshot() as connection:
            return check_available(core, ref, connection)
    row = _state(connection, ref)
    if row and json.loads(row['data_json'])['trashed_at']:
        raise ContractError('此智能体团队已移到垃圾箱，请先恢复。')


def catalog(core):
    if not Path(core.repository.path).is_file():
        return []
    with core.repository.read_snapshot() as connection:
        return _catalog(connection)


def hidden_source_references():
    from runteams_core.work.device_work import DeviceWorkStorage
    storage = DeviceWorkStorage()
    if not Path(storage.path).is_file():
        return []
    with storage.connect(readonly=True) as connection:
        return [item['reference'] for item in _catalog(connection)]


def hidden_source_keys():
    from runteams_core.assets.source_links import source_key
    return {source_key(ref['source_id'], ref['pipeline_source']) for ref in hidden_source_references()}


def _catalog(connection):
    rows = connection.execute('SELECT id,data_json FROM events WHERE id IN '
                              '(SELECT max(id) FROM events WHERE type=? GROUP BY stream) ORDER BY id',
                              (EVENT,))
    items = []
    for row in rows:
        state = json.loads(row['data_json'])
        if state['trashed_at']:
            items.append({'kind': 'pipeline', 'id': row['id'], 'can_delete': False, **state})
    return items


def change(core, ref, *, restore_id=None, active_ids=()):
    from runteams_core.pipelines import source_pipeline_control as control, source_pipeline_workspace as workspace
    ref = pipeline_references.checked_reference(ref)
    if ref['schema'] != pipeline_references.REFERENCE:
        raise PermissionError('只能将自己创建的智能体团队移到垃圾箱。')
    title = workspace._definition(ref)[1]['pipeline']['name'] if restore_id is None else ''
    with core.repository.connect() as connection:
        previous = _state(connection, ref)
        state = json.loads(previous['data_json']) if previous else None
        if restore_id is not None:
            if not state or previous['id'] != restore_id or not state['trashed_at']:
                raise ContractError('智能体团队垃圾箱记录已变化，请重新读取。')
            value = {**state, 'trashed_at': None}
        else:
            if state and state['trashed_at']:
                return {'trashed': True, 'reference': ref}
            runs = control._rows(connection, ref)
            if control._live(runs, active_ids) or any(row['state'] in ('ready', 'waiting_retry') for row in runs):
                raise ContractError('此智能体团队有等待开始或正在执行的任务，请先完成或停止任务。')
            value = {'reference': ref, 'title': title, 'trashed_at': utc_now()}
        core.repository.event(_stream(ref), EVENT, value, connection=connection)
    return {'trashed': restore_id is None, 'reference': ref}
