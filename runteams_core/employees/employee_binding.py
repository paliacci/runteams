"""Resolve an employee from its verified session, never a name or bare record ID.

Source, installed asset and frozen work are facts about an employee. Internal
asset/work record numbers are deliberately confined to the asset adapter here.
"""
from runteams_core.documents import document_ownership
from runteams_core.employees import employee_references
from copy import deepcopy
from contextlib import contextmanager


from runteams_core.storage import device_data
from runteams_core.foundation.contracts import ContractError


def authoring_reference(session):
    """Resolve one author-owned source through its original scoped session."""
    if not session or session.get('kind') != 'employee_design':
        return None
    from runteams_core.authoring.creator_local_authoring import source
    from runteams_core.employees.employee_directory import for_session
    source(session)  # Checks the saved source context and current account scope.
    return employee_references.checked_reference(for_session(session)['source']['reference'])


def resolve(session):
    """Read exact frozen bytes. This neither acquires nor publishes an asset."""
    from runteams_core.storage import product_store
    if not session or not product_store.device_chat(session['id']):
        raise ContractError('请在员工的原工作对话中继续。')
    reference = authoring_reference(session)
    if reference is not None:
        from runteams_core.employees.source_employee_runtime import prepare, employee
        import uuid
        package = prepare(reference, str(uuid.uuid4()))
        return {'reference': reference, 'employee': employee(package),
                'package': package, 'asset_id': None}
    if session.get('kind') != 'general' or session.get('subject_type') != 'employee':
        raise ContractError('请在员工的原工作对话中继续。')
    context = session.get('context') or {}
    package = context.get('local_employee_package')
    if package is not None:
        from runteams_core.employees.source_employee_runtime import for_chat
        employee = for_chat(session['id'])
        reference = employee_references.checked_reference(package['reference'])
        if context.get('source_employee') != reference:
            raise ContractError('员工会话的源码绑定已变化。')
        return {'reference': reference, 'employee': employee,
                'package': deepcopy(package), 'asset_id': None}
    from runteams_core.employees.employee_context import current
    return current().acquired_binding(session)


def for_context(context):
    """Model-provided names/IDs cannot override the server-owned chat binding."""
    from runteams_core.storage import product_store
    from runteams_core.foundation.identity.work_identity import principal
    if (context or {}).get("actor_id") not in (None,principal(device_data.identity())):
        raise PermissionError("员工不属于当前账户。")
    cid = (context or {}).get('chat_id')
    if not cid or not product_store.device_chat(cid):
        if ((context or {}).get('conversation_context') or {}).get('source_employee'):
            raise PermissionError('请在员工的原工作对话中继续。')
        return None
    session = product_store.get_chat(cid, include_messages=False)
    if not session or (session.get('subject_type') != 'employee' and
                       session.get('kind') != 'employee_design'):
        return None
    binding = resolve(session)
    supplied = (context or {}).get('conversation_context') or {}
    for field in ('source_employee', 'employee_reference'):
        if supplied.get(field) is not None and not employee_references.same(supplied[field], binding['reference']):
            raise PermissionError('当前工作不能更换员工。')
    return binding


def summary(binding):
    item = binding['employee']
    from runteams_core.employees.source_employee_runtime import units, package_asset
    skills = units(package_asset(binding['package'])) if binding['package'] else [
        {'key': u['skill_key'], 'name': u['work']['name'],
         'input_schema': u['work']['input_schema']}
        for u in item['active_release']['snapshot_json']['work_units']]
    if binding['package']:
        from runteams_core.authoring.creator_conversation_assets import extension
        declared={bundle['package_key']:extension(bundle).get('work') for bundle in package_asset(binding['package'])['skill_bundles']}
        skills=[{**(declared.get(skill['key']) or {}),**skill} for skill in skills]
    return {'schema': 'runteams.bound-employee/v1', 'reference': deepcopy(binding['reference']),
            'name': item['name'], 'avatar': item['avatar'], **({'avatar_src':item['avatar_src']} if item.get('avatar_src') else {}), 'skills': skills,
            'storage_scope': 'device', 'source_revision': (binding['package'] or {}).get('revision')}


def public(session):
    binding = resolve(session)
    return summary(binding)


@contextmanager
def document_owner(session):
    binding=resolve(session) if (session.get('subject_type')=='employee' or
                               session.get('kind')=='employee_design') else None
    marker=document_ownership._document_owner.set({'employee_reference':binding['reference'],
        'workflow_id':(session.get('context') or {}).get('employee_work',{}).get('workflow_id')} if binding else None)
    try:yield
    finally:document_ownership._document_owner.reset(marker)


def related_references(reference):
    from runteams_core.assets.rented_references import is_rented
    if is_rented(reference) or reference.get('schema') == employee_references.ACQUIRED_SCHEMA:
        return [employee_references.checked_reference(reference)]
    """Explicit author/publication links are read-only relationship facts."""
    reference=employee_references.checked_reference(reference);result=[reference]
    from runteams_core.assets.source_links import links
    from runteams_core.assets.source_links import linked_source
    from runteams_core.authoring.source.creator_local_source import current_store
    store=current_store(device_data.identity()['cache_scope'])
    if reference['schema']=='runteams.local-employee-reference/1':
        try:mapping=links(store,reference['source_id'])
        except FileNotFoundError:return result
        asset=mapping.get(reference['employee_source'])
        if asset:result.append(employee_references.checked_reference(asset))
    else:
        original=linked_source(store,reference)
        if original:
            from runteams_core.employees.source_employee_runtime import reference as source_reference
            result.append(source_reference(*original))
    return result
