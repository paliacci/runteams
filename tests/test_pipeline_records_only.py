"""Record-only endings retain completion semantics across source/local contracts."""
from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator
from runteams_core.authoring.creator_definitions import author_schema
from runteams_core.foundation.contracts import ContractError, normalize_pipeline_definition
from runteams_core.pipelines.portable_pipeline import pipeline_schema, portable_definition


class RecordsOnlyTests(unittest.TestCase):
    def setUp(self):
        self.definition = {
            'positions': [{'key': 'scout', 'kind': 'employee', 'name': 'Scout',
                           'employee_id': 1, 'skill_key': 'scan'}],
            'edges': [{'from': 'scout', 'to': 'empty', 'when': 'no_changes'}],
            'states': [{'key': 'empty', 'kind': 'done', 'name': 'No candidates', 'records_only': True}],
        }

    def test_round_trip_retains_completion_and_record_policy(self):
        normalized = normalize_pipeline_definition(self.definition)
        self.assertEqual(normalized['states'], self.definition['states'])
        exported = portable_definition(normalized, {1: 'scout'})
        self.assertEqual(exported['states'], self.definition['states'])
        self.assertEqual(exported['edges'], normalized['edges'])
        Draft202012Validator(pipeline_schema()['$defs']['state']).validate(exported['states'][0])

    def test_only_completed_endings_may_hide_cards(self):
        for kind, policy in [('pool', True), ('dropped', True), ('done', 'true'), ('done', 1)]:
            value = deepcopy(self.definition)
            value['states'][0].update(kind=kind, records_only=policy)
            with self.subTest(kind=kind, policy=policy):
                with self.assertRaises(ContractError):
                    normalize_pipeline_definition(value)
                self.assertFalse(Draft202012Validator(pipeline_schema()['$defs']['state']).is_valid(value['states'][0]))

    def test_source_authoring_uses_the_same_record_only_contract(self):
        definition = portable_definition(normalize_pipeline_definition(self.definition), {1: 'scout'})
        source = {'schema': 'runteams.pipeline-source/3', 'key': 'scan',
                  'employees': [{'ref': 'scout', 'source': 'employees/scout.json'}],
                  'pipeline': {'name': 'Scout', **definition}}
        Draft202012Validator(author_schema('pipeline')).validate(source)

    def test_existing_states_and_explicit_false_keep_default_visibility(self):
        for policy in [None, False]:
            value = deepcopy(self.definition)
            if policy is None:
                value['states'][0].pop('records_only')
            else:
                value['states'][0]['records_only'] = policy
            self.assertEqual(normalize_pipeline_definition(value)['states'], value['states'])
