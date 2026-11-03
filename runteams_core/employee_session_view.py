"""Canonical projection of verified employee sessions for both hosts."""
SESSION_KIND='employee_design'

def work_session_record(session):
    """Validate a saved local work identity without authorizing its execution."""
    context=(session or {}).get('context') or {}
    package=context.get('local_employee_package')
    if package is None:
        return False
    from . import device_data
    from .employee_references import checked_reference
    from .employee_work_contracts import SCHEMA,verify_frozen
    if (session.get('kind')!='general' or session.get('subject_type')!='employee'
            or session.get('scope_type')!='global' or not device_data.contains(session['id'])):
        raise PermissionError('原员工工作对话引用无效。')
    reference=checked_reference(context.get('source_employee'))
    verify_frozen({'schema':SCHEMA,'employee_reference':reference,'package':package},device_data.identity())
    if context.get('pipeline_work'):
        from .source_pipeline_work import verify_context
        verify_context(context['pipeline_work'],package)
    return True

def public_session(session):
    if not session:
        return session
    value = dict(session)
    context = dict(value.get("context") or {})
    value["context"] = context
    if value.get('kind') == SESSION_KIND and context.get('creator_local_source_id'):
        from runteams_core.employee_directory import for_session
        try:employee = for_session(session)
        except (ValueError,OSError) as exc:
            # A broken resource projection cannot make the original transcript
            # unreadable. No employee or permission is synthesized from its title.
            value['employee_error']=str(exc)
        else:
            value['employee'] = employee
            value['identity'] = {key:employee['record'][key] for key in ('name','avatar','avatar_src') if key in employee['record']}
    if value.get('kind') == 'general' and context.get('local_employee_package'):
        from runteams_core.source_employee_runtime import for_chat
        try:
            employee = for_chat(value['id'])
            value['identity'] = {key:employee[key] for key in ('name','avatar','avatar_src') if key in employee}
            from runteams_core.device_employee_mcp import bundles
            value['identity']['local_mcp'] = bool(bundles(employee))
        except (ValueError,OSError) as exc:value['employee_error']=str(exc)
    if value.get('kind')=='general' and value.get('subject_type')=='employee':
        from runteams_core.employee_binding import public
        try:value['employee_binding']=public(session)
        except (ValueError,OSError) as exc:value['employee_error']=str(exc)
    return value

