import json
import unittest

from runteams_core.authoring.source.employee_starters import validate_edit


def source(*counts):
    def encode(obj):
        return json.dumps(obj).encode()
    files = {'project.json': encode({'entrypoints': {'employees': ['employee.json']}}),
             'employee.json': encode({'skill_dirs': [str(i) for i in range(len(counts))]})}
    for i, count in enumerate(counts):
        examples = [{'title': f'T{i}{j}', 'prompt': f'P{i}{j}'} for j in range(count)]
        files[f'{i}/runteams.json'] = encode({'work': {'examples': examples}})
    return files


class StarterLimits(unittest.TestCase):
    def test_limits_across_skills_and_legacy_edit(self):
        for after in (source(1, 1), source(2, 1)):
            validate_edit(source(1), after)
        for after in (source(0), source(1), source(2, 2)):
            with self.assertRaisesRegex(ValueError, '2–3'):
                validate_edit(source(2), after)
        validate_edit(source(5), {**source(5), 'soul.md': b'updated'})
