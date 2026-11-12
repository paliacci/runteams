"""Employee records identify their existing pipeline task without a second task."""
from unittest import TestCase
from unittest.mock import patch

from runteams_core.employees import employee_chat_work


class EmployeePipelineRecordTests(TestCase):
    def project(self, snapshot):
        work = {'created_at': '2026-11-10T00:00:00Z', 'updated_at': '2026-11-10T01:00:00Z',
                'employee_runs': [], 'snapshot_json': snapshot}
        job = {'id': 42, 'workflow_id': 42, 'title': 'Original task', 'state': 'needs_human', 'chat_id': 7}
        with patch.object(employee_chat_work, 'detail', return_value=work):
            return employee_chat_work.delivery(None, job, [])

    def test_pipeline_record_points_at_original_task_and_reference(self):
        reference = {'source_id': 'fixture', 'pipeline_source': 'pipelines/example.json'}
        result = self.project({'pipeline_work': {'reference': reference}})
        self.assertEqual(result['workflow_id'], 42)
        self.assertEqual(result['pipeline_reference'], reference)
        self.assertEqual(result['state'], 'needs_human')

    def test_independent_employee_work_has_no_pipeline_task_route(self):
        result = self.project({})
        self.assertNotIn('pipeline_reference', result)
        self.assertEqual(result['task_kind'], 'employee')
