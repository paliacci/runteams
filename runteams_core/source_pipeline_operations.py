"""Canonical source pipeline HTTP operations for both host compositions."""
from .contracts import ContractError

def dispatch(core,action,data,active_ids=(),wake=lambda:None):
    from . import source_pipeline_work as pipelines
    core._actor()
    if action in ('ui-state-read','ui-state-save'):
        from . import work_ui_state
        if action=='ui-state-read':
            if data:raise ContractError('界面读取请求无效。')
            return work_ui_state.read(),200
        value=work_ui_state.save(data)
        return value if isinstance(value,tuple) else (value,200)
    if action in ('catalog', 'workspace', 'preferences', 'conversation', 'creation-choices', 'create'):
        from . import source_pipeline_workspace as workspace
        if action == 'creation-choices' and not data:
            return workspace.creation_choices(core), 200
        if action == 'create':
            return workspace.create(core, data), 200
        if action == 'catalog' and not data:
            return workspace.catalog(core), 200
        if action == 'workspace' and set(data) == {'reference'}:
            return workspace.workspace(core, data['reference'], active_ids), 200
        if action == 'preferences':
            return {'ui': workspace.preferences(data.get('reference'), data), 'storage_scope': 'device'}, 200
        if action == 'conversation' and set(data) == {'reference', 'runtime'}:
            return workspace.conversation(core, data['reference'], data['runtime']), 200
        raise ContractError('流水线工作区请求无效。')
    if action in ('settings','edit','edit-operation','history','employee-configuration','configuration','records'):
        from . import source_pipeline_settings as settings
        if action in ('settings','history','records') and set(data)=={'reference'}:
            return getattr(settings, {'settings':'read','history':'history','records':'records'}[action])(core,data['reference']),200
        if action=='edit':return settings.edit(core,data),200
        if action=='edit-operation':return settings.edit_receipt(core,data),200
        if action in ('employee-configuration','configuration'):
            from .employee_configuration import ConfigurationConflict,ConfigurationInvalid
            try:return (settings.own_configuration if action=='configuration' else settings.employee_configuration)(core,data),200
            except ConfigurationConflict as error:return {'error':str(error),'code':'employee_configuration_conflict'},409
            except ConfigurationInvalid as error:return {'error':str(error),'code':'employee_configuration_invalid','fields':error.errors},422
        raise ContractError('流水线设置请求无效。')
    if action in ('flow','flow-operation'):
        from .source_pipeline_flow import command
        result=command(core,data,active_ids,read_only=action=='flow-operation')
        if action=='flow':wake()
        return result,200
    if action in ('state','control','control-operation'):
        from . import source_pipeline_control as control
        if action == 'state' and set(data) == {'reference'}:
            return control.state(core,data['reference'],active_ids),200
        if action == 'control-operation':
            return control.control_operation(core,data,active_ids),200
        if action == 'control':
            result=control.command(core,data,active_ids)
            if data.get('action')=='start':wake()
            return result,200
        raise ContractError('流水线控制读取参数无效。')
    if action == 'contract' and set(data) in ({'reference'},{'reference','start_column_key'}):
        from .source_pipeline_control import dispatch_contract
        return dispatch_contract(core, data['reference'],data.get('start_column_key')), 200
    if action == 'operation':
        return pipelines.operation(core, data), 200
    if action == 'dispatch':
        result = pipelines.create(core, data)
        wake()
        return result, 200
    if action == 'work' and set(data) == {'reference', 'workflow_id'} and type(data['workflow_id']) is int:
        return pipelines.work(core, data['reference'], data['workflow_id']), 200
    raise ContractError('不支持的流水线工作操作。')
