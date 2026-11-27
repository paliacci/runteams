"""Canonical source pipeline HTTP operations for both host compositions."""
from runteams_core.foundation.contracts import ContractError

def dispatch(core,action,data,active_ids=(),wake=lambda:None):
    from runteams_core.pipelines import source_pipeline_work as pipelines
    core._actor()
    if action == 'environment-check':
        from runteams_core.agents.environment.media_checks import check
        return check(data), 200
    from runteams_core.pipelines import source_pipeline_trash as trash
    if action == 'trash-catalog' and not data:
        return {'items': trash.catalog(core), 'storage_scope': 'device'}, 200
    if action == 'trash' and set(data) == {'reference'}:
        return trash.change(core, data['reference'], active_ids=active_ids), 200
    if action == 'restore' and set(data) == {'reference', 'id'} and type(data['id']) is int:
        return trash.change(core, data['reference'], restore_id=data['id']), 200
    trash.check_available(core, data.get('reference'))
    if action == 'asset-knowledge':
        from runteams_core.conversations.asset_sources import drawer
        from runteams_core.authoring.creator_contracts import CreatorContractError
        from runteams_core.documents.office_text import UnreadableOfficeFile
        try:
            return drawer(data), 200
        except UnreadableOfficeFile as error:
            return {'error': str(error), 'code': 'knowledge_office_unreadable'}, 422
        except CreatorContractError as error:
            if data.get('export') is True and error.code == 'knowledge_name_conflict':
                return {'error': error.details, 'code': error.code}, 409
            raise
    if action in ('card', 'card-operation'):
        from runteams_core.pipelines.pipeline_card_actions import command
        result = command(core, data, active_ids, read_only=action == 'card-operation')
        if action == 'card' and data.get('action') in ('resume', 'edit'):
            wake()
        return result, 200
    if action in ('ui-state-read','ui-state-save'):
        from runteams_core.work import work_ui_state
        if action=='ui-state-read':
            if data:raise ContractError('界面读取请求无效。')
            return work_ui_state.read(),200
        value=work_ui_state.save(data)
        return value if isinstance(value,tuple) else (value,200)
    if action in ('catalog', 'workspace', 'preferences', 'conversation', 'creation-choices', 'create'):
        from runteams_core.pipelines import source_pipeline_workspace as workspace
        if action == 'creation-choices' and not data:
            return workspace.creation_choices(core), 200
        if action == 'create':
            from runteams_core.authoring.source.creator_source_revisions import SourceRevisionChanged
            try:
                return workspace.create(core, data), 200
            except SourceRevisionChanged as error:
                return {'error': str(error), 'code': 'source_revision_conflict', 'status': 409}, 409
        if action == 'catalog' and not data:
            return workspace.catalog(core), 200
        if action == 'workspace' and set(data) in ({'reference'}, {'reference', 'background_revision'}):
            background_revision = data.get('background_revision')
            if background_revision is not None and (not isinstance(background_revision, str) or len(background_revision) not in (64, 66)):
                raise ContractError('背景图修订参数无效。')
            return workspace.workspace(core, data['reference'], active_ids, background_revision=background_revision), 200
        if action == 'preferences':
            return {'ui': workspace.preferences(data.get('reference'), data), 'storage_scope': 'device'}, 200
        if action == 'conversation' and set(data) in ({'reference', 'runtime'},
                                                     {'reference', 'runtime', 'signing_workflow_id'},
                                                     {'reference', 'runtime', 'discussion_id'}):
            result = workspace.conversation(core, data['reference'], data['runtime'],
                                            **({'discussion_id': data['discussion_id']} if 'discussion_id' in data else {}))
            if 'signing_workflow_id' in data:
                from runteams_core.pipelines.pipeline_signing_assistance import bind
                bind(core, result['session']['id'], data['reference'], data['signing_workflow_id'])
            return result, 200
        raise ContractError('智能体团队工作区请求无效。')
    if action == 'position-runtime':
        from runteams_core.pipelines.pipeline_position_runtime import configuration
        fields = {'reference', 'position_key'}
        updates = {'selection', 'expected_selection', 'source_revision'}
        if set(data) not in (fields, fields | updates):
            raise ContractError('岗位模型设置请求无效。')
        change = {key: data[key] for key in updates} if updates <= set(data) else None
        return configuration(core, data['reference'], data['position_key'], change), 200
    if action in ('settings','edit','edit-operation','history','employee-configuration','configuration','records'):
        from runteams_core.pipelines import source_pipeline_settings as settings
        if action == 'settings' and set(data) == {'reference', 'include_configuration'} and data['include_configuration'] is True:
            return settings.read(core, data['reference'], include_configuration=True), 200
        if action == 'records' and set(data) == {'reference', 'overview'} and data['overview'] is True:
            return settings.records(core, data['reference'], overview=True), 200
        if action in ('settings','history','records') and set(data)=={'reference'}:
            return getattr(settings, {'settings':'read','history':'history','records':'records'}[action])(core,data['reference']),200
        if action=='edit':return settings.edit(core,data),200
        if action=='edit-operation':return settings.edit_receipt(core,data),200
        if action in ('employee-configuration','configuration'):
            from runteams_core.configuration.employee_configuration import ConfigurationConflict, ConfigurationInvalid
            try:return (settings.own_configuration if action=='configuration' else settings.employee_configuration)(core,data),200
            except ConfigurationConflict as error:return {'error':str(error),'code':'employee_configuration_conflict'},409
            except ConfigurationInvalid as error:return {'error':str(error),'code':'employee_configuration_invalid','fields':error.errors},422
        raise ContractError('智能体团队设置请求无效。')
    if action == 'work-configuration':
        from runteams_core.pipelines.pipeline_task_configuration import request, ConfigurationInvalid
        try:result = request(core, data, active_ids)
        except ConfigurationInvalid as error:
            return {'error':str(error), 'code':'task_configuration_invalid', 'fields':error.fields},422
        return result if isinstance(result, tuple) else (result, 200)
    if action in ('flow','flow-operation'):
        from runteams_core.employees.employee_work_contracts import WorkPreparationRequired
        from runteams_core.pipelines.source_pipeline_flow import WorkflowVisitChanged, command
        try:
            result=command(core,data,active_ids,read_only=action=='flow-operation')
        except WorkflowVisitChanged as error:
            return {'error':str(error), 'code':'workflow_visit_changed'},409
        except WorkPreparationRequired as error:
            return {'error':str(error), 'code':'work_preparation_required', 'reason':error.reason},409
        if action=='flow' and data.get('action') not in ('suggest_responses','suggest_approval'):wake()
        return result,200
    if action in ('state','control','control-operation'):
        from runteams_core.pipelines import source_pipeline_control as control
        if action == 'state' and set(data) == {'reference'}:
            return control.state(core,data['reference'],active_ids),200
        if action == 'control-operation':
            return control.control_operation(core,data,active_ids),200
        if action == 'control':
            result=control.command(core,data,active_ids)
            if data.get('action')=='start':wake()
            return result,200
        raise ContractError('智能体团队控制读取参数无效。')
    if action == 'contract' and set(data) in ({'reference'},{'reference','start_column_key'}):
        from runteams_core.pipelines.source_pipeline_control import dispatch_contract
        return dispatch_contract(core, data['reference'],data.get('start_column_key')), 200
    if action == 'operation':
        return pipelines.operation(core, data), 200
    if action == 'dispatch':
        result = pipelines.create(core, data)
        wake()
        return result, 200
    if action == 'work' and set(data) == {'reference', 'workflow_id'} and type(data['workflow_id']) is int:
        return pipelines.work(core, data['reference'], data['workflow_id']), 200
    if (action == 'work-activity' and set(data) == {'reference', 'workflow_id', 'run_id'}
            and all(type(data[key]) is int and 0 < data[key] < 2**53 for key in ('workflow_id', 'run_id'))):
        return pipelines.work_activity(core, data['reference'], data['workflow_id'], data['run_id']), 200
    if action == 'task-report' and set(data) == {'reference', 'workflow_id'} and type(data['workflow_id']) is int:
        from runteams_core.pipelines.pipeline_task_report import open_report
        return open_report(core, data['reference'], data['workflow_id']), 200
    raise ContractError('不支持的智能体团队工作操作。')
