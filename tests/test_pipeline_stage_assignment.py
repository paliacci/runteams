"""The initial request is retained as context, with an independent downstream assignment."""
import json
import sqlite3
from unittest import TestCase
from unittest.mock import patch

from runteams_core.employees import source_employee_runtime
from runteams_core.pipelines.source_pipeline_flow import add_approval_history, stage_assignment, stage_prompt


class PipelineStageAssignmentTests(TestCase):
    def setUp(self):
        asset = {'employees': [{'ref': 'pm'}, {'ref': 'tester'}], 'pipeline': {'positions': [
            {'key': 'plan', 'kind': 'employee', 'name': '产品经理', 'employee_ref': 'pm'},
            {'key': 'approve', 'kind': 'approval', 'name': '人工立项批准'},
            {'key': 'test', 'kind': 'employee', 'name': '功能测试员', 'employee_ref': 'tester',
             'description': '操作已交接构建，按验收标准记录结果。'},
        ]}}
        self.start = {'asset': asset, 'position_key': 'plan'}
        self.tester = {'asset': asset, 'position_key': 'test'}
        self.objective = '从产品经理岗启动立项，核对市场证据，提交立项单。'
        self.frozen = {'pipeline_work': self.start, 'pipeline_input': {'objective': self.objective}}

    def test_entry_and_return_to_entry_keep_the_user_assignment(self):
        first = stage_assignment(self.frozen)
        self.assertEqual(stage_prompt(first), self.objective)
        self.frozen['pipeline_history'] = [{'snapshot': {'pipeline_work': self.start}}]
        self.assertEqual(stage_assignment(self.frozen), first)

    def test_downstream_and_prospective_handoff_use_the_bound_role(self):
        planned = stage_assignment(self.frozen, self.tester)
        self.frozen.update(pipeline_work=self.tester,
                           pipeline_history=[{'snapshot': {'pipeline_work': self.start}}])
        actual = stage_assignment(self.frozen)
        self.assertEqual(actual, planned)
        self.assertEqual(actual['project_background'], self.objective)
        prompt = stage_prompt(actual)
        self.assertIn('在「功能测试员」岗位', prompt)
        self.assertIn('操作已交接构建', prompt)
        self.assertNotIn(self.objective, prompt)
        self.assertEqual(self.frozen['pipeline_input']['objective'], self.objective)

    def test_approval_history_uses_only_the_current_tasks_latest_decisions(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,stream TEXT,type TEXT,data_json TEXT)')
        for stream, gate, decision, note in [
            ('workflow_run:1', 'approve', 'revise', '补充范围'),
            ('workflow_run:1', 'approve', 'approved', '已批准立项，提审另行确认'),
            ('workflow_run:2', 'approve', 'rejected', '别的任务'),
            ('workflow_run:1', 'removed-gate', 'approved', '已移除关卡'),
        ]:
            db.execute('INSERT INTO events(stream,type,data_json) VALUES(?,?,?)', (
                stream, 'workflow.approval_decided',
                json.dumps({'position_key': gate, 'decision': decision, 'note': note})))
        stage = stage_assignment(self.frozen, self.tester)
        add_approval_history(db, 1, self.tester, stage)
        self.assertEqual(stage['approval_history'], [{
            'position_name': '人工立项批准', 'decision': 'approved', 'note': '已批准立项，提审另行确认',
        }])

    def test_pipeline_dialog_accepts_only_its_pinned_plain_skill(self):
        self.tester['asset']['pipeline']['positions'][-1]['skill_key'] = 'plain'
        context = {'pipeline_work': self.tester, 'preferred_skill_key': 'plain'}
        asset = {'skill_bundles': [{'package_key': 'plain'}, {'package_key': 'other'}]}
        with patch.object(source_employee_runtime, 'for_chat', return_value={'local_package': {}}), \
                patch.object(source_employee_runtime, 'package_asset', return_value=asset), \
                patch.object(source_employee_runtime, 'units', return_value=[]):
            session = {'id': 1, 'context': context}
            self.assertEqual(source_employee_runtime.work_config_context(session, None), context)
            with self.assertRaises(ValueError):
                source_employee_runtime.work_config_context(session, {**context, 'preferred_skill_key': 'other'})
            with self.assertRaises(ValueError):
                source_employee_runtime.work_config_context(
                    {'id': 2, 'context': {'preferred_skill_key': 'plain'}}, None)
