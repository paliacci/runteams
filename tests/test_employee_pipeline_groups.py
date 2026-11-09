"""Employee sidebar grouping is derived from exact saved source membership."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import subprocess
import sys
import unittest

from runteams_core.application.local_application import LocalApplication
from runteams_core.authoring.creator_contracts import canonical, tree
from runteams_core.authoring.source.creator_local_source import current_store
from runteams_core.authoring.source.creator_source_archive import pack
from runteams_core.authoring.source.creator_source_import import inspect_source
from runteams_core.storage import device_data


def save_project(store, key, employees, pipelines=()):
    paths = [f'employees/{identifier}.json' for identifier, _, _ in employees]
    pipeline_paths = [f'pipelines/{identifier}.json' for identifier, _, _ in pipelines]
    files = {
        'project.json': canonical({'schema': 'runteams.creator-project/2', 'key': key, 'name': key,
            'version': '1.0.0', 'sdk': 'mcp-apps/1-dev',
            'entrypoints': {'employees': paths, 'pipelines': pipeline_paths},
            'dependency_lock': 'dependencies.lock.json', 'source_access': {'default': 'author', 'public_files': []}}),
        'dependencies.lock.json': canonical({'schema': 'runteams.dependencies/2', 'root': key,
            'runtime': {'protocol': 'mcp', 'managed_node': '24'}, 'dependencies': []}),
        'soul.md': b'Fixture employee.',
        'skills/worker/SKILL.md': b'---\nname: worker\ndescription: Fixture skill\n---\nFixture instructions.\n',
    }
    for path, (identifier, name, avatar) in zip(paths, employees):
        files[path] = canonical({'schema': 'runteams.employee-source/3', 'key': identifier, 'name': name,
            'avatar': avatar, 'soul_file': 'soul.md', 'skill_dirs': ['skills/worker'],
            'runtime_requirement': {'provider': 'codex', 'model': '', 'effort': ''}})
    for path, (identifier, name, members) in zip(pipeline_paths, pipelines):
        positions = [{'key': f'role-{i}', 'kind': 'employee', 'name': f'Role {i}',
            'employee_ref': member['ref'], 'skill_key': 'worker'} for i, member in enumerate(members)]
        edges = [{'from': left['key'], 'to': right['key'], 'when': 'completed'}
                 for left, right in zip(positions, positions[1:] + [{'key': 'done'}])]
        files[path] = canonical({'schema': 'runteams.pipeline-source/3', 'key': identifier, 'employees': members,
            'pipeline': {'name': name, 'routing_policy': 'status-first', 'positions': positions,
                         'edges': edges, 'states': [{'key': 'done', 'name': 'Done', 'kind': 'done'}]}})
    return store.save(pack(files), tree(files)['sha256'], inspect_source)['id']


def member(identifier):
    return {'ref': identifier, 'source': f'employees/{identifier}.json'}


class EmployeePipelineGroupTests(unittest.TestCase):
    def test_directory_groups_inline_and_referenced_employees_by_exact_identity_and_order(self):
        with TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-B', '-c',
                'import runpy, sys; runpy.run_path(sys.argv[1])["check_directory"](sys.argv[2])',
                __file__, directory], check=True, timeout=30,
                env={**os.environ, 'RUNTEAMS_DATA': directory, 'RUNTEAMS_AUTOMATION_DISPATCH': '0'})


def check_directory(directory):
    check = unittest.TestCase()
    app = LocalApplication(Path(directory))
    try:
        with app.runtime.scope():
            store = current_store(device_data.identity()['cache_scope'])
            first = save_project(store, 'first', [(name, name, '👤') for name in
                ('one', 'two', 'shared', 'pinned', 'standalone')], [
                ('first', 'Same name', [member(name) for name in ('two', 'one', 'shared', 'pinned')]),
                ('second', 'Same name', [member('shared')]),
            ])
            second = save_project(store, 'second', [('one', 'one', '👤')], [
                ('first', 'Same name', [member('one'), {'ref': 'external', 'dependency': {
                    'kind': 'source', 'source_id': first, 'employee_source': 'employees/pinned.json',
                    'revision': first, 'skills': ['worker']}}]),
            ])
            third = save_project(store, 'third', [], [
                ('first', 'Same name', [{'ref': 'external', 'dependency': {
                    'kind': 'source', 'source_id': first, 'employee_source': 'employees/pinned.json',
                    'revision': first, 'skills': ['worker']}}]),
            ])
        reply = app.dispatch('GET', '/api/employee-directory', {'view': 'local'})
        rows = {(row['source']['id'], row['source']['path']): row for row in reply['items']}
        groups = {key: {group['key']: (group['name'], group['order']) for group in row['pipeline_groups']}
                  for key, row in rows.items() if 'pipeline_groups' in row}
        check.assertEqual(groups, {
            (first, 'employees/two.json'): {f'source:{first}:pipelines/first.json': ('Same name', 0)},
            (first, 'employees/one.json'): {f'source:{first}:pipelines/first.json': ('Same name', 1)},
            (first, 'employees/shared.json'): {
                f'source:{first}:pipelines/first.json': ('Same name', 2),
                f'source:{first}:pipelines/second.json': ('Same name', 0),
            },
            (first, 'employees/pinned.json'): {
                f'source:{first}:pipelines/first.json': ('Same name', 3),
                f'source:{second}:pipelines/first.json': ('Same name', 1),
                f'source:{third}:pipelines/first.json': ('Same name', 0),
            },
            (second, 'employees/one.json'): {f'source:{second}:pipelines/first.json': ('Same name', 0)},
        })
        check.assertEqual(len(rows), 6)
        check.assertEqual(reply['errors'], {})
        check.assertTrue(all(row['open'] == {'action': 'source-work'} for row in rows.values()))
    finally:
        app.close()

