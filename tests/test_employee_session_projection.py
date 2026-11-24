"""A history read verifies its original package once, including failed reads."""
import unittest
from unittest.mock import patch

from runteams_core.employees import employee_session_view
from runteams_core.foundation.contracts import ContractError


class EmployeeSessionProjectionTests(unittest.TestCase):
    def setUp(self):
        self.reference = {'source_id': 'source'}
        self.session = {'id': 7, 'kind': 'general', 'subject_type': 'employee',
                        'context': {'local_employee_package': {'reference': self.reference},
                                    'source_employee': self.reference},
                        'messages': [{'text': 'saved reply'}]}
        self.enterContext(patch('runteams_core.storage.product_store.device_chat', return_value=True))
        self.enterContext(patch('runteams_core.employees.employee_references.checked_reference',
                                side_effect=lambda value: value))
        self.verify = self.enterContext(patch('runteams_core.employees.source_employee_runtime.for_chat'))
        self.verify.return_value = {'name': 'Original employee', 'workspace_background_color': '10,20,30',
                                    'active_release': {'snapshot_json': {'skill_bundles': []}}}
        self.summary = self.enterContext(patch('runteams_core.employees.employee_binding.summary',
                                               side_effect=lambda binding: {'reference': binding['reference']}))

    def test_identity_and_binding_share_one_verification(self):
        view = employee_session_view.public_session(self.session)
        self.verify.assert_called_once_with(7, include_background=True)
        self.assertEqual(view['employee_binding']['reference'], self.reference)
        self.assertEqual(view['identity'], {'name': 'Original employee',
                         'workspace_background_color': '10,20,30', 'local_mcp': False})
        self.assertEqual(view['messages'], self.session['messages'])

    def test_failed_verification_keeps_transcript_and_is_retried_on_next_read(self):
        self.verify.side_effect = ContractError('Original runtime changed')
        for attempt in (1, 2):
            view = employee_session_view.public_session(self.session)
            self.assertEqual(self.verify.call_count, attempt)
            self.assertEqual(view['employee_error'], 'Original runtime changed')
            self.assertEqual(view['messages'], self.session['messages'])
            self.assertNotIn('identity', view)
            self.assertNotIn('employee_binding', view)
        self.summary.assert_not_called()

    def test_mismatched_reference_cannot_supply_a_binding(self):
        self.session['context']['source_employee'] = {'source_id': 'other'}
        view = employee_session_view.public_session(self.session)
        self.assertIn('employee_error', view)
        self.assertNotIn('employee_binding', view)
        self.summary.assert_not_called()
