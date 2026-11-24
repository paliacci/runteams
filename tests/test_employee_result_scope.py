import unittest
from unittest.mock import patch

from runteams_core.employees import employee_references as refs


class EmployeeResultScopeTests(unittest.TestCase):
    def test_repeated_source_rows_share_scope_and_reject_switch_before_return(self):
        scope = {'storage_kind': 'local', 'library_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}
        source = {'schema': refs.SOURCE_SCHEMA, 'employee_source': 'employees/a.json',
                  'source_id': 'a' * 64, **scope}
        with patch.object(refs.device_data, 'identity', side_effect=[scope, dict(scope, library_id='changed')]) as identity, \
                patch.object(refs.device_data, 'personal', return_value=True):
            with self.assertRaises(PermissionError):
                with refs.matching_references([source]) as matches:
                    for _ in range(10):
                        self.assertTrue(matches(source))
                    self.assertFalse(matches(dict(source, employee_source='employees/b.json')))
                    with self.assertRaises(PermissionError):
                        matches(dict(source, library_id='another-library'))
            self.assertEqual(identity.call_count, 2)
