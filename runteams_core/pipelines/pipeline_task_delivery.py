"""Compose a native document from the completed task's accepted run lineage."""
import copy
from functools import lru_cache
import hashlib
import json
import re

from jsonschema import Draft202012Validator

from runteams_core.documents import rich_document_assets, rich_documents
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_references


@lru_cache(maxsize=1)
def _validator():
    from runteams_core.pipelines.portable_pipeline import pipeline_schema
    return Draft202012Validator(pipeline_schema()['$defs']['task_delivery'])


def validate(policy, parameters):
    if not _validator().is_valid(policy):
        raise ContractError('交付物配置无效。')
    fields = {field['key']: field for field in parameters}
    field = fields.get(policy['parameter'], {})
    if (field.get('source') != 'user' or field.get('type') != 'select'
            or set(field.get('options', [])) != set(policy['goals'])):
        raise ContractError('所有期望交付选项都必须配置交付物。')
    sections = policy['sections']
    for keys in policy['goals'].values():
        if set(keys) - sections.keys() or all(sections[key].get('optional') for key in keys):
            raise ContractError('每项期望交付都必须包含至少一个必需成果。')
    for section in sections.values():
        field = fields.get(section['output'].split('.')[0], {})
        if field.get('source') != 'employee' or field.get('type') == 'secret':
            raise ContractError('交付物只能引用员工的公开交接结果。')
    return policy


def _report(section, runs):
    key, *path = section['output'].split('.')
    for run_id, output in reversed(runs):
        value = output.get('output', {})
        if key not in value:
            continue
        references = output.get('report_references', [])
        value = value[key]
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, dict) and 'report_id' in value:
            # Pass-through fields retain the exact pin even when another role forwards them.
            for producer, result in reversed(runs):
                for ref in result.get('report_references', []):
                    if (ref.get('id') == value['report_id']
                            and all(ref.get(k) == value.get(k) for k in ('artifact_id', 'revision', 'sha256'))):
                        return producer, ref
            return None
        return (run_id, references[0]) if not path and len(references) == 1 else None
    return None


def _verified_document(core, connection, identifier, run_id, ref):
    file = connection.execute(
        'SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL',
        (ref['artifact_id'],)).fetchone()
    meta = json.loads(file['meta_json']) if file else {}
    binding = meta.get('work_report') or {}
    if (meta.get('content_model') != rich_documents.MODEL or binding.get('workflow_id') != identifier
            or binding.get('employee_run_id') != run_id or meta.get('revision_of') != ref['id']
            or meta.get('revision', 1) != ref['revision'] or meta.get('sha256') != ref['sha256']):
        raise ContractError('成果文件与当次验收的版本不一致。')
    content = core._read_document_body(file)
    if hashlib.sha256(content.encode()).hexdigest() != ref['sha256']:
        raise ContractError('成果文件内容与当次验收的版本不一致。')
    return json.loads(content)


def _blocks(core, document, root, section, key, attachments, sources):
    def walk(blocks):
        for block in blocks:
            yield block
            yield from walk(block.get('children', []))

    def at_heading(text, title):
        return re.search(r'^#{1,6}[ \t]+' + re.escape(title) + r'[ \t]*$', text, re.M)

    parts = []
    for index, block in enumerate(walk(document['blocks'])):
        props = copy.deepcopy(block.get('props', {}))
        block_id = f'delivery-{key}-{index}'
        if block['type'] == 'image' and props.get('assetId'):
            image = rich_document_assets.read(core, root, props['assetId'])
            if image['type'] not in {'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/avif'}:
                raise ContractError('成果文件中的图片格式无法打开。')
            attachments[image['id']] = {field: image[field] for field in ('name', 'type', 'data')}
            parts.append({'id': block_id, 'type': 'image', 'props': props, 'children': []})
        elif section.get('images_only'):
            continue
        elif block['type'] == 'file' and props.get('mime') == 'audio/mpeg' and props.get('assetId'):
            file = rich_document_assets.read(core, root, props['assetId'])
            if file['type'] != 'audio/mpeg':
                raise ContractError('交付物中的配音附件格式不一致。')
            attachments[file['id']] = {field: file[field] for field in ('name', 'type', 'data')}
            parts.append({'id': block_id, 'type': 'file', 'props': props, 'children': []})
        elif block['type'] == 'video' and props.get('mime') == 'video/mp4' and props.get('assetId'):
            file = rich_document_assets.read(core, root, props['assetId'])
            if file['type'] != 'video/mp4':
                raise ContractError('交付物中的视频附件格式不一致。')
            attachments[file['id']] = {field: file[field] for field in ('name', 'type', 'data')}
            parts.append({'id': block_id, 'type': 'video', 'props': props, 'children': []})
        elif block['type'] == 'dataTable':
            if props.get('source'):
                sources[block_id] = document['sources'][props['source']]
                props['source'] = block_id
            parts.append({'id': block_id, 'type': 'dataTable', 'props': props, 'children': []})
        elif block['type'] not in {'columns', 'column'}:
            text = rich_documents.narrative({**document, 'blocks': [{**block, 'children': []}]})
            if section.get('start_heading') and (start := at_heading(text, section['start_heading'])):
                heading = re.match(r'^# [^\n]+', text)
                text = (heading[0] + '\n\n' if heading else '') + text[start.start():]
            stop = at_heading(text, section['stop_heading']) if section.get('stop_heading') else None
            if stop:
                text = text[:stop.start()]
            if text.strip():
                text = re.sub(r'\[([^\]\n]*)\]\(runteams://document/[^\s)]+\)', r'\1', text)
                parts.append({'id': block_id, 'type': 'markdown', 'props': {'text': text}, 'children': []})
            if stop:
                break
    return parts


