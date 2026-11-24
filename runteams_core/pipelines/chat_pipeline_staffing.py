"""Staff draft roles with the same employee and skill choices as the editor."""
from copy import deepcopy
import uuid

from runteams_core.authoring.creator_contracts import digest
from runteams_core.employees.employee_references import SOURCE_SCHEMA
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import source_pipeline_workspace as workspace

OPERATIONS = ('staffing_choices', 'save_staffing')
REQUIRED = {'staffing_choices': set(), 'save_staffing': {'source_revision', 'intent', 'choice_id', 'position_key'}}
OPTIONAL = {'staffing_choices': {'query'}, 'save_staffing': {'position_name', 'edges'}}
PROPERTIES = {
    'query': {'type': 'string', 'minLength': 1, 'maxLength': 160,
              'description': 'Optional name, project, version or skill filter for staffing_choices only.'},
    'choice_id': {'type': 'string', 'pattern': '^[a-f0-9]{64}$',
                  'description': 'Exact employee and skill choice returned by staffing_choices in this turn.'},
    'position_key': {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,79}$',
                     'description': 'Copy the existing employee role key. For a new role, use a unique key with lowercase letters, digits and hyphens.'},
    'position_name': {'type': 'string', 'minLength': 1, 'maxLength': 160,
                      'description': 'Name of the new employee role. Omit when changing an existing assignment.'},
}
DESCRIPTION = (
    ' For author drafts, staffing_choices lists employee skills actually available in the team editor. '
    'Use save_staffing to replace an employee assignment or add a staffed role with explicit routes; '
    'copy the choice_id and inspected source_revision. This saves a draft only.'
)
GUIDANCE = (
    '\n\n# 用实际员工和技能编辑作者团队草稿\n'
    '要查询员工技能或换岗，先用 inspect_draft 核对岗位，再用 staffing_choices 查可选员工和技能。'
    '需要缩小结果时用 query 搜索员工名、技能名、项目名或版本。若有重名员工、多个技能或不同版本，'
    '且不能从本轮指令唯一确定，用返回的名称、项目或版本让用户选。只用工具返回的精确 choice_id。'
    '用户本轮明确要求保存时，用 save_staffing 传岗位 key、刚核对的 source_revision 和明确指令原话 intent。'
    '换人时保留该岗位名称及其余设置。添加新岗位时，用小写字母、数字和连字符组成未使用的 position_key，并传 position_name 和保留其他路由的完整 edges；'
    '若新岗位接到哪里不明确，先向用户核对。不得用 save_draft 伪造员工或技能引用。'
    '只按草稿保存回执汇报实际变更，遇到未知结果用 draft_receipt。'
)


def _pin_identity(pin):
    return {**pin, 'skills': sorted(pin['skills'])}


def _choices(core, runtime, query):
    directory = workspace.creation_choices(core)
    candidates = {}
    for choice in directory['items']:
        if query and not any(query in choice[key].casefold() for key in (
                'employee_name', 'skill_name', 'skill_key', 'project_name', 'version', 'origin')):
            continue
        pin = _pin_identity(choice['dependency'])
        choice_id = digest({'pin': pin, 'skill_key': choice['skill_key']})
        candidates[choice_id] = choice
    shown = dict(list(candidates.items())[:40])
    runtime.staffing_choices.update(shown)
    fields = ('employee_name', 'skill_key', 'skill_name', 'project_name', 'version', 'origin', 'revision', 'skill')
    return {'status': 'staffing_choices',
            'items': [{'choice_id': key, **{field: choice[field] for field in fields}}
                      for key, choice in shown.items()],
            'remaining': len(candidates) - len(shown), 'unavailable_employees': len(directory['errors'])}


def _staff(previous, reference, choice, arguments, operation_id):
    asset = deepcopy(previous)
    graph = asset['pipeline']
    key = arguments['position_key']
    position = next((item for item in graph['positions'] if item['key'] == key), None)
    if position is None:
        if any(state['key'] == key for state in graph.get('states', [])):
            raise ContractError('这个编号已用于结束或等待状态，请选择新的岗位编号。')
        name = arguments.get('position_name', '').strip()
        if not name or 'edges' not in arguments or not any(
                key in (edge.get('from'), edge.get('to')) for edge in arguments['edges']):
            raise ContractError('添加岗位需要名称，并在流转中连到该岗位。')
        position = {'key': key, 'kind': 'employee', 'name': name}
        graph['positions'].append(position)
    elif position['kind'] != 'employee' or 'position_name' in arguments:
        raise ContractError('只能更换现有员工岗位的负责人，或用新编号添加岗位。')

    selected = choice['reference']
    embedded = selected['schema'] == SOURCE_SCHEMA and selected['source_id'] == reference['source_id']
    pin = choice['dependency']
    for member in asset['employees']:
        if 'dependency' in member:
            if _pin_identity(member['dependency']) == _pin_identity(pin):
                break
        elif embedded and member['source'] == selected['employee_source']:
            break
    else:
        member_id = uuid.uuid5(uuid.UUID(operation_id), key).hex
        member = {'ref': 'e-' + member_id[:12],
                  **({'source': selected['employee_source']} if embedded else {'dependency': deepcopy(pin)})}
        asset['employees'].append(member)
    position.update(employee_ref=member['ref'], skill_key=choice['skill_key'])
    in_use = {item.get('employee_ref') for item in graph['positions']}
    asset['employees'] = [member for member in asset['employees'] if member['ref'] in in_use]
    if 'edges' in arguments:
        graph['edges'] = arguments['edges']
    return asset


def execute(core, runtime, arguments, *, save, draft_message):
    turn = runtime.turn
    if arguments['operation'] == 'staffing_choices':
        with turn.lock:
            draft_message(turn)
            return _choices(core, runtime, arguments.get('query', '').strip().casefold())

    selection = {}

    def transform(previous):
        choice = runtime.staffing_choices.get(arguments['choice_id'])
        if choice is None:
            raise ContractError('请先从本轮实际显示的可用员工和技能中选择。')
        reference = choice['reference']
        if reference['schema'] == SOURCE_SCHEMA and not any(
                entry['source']['reference'] == reference for entry in workspace.source_staffing_entries(errors={})):
            raise ContractError('所选员工已不在可用目录中，请重新选择。')
        operation_id = turn.operation_id(0, 'save_draft')
        selection.update(employee_name=choice['employee_name'], skill_name=choice['skill_name'],
                         version=choice['version'], position_key=arguments['position_key'])
        return _staff(previous, turn.reference, choice, arguments, operation_id)

    result = save(core, runtime, arguments, transform=transform)
    if selection and result.get('status') in ('unchanged', 'saved'):
        result = {**result, 'assignment': selection}
    return result
