"""Pipeline reference syntax and scope, independent of work execution."""
import copy
import re
from runteams_core.storage import device_data
from runteams_core.assets import rented_references
from runteams_core.foundation.contracts import ContractError
from runteams_core.authoring.creator_contracts import relative

REFERENCE = 'runteams.local-pipeline-reference/1'


FIELDS = {'schema', 'source_id', 'pipeline_source'}


def checked_reference(value, scope=None):
    scope = device_data.identity() if scope is None else scope
    if rented_references.is_rented(value):
        if scope.get('storage_kind')=='local':raise PermissionError('本机资料库不提供租用资产授权。')
        return rented_references.checked(value,scope)
    from runteams_core.foundation.identity.work_identity import checked_source_scope
    if not isinstance(value,dict):raise ContractError('流水线源码引用无效。')
    try:owner_fields=checked_source_scope(value,scope)
    except PermissionError:raise PermissionError('流水线不属于当前资料库、账户或部署。') from None
    if not isinstance(value, dict) or set(value) != FIELDS | owner_fields or value.get('schema') != REFERENCE:
        raise ContractError('流水线源码引用无效。')
    if not isinstance(value['source_id'], str) or not re.fullmatch('[a-f0-9]{64}', value['source_id']):
        raise ContractError('流水线源码身份无效。')
    relative(value['pipeline_source'])
    return copy.deepcopy(value)


def reference(source_id, pipeline_source):
    scope = device_data.identity()
    from runteams_core.foundation.identity.work_identity import source_scope
    return checked_reference({'schema': REFERENCE, 'source_id': source_id, 'pipeline_source': pipeline_source,
        **source_scope(scope)})
