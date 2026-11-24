"""Inspect saved revisions and restore a historical flow into the current draft."""
import logging
import re

from runteams_core.authoring.creator_contracts import strict_json
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_employee_dependencies
from runteams_core.pipelines import source_pipeline_settings as settings
from runteams_core.pipelines import source_pipeline_work as work


def _item(history, revision):
    for item in history['items']:
        if item['revision'] == revision:
            return item
    raise ContractError('这不是当前团队的历史草稿修订，请先查看本团队的草稿历史。')


def _positions(reference, revision, files, asset):
    members = {member['ref']: member for member in asset['employees']}
    bindings = {}
    for position in asset['pipeline']['positions']:
        member_ref = position.get('employee_ref')
        if member_ref is None or member_ref in bindings:
            continue
        member = members[member_ref]
        if 'source' in member:
            employee = strict_json(files[member['source']])
            bindings[member_ref] = {'source': member['source'], 'name': employee['name']}
        else:
            binding = {'dependency': member['dependency']}
            try:
                employee = pipeline_employee_dependencies.describe(reference, member, revision)['asset']['employee']
                binding['name'] = employee['name']
            except (OSError, PermissionError, ValueError):
                # Keep the exact pin visible even if the historical asset is unavailable.
                pass
            bindings[member_ref] = binding
    return {position['key']: {**position, **({'employee': bindings[position['employee_ref']]}
             if 'employee_ref' in position else {})} for position in asset['pipeline']['positions']}


def _routes(graph):
    routes = {}
    for edge in graph.get('edges', ()):
        routes.setdefault(edge['from'], []).append(edge)
    return routes


