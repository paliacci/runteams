"""Employee-wide limits on authored conversation starters, across visible skills."""
import json

from runteams_core.authoring.definition_contracts import validate_definition


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
                    rows.append(item)
        result[path] = rows
    return result


def validate_edit(before, after):
    previous = _by_employee(before)
    for path, rows in _by_employee(after).items():
        old_rows = previous.get(path, [])
        original = [_text(row) for row in rows]
        if original != [_text(row) for row in old_rows]:
            titles = {title for title, _ in original if title}
            prompts = {prompt for _, prompt in original if prompt}
            if not (2 <= len(original) <= 3 and len(original) == len(titles) == len(prompts)):
                raise ValueError(f'{path}：请为这名员工设置 2–3 个快捷问题，标题和提问内容分别不能重复。')
        _validate_translations(path, rows, old_rows)


def validate_submission(files):
    for path, rows in _by_employee(files).items():
        _validate_translations(path, rows, [])


def _text(row):
    return str(row.get('title') or '').strip(), str(row.get('prompt') or '').strip()


def _validate_translations(path, rows, old_rows):
    previous = [(_text(row), row.get('translations', {})) for row in old_rows]
    for index, row in enumerate(rows, 1):
        original = _text(row)
        translations = row.get('translations', {})
        if (original, translations) in previous:
            continue
        try:
            validate_definition('work_example_translations', translations)
        except ValueError as error:
            raise ValueError(f'{path}：第 {index} 个快捷问题的译文无效，请提供另一种语言的标题和提问内容（{error}）。') from error
        if all(_text(translation) == original for translation in translations.values()):
            raise ValueError(f'{path}：第 {index} 个快捷问题的译文与原文相同，请提供另一种语言的标题和提问内容。')