def compose_current(core, connection, identifier, frozen, document):
    """Display accepted results together. Pins, attachment ownership and retries stay per run."""
    lineage = frozen.get('pipeline_lineage')
    rows = connection.execute(
        "SELECT id,output_json FROM employee_runs WHERE workflow_run_id=? AND state='completed' ORDER BY id",
        (identifier,)).fetchall()
    outputs = {row['id']: json.loads(row['output_json']) for row in rows}
    accepted = [(run, ref) for run in (lineage if lineage is not None else outputs)
                for ref in outputs.get(run, {}).get('report_references', [])]
    attachments = {}
    for index, (run, ref) in enumerate(reversed(accepted)):
        artifact = connection.execute('SELECT trashed_at FROM artifacts WHERE id=?', (ref['artifact_id'],)).fetchone()
        if not artifact or artifact['trashed_at']:
            continue
        source = _verified_document(core, connection, identifier, run, ref)
        prefix = f"stage-{ref['artifact_id']}-"
        sources = {prefix + key: value for key, value in source['sources'].items()}
        media = set()
        def bind(blocks):
            for block in blocks:
                block['id'] = prefix + 'block-' + block['id']
                props = block.get('props', {})
                if props.get('source') in source['sources']:
                    props['source'] = prefix + props['source']
                if block['type'] in {'image', 'video', 'file'} and props.get('assetId'):
                    media.add(props['assetId'])
                bind(block.get('children', []))
        bind(source['blocks'])
        name = ref.get('name') or str(ref['id'])
        title = {'id': prefix + 'title-section', 'type': 'heading' if index == 0 else 'toggleListItem',
                 'props': {'level': 2} if index == 0 else {},
                 'content': [{'type': 'text', 'text': name, 'styles': {}}], 'children': []}
        if index == 0:
            parts = [title, *source['blocks']]
        else:
            title['children'] = source['blocks']
            parts = [title]
        candidate = {**document, 'blocks': document['blocks'] + parts, 'sources': {**document['sources'], **sources}}
        try:
            rich_documents.validate(candidate)
        except ContractError:
            # An individually valid report may exceed the combined reader's size or nesting limit.
            link = f"[{name}](runteams://document/{ref['artifact_id']})"
            previous = document['blocks'][0]
            previous['props']['text'] += '\n\n' + link
            continue
        for asset_id in media:
            file = rich_document_assets.read(core, ref['id'], asset_id)
            attachments[asset_id] = {key: file[key] for key in ('name', 'type', 'data')}
        document = candidate
    if not accepted:
        last = next((outputs[run] for run in reversed(list(lineage if lineage is not None else outputs))
                     if run in outputs and outputs[run].get('summary')), None)
        if last:
            document['blocks'].append({'id': 'task-result', 'type': 'markdown',
                                       'props': {'text': last['summary']}, 'children': []})
    return document, attachments


def policy_for(frozen):
    work = frozen['pipeline_work']
    policy = work['asset']['pipeline'].get('delivery')
    reference = work['reference']
    if policy is None and reference.get('schema') == pipeline_references.REFERENCE:
        # Existing completed tasks can adopt the source's delivery layout.
        # The selected goal and accepted versions remain those from the task.
        from runteams_core.pipelines.source_pipeline_workspace import _definition
        try:
            policy = _definition(reference)[1]['pipeline'].get('delivery')
        except FileNotFoundError:
            return None
    return policy


class MissingDeliverySection(ContractError):
    """A historical task did not collect a required output of a later layout."""


def compose(core, connection, identifier, frozen, policy):
    original = frozen['pipeline_work']['asset']['pipeline']
    field = next((field for field in original.get('parameters', []) if field['key'] == policy['parameter']), {})
    inputs = frozen['pipeline_input'].get('parameters', {})
    goal = inputs.get(policy['parameter']) or field.get('default')
    keys = policy['goals'].get(goal, [])
    if not keys:
        raise MissingDeliverySection('这项期望交付没有配置交付物。')
    runs = []
    for run_id in frozen.get('pipeline_lineage', []):
        run = connection.execute(
            "SELECT output_json FROM employee_runs WHERE id=? AND workflow_run_id=? AND state='completed'",
            (run_id, identifier)).fetchone()
        if run is None:
            raise ContractError('交付文件关联的执行记录无法核对。')
        runs.append((run_id, json.loads(run['output_json'])))
    blocks, attachments, sources = [], {}, {}
    for key in keys:
        section = policy['sections'][key]
        source = _report(section, runs)
        if source is None and not any(section['output'].split('.')[0] in run.get('output', {}) for _, run in runs):
            if section.get('optional'):
                continue
            raise MissingDeliverySection('原任务没有这项交付：' + section['title'])
        if source is None:
            raise ContractError('无法核对交付版本：' + section['title'])
        run_id, reference = source
        document = _verified_document(core, connection, identifier, run_id, reference)
        parts = _blocks(core, document, reference['id'], section, key, attachments, sources)
        if not parts:
            raise ContractError('交付物缺少内容：' + section['title'])
        blocks.append({'id': f'delivery-section-{key}', 'type': 'heading', 'props': {'level': 2},
                       'content': [{'type': 'text', 'text': section['title'], 'styles': {}}], 'children': []})
        blocks.extend(parts)
    return {'schema': rich_documents.SCHEMA, 'blocks': blocks, 'sources': sources}, attachments