def _changes(before, after):
    return [{'key': key, 'before': before.get(key), 'after': after.get(key)}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def _compare(before, after, old_positions, new_positions):
    old_states = {state['key']: state for state in before.get('states', ())}
    new_states = {state['key']: state for state in after.get('states', ())}
    return {
        'positions': _changes(old_positions, new_positions),
        'states': _changes(old_states, new_states),
        'routes': _changes(_routes(before), _routes(after)),
        'other_fields': _changes({key: value for key, value in before.items()
                                  if key not in ('positions', 'states', 'edges')},
                                 {key: value for key, value in after.items()
                                  if key not in ('positions', 'states', 'edges')}),
        'position_order': {'before': list(old_positions), 'after': list(new_positions)}
        if list(old_positions) != list(new_positions) else None,
        'state_order': {'before': list(old_states), 'after': list(new_states)}
        if list(old_states) != list(new_states) else None,
    }


def _named_targets(intent, history):
    items = history['items']
    by_number = {str(item['revision_number']): item['revision'] for item in items}
    matches = re.findall(r'(?:(?:修订\s*(?:号\s*)?|版本\s*|\brevision\s*#?\s*)(?:第\s*)?(\d+)|'
                         r'第\s*(\d+)\s*(?:版|次修订))', intent, re.IGNORECASE)
    targets = {by_number[number or alternate] for number, alternate in matches
               if (number or alternate) in by_number}
    for candidate in re.findall(r'(?<![a-z0-9-])(?:r-)?[a-f0-9]{8,64}(?![a-z0-9-])', intent, re.IGNORECASE):
        prefix = candidate.lower().removeprefix('r-')
        targets.update(row['revision'] for row in items if row['revision'].removeprefix('r-').startswith(prefix))
    return targets


def _restored_asset(current, historical):
    flow_fields = ('positions', 'edges', 'states', 'parameters', 'routing_policy', 'delivery')
    graph = {key: value for key, value in current['pipeline'].items() if key not in flow_fields}
    graph.update({key: value for key, value in historical['pipeline'].items() if key in flow_fields})
    needed = {position.get('employee_ref') for position in graph['positions']}
    members = {member['ref']: member for member in historical['employees'] if member['ref'] in needed}
    # Maintain the current ordering where possible. Only the historical graph's
    # referenced assignments are carried into the draft.
    ordered_refs = dict.fromkeys([member['ref'] for member in current['employees']] + list(members))
    return {**current, 'pipeline': graph, 'employees': [members[ref] for ref in ordered_refs if ref in members]}


def _restore_request(message):
    action = r'恢复|还原|回退|回滚|\brestore\b|\broll back\b|\brevert\b'
    negative = (
        rf'(?:不要|别|不必|无需|不允许|不|仅预览)\s*(?:实际|真的|现在|先)?\s*(?:{action})|'
        rf"(?:do not|don['’]t|never)\s+(?:actually\s+)?(?:{action})"
    )
    for clause in re.split(r'[。！？；，、,;!?\n]|\.(?=\s|$)', message):
        if re.search(action, clause, re.IGNORECASE) and not re.search(negative, clause, re.IGNORECASE):
            yield clause


def _authorize_target(intent, item, history, *, compared_from, confirm, policy):
    requested = ' '.join(_restore_request(intent))
    targets = _named_targets(requested, history)
    if targets:
        return targets == {item['revision']}
    if re.search(r'上一版|上一个修订|前一版|\b(?:previous|prior) (?:draft|revision|version)\b',
                 requested, re.IGNORECASE):
        return len(history['items']) > 1 and history['items'][1] == item
    if re.search(r'初版|首版|第一版|最早(?:那|一)?版|\b(?:first|original) (?:draft|revision|version)\b',
                 requested, re.IGNORECASE):
        return history['items'][-1] == item
    contextual = re.search(r'刚(?:才)?(?:比较|对比|查看|看的)|(?:比较|对比)过|'
                           r'\b(?:just|previously) (?:compared|viewed)\b', requested, re.IGNORECASE)
    if not contextual:
        return False
    if compared_from is not None:
        return compared_from == item['revision']
    if not callable(confirm):
        return False

    from runteams_core.agents.language_policy import snapshot
    english = snapshot(policy or {'communication_language': 'zh-CN'})['communication_language'] == 'en'
    key = 'pipeline-draft-restore'
    label = f'Revision {item["revision_number"]}' if english else item['version']
    prefix = item['revision'][:14]
    response = confirm([{'id': key,
        'header': 'Restore flow draft' if english else '恢复流程草稿',
        'question': (f'Restore {label} ({prefix}) as a new flow draft?' if english
                     else f'将{label}（{prefix}）的流程恢复为新草稿？'),
        'options': [
            {'label': label, 'description': 'Restore positions and routing' if english else '恢复这版的岗位和流转'},
            {'label': 'Cancel' if english else '取消',
             'description': 'Keep the current draft' if english else '保留当前草稿'}]}])
    answers = (response or {}).get('answers', {}).get(key, {}).get('answers')
    return True if answers == [label] else None


def execute(core, reference, arguments, *, inspected_revision=None, operation_id=None, check_intent=None,
            compared_from=None, confirm=None, policy=None):
    operation = arguments['operation']
    history = settings.history(core, reference)
    if operation == 'draft_history' and 'history_revision' not in arguments:
        return {'status': 'history', **history}

    revisions = work.source(reference)
    if operation == 'compare_drafts':
        old = _item(history, arguments['from_revision'])
        new = _item(history, arguments['to_revision'])
        old_files, new_files = revisions.files_at(old['revision']), revisions.files_at(new['revision'])
        before, after = settings._asset(old_files, reference), settings._asset(new_files, reference)
        return {'status': 'comparison', 'from': old, 'to': new,
                'definition_changes': _compare(before['pipeline'], after['pipeline'],
                    _positions(reference, old['revision'], old_files, before),
                    _positions(reference, new['revision'], new_files, after))}

    item = _item(history, arguments['history_revision'])
    files = revisions.files_at(item['revision'])
    historical = settings._asset(files, reference)
    if operation == 'draft_history':
        return {'status': 'historical_draft', 'item': item, 'pipeline': historical['pipeline'],
                'positions': list(_positions(reference, item['revision'], files, historical).values())}

    base = arguments['source_revision']
    if base != inspected_revision:
        raise ContractError('请先查看当前草稿，再恢复历史版本。')
    authorization = _authorize_target(check_intent(), item, history, compared_from=compared_from,
                                      confirm=confirm, policy=policy)
    if authorization is None:
        return {'status': 'cancelled'}
    if not authorization:
        raise PermissionError('请明确要恢复哪版草稿，再试一次。')

    current = settings._asset(revisions.files_at(base), reference)
    restored = _restored_asset(current, historical)
    if current == restored:
        with revisions.locked():
            if revisions._head() != base:
                raise ContractError('源码已在其他位置更新，请重新查看草稿。')
        return {'status': 'unchanged', 'source_revision': base, 'restored_from': item,
                'pipeline': current['pipeline']}
    try:
        result = settings.edit(core, {'reference': reference, 'operation_id': operation_id,
                               'base_revision': base, 'asset': restored}, before_commit=check_intent)
    except OSError:
        logging.getLogger(__name__).exception('Could not confirm pipeline draft restore %s', operation_id)
        return {'status': 'unknown', 'operation_id': operation_id}
    return {'status': 'restored', 'source_revision': result['revision'], 'restored_from': item,
            'pipeline': result['pipeline']}
