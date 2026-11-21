"""Public page identities for device conversations and their owning assets."""
from runteams_core.assets import source_links
from runteams_core.authoring.creator_contracts import digest


def page_id(identity):
    return digest(identity)[:32]


def _owner_identity(context):
    pipeline = context.get('source_pipeline_workspace')
    if pipeline:
        return 'pipelines', pipeline
    employee = context.get('source_employee') or context.get('employee_reference')
    if employee:
        if 'employee_source' in employee:
            return 'employees', source_links.source_key(employee['source_id'], employee['employee_source'])
        return 'employees', source_links.reference_key(employee)
    if context.get('creator_employee_source'):
        return 'employees', source_links.source_key(context['creator_local_source_id'], context['creator_employee_source'])
    return '', None


def chat_owner_paths(contexts):
    """Match published employees to their source identities once per read."""
    owners = [_owner_identity(context) for context in contexts]
    assets = {key for kind, key in owners if kind == 'employees' and key.startswith('asset:')}
    source_keys = {}
    if assets:
        from runteams_core.authoring.source.creator_local_source import current_store
        from runteams_core.storage import device_data
        store = current_store(device_data.identity()['cache_scope'])
        for key, source in source_links.linked_sources(store, assets).items():
            source_keys[key] = source_links.source_key(*source)

    paths = []
    for kind, key in owners:
        if kind == 'employees':
            key = source_keys.get(key, key)
        paths.append('/' + kind + '/' + page_id(key) if kind else '')
    return paths


def chat_owner_path(context):
    return chat_owner_paths([context])[0]
