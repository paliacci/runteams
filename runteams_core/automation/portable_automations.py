"""Select personal device schedules and import reviewed asset templates."""
import json
import uuid

from runteams_core.authoring.creator_contracts import canonical
from runteams_core.automation.automation_template_contract import LIMIT, template_id, validate_templates
from runteams_core.foundation.contracts import ContractError

_NAMESPACE = uuid.UUID('cd9878ed-5483-5e44-9260-7eff55c060b4')


def _key(reference):
    if not isinstance(reference, dict):
        raise ContractError('资产引用无效。')
    return 'pipeline_source' if 'pipeline_source' in reference else 'employee_source'


def _kind(reference):
    return _key(reference).removesuffix('_source')


def _scope_id(*parts):
    return str(uuid.uuid5(_NAMESPACE, canonical(parts).decode('utf-8')))


def source_reference(source_id, kind, entry):
    if kind == 'employee':
        from runteams_core.employees.employee_references import source_reference as employee_reference
        return employee_reference(source_id, entry)
    if kind == 'pipeline':
        from runteams_core.pipelines.pipeline_references import reference as pipeline_reference
        return pipeline_reference(source_id, entry)
    raise ContractError('资产类型无效。')


def available(host, reference):
    """List this author asset's device schedules without runtime history."""
    from runteams_core.automation.device_employee_schedules import canonical as schedule_key
    from runteams_core.employees.employee_references import SOURCE_SCHEMA, checked_reference as employee_check
    from runteams_core.pipelines.pipeline_references import REFERENCE, checked_reference as pipeline_check

    kind = _kind(reference)
    schema, check = (SOURCE_SCHEMA, employee_check) if kind == 'employee' else (REFERENCE, pipeline_check)
    if reference.get('schema') != schema:
        raise PermissionError('只能从自己的源码资产选择自动化。')
    backend = host.backend(kind)
    ref = check(reference)
    with backend.connection() as connection:
        if connection is None:
            return []
        rows = connection.execute(
            'SELECT id,name,payload,schedule_kind,interval_sec,schedule FROM schedules '
            'WHERE reference=? AND deleted=0 ORDER BY id DESC', (schedule_key(ref),)).fetchall()
    result = []
    for row in rows:
        payload = json.loads(row['payload'])
        schedule = json.loads(row['schedule'])
        fields = {'timezone'} | ({'time'} if row['schedule_kind'] != 'interval' else set())
        if row['schedule_kind'] == 'weekly':
            fields.add('weekdays')
        item = {**{key: row[key] for key in ('id', 'name', 'schedule_kind', 'interval_sec')},
                'objective': payload.get('original_objective', payload['objective']),
                'schedule': {key: val for key, val in schedule.items() if key in fields}}
        for key in ('skill_key', 'start_column_key'):
            if payload.get(key) is not None:
                item[key] = payload[key]
        if any(key in payload.get('parameters', {}) for key in ('followup_pipeline', 'followup_state')):
            item['unavailable'] = '此自动化依赖个人跟进对象。'
        result.append(item)
    return result


def export_selected(host, reference, schedule_ids, *, expected_digest=None):
    if (not isinstance(schedule_ids, list) or len(schedule_ids) > LIMIT
            or any(type(identifier) is not int or identifier < 1 for identifier in schedule_ids)
            or len(set(schedule_ids)) != len(schedule_ids)):
        raise ContractError('请选择要发布的自动化。')
    if not schedule_ids:
        return []
    rows = available(host, reference)
    if expected_digest is not None:
        from runteams_core.authoring.creator_contracts import digest
        from runteams_core.authoring.source.creator_source_revisions import SourceConflict
        if digest(rows) != expected_digest:
            raise SourceConflict('自动化配置已修改，请重新打开发布页。')
    by_id = {row['id']: row for row in rows}
    if set(schedule_ids) - set(by_id):
        raise ContractError('自动化已变化，请重新选择。')
    if any('unavailable' in by_id[identifier] for identifier in schedule_ids):
        raise ContractError('依赖个人跟进对象的自动化无法加入资产。')
    templates = [{**by_id[identifier], 'id': _scope_id('export', reference, identifier)} for identifier in schedule_ids]
    return validate_templates(templates, _kind(reference))


def _recipient_reference(reference):
    if _kind(reference) == 'employee':
        from runteams_core.employees.employee_references import checked_reference
    else:
        from runteams_core.pipelines.pipeline_references import checked_reference
    return checked_reference(reference)


def imported_ids(host, reference, templates):
    """Recover completed imports for this asset, including deliberately deleted plans."""
    reference = _recipient_reference(reference)
    kind = _kind(reference)
    backend = host.backend(kind)
    return [row['id'] for row in validate_templates(templates, kind)
            if backend.receipt(_scope_id('import', reference, row['id']))['state'] == 'committed']


def import_selected(host, reference, templates, template_ids, *, parameters=None):
    """Use existing device save validation and command receipts; never enable a plan."""
    reference = _recipient_reference(reference)
    kind = _kind(reference)
    by_id = {row['id']: row for row in validate_templates(templates, kind)}
    parameters = {} if parameters is None else parameters
    if (not isinstance(template_ids, list) or len(template_ids) > LIMIT or any(not template_id(key) for key in template_ids)
            or len(set(template_ids)) != len(template_ids) or set(template_ids) - set(by_id)
            or not isinstance(parameters, dict) or set(parameters) - set(template_ids)
            or any(not isinstance(value, dict) for value in parameters.values())):
        raise ContractError('请选择要加入本机的自动化模板。')
    if any(not ({'skill_key', 'start_column_key'} & set(by_id[key])) for key in parameters):
        raise ContractError('任务说明类型的模板没有参数。')

    backend = host.backend(kind)
    results = []
    for identifier in template_ids:
        template = by_id[identifier]
        operation_id = _scope_id('import', reference, identifier)
        receipt = backend.receipt(operation_id)
        if receipt['state'] == 'committed':
            result = receipt['result']
        else:
            value = {key: item for key, item in template.items() if key != 'id'}
            value['enabled'] = False
            if 'skill_key' in value or 'start_column_key' in value:
                value['parameters'] = parameters.get(identifier, {})
            result = backend.command({'action': 'save', 'operation_id': operation_id,
                                     'reference': reference, 'id': None, 'expected_revision': None, 'value': value})
        results.append({**result, 'template_id': identifier})
    return results
