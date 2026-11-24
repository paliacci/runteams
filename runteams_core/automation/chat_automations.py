"""Apply automation tools to the already authorized asset of a chat turn."""
import uuid

from runteams_core.automation.device_employee_schedules import canonical
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data

_NAMESPACE = uuid.UUID('f59592df-fb5d-4058-be55-45720a741936')
_TARGET = {'id', 'expected_revision'}
_SCHEDULE = {'schedule_kind', 'interval_sec', 'schedule'}
_MUTATIONS = {'edit', 'reschedule', 'pause', 'resume', 'delete', 'run'}


def execute(host, *, kind, reference, turn_key, operation, arguments, templates=None):
    """Use server-owned conversation context and the existing durable command ledger."""
    if not device_data.personal():
        raise PermissionError('请在个人工作对话中设置自动化。')
    if kind not in ('employee', 'pipeline') or not isinstance(reference, dict) or not turn_key:
        raise PermissionError('此对话未绑定可设置自动化的资产。')
    if not isinstance(arguments, dict):
        raise ContractError('自动化操作内容无效。')

    if operation == 'compare':
        from runteams_core.automation.automation_run_history import execute as history
        keys = arguments.get('run_keys')
        if (set(arguments) != {'run_keys'} or not isinstance(keys, list) or len(keys) != 2
                or not all(isinstance(key, str) and key for key in keys) or keys[0] == keys[1]):
            raise ContractError('请从当前资产的历史记录中选择两次不同的运行。')
        return {'runs': [history(host, kind=kind, reference=reference, operation='review',
                                 arguments={'run_key': key}) for key in keys]}

    if operation == 'history' or operation == 'review' and 'run_key' in arguments:
        from runteams_core.automation.automation_run_history import execute as history
        return history(host, kind=kind, reference=reference, operation=operation, arguments=arguments)

    if operation == 'review':
        from runteams_core.automation.automation_run_review import execute as review
        return review(host, kind=kind, reference=reference, arguments=arguments)

    if operation == 'stop_current':
        from runteams_core.automation.stop_current_task import execute as stop_current
        return stop_current(host, kind=kind, reference=reference, turn_key=turn_key, arguments=arguments)

    if operation == 'rerun':
        from runteams_core.automation.automation_rerun import execute as rerun
        return rerun(host, kind=kind, reference=reference, turn_key=turn_key, arguments=arguments)

    if operation in ('skip_next', 'move_next'):
        from runteams_core.automation.single_occurrence import execute as adjust_once
        return adjust_once(host, kind=kind, reference=reference, turn_key=turn_key,
                           operation=operation, arguments=arguments)

    if operation in ('list_templates', 'import_templates'):
        if templates is None:
            raise ContractError('当前应用不提供资产自动化模板。')
        return templates(reference, operation, arguments)

    if operation == 'list' and not arguments:
        return host.backend(kind).list_reference(reference)

    if operation == 'start_input' and kind == 'pipeline' and set(arguments) == {'start_column_key'}:
        contract = host.backend(kind).contract(reference, arguments['start_column_key'])
        return {key: contract[key] for key in ('position_key', 'position_name', 'input_schema')}

    identifier = None
    revision = None
    value = None
    action = operation
    if operation == 'create' and set(arguments) == {'value'}:
        value = arguments['value']
        action = 'save'
    elif operation in _MUTATIONS:
        expected = _TARGET | _SCHEDULE if operation == 'reschedule' else _TARGET
        if operation == 'edit':
            expected = expected | {'changes'}
        if set(arguments) != expected:
            raise ContractError('请先读取自动化及其当前版本。')
        identifier, revision = arguments['id'], arguments['expected_revision']
        if type(identifier) is not int or identifier < 1 or type(revision) is not int or revision < 0:
            raise ContractError('请先读取自动化及其当前版本。')
        if operation == 'reschedule':
            value = {key: arguments[key] for key in _SCHEDULE}
        elif operation == 'edit':
            value = arguments['changes']
    else:
        raise ContractError('自动化操作内容无效。')

    # The same turn/action/target can recover its committed result. A changed
    # payload with this identity is rejected by the backend rather than replayed.
    command_id = str(uuid.uuid5(_NAMESPACE, canonical([turn_key, kind, reference, operation, identifier])))
    result = host.backend(kind).command({
        'operation_id': command_id,
        'action': action,
        'reference': reference,
        'id': identifier,
        'expected_revision': revision,
        'value': value,
    })
    host.start(kind)
    if operation == 'run':
        return {**result, 'status': 'queued'}
    return result
