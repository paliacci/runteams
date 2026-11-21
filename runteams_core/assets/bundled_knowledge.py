"""Resolve version-owned knowledge from a verified asset or frozen job binding."""
from runteams_core.assets import knowledge_archive as archive, rented_references
from runteams_core.authoring.creator_contracts import digest, strict_json
from runteams_core.authoring.source import knowledge_packages
from runteams_core.authoring.source.creator_local_source import current_store
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.employees import employee_references
from runteams_core.pipelines import pipeline_context, pipeline_references, pipeline_employee_dependencies
from runteams_core.storage import device_data, product_store


def _employee_name(files, path):
    raw = files.get(path)
    return strict_json(raw).get('name') if raw else None


def records(reference, revision=None, package=None):
    owner = reference.get('employee_source') or reference.get('pipeline_source')
    if reference.get('schema') not in (employee_references.SOURCE_SCHEMA, pipeline_references.REFERENCE):
        from runteams_core.employees.employee_context import current
        provider = current()
        rows, folder = provider.bundled_knowledge(reference, revision, package)
        if rows and package and package.get('reference') == reference:
            name = provider.package_asset(package)['employee']['name']
            rows = [{**r, 'employee_name': name} for r in rows]
        return rows, folder
    store = current_store(device_data.identity()['cache_scope'])
    if not store._directory(reference['source_id']).exists():
        return [], None
    revisions = Revisions(store, reference['source_id'], display_only=True)
    if revision is None:
        revision = revisions._head()
    meta = revisions.original if revision == revisions.identity else revisions._revision_metadata(revision)[1]
    if not any(f['path'] == archive.INDEX for f in meta['source']['files']):
        return [], None
    files = revisions.files_at(revision)
    mapping = knowledge_packages.require(revisions.root, files)
    rows = mapping.get(owner, [])
    if rows and 'employee_source' in reference:
        name = _employee_name(files, owner)
        rows = [{**r, 'employee_name': name} for r in rows]
    return rows, knowledge_packages.location(revisions.root, mapping)


def _add(items, reference, rows, folder, name=None):
    for row in rows:
        key = digest([reference, row['path'], row['sha256']])
        items[key] = {**row, 'file': folder / row['sha256'], 'employee_name': name or row.get('employee_name')}


def team_catalog(reference):
    """Collect the team's own and declared members' bundled files from the same revision."""
    from runteams_core.employees.employee_context import current

    owner = reference['pipeline_source']
    names = {}
    rented = rented_references.is_rented(reference)
    if rented:
        members, mapping, folder = current().team_knowledge_snapshot(reference)
    else:
        store = current_store(device_data.identity()['cache_scope'])
        if not store._directory(reference['source_id']).exists():
            return {}
        revisions = Revisions(store, reference['source_id'], display_only=True)
        with revisions.display_files() as snapshot:
            project = snapshot.get('project.json')
            if owner not in strict_json(project)['entrypoints'].get('pipelines', []):
                raise ValueError('当前工程不包含此智能体团队。')
            members = strict_json(snapshot.get(owner))['employees']
            files = {'project.json': project}
            if archive.INDEX in snapshot:
                files[archive.INDEX] = snapshot.get(archive.INDEX)
            mapping = knowledge_packages.require(revisions.root, files)
            folder = knowledge_packages.location(revisions.root, mapping) if mapping else None
            names = {m['ref']: _employee_name(snapshot, m['source']) for m in members
                     if 'source' in m and 'dependency' not in m and mapping.get(m['source'])}
    items = {}
    _add(items, reference, mapping.get(owner, []), folder)
    revision = None
    for member in members:
        name = names.get(member['ref'])
        pin = member.get('dependency')
        if pin is None:
            rows = mapping.get(member['source'])
            if not rows:
                continue
            directory = folder
            member_ref = (pipeline_employee_dependencies.member_reference(reference, member)
                          if rented else
                          employee_references.source_reference(reference['source_id'], member['source']))
        else:
            if rented:
                raise PermissionError('租用智能体团队不能改绑其他员工。')
            member_ref = pipeline_employee_dependencies.member_reference(reference, member)
            if pin['kind'] == 'source':
                rows, directory = records(member_ref, pin['revision'])
            else:
                rows, directory = current().dependency_knowledge(pin)
        if rows and rented:
            if revision is None:
                revision, _ = pipeline_context.current().definition(reference)
            name = pipeline_employee_dependencies.describe(reference, member, revision)['asset']['employee']['name']
        elif rows and pin and pin['kind'] != 'source':
            name = pipeline_context.current().acquired_member_description(pin)['asset']['employee']['name']
        _add(items, member_ref, rows, directory, name)
    return items


def catalog(reference, chat_id=None):
    ctx = {}
    employee_chat = False
    if chat_id:
        session = product_store.get_chat(chat_id, include_messages=False) or {}
        ctx = session.get('context') or {}
        employee_chat = session.get('subject_type') == 'employee'
    if 'pipeline_source' in reference and not employee_chat:
        return team_catalog(reference)
    package = ctx.get('local_employee_package') or {}
    flow = ctx.get('pipeline_work') or {}
    team_revision = flow.get('source_revision') or package.get('revision')
    targets = [(reference, team_revision if flow.get('reference') == reference else None)]
    employee = package.get('reference')
    if employee == reference:
        targets = [(reference, package['revision'])]
    elif employee and (flow.get('reference') == reference or not flow and 'pipeline_source' in reference):
        # The scheduled-team binding already checked this employee's membership.
        targets.append((employee, package['revision']))
    items = {}
    for ref, revision in targets:
        rows, folder = records(ref, revision, package if employee == ref else None)
        name = None
        if rows and employee_chat and not package and 'employee_source' in ref and not rows[0].get('employee_name'):
            from runteams_core.employees import employee_binding
            binding = employee_binding.resolve(session, read_only=True)
            if binding['reference'] == ref:
                name = binding['employee']['name']
        _add(items, ref, rows, folder, name)
    return items
