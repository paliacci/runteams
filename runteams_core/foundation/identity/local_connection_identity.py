"""Actual local-source work identity for the original native HTTPS transport.

This encodes identity only. Original program enablement, current user connection
consent, token lease and durable effect admission must still be supplied by the
host; this module cannot turn a declaration or portable record into authority.
"""
import re
import uuid
from runteams_core.authoring.creator_contracts import contract, digest

SCHEMA='runteams.local-connection-binding/1'
FIELDS=frozenset({'schema','library_id','source_id','source_revision','owner_kind','owner_sha256',
    'release_digest','program_sha256','work_id','connection','descriptor_sha256'})
DIGESTS=('source_id','owner_sha256','release_digest','program_sha256','descriptor_sha256')


def valid_binding(value):
    from runteams_core.authoring.source.creator_source_revisions import REV
    if (not isinstance(value,dict) or set(value)!=FIELDS or value.get('schema')!=SCHEMA
            or value.get('owner_kind') not in ('employee','pipeline')
            or any(not isinstance(value.get(key),str) or re.fullmatch('[a-f0-9]{64}',value[key]) is None for key in DIGESTS)
            or not isinstance(value.get('work_id'),str) or not 1<=len(value['work_id'])<=256
            or not isinstance(value.get('connection'),str) or re.fullmatch('[a-z][a-z0-9_.-]{0,79}',value['connection']) is None):return False
    if value.get('source_revision') != value.get('source_id') and (not isinstance(value.get('source_revision'),str) or not REV.fullmatch(value['source_revision'])):return False
    try:return isinstance(value['library_id'],str) and str(uuid.UUID(value['library_id']))==value['library_id']
    except ValueError:return False


def for_work(reference,revision,binding,program,descriptor):
    from runteams_core.storage import device_data
    from runteams_core.employees.mcp.employee_mcp import WorkBinding, PipelineWorkBinding
    scope=device_data.identity()
    if not scope.get('library_id') or not device_data.personal():raise PermissionError('请在原个人资料库连接服务。')
    if not isinstance(reference,dict):raise PermissionError('连接缺少源码引用。')
    if type(binding) is WorkBinding:
        from runteams_core.employees.employee_references import checked_reference
        if reference.get('schema')!='runteams.local-employee-reference/1':raise PermissionError('连接不属于源码员工。')
        checked=checked_reference(reference);kind='employee'
        from runteams_core.assets.source_links import source_key
        if binding.employee_id!=source_key(checked['source_id'],checked['employee_source']):raise PermissionError('连接不属于原员工。')
    elif type(binding) is PipelineWorkBinding:
        from runteams_core.pipelines.pipeline_references import checked_reference
        checked=checked_reference(reference);kind='pipeline'
        if binding.pipeline_id!=digest(checked):raise PermissionError('连接不属于原流水线。')
    else:raise PermissionError('连接缺少实际工作身份。')
    if binding.account_scope!=scope['cache_scope'] or checked.get('storage_kind')=='local' and checked.get('library_id')!=scope['library_id']:
        raise PermissionError('连接不属于当前资料库。')
    contract('connection.schema.json',descriptor)
    value={'schema':SCHEMA,'library_id':scope['library_id'],'source_id':checked['source_id'],
        'source_revision':revision,'owner_kind':kind,'owner_sha256':digest(checked),
        'release_digest':binding.release_digest,'program_sha256':program,'work_id':binding.work_id,
        'connection':descriptor['key'],'descriptor_sha256':digest(descriptor)}
    if not valid_binding(value):raise ValueError('本机连接工作身份无效。')
    device_data.check(scope);return value


AUTHORITY_SCHEMA='runteams.local-connection-authorization/1'
AUTHORITY_FIELDS=FIELDS-{'work_id','release_digest'}


def for_authority(binding):
    """Service consent follows exact source/owner/program/descriptor, not work.

    This is an identity projection, not a grant. The actual credential and
    HTTPS request still use the original full current work binding.
    """
    if not valid_binding(binding):raise ValueError('本机连接工作身份无效。')
    return {**{key:binding[key] for key in sorted(AUTHORITY_FIELDS)},'schema':AUTHORITY_SCHEMA}
