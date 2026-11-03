"""Workspace and employee tools on the actual device session.

These return reviewed proposals, never asset writes, authorization or task effects.
Other conversation scopes use their explicitly bound adapters.
"""
from copy import deepcopy

WORKSPACE_TOOLS=frozenset({'runteams_get_context','runteams_request_choice','runteams_creator_source'})


def dispatch(name,arguments,context):
    supported={'runteams_get_context','runteams_get_employee','runteams_propose_task',
               'runteams_propose_tasks','runteams_request_choice','runteams_creator_source'}
    if name not in supported:return None
    from runteams_core import agent_tool_registry as registry
    from runteams_core import product_store as store
    from runteams_core import device_data
    cid=(context or {}).get('chat_id')
    if not cid or not store.device_chat(cid):return None
    session=store.get_chat(cid,include_messages=False)
    if not session:raise registry.AgentToolError('本机对话已不存在，请重新打开。')
    saved=session.get('context') or {}
    if saved.get('pipeline_work'):
        raise registry.AgentToolError('本次岗位已有流水线工作，请通过岗位交接工具读取输入或提交问题与结果，不能另行派工或代替人工决定。')
    workspace=(session.get('kind')=='general' and session.get('subject_type')=='workspace'
               and saved.get('context_type','general')=='general')
    worker=(session.get('kind')=='general' and session.get('subject_type')=='employee'
            and saved.get('context_type')=='worker' and saved.get('intent') in ('chat','work'))
    if session.get('kind')=='employee_design':
        from runteams_core.creator_local_authoring import source
        source(session)
        worker=True
    if not worker and not workspace:return None
    actual=device_data.identity()
    from runteams_core.work_identity import principal
    if (context or {}).get('actor_id')!=principal(actual):raise PermissionError('账户已变化，请重新打开本机员工对话。')
    if workspace:
        if name not in WORKSPACE_TOOLS:
            raise registry.AgentToolError('请从员工设置或绑定员工的工作对话继续。')
        if name=='runteams_get_context':
            if arguments:raise registry.AgentToolError('上下文读取不接受额外参数。')
            return registry.AgentToolResult('context','已读取当前员工创作上下文。', {
                'conversation':saved,'runtime':deepcopy(context.get('runtime') or {}),
                'employee_creation':{'format':'runteams.creator-project/2',
                    'tool':'runteams_creator_source','source_required':True,
                    'program_optional':True,'ui_optional':True}})
        result=registry.get(name).handler(deepcopy(arguments or {}),{**context,'conversation_context':saved})
        device_data.check(actual)
        return result
    if name=='runteams_creator_source':
        raise registry.AgentToolError('当前工作使用冻结的 SDK 版本，请在原源码对话中修改员工。')
    if name=='runteams_request_choice':
        # Asking a question must remain possible while repairing invalid source.
        result=registry.get(name).handler(deepcopy(arguments or {}),
            {**context,'conversation_context':saved})
        device_data.check(actual);return result
    from runteams_core import employee_binding
    binding=employee_binding.for_context(context)
    employee=binding['employee'];values=deepcopy(arguments or {})
    ctx={**context,'conversation_context':saved}
    summary=employee_binding.summary(binding)
    if name in ('runteams_get_context','runteams_get_employee'):
        allowed=set() if name=='runteams_get_context' else {'employee_id','name','task_limit'}
        if set(values)-allowed:raise registry.AgentToolError('员工读取包含未知参数。')
        if values.get('employee_id') is not None and values['employee_id']!=binding['asset_id']:
            raise registry.AgentToolError('当前对话只能读取原绑定员工。')
        if values.get('name') not in (None,'',employee['name']):
            raise registry.AgentToolError('当前对话只能读取原绑定员工。')
        contracts=[];recent=[]
        if binding['package']:
            from runteams_core.employee_chat_work import catalog
            recent=catalog(binding['reference'],limit=registry._positive_int(values.get('task_limit'),'task_limit') or 50)
            contracts=[{'employee_reference':binding['reference'],'skill_key':skill['key'],
                'name':skill['name'],'input_schema':skill['input_schema']} for skill in summary['skills']]
        else:
            from runteams_core.employee_context import current
            contracts,recent=current().work_catalog(binding,500)
        device_data.check(actual)
        data={'storage_scope':'device','employee':summary,'dispatch_contracts':contracts,'recent_tasks':recent}
        if name=='runteams_get_context':data.update(conversation=saved,resolved={'employee':summary},runtime=deepcopy(context.get('runtime') or {}))
        return registry.AgentToolResult('context' if name=='runteams_get_context' else 'employee','已读取当前员工的工作。',data)
    if values.get('pipeline') or values.get('employee') not in (None,'',employee['name']):
        raise registry.AgentToolError('请在要交办的员工对话中提出工作。')
    values['employee']=employee['name']
    result=registry.get(name).handler(values,ctx)
    for action in result.data.get('actions',[]):
        action['employee_reference']=deepcopy(binding['reference'])
        if session.get('kind')=='employee_design':
            # The name may be edited before this turn commits. The validated
            # source reference owns dispatch; freeze its resulting name later.
            action.pop('employee',None)
    device_data.check(actual);return result
