"""Read-only source import preparation; no business persistence or execution.

A successful inspection is preflight only. Saving an explicitly selected local
source draft is a separate account-bound operation, not a publish/install receipt.
"""
from .creator_contracts import CreatorContractError, compile_source
from .creator_definitions import definition_artifacts
from .creator_dependencies import validate_dependency_sources
from .creator_source_archive import FORMAT, inspect


def validate_source(files, *, require_work=False):
    compiled = compile_source(files)
    from .creator_mcp_source import packages
    packages(files,compiled)
    if require_work:
        definition_artifacts(files, compiled, require=True)
    else:
        from .creator_conversation_assets import artifacts
        artifacts(files,compiled)
    validate_dependency_sources(files, compiled)
    return compiled


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
