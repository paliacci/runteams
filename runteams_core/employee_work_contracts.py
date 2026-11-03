"""Immutable employee-work backup facts, without acquisition or execution rights."""
from . import employee_acquisition_refs, rented_references
from .contracts import ContractError

SOURCE_PACKAGE = 'runteams.local-employee-package/1'
RENTED_PACKAGE = 'runteams.rented-employee-package/1'
ACQUIRED_PACKAGE = 'runteams.acquired-employee-package/1'
SCHEMA = 'runteams.employee-chat-work/v1'

class WorkPreparationRequired(ContractError):
    """The original chat exists, but no work send has been admitted."""

def verify_prepared_session(frozen,session,workflow_id,task_id):
    context=(session or {}).get('context') or {}
    if (not session or session['id']!=frozen.get('work_chat_id')
            or context.get('local_employee_package')!=frozen['package']
            or context.get('employee_work')!={'workflow_id':workflow_id,'task_id':task_id}
            or context.get('pipeline_work')!=frozen.get('pipeline_work')
            or context.get('pipeline_generation')!=frozen.get('pipeline_generation')
            or context.get('employee_configuration_snapshot')!=frozen.get('configuration')):
        raise ContractError('原岗位准备会话与固定工作不一致。')


def verify_frozen(value,scope):
    """Check backup cross-links without reading or authorizing mutable sources."""
    import re
    PACKAGE = SOURCE_PACKAGE
    from .employee_references import SOURCE_SCHEMA as REFERENCE_SCHEMA
    rental=isinstance(value.get('package'),dict) and value['package'].get('schema')==RENTED_PACKAGE
    if rental:PACKAGE,REFERENCE_SCHEMA=RENTED_PACKAGE,rented_references.EMPLOYEE
    acquired_package = isinstance(value.get('package'), dict) and value['package'].get('schema') == ACQUIRED_PACKAGE
    if acquired_package:
        from .employee_references import ACQUIRED_SCHEMA
        PACKAGE, REFERENCE_SCHEMA = ACQUIRED_PACKAGE, ACQUIRED_SCHEMA
    from .definition_contracts import validate_definition
    if value.get('schema')!=SCHEMA:raise ContractError('员工工作快照无效。')
    package=value.get('package');reference=value.get('employee_reference')
    from .work_identity import checked_source_scope
    if not isinstance(reference,dict):raise ContractError('员工工作引用无效。')
    fields={'schema','source_id','employee_source'}|checked_source_scope(reference,scope)
    if not isinstance(reference,dict) or set(reference)!=fields or reference['schema']!=REFERENCE_SCHEMA:
        raise ContractError('员工工作引用无效。')
    from .creator_contracts import relative
    relative(reference['employee_source'])
    if reference.get('storage_kind')=='local' and (rental or acquired_package):
        raise PermissionError('本机资料库不包含下载或租用授权。')
    expected={'schema','reference','revision','build_operation_key','result_sha256','runtime'}
    if acquired_package:
        expected.add('acquisition')
        from .resource_ids import resource_id
        origin = package.get('acquisition')
        if not isinstance(origin, dict) or set(origin) not in ({'installation_id','release_id'}, {'installation_id','release_id','rental_source_id'}):
            raise ContractError('已下载员工的冻结来源无效。')
        resource_id(origin['installation_id']); resource_id(origin['release_id'])
        if (reference['source_id'] != employee_acquisition_refs.source_id({**origin,'employee_source':reference['employee_source']})
                or package['revision'] != 'r-' + package['result_sha256'] or package['build_operation_key'] != 'release-' + origin['release_id']):
            raise ContractError('已下载员工的冻结版本不一致。')
    if not isinstance(package,dict) or set(package)!=expected or package['schema']!=PACKAGE or package['reference']!=reference:
        raise ContractError('员工工作运行包无效。')
    if any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in [reference['source_id'],package['result_sha256']]):
        raise ContractError('员工工作冻结内容无效。')
    from .creator_source_revisions import REV
    if package['revision'] != reference['source_id'] and (
            not isinstance(package['revision'], str) or not REV.fullmatch(package['revision'])):
        raise ContractError('员工工作源码修订无效。')
    from .source_artifacts import KEY
    if not isinstance(package['build_operation_key'],str) or not KEY.fullmatch(package['build_operation_key']):
        raise ContractError('员工工作构建引用无效。')
    validate_definition('runtime_snapshot',package['runtime'])
    if value.get('pipeline_work') is not None:
        from .source_pipeline_work import verify_context
        verify_context(value['pipeline_work'], package, scope)
        if type(value.get('pipeline_generation')) is not int or value['pipeline_generation']<1:
            raise ContractError('流水线工作应用代际无效。')
        history=value.get('pipeline_history',[])
        if not isinstance(history,list):raise ContractError('流水线工作历史无效。')
        if type(value.get('pipeline_visit')) is not int or value['pipeline_visit']<1:raise ContractError('流水线岗位访问记录无效。')
        last=0;generation=0
        for item in history:
            if not isinstance(item,dict) or set(item)!={'snapshot'}:raise ContractError('流水线工作历史无效。')
            old=item['snapshot']
            if old.get('pipeline_history') or old.get('pipeline_work',{}).get('reference')!=value['pipeline_work']['reference']:
                raise ContractError('流水线历史归属无效。')
            verify_frozen(old,scope)
            if not generation<=old['pipeline_generation']<=value['pipeline_generation'] or not last<old['pipeline_visit']<value['pipeline_visit']:raise ContractError('流水线历史代际无效。')
            last=old['pipeline_visit'];generation=old['pipeline_generation']
    preparation=value.get('pipeline_setup_required')
    if preparation is not None:
        if (not value.get('pipeline_work') or not isinstance(preparation,dict) or set(preparation)!={'chat_id','message'}
                or type(preparation.get('chat_id')) is not int or preparation['chat_id']!=value.get('work_chat_id')
                or not isinstance(preparation.get('message'),str) or not 0<len(preparation['message'])<=1000
                or value.get('send_admitted') or value.get('employee_run_id') or value.get('pipeline_unresolved')):
            raise ContractError('岗位准备现场记录无效。')
    if value.get('send_admitted') and (type(value.get('work_chat_id')) is not int or type(value.get('employee_run_id')) is not int):
        raise ContractError('员工工作缺少原执行回执。')
    return value
