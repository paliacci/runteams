"""Derive the complete, owned source subset for one employee or pipeline."""
import hashlib

from runteams_core.authoring.compilation.creator_mcp_source import program_sources
from runteams_core.authoring.creator_contracts import canonical, strict_json
from runteams_core.employees.employee_avatars import bundled
from runteams_core.pipelines.pipeline_closure_contracts import MANIFEST, PREFIX


def selected_source(files, kind, entry, *, keep_project_key=False):
    project = strict_json(files['project.json'])
    entries = project['entrypoints']
    if kind not in ('employee', 'pipeline') or entry not in entries.get(kind + 's', []):
        raise ValueError('这份工程不包含要发布的资产。')
    pipeline = strict_json(files[entry]) if kind == 'pipeline' else None
    employees = {entry} if pipeline is None else {
        row['source'] for row in pipeline['employees'] if 'source' in row}
    pipelines = {entry} if pipeline is not None else set()
    from runteams_core.assets.knowledge_archive import INDEX, index
    materials = {k: v for k, v in index(files).items() if k in employees | pipelines}
    from runteams_core.automation import automation_template_contract
    templates = automation_template_contract.read(files, entry)
    unrelated = (set(entries['employees']) - employees) | (set(entries.get('pipelines', [])) - pipelines)
    if not keep_project_key:
        suffix = hashlib.sha256(f"{project['key']}:{kind}:{entry}".encode()).hexdigest()[:16]
        project['key'] = project['key'][:63] + '-' + suffix
    entries['employees'] = [path for path in entries['employees'] if path in employees]
    if 'pipelines' in entries:
        entries['pipelines'] = [path for path in entries['pipelines'] if path in pipelines]

    lock_path = project['dependency_lock']
    lock = strict_json(files[lock_path])
    project['source_access']['public_files'] = [
        path for path in project['source_access']['public_files'] if path not in unrelated]
    kept = {'project.json', lock_path, *employees, *pipelines,
            *project['source_access']['public_files'],
            *project.get('data_models', []), *project.get('migrations', []),
            *project.get('connections', [])}
    prefixes = set()
    for path in employees:
        employee = strict_json(files[path])
        kept.add(employee['soul_file'])
        if employee.get('workspace_background'):
            kept.add(employee['workspace_background'])
        if bundled(employee['avatar']):
            kept.add(employee['avatar'])
        prefixes.update(directory + '/' for directory in employee['skill_dirs'])
    if pipeline is not None:
        if pipeline.get('workspace_background'):
            kept.add(pipeline['workspace_background'])
        if 'avatar' in pipeline and bundled(pipeline['avatar']):
            kept.add(pipeline['avatar'])
        prefixes.update(program['source'] + '/' for program in program_sources(pipeline))
    for operation in project.get('operations', []):
        kept.update(operation[key] for key in ('handler', 'input', 'output'))
    for path in project.get('connections', []):
        for endpoint in strict_json(files[path])['endpoints'].values():
            kept.update([endpoint['input'], endpoint['output'], *endpoint['query'].values()])
    if lock['dependencies']:
        kept.add('dependencies.sources.json')
        prefixes.update(path + '/' for path in strict_json(files['dependencies.sources.json']).values())
    if 'data/models.json' in files:
        kept.add('data/models.json')
    if 'ui/views.json' in files:
        kept.add('ui/views.json')
        registry = strict_json(files['ui/views.json'])
        for view in registry['views']:
            kept.update(view[key] for key in ('entry', 'input_schema', 'context_schema'))
        for operation in registry['operations']:
            kept.update(operation[key] for key in ('entry', 'input_schema', 'output_schema'))

    result = {path: value for path, value in files.items()
              if path in kept or path.startswith(tuple(prefixes))}
    if MANIFEST in files:
        closure = strict_json(files[MANIFEST])
        closure['employees'] = {path: record for path, record in closure['employees'].items()
                                if path in employees and record['pipeline_source'] in pipelines}
        if closure['employees']:
            result[MANIFEST] = canonical(closure)
        for path in set(result) - kept:
            if path.startswith(PREFIX) and not any(path.startswith(key.rsplit('/', 1)[0] + '/')
                                                   for key in closure['employees']):
                del result[path]
    result['project.json'] = canonical(project)
    if lock['root'] != project['key']:
        result[lock_path] = canonical({**lock, 'root': project['key']})
    result.pop(INDEX, None)
    if materials:
        result[INDEX] = canonical(materials)
    result.pop(automation_template_contract.INDEX, None)
    return automation_template_contract.put(result, entry, templates) if templates else result


def selected_publication_source(files, kind, entry, *, keep_project_key=False):
    """Derive the exact source for the next market version."""
    from runteams_core.authoring.source import publication_exclusions

    return publication_exclusions.apply(
        files, selected_source(files, kind, entry, keep_project_key=keep_project_key), entry)
