"""Employee-wide limits on authored conversation starters, across visible skills."""
import json


def _object(files, path):
    try:
        value = json.loads(files.get(path, b'{}'))
    except (ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _by_employee(files):
    project = _object(files, 'project.json')
    entries = project.get('entrypoints')
    if not isinstance(entries, dict) or not isinstance(entries.get('employees'), list):
        return {}
    result = {}
    for path in entries['employees']:
        if not isinstance(path, str):
            continue
        employee = _object(files, path)
        rows = []
        directories = employee.get('skill_dirs')
        if not isinstance(directories, list):
            continue
        for directory in directories:
            work = _object(files, f'{directory}/runteams.json').get('work')
            if not isinstance(work, dict) or work.get('show_in_overview') is False:
                continue
            examples = work.get('examples')
            if not isinstance(examples, list):
                continue
            for item in examples:
                if isinstance(item, dict):
                    rows.append((str(item.get('title') or '').strip(), str(item.get('prompt') or '').strip()))
        result[path] = rows
    return result


def validate_edit(before, after):
    previous = _by_employee(before)
    for path, rows in _by_employee(after).items():
        if rows == previous.get(path, []):
            continue  # An unrelated edit to a legacy employee preserves its original examples.
        titles = {title for title, _ in rows if title}
        prompts = {prompt for _, prompt in rows if prompt}
        if not (2 <= len(rows) <= 3 and len(rows) == len(titles) == len(prompts)):
            raise ValueError(f'{path}：请为这名员工设置 2–3 个快捷问题，标题和提问内容分别不能重复。')
