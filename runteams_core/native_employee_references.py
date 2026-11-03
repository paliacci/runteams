"""Pure frozen native employee identities; no acquisition or cloud access."""
import hashlib
import json

from .asset_references import BusinessReference, StaleBusinessReference


def local_employee_id(reference):
    reference = BusinessReference.from_json(reference)
    if reference.resource != 'employees':
        raise StaleBusinessReference()
    body = json.dumps(reference.to_json(), sort_keys=True, separators=(',', ':')).encode()
    return (1 << 52) | (int.from_bytes(hashlib.sha256(body).digest()[:8], 'big') & ((1 << 52) - 1))


def source_employee_id(value, local_id, account_id, deployment_id=None):
    if not isinstance(value, dict) or set(value) != {'employee_reference', 'release_reference'}:
        raise StaleBusinessReference()
    employee = BusinessReference.from_json(value['employee_reference'])
    release = BusinessReference.from_json(value['release_reference'])
    if (employee.resource != 'employees' or release.resource != 'employee_releases'
            or employee.workspace_id != account_id or release.workspace_id != account_id
            or employee.deployment_id != release.deployment_id or employee.data_epoch != release.data_epoch
            or deployment_id is not None and employee.deployment_id != deployment_id
            or local_employee_id(employee.to_json()) != local_id):
        raise StaleBusinessReference()
    return employee.id
