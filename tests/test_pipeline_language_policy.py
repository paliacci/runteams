"""Task language survives role handoffs without rewriting asset instructions."""
import copy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from runteams_core.pipelines import source_pipeline_flow as flow
from runteams_core.pipelines import source_pipeline_work as work
from runteams_core.employees import employee_context
from runteams_core.agents import language_policy
from runteams_core.pipelines import pipeline_task_configuration


class PipelineLanguagePolicyTests(TestCase):
    def test_creation_freezes_device_language_without_rewriting_input(self):
        frozen = self.fixture()
        context = frozen['pipeline_work']
        context['asset']['pipeline']['positions'][0]['skill_key'] = 'write'
        role = {'package': {}, 'context': context, 'configuration': None}
        payload = {'objective': 'Write a French document', 'parameters': {}}
        original = copy.deepcopy(payload)
        with patch.object(work, 'stage_snapshot', return_value={'pipeline_work': context}), \
                patch.object(language_policy, 'snapshot', return_value={'communication_language': 'en'}), \
                patch.object(pipeline_task_configuration, 'fields', return_value=[]), \
                patch.object(pipeline_task_configuration, 'validate_values'), \
                patch.object(flow, 'payload_for', return_value=payload):
            result, _ = flow.initial(None, None, role, {'generation': 1, 'asset': context['asset']}, payload, 'first')
        self.assertEqual(result['language_policy'], {'communication_language': 'en'})
        self.assertEqual(result['pipeline_input'], original)
        self.assertEqual(payload, original)

    def fixture(self):
        asset = {'employees': [{'ref': 'worker'}], 'pipeline': {'name': 'Pipeline', 'positions': [
            {'key': 'first', 'name': 'First', 'kind': 'employee', 'employee_ref': 'worker'},
            {'key': 'next', 'name': 'Next', 'kind': 'employee', 'employee_ref': 'worker',
             'prompt': 'Deliver the final document in French.'}], 'states': []}}
        context = {'reference': {}, 'asset': asset, 'position_key': 'first'}
        return {'pipeline_work': context, 'pipeline_input': {'objective': 'Write a French document'},
                'pipeline_visit': 1, 'pipeline_generation': 'generation', 'pipeline_lineage': []}

    def test_handoff_keeps_frozen_language_and_original_prompt(self):
        for policy in ({'communication_language': 'en'}, None):
            with self.subTest(policy=policy):
                frozen = self.fixture()
                if policy:
                    frozen['language_policy'] = policy
                original = copy.deepcopy(frozen)
                context = {**frozen['pipeline_work'], 'position_key': 'next'}
                role = {'package': {'reference': {}}, 'context': context, 'configuration': None}
                result = {'status': 'completed', 'summary': 'Done', 'issues': [], 'output': {}}
                fake_employee = SimpleNamespace(package_asset=lambda _: {'employee': {'name': 'Worker', 'avatar': ''}})
                with patch.object(flow, '_lineage'), patch.object(flow, 'archive', return_value=[{'snapshot': original}]), \
                        patch.object(flow.control, 'bundle_for_work', return_value={'roles': {'next': role}}), \
                        patch.object(flow.control, 'read', return_value={'status': 'running'}), \
                        patch.object(employee_context, 'current', return_value=fake_employee), \
                        patch.object(work.device_data, 'identity', return_value={'storage_kind': 'local'}), \
                        patch('runteams_core.foundation.identity.work_identity.principal', return_value='test'), \
                        patch.object(flow, 'payload_for', return_value={}), patch.object(flow, '_save') as save:
                    flow._move(None, None, {'cursor_key': 'first'}, frozen, 'next', result)
                next_frozen = save.call_args.args[3]
                self.assertEqual(next_frozen['language_policy'], policy or {'communication_language': 'zh-CN'})
                self.assertEqual(next_frozen['pipeline_input'], original['pipeline_input'])
                self.assertEqual(next_frozen['pipeline_work']['asset'], original['pipeline_work']['asset'])
                self.assertIn('Deliver the final document in French.', flow.stage_prompt(flow.stage_assignment(next_frozen)))
