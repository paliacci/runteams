"""Canonical projection of verified employee sessions for both hosts."""
SESSION_KIND='employee_design'
BACKGROUND_FIELDS=('workspace_background_src','workspace_background_color')
IDENTITY_FIELDS=('name','avatar','avatar_src',*BACKGROUND_FIELDS)

def work_session_record(session):
    """Validate a saved local work identity without authorizing its execution."""
    context=(session or {}).get('context') or {}
    package=context.get('local_employee_package')
    if package is None:
        return False
    from runteams_core.storage import device_data
    from runteams_core.employees.employee_references import checked_reference
    from runteams_core.employees.employee_work_contracts import SCHEMA, verify_frozen
    if (session.get('kind')!='general' or session.get('subject_type')!='employee'
            or session.get('scope_type')!='global' or not device_data.contains(session['id'])):
        raise PermissionError('原员工工作对话引用无效。')
    reference=checked_reference(context.get('source_employee'))
    verify_frozen({'schema':SCHEMA,'employee_reference':reference,'package':package},device_data.identity())
    if context.get('pipeline_work'):
        from runteams_core.pipelines.source_pipeline_work import verify_context
        verify_context(context['pipeline_work'],package)
    return True

def public_session(session, *, include_background=True):
    if not session:
        return session
    value = dict(session)
    context = dict(value.get("context") or {})
    value["context"] = context
    if value.get('kind') == SESSION_KIND and context.get('creator_local_source_id'):
        from runteams_core.employees.employee_directory import for_session
        try:employee = for_session(session, include_background=include_background)
        except (ValueError,OSError) as exc:
            # A broken resource projection cannot make the original transcript
            # unreadable. No employee or permission is synthesized from its title.
            value['employee_error']=str(exc)
        else:
            value['employee'] = employee
            value['identity'] = {key:employee['record'][key] for key in IDENTITY_FIELDS if key in employee['record']}
            for key in BACKGROUND_FIELDS:
                employee['record'].pop(key, None)
    if value.get('kind') == 'general' and context.get('local_employee_package'):
        from runteams_core.employees.employee_binding import resolve, summary
        from runteams_core.employees.mcp.device_employee_mcp import inspect_attachments
        try:
            binding = resolve(session, include_background=include_background)
        except (ValueError, OSError) as exc:
            value['employee_error'] = str(exc)
            return value
        employee = binding['employee']
        value['identity'] = {key: employee[key] for key in IDENTITY_FIELDS if key in employee}
        try:
            value['identity']['local_mcp'] = bool(inspect_attachments(employee))
        except (ValueError, OSError) as exc:
            value['employee_error'] = str(exc)
        try:
            value['employee_binding'] = summary(binding)
        except (ValueError, OSError) as exc:
            value['employee_error'] = str(exc)
    elif value.get('kind')=='general' and value.get('subject_type')=='employee':
        from runteams_core.employees.employee_binding import public
        try:value['employee_binding']=public(session)
        except (ValueError,OSError) as exc:value['employee_error']=str(exc)
    return value

