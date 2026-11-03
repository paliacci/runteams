"""Canonical declaration-bound collection choices and idempotent imports."""
from contextlib import nullcontext
from runteams_core.authoring.creator_contracts import strict_json
from runteams_core.configuration.employee_configuration import for_source
from runteams_core.configuration.configuration_schema import fields
from runteams_core.assets.collections.local_collections import Collections

def dispatch(method,body,*,importing=False):
    if not isinstance(body,dict):raise ValueError('配置请求无效。')
    work = 'chat_id' in body
    source = {'source_id', 'employee_source'} <= set(body)
    pipeline = 'pipeline_reference' in body
    target = {'chat_id'} if work else ({'pipeline_reference','employee_source'} if 'employee_source' in body else {'pipeline_reference'}) if pipeline else {'source_id', 'employee_source'} if source else {'employee_id'}
    write_fields = {'selection', 'records', 'operation_id', 'definition_sha256'} if importing else {'name', 'operation_id', 'definition_sha256'}
    expected = target | {'field'} | (write_fields if method == 'POST' else set())
    if set(body) != expected: raise ValueError()
    if work:
        value=body['chat_id']
        if isinstance(value,bool) or not isinstance(value,(str,int)) or str(int(value))!=str(value) or int(value)<=0:raise ValueError('工作引用无效。')
        from runteams_core.configuration.employee_configuration import for_work_settings
        manager=nullcontext(for_work_settings(int(value)))
    elif pipeline:
        from runteams_core.pipelines.pipeline_context import current
        ref = strict_json(body['pipeline_reference'].encode()) if method=='GET' else body['pipeline_reference']
        manager = current().configuration_store(ref,body['employee_source']) if 'employee_source' in body else current().own_configuration_store(ref)
    elif source:
        from runteams_core.employees.source_employee_runtime import reference
        manager = for_source(reference(body['source_id'], body['employee_source']))
    else:
        from runteams_core.employees.employee_context import current
        manager = nullcontext(current().downloaded_configuration(int(body['employee_id'])))
    with manager as config:
        if method == 'POST' and body['definition_sha256'] != config.definition_sha256:
            raise ValueError('配置已更新，请保留原创建请求后核对。')
        field = next((f for f in fields(config.definition) if f['key'] == body['field']), None)
        from runteams_core.configuration import configuration_documents, configuration_collections
        if field and configuration_documents.supports(field):
            if method!='GET' or importing:raise PermissionError('请在原文档入口创建或编辑文档，再选择用于工作。')
            return {'items':configuration_documents.options(field)}
        if field and configuration_collections.supports(field):
            if method!='GET' or importing:raise PermissionError('请从已有数据集合选择工作资料。')
            return {'items':configuration_collections.options(field)}
        if not field or field.get('binding', {}).get('provider') != 'local_collection':
            raise PermissionError('当前资产未声明这项本机数据配置。')
        store = Collections()
        result = ({'items': store.options(field)} if method == 'GET' else
                  store.import_records(field, body['selection'], body['records'], body['operation_id']) if importing else
                  {'selection': store.create(field, body['name'], body['operation_id'])})
    return result
