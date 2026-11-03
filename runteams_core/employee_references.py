"""Validated employee identities; reference equality grants no execution rights."""
from copy import deepcopy
import json
from . import device_data, rented_references
from .contracts import ContractError

SOURCE_SCHEMA = 'runteams.local-employee-reference/1'
ACQUIRED_SCHEMA = 'runteams.acquired-employee-reference/1'


def checked_reference(value):
    actual=device_data.identity()
    if actual.get('storage_kind')=='local' and (not isinstance(value,dict) or value.get('schema')!=SOURCE_SCHEMA or value.get('storage_kind')!='local'):
        raise PermissionError('本机资料库只提供自己的源码员工。')
    if rented_references.is_rented(value):return deepcopy(rented_references.checked(value,employee=True))
    if isinstance(value, dict) and value.get('schema') in (SOURCE_SCHEMA, ACQUIRED_SCHEMA):
        if not device_data.personal():raise PermissionError('员工不属于当前账户或部署。')
        return checked_source_reference(value,actual)
    from runteams_core.asset_references import BusinessReference
    ref = BusinessReference.from_json(value)
    scope = device_data.identity()
    if (not device_data.personal() or ref.resource != 'employees' or
            ref.deployment_id != scope['deployment_id'] or ref.workspace_id != scope['account_id']):
        raise PermissionError('员工不属于当前账户或部署。')
    return ref.to_json()


def key(reference):
    return json.dumps(checked_reference(reference), sort_keys=True, separators=(',', ':'))


def same(left, right):
    return key(left) == key(right)


def checked_source_reference(value,scope):
    """Immutable source/acquired identity validation; never an access grant."""
    from .work_identity import checked_source_scope
    if not isinstance(value,dict) or value.get('schema') not in (SOURCE_SCHEMA,ACQUIRED_SCHEMA):
        raise ContractError('员工引用无效。')
    if (scope.get('storage_kind')=='local' or value.get('storage_kind')=='local') and value.get('schema')!=SOURCE_SCHEMA:
        raise PermissionError('本机资料库只提供自己的源码员工。')
    fields={'schema','source_id','employee_source'}|checked_source_scope(value,scope)
    if set(value)!=fields:raise ContractError('员工引用无效。')
    import re
    from .creator_contracts import relative
    if not isinstance(value['source_id'],str) or not re.fullmatch('[a-f0-9]{64}',value['source_id']):raise ContractError('员工引用无效。')
    relative(value['employee_source'])
    return deepcopy(value)
