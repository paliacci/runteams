"""Draft-only exclusions from the next market package for each publication entry."""
from runteams_core.assets import knowledge_archive
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, relative, strict_json
from runteams_core.automation import automation_template_contract

INDEX = 'publication-exclusions.json'


def index(files):
    if INDEX not in files:
        return {}
    value = strict_json(files[INDEX])
    if not isinstance(value, dict):
        raise CreatorContractError('invalid_publication_exclusions', '发布清单中的撤下项无效。')
    for entry, selection in value.items():
        relative(entry)
        if (not isinstance(selection, dict) or set(selection) != {'knowledge', 'automations'}
                or not isinstance(selection['knowledge'], dict) or not isinstance(selection['automations'], list)
                or len(selection['automations']) > automation_template_contract.LIMIT
                or not all(automation_template_contract.template_id(key) for key in selection['automations'])
                or len(set(selection['automations'])) != len(selection['automations'])):
            raise CreatorContractError('invalid_publication_exclusions', '发布清单中的撤下项无效。')
        for owner, paths in selection['knowledge'].items():
            relative(owner)
            if not isinstance(paths, list) or len(paths) > knowledge_archive.MAX_FILES:
                raise CreatorContractError('invalid_publication_exclusions', '发布清单中的资料撤下项无效。')
            for path in paths:
                knowledge_archive.file_name(path)
            if len(set(paths)) != len(paths):
                raise CreatorContractError('invalid_publication_exclusions', '发布清单中的资料撤下项重复。')
    return value


def edit(files, entry, *, remove_sources=(), remove_automations=(), restore_paths=(), restore_sources=(), restore_automations=()):
    """Update only the specified market entry's selectors."""
    mapping = index(files)
    selection = mapping.get(entry, {'knowledge': {}, 'automations': []})
    knowledge = {owner: set(paths) for owner, paths in selection['knowledge'].items()}
    automations = set(selection['automations'])
    for row in remove_sources:
        knowledge.setdefault(row['owner'], set()).add(row['path'])
    for row in restore_sources:
        if row['owner'] in knowledge:
            knowledge[row['owner']].discard(row['path'])
    if entry in knowledge:
        knowledge[entry].difference_update(restore_paths)
    automations.update(remove_automations)
    automations.difference_update(restore_automations)
    knowledge = {owner: sorted(paths) for owner, paths in knowledge.items() if paths}
    if knowledge or automations:
        mapping[entry] = {'knowledge': knowledge, 'automations': sorted(automations)}
    else:
        mapping.pop(entry, None)
    updated = dict(files)
    updated.pop(INDEX, None)
    if mapping:
        updated[INDEX] = canonical(mapping)
        index(updated)
    return updated


def apply(files, exported, entry):
    """Filter delivered indexes and keep the publication preference local."""
    exported.pop(INDEX, None)
    if INDEX in files:
        project = strict_json(exported['project.json'])
        public_files = project['source_access']['public_files']
        if INDEX in public_files:
            public_files.remove(INDEX)
            exported['project.json'] = canonical(project)
    selection = index(files).get(entry)
    if not selection:
        return exported
    original = knowledge_archive.index(exported)
    materials = {owner: [row for row in rows if row['path'] not in selection['knowledge'].get(owner, ())]
                 for owner, rows in original.items()}
    from runteams_core.pipelines import pipeline_closure_contracts as closure
    if closure.MANIFEST in exported:
        manifest = strict_json(exported[closure.MANIFEST])
        filtered = [owner for owner in manifest['employees'] if materials.get(owner) != original.get(owner)]
        if filtered:
            from runteams_core.authoring.creator_contracts import compile_source
            compiled = compile_source(exported)
            for owner in filtered:
                asset = closure.portable_employee(exported, compiled, owner)
                manifest['employees'][owner]['asset_sha256'] = closure.delivered_employee_digest(asset, materials.get(owner))
            exported[closure.MANIFEST] = canonical(manifest)
    materials = {owner: rows for owner, rows in materials.items() if rows}
    exported.pop(knowledge_archive.INDEX, None)
    if materials:
        exported[knowledge_archive.INDEX] = canonical(materials)
    return automation_template_contract.put(exported, entry, [
        row for row in automation_template_contract.read(exported, entry)
        if row['id'] not in selection['automations']])
