"""Read-only delivery projection. Business objects remain references to their owners.

runteams.result-view/v1 has one delivery per workflow, frozen conclusions per
attempt, schema-labelled fields, artifacts, and current related-object references.
Its outputs point at the work actually produced by this task; other references
remain available as context without being presented as fresh deliverables.
It grants no capabilities; declared actions are resolved by the platform through normal tasks.
New output schemas render without adding a business section to the public UI.
"""
import copy


def output_fields(output, schema):
    """Use the frozen output contract, with a lossless fallback for old releases."""
    if not isinstance(output, dict):
        return [{'key': 'output', 'label': schema.get('title') or '交付内容', 'value': copy.deepcopy(output), 'schema': copy.deepcopy(schema)}]
    properties = schema.get('properties') or {}
    return [{'key': key, 'label': (properties.get(key) or {}).get('title') or key,
             'value': copy.deepcopy(value), 'schema': copy.deepcopy(properties.get(key) or {})}
            for key, value in output.items()]


def delivery_view(task, references):
    attempts = task['attempts']
    # Employee attempts at earlier pipeline positions are not the final delivery.
    # Keep only the latest attempt of each position in the visible contribution set.
    contributions, seen = [], set()
    for attempt in attempts:
        position = attempt['position_key']
        if position in seen:
            continue
        seen.add(position)
        contributions.append(attempt)
    outputs = [{'kind': 'reference', 'key': ref['key']}
               for ref in references if ref.get('relation') == 'produced']
    outputs.extend({'kind': 'document', 'id': artifact['id'], 'run_id': attempt['id']}
                   for attempt in contributions for artifact in attempt.get('artifacts') or []
                   if artifact.get('purpose') == 'document')
    if not outputs and task['state'] not in ('blocked', 'failed'):
        for attempt in contributions:
            field = next((field for field in attempt.get('fields') or []
                          if field.get('value') not in (None, '', [], {})), None)
            if field:
                outputs.append({'kind': 'field', 'key': field['key'], 'run_id': attempt['id']})
                break
    return {'key': 'workflow-{}'.format(task['workflow_id']),
            'workflow_id': task['workflow_id'], 'title': task['title'],
            'state': task['state'], 'created_at': task['created_at'],
            'updated_at': task['updated_at'],
            'human_request': task.get('human_request'),
            'summary': (contributions[0]['summary'] or next(iter(contributions[0].get('issues') or []), '')) if contributions else '',
            'sources': list(dict.fromkeys(i['employee_name'] for i in contributions if i['employee_name'])),
            'contributions': contributions,
            'attempts': [{key: copy.deepcopy(attempt[key]) for key in
                          ('id', 'position_key', 'employee_name', 'state', 'created_at',
                           'updated_at', 'summary', 'work_done', 'output', 'fields',
                           'issues', 'artifacts') if key in attempt} for attempt in attempts],
            'origin': ({'kind': 'employee_chat', 'chat_id': task['chat_id']}
                       if type(task.get('chat_id')) is int and task['chat_id'] > 0
                       else {'kind': 'workflow', 'workflow_id': task['workflow_id']}),
            'outputs': outputs,
            'references': references}


def issue_reference(item, relation='related'):
    return {'key': item['key'], 'kind': 'work_item', 'type_label': '问题',
            'title': item['title'], 'summary': item.get('impact', ''),
            'state': item['state'], 'state_label': item.get('state_label', item['state']),
            'identity_label': item.get('issue_id', ''), 'relation': relation,
            'detail': item}


def opportunity_reference(item, relation='related'):
    return {'key': 'opportunity:'+item['opportunity_key'], 'kind': 'opportunity',
            'type_label': '机会', 'title': item['title'],
            'summary': item.get('summary') or item.get('decision_reason', ''),
            'state': item.get('analysis_decision', ''), 'relation': relation,
            'fields': output_fields(item.get('output') or {}, {})}
