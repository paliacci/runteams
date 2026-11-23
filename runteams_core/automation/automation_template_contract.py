"""Portable automation values and their owned creator source index."""
import re
import uuid

from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, strict_json

INDEX = 'automation.templates.json'
FIELD = 'automation_templates'
LIMIT = 30
_KEY = re.compile(r'[a-z][a-z0-9-]{0,79}')
_COMMON = {'name', 'objective', 'schedule_kind', 'interval_sec', 'schedule'}
_PRIVATE_TEXT = re.compile(
    r'(?i)(?:^|[\s"`\x27(<（：，=])(?:file:|[A-Z]:[\\/]|\\\\[^\\\s]+\\|'
    r'~[\\/]|\.{1,2}[\\/]|/(?=[^/\s]))'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----'
    r'|\b(?:Bearer\s+[A-Za-z0-9._~+/=-]{8,}|'
    r'(?:api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*\S+)'
)


def template_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _invalid():
    return CreatorContractError('invalid_automation_templates', '资产自动化模板格式无效。')


def validate_templates(templates, kind):
    """The archive shares only reviewed instructions and recurrence settings."""
    if kind not in ('employee', 'pipeline') or not isinstance(templates, list) or len(templates) > LIMIT:
        raise _invalid()
    required = _COMMON | {'id'}
    allowed = ({frozenset(required), frozenset(required | {'skill_key'})}
               if kind == 'employee' else {frozenset(required | {'start_column_key'})})
    seen = set()
    for row in templates:
        if not isinstance(row, dict) or frozenset(row) not in allowed or not template_id(row['id']) or row['id'] in seen:
            raise _invalid()
        for key, limit in (('name', 120), ('objective', 20000)):
            value = row[key]
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise _invalid()
            if _PRIVATE_TEXT.search(value):
                raise CreatorContractError('private_automation_input', '请先从自动化名称或任务说明中移除凭据与本机路径。')
        for key in ('skill_key', 'start_column_key'):
            if key in row and (not isinstance(row[key], str) or not _KEY.fullmatch(row[key])):
                raise _invalid()
        _validate_schedule(row)
        seen.add(row['id'])
    return templates


def _validate_schedule(row):
    kind = row['schedule_kind']
    schedule = row['schedule']
    if (kind not in ('interval', 'daily', 'weekly') or type(row['interval_sec']) is not int
            or not 60 <= row['interval_sec'] <= 2592000 or not isinstance(schedule, dict)):
        raise _invalid()
    expected = {'timezone'}
    if kind != 'interval':
        expected.add('time')
    if kind == 'weekly':
        expected.add('weekdays')
    if set(schedule) != expected or not isinstance(schedule['timezone'], str):
        raise _invalid()
    if not re.fullmatch(r'[A-Za-z0-9_+\-]+(?:/[A-Za-z0-9_+\-]+)*', schedule['timezone']) or len(schedule['timezone']) > 100:
        raise _invalid()
    if kind != 'interval' and (not isinstance(schedule['time'], str)
                               or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', schedule['time'])):
        raise _invalid()
    if kind == 'weekly':
        days = schedule['weekdays']
        if (not isinstance(days, list) or not days or any(type(day) is not int or not 0 <= day <= 6 for day in days)
                or sorted(set(days)) != days):
            raise _invalid()


def _owners(files):
    project = strict_json(files.get('project.json'))
    entries = project.get('entrypoints') if isinstance(project, dict) else None
    if not isinstance(entries, dict):
        raise _invalid()
    result = {}
    for kind in ('employee', 'pipeline'):
        paths = entries.get(kind + 's', [])
        if not isinstance(paths, list) or any(not isinstance(path, str) or path not in files for path in paths):
            raise _invalid()
        result.update(dict.fromkeys(paths, kind))
    return result


def index(files):
    raw = files.get(INDEX)
    if raw is None:
        return {}
    owners = _owners(files)
    mapping = strict_json(raw)
    if not isinstance(mapping, dict) or not mapping or set(mapping) - set(owners):
        raise _invalid()
    for owner, templates in mapping.items():
        if not validate_templates(templates, owners[owner]):
            raise _invalid()
    return mapping


def read(files, owner_path):
    return index(files).get(owner_path, [])


def put(files, owner_path, templates):
    kind = _owners(files).get(owner_path)
    validate_templates(templates, kind)
    mapping = index(files)
    result = dict(files)
    result.pop(INDEX, None)
    mapping.pop(owner_path, None)
    if templates:
        mapping[owner_path] = templates
    if mapping:
        result[INDEX] = canonical(mapping)
    return result
