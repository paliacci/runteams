"""Read-only source import preparation; no business persistence or execution.

A successful inspection is preflight only. Saving an explicitly selected local
source draft is a separate account-bound operation, not a publish/install receipt.
"""
from runteams_core.authoring.creator_contracts import CreatorContractError, compile_source
from runteams_core.authoring.creator_definitions import definition_artifacts
from runteams_core.authoring.compilation.creator_dependencies import validate_dependency_sources
from runteams_core.authoring.source.creator_source_archive import FORMAT, inspect


def _validated_catalog(files, require_work):
    compiled = compile_source(files)
    # Both artifact compilers validate all source packages when assembling definition_files.
    if require_work:
        definition_artifacts(files, compiled, require=True)
        catalog = None
    else:
        from runteams_core.authoring.creator_conversation_assets import compile_catalog
        catalog = compile_catalog(files, compiled)
    validate_dependency_sources(files, compiled, source_index=compiled['source'])
    return compiled, catalog


def validate_source(files, *, require_work=False):
    compiled, _ = _validated_catalog(files, require_work)
    return compiled


def validated_catalog(files):
    return _validated_catalog(files, False)


def validated_employee_assets(files):
    _, catalog = validated_catalog(files)
    return catalog['employees']


def inspect_source(raw):
    files = inspect(raw)
    compiled = validate_source(files)
    project = compiled['project']
    return {'schema': 'runteams.source-import-inspection/2-dev', 'format': FORMAT,
        'project': {k: project[k] for k in ('name', 'key', 'version')},
        'source': compiled['source'],
        'employees': len(project['entrypoints']['employees']),
        'pipelines': len(project['entrypoints']['pipelines']),
        'dependencies': [{k: d[k] for k in ('key', 'version', 'sha256')} for d in compiled['dependencies']['dependencies']],
        'scope': 'local-preflight', 'imported': False, 'cloud_verified': False}
