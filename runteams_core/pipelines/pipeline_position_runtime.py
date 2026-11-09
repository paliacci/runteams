"""Local, role-scoped model choices for future pipeline work."""
import copy
import json

from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data


def _key(ref, position_key, employee_reference):
    return 'source-pipeline-runtime-choice:' + digest([ref, position_key, employee_reference])


def _read(connection, key):
    row = connection.execute('SELECT value FROM device_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def selections(ref, employees):
    with device_data.connect(readonly=True) as connection:
        return {position: _read(connection, _key(ref, position, reference))
                for position, reference in employees.items()}


def refresh_bundle(ref, bundle):
    from runteams_core.employees.source_employee_runtime import package_asset, resolve_runtime
    configured = selections(ref, {key: role['package']['reference'] for key, role in bundle['roles'].items()})
    updated = None
    for key, role in bundle['roles'].items():
        package, selection = role['package'], configured[key]
        if selection is None and package['runtime'].get('selection_source') != 'position_override':
            continue
        requirement = package_asset(package)['employee']['runtime_requirement']
        runtime = resolve_runtime(requirement, selection=selection)
        if runtime != package['runtime']:
            if updated is None:
                updated = copy.deepcopy(bundle)
            updated['roles'][key]['package']['runtime'] = runtime
    return updated if updated is not None else bundle


def configuration(core, ref, position_key, change=None):
    from runteams_core.agents.models import model_channels
    from runteams_core.assets import rented_references
    from runteams_core.employees.source_employee_runtime import resolve_runtime
    from runteams_core.pipelines import source_pipeline_control as control, source_pipeline_settings as settings, source_pipeline_work as work
    from runteams_core.pipelines.pipeline_employee_dependencies import describe
    from runteams_core.storage import product_store

    core._actor()
    ref, revisions = settings._source(ref)
    if rented_references.is_rented(ref):
        raise ContractError('请使用租用岗位的模型配置。')
    with revisions.locked():
        revision = revisions._head()
        asset = settings._asset(revisions._files(revision), ref)
    _, member = work._position(asset, position_key)
    description = describe(ref, member, revision)
    requirement = description['asset']['employee']['runtime_requirement']
    key = _key(ref, position_key, description['reference'])
    with device_data.connect(readonly=True) as connection:
        selection = _read(connection, key)
    catalogs = {}
    channels = []
    for channel in product_store.list_channels():
        if not channel.get('enabled') or channel['provider'] != requirement['provider']:
            continue
        try:
            catalog = model_channels.require_catalog(channel)
        except ValueError:
            continue
        catalogs[channel['id']] = catalog
        if catalog['models']:
            models = [{k: item[k] for k in ('value', 'label', 'efforts', 'default_effort') if k in item}
                      for item in catalog['models']]
            channels.append({'id': channel['id'], 'name': channel['name'], 'models': models})
    if change is not None:
        new = change['selection']
        if change['source_revision'] != revision:
            raise ContractError('岗位版本已变化，请重新打开岗位详情。')
        if new is not None:
            if (not isinstance(new, dict) or set(new) != {'channel_id', 'model', 'effort'}
                    or type(new['channel_id']) is not int or not isinstance(new['model'], str)
                    or not new['model'] or not isinstance(new['effort'], str)):
                raise ContractError('模型选择格式无效。')
            resolve_runtime(requirement, selection=new, catalogs=catalogs)
        with revisions.locked(), device_data.connect() as connection:
            if revisions._head() != revision:
                raise ContractError('岗位版本已变化，请重新打开岗位详情。')
            current = _read(connection, key)
            if current != new and current != change['expected_selection']:
                raise ContractError('模型选择已变化，请重新读取后再试。')
            if new is None:
                connection.execute('DELETE FROM device_settings WHERE key=?', (key,))
            else:
                connection.execute('INSERT INTO device_settings(key,value) VALUES(?,?) '
                                   'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, canonical(new).decode()))
        selection = new
    bundle = control.read(core, ref)['bundle']
    role = bundle['roles'].get(position_key) if bundle and bundle['revision'] == revision else None
    applied = role['package']['runtime'] if role else None
    try:
        if selection is None and applied and applied.get('selection_source') != 'position_override':
            effective = applied
        else:
            effective = resolve_runtime(requirement, selection=selection, catalogs=catalogs)
        error = ''
    except (ContractError, ValueError) as exc:
        effective, error = None, str(exc)
    return {'source_revision': revision, 'selection': selection, 'effective': effective,
            'error': error, 'channels': channels}
