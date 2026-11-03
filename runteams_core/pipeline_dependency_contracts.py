"""Pure exact employee-pin declarations and compiler selection metadata.

These facts neither acquire assets nor authorize their use or redistribution.
"""
import copy
from pathlib import Path
from .creator_contracts import CreatorContractError, digest, relative


def schema():
    key = {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,79}$'}
    sha = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    path = {'type': 'string', 'minLength': 1, 'maxLength': 240}
    common = {'employee_source': path, 'skills': {'type': 'array', 'items': key,
               'minItems': 1, 'maxItems': 64, 'uniqueItems': True}}
    uuid = {'type': 'string', 'pattern': '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'}
    return {'oneOf': [
        {'type': 'object', 'additionalProperties': False,
         'required': ['kind', 'source_id', 'employee_source', 'revision', 'skills'],
         'properties': {**common, 'kind': {'const': 'source'}, 'source_id': sha,
                        'revision': {'type': 'string', 'pattern': '^(r-)?[a-f0-9]{64}$'}}},
        {'type': 'object', 'additionalProperties': False,
         'required': ['kind', 'installation_id', 'release_id', 'employee_source', 'sha256', 'skills'],
         'properties': {**common, 'kind': {'const': 'download'}, 'installation_id': uuid,
                        'release_id': uuid, 'sha256': sha, 'rental_source_id': sha}}]}


def checked(pin):
    from jsonschema import Draft202012Validator
    if next(Draft202012Validator(schema()).iter_errors(pin), None):
        raise CreatorContractError('invalid_employee_dependency')
    relative(pin['employee_source'])
    return copy.deepcopy(pin)


def selector(member):
    return member.get('source') or member['ref']


def key(member):
    return digest(member['dependency']) if 'dependency' in member else member['source']


def skills(member, employees):
    if 'dependency' in member:
        return checked(member['dependency'])['skills']
    return [Path(path).name for path in employees[relative(member['source'])]['skill_dirs']]
