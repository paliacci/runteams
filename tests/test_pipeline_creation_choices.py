"""The first-role options follow the visible employee list and exact local source files."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch

from runteams_core.employees import source_employee_runtime
from runteams_core.pipelines import source_pipeline_workspace as workspace


class CreationChoiceTests(unittest.TestCase):
    def test_replacing_original_archive_invalidates_edited_project_rows(self):
        import json
        revision = 'r-' + 'a' * 64
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'head.json').write_text(json.dumps({'revision': revision}))
            (root / 'draft.json').write_text('{}')
            (root / 'source.zip').write_bytes(b'original')
            edited = root / 'revisions' / revision
            edited.mkdir(parents=True)
            (edited / 'revision.json').write_text('{}')
            (edited / 'source.zip').write_bytes(b'edited')
            store = Mock()
            store._directory.return_value = root
            before = workspace.Revisions.display_fingerprint(store, 'draft')
            (root / 'replacement').write_bytes(b'changed!')
            (root / 'replacement').replace(root / 'source.zip')
            self.assertNotEqual(before, workspace.Revisions.display_fingerprint(store, 'draft'))

    def test_project_read_finishes_in_same_scope_and_reader_expires(self):
        from runteams_core.authoring.source.creator_local_source import LocalSources

        scope = ['first']
        def check():
            if scope[0] != 'first':
                raise PermissionError('changed')
        with tempfile.TemporaryDirectory() as directory:
            store = LocalSources(Path(directory).resolve() / 'sources', check)
            with self.assertRaises(PermissionError):
                with store.reading_project() as reader:
                    self.assertEqual(reader.identities(), [])
                    scope[0] = 'second'
            with self.assertRaises(RuntimeError):
                reader.identities()

    def test_bundle_proof_cannot_hide_changes_after_the_first_read(self):
        import base64
        import copy
        import hashlib
        from runteams_core.authoring.definition_contracts import validate_definition
        from runteams_core.foundation.contracts import ContractError

        path, body = 'SKILL.md', b'skill'
        tree = len(path).to_bytes(4, 'big') + path.encode() + len(body).to_bytes(8, 'big') + body
        bundle = {'package_key': 'staff', 'digest': hashlib.sha256(tree).hexdigest(), 'files': [
            {'path': path, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
             'content_base64': base64.b64encode(body).decode()}]}
        validate_definition('portable_skill_bundle', bundle)
        returned = validate_definition('portable_skill_bundle', copy.deepcopy(bundle))
        returned['files'][0]['path'] = 'wrong'
        self.assertEqual(validate_definition('portable_skill_bundle', bundle), bundle)
        for field, value in [('size', True), ('size', 3), ('content_base64', 'c2tpbGw!'),
                             ('sha256', '0' * 64), ('path', 'other.md'), ('extra', 'ignored')]:
            changed = copy.deepcopy(bundle)
            changed['files'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                validate_definition('portable_skill_bundle', changed)

    def test_only_unchanged_options_are_reused_in_the_same_library(self):
        scope = {'cache_scope':'first'}
        store = Mock(root='library')
        stamps = {'a':('r-1',1), 'b':('r-1',2)}
        def row(key):
            return {'source':{'reference':{'source_id':key,'employee_source':'staff.json'}}, 'record':{'name':key}}
        def describe(ref, store, scope, catalogs):
            return {'reference':ref, 'revision':stamps[ref['source_id']][0], 'skills':[{'key':'work'}],
                    'asset':{'employee':{'name':ref['source_id']},'skill_bundles':[{'package_key':'work'}]}}
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        with patch('runteams_core.pipelines.pipeline_choice_index._index_directory', return_value=Path(cache.name)), \
                patch.object(workspace.device_data, 'identity', side_effect=lambda:dict(scope)), \
                patch.object(workspace, 'current_store', return_value=store), \
                patch.object(workspace.Revisions, 'display_fingerprint', side_effect=lambda _,key:stamps[key]), \
                patch.object(source_employee_runtime, 'describe_current_source', side_effect=describe) as read, \
                patch.object(workspace, 'skill_description', return_value={'name':'Work'}):
            entries = [row('a'),row('b')]
            first = workspace._source_choices(entries, [])
            first[0]['skill']['name'] = 'changed by caller'
            self.assertEqual(workspace._source_choices(entries, [])[0]['skill']['name'], 'Work')
            self.assertEqual(read.call_count, 2)
            stamps['a'] = ('r-1',3)  # Restore can replace files without changing the head.
            self.assertEqual(len(workspace._source_choices(entries[:1], [])), 1)
            self.assertEqual(read.call_count, 3)
            index = workspace.ChoiceIndex(store.root, scope, 'source-roles/2/a')
            index.path.write_bytes(b'interrupted index')
            workspace._source_choices(entries[:1], [])
            self.assertEqual(read.call_count, 4)
            scope['cache_scope'] = 'second'
            workspace._source_choices(entries[:1], [])
            self.assertEqual(read.call_count, 5)

    def test_cached_membership_follows_live_employee_and_team_trash(self):
        from runteams_core.assets.source_links import source_key
        sid = 'a' * 64
        left, right = 'employees/left.json', 'employees/right.json'
        left_key, right_key = source_key(sid, left), source_key(sid, right)
        groups = {left_key: {'one': {'key': 'one'}, 'two': {'key': 'two'}}, right_key: {'two': {'key': 'two'}}}
        scope = {'storage_kind': 'local', 'library_id': 'library', 'cache_scope': 'first'}
        store = MagicMock(root='library')
        store.identities.return_value = [sid]
        stamp = ['r-1', 1]
        hidden_employees, hidden_teams = set(), set()
        with tempfile.TemporaryDirectory() as directory, \
                patch('runteams_core.pipelines.pipeline_choice_index._index_directory', return_value=Path(directory)), \
                patch.object(workspace.device_data, 'personal', return_value=True), \
                patch.object(workspace.device_data, 'identity', return_value=scope), \
                patch.object(workspace, 'current_store', return_value=store), \
                patch.object(workspace.Revisions, 'display_fingerprint', return_value=stamp), \
                patch('runteams_core.employees.employee_directory.staffing_project',
                      return_value=('r-1', [[left, 'Left'], [right, 'Right']], groups)) as project, \
                patch('runteams_core.employees.source_employee_trash.hidden_keys', return_value=hidden_employees), \
                patch('runteams_core.pipelines.source_pipeline_trash.hidden_source_keys', return_value=hidden_teams):
            def keys():
                return [row['key'] for row in workspace.source_staffing_entries(errors={})]
            self.assertEqual(keys(), [left_key, right_key])
            hidden_teams.add('two')
            self.assertEqual(keys(), [left_key])
            hidden_employees.add(left_key)
            self.assertEqual(keys(), [])
            hidden_employees.clear()
            hidden_teams.clear()
            self.assertEqual(keys(), [left_key, right_key])
            self.assertEqual(project.call_count, 1)
            stamp[1] = 2
            self.assertEqual(keys(), [left_key, right_key])
            self.assertEqual(project.call_count, 2)
