import unittest
from unittest.mock import Mock, patch

from runteams_core.employees import employee_directory as directory
from runteams_core.pipelines import source_pipeline_trash


class EmployeeTrashMembershipReadTests(unittest.TestCase):
    def test_scan_full_roster_only_for_possible_hidden_member(self):
        store = Mock()
        key = 'source:employee:entry'
        hidden = [{'source_id':'project','pipeline_source':'hidden.json'}]
        visible = 'source:project:live.json'
        removed = 'source:project:hidden.json'
        for group, other_active, expected in [(visible, False, False), (removed, True, False), (removed, False, True)]:
            with self.subTest(group=group, other_active=other_active):
                def membership(store, source_id, hidden_paths):
                    self.assertEqual(hidden_paths, {'hidden.json'})
                    return {key: {group: {}}} if group == removed else {}
                with patch.object(directory, '_hidden_members_snapshot', None), \
                     patch.object(directory.Revisions, 'display_fingerprint', return_value='v1'), \
                     patch.object(directory.source_employee_trash, 'hidden_keys', return_value=set()), \
                     patch.object(source_pipeline_trash, 'hidden_source_references', return_value=hidden), \
                     patch.object(directory, '_hidden_team_members', side_effect=membership), \
                     patch.object(directory, 'local_entries', return_value=[{'key': key, 'trashed': not other_active}]) as scan:
                    self.assertIs(directory._hidden_source_employee(store, key), expected)
                    self.assertEqual(scan.call_count, int(group == removed))

    def test_membership_snapshot_tracks_source_files_selected_teams_and_scope(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from runteams_core.authoring.source.creator_local_source import LocalSources
        from tests.test_employee_pipeline_groups import member, save_project

        with TemporaryDirectory() as temp:
            check = Mock()
            store = LocalSources(Path(temp).resolve() / 'sources', check)
            source = save_project(store, 'example', [('first', 'First', '👤'), ('second', 'Second', '👤')],
                                  [('one', 'One', [member('first')]), ('two', 'Two', [member('second')])])
            one = {source: {'pipelines/one.json'}}
            two = {source: {'pipelines/two.json'}}
            key = lambda employee: f'source:{source}:employees/{employee}.json'
            with patch.object(directory, '_hidden_members_snapshot', None), \
                 patch.object(directory, '_hidden_team_members', wraps=directory._hidden_team_members) as scan:
                self.assertEqual(directory._hidden_team_member_keys(store, one), {key('first')})
                self.assertEqual(directory._hidden_team_member_keys(store, one), {key('first')})
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(directory._hidden_team_member_keys(store, two), {key('second')})
                self.assertEqual(scan.call_count, 2)
                check.side_effect = PermissionError('library changed')
                with self.assertRaises(PermissionError):
                    directory._hidden_team_member_keys(store, two)
                check.side_effect = None
                # A restored or corrupted archive at the same head must be read again.
                (store.root / source / 'source.zip').write_bytes(b'invalid')
                with self.assertRaises(ValueError):
                    directory._hidden_team_member_keys(store, two)
                self.assertEqual(scan.call_count, 3)
