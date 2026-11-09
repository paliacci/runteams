"""The task's pending feedback accepts an offered choice or a custom reply."""
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import uuid

from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import source_pipeline_flow as flow
from runteams_core.storage import device_data
from runteams_core.storage.repository import Repository, utc_now
from runteams_core.work.device_work import DeviceWorkStorage


QUESTION = {'question': '怎么继续验收？', 'options': [
    {'label': '已解锁，继续验收', 'description': '在已连接设备上重试。', 'recommended': True},
    {'label': '汇总现有结果'},
]}
DECISIONS = {**QUESTION, 'options': [{**option, 'input_mode': 'none'} for option in QUESTION['options']]}


class PipelineFeedbackTests(TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(TemporaryDirectory()))
        scope = {'storage_kind': 'local', 'library_id': 'feedback-test', 'storage_namespace': 'feedback-test'}
        for name, value in [('root', root), ('identity', scope), ('personal', True), ('check', None)]:
            stack.enter_context(patch.object(device_data, name, return_value=value))
        storage = DeviceWorkStorage()
        storage.initialize()
        self.repo = Repository(storage.path, storage=storage)
        self.core = SimpleNamespace(repository=self.repo, _actor=lambda: None)
        self.ref = {'pipeline': 'example'}
        self.snapshot = {'pipeline_work': {'reference': self.ref, 'position_key': 'test'}, 'employee_reference': {},
                         'pipeline_visit': 4, 'pipeline_waiting': {'kind': 'result', 'position_key': 'test',
                         'source_run_id': 5, 'result': {'status': 'blocked', 'output': {}}}}
        with self.repo.connect() as connection:
            now = utc_now()
            task = connection.execute("INSERT INTO tasks(employee_reference,title,payload_json,state,created_at,updated_at)"
                                      " VALUES('{}','验收','{}','blocked',?,?)", (now, now)).lastrowid
            self.identifier = connection.execute("INSERT INTO workflow_runs(task_id,state,cursor_key,snapshot_json,created_at,updated_at)"
                                                 " VALUES(?,'blocked','test',?,?,?)",
                                                 (task, json.dumps(self.snapshot), now, now)).lastrowid
        stack.enter_context(patch.object(flow.pipeline_references, 'checked_reference', side_effect=lambda value: value))
        stack.enter_context(patch.object(flow.control, 'read', return_value={'status': 'running'}))
        stack.enter_context(patch.object(flow.control, 'settle_pause'))
        stack.enter_context(patch.object(flow.work, 'work', side_effect=lambda *_: self.read()))
        stack.enter_context(patch.object(flow, '_move', side_effect=self.move))

    @staticmethod
    def move(core, connection, row, frozen, position, result, run_id):
        frozen['pipeline_visit'] += 1
        flow._save(core, connection, row, frozen, 'ready', position)

    def read(self):
        with self.repo.read_snapshot() as connection:
            row = flow._row(connection, self.identifier)
            return {'state': row['state'], 'snapshot': json.loads(row['snapshot_json'])}

    def request(self, action, **fields):
        return {'workflow_id': self.identifier, 'operation_id': str(uuid.uuid4()), 'reference': self.ref,
                'expected_visit': 4, 'action': action, **fields}

    def test_add_choices_to_original_wait_without_resuming(self):
        command = self.request('suggest_responses', human_request=DECISIONS)
        result = flow.command(self.core, command)
        self.assertEqual(result, flow.command(self.core, command))
        state = self.read()
        self.assertEqual(state['state'], 'blocked')
        wait = state['snapshot']['pipeline_waiting']
        self.assertEqual(flow.human_request(wait), DECISIONS)
        self.assertEqual(wait['result'], self.snapshot['pipeline_waiting']['result'])
        with self.assertRaises(ContractError):
            flow.command(self.core, self.request('suggest_responses', human_request=DECISIONS))

    def test_select_and_continue_only_accepts_a_current_offered_choice(self):
        flow.command(self.core, self.request('suggest_responses', human_request=DECISIONS))
        with self.assertRaisesRegex(ContractError, '选项已失效'):
            flow.command(self.core, self.request('respond', response='', choice='其他选项'))
        command = self.request('respond', response='', choice='已解锁，继续验收')
        self.assertEqual(flow.command(self.core, command), flow.command(self.core, command))
        self.assertEqual(self.read()['snapshot']['pipeline_response'], '选择：已解锁，继续验收')
        self.assertEqual(self.read()['snapshot']['pipeline_visit'], 5)

    def test_stale_visit_reports_conflict_and_keeps_the_original_receipt(self):
        from runteams_core.pipelines.source_pipeline_operations import dispatch

        original = self.request('respond', response='已经补齐。')
        receipt = flow.command(self.core, original)
        stale = self.request('respond', response='再次补齐。')
        response, status = dispatch(self.core, 'flow', stale)
        self.assertEqual(status, 409)
        self.assertEqual(response['code'], 'workflow_visit_changed')
        self.assertEqual(self.read()['snapshot']['pipeline_visit'], 5)
        saved, status = dispatch(self.core, 'flow-operation', original)
        self.assertEqual(status, 200)
        self.assertEqual(saved, receipt)

    def test_custom_reply_keeps_the_existing_contract(self):
        with self.assertRaises(ContractError):
            flow.command(self.core, self.request('respond', response='   '))
        flow.command(self.core, self.request('respond', response='等下一台测试设备。'))
        self.assertEqual(self.read()['snapshot']['pipeline_response'], '等下一台测试设备。')

    def launch_failure(self, **overrides):
        snapshot = {key: value for key, value in self.snapshot.items() if key != 'pipeline_waiting'}
        snapshot.update(overrides)
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='needs_human',snapshot_json=? WHERE id=?",
                               (json.dumps(snapshot), self.identifier))
            stream = 'workflow_run:' + str(self.identifier)
            self.repo.event(stream, 'workflow.claimed', {'from_state': 'ready'}, connection=connection)
            self.repo.event(stream, 'workflow.needs_human', {'position_key': 'test', 'reason': '启动检查未通过'},
                            connection=connection)

    def test_launch_retry_requeues_the_same_visit_once(self):
        self.launch_failure()
        command = self.request('retry', verified=False)
        with patch.object(flow.control, 'read', return_value={'status': 'running', 'bundle': {'roles': {'test': {}}}}):
            first = flow.command(self.core, command)
            self.assertEqual(first, flow.command(self.core, command))
            with self.assertRaises(ContractError):
                flow.command(self.core, self.request('retry', verified=False))
        self.assertEqual(self.read()['state'], 'ready')
        self.assertEqual(self.read()['snapshot']['pipeline_visit'], 4)
        self.assertEqual(sum(event['type'] == 'workflow.launch_retried'
                             for event in self.repo.events('workflow_run:' + str(self.identifier))), 1)

    def test_launch_retry_does_not_admit_a_sent_execution(self):
        self.launch_failure(send_admitted=True)
        with patch.object(flow.control, 'read', return_value={'status': 'running', 'bundle': {'roles': {'test': {}}}}):
            with self.assertRaises(ContractError):
                flow.command(self.core, self.request('retry', verified=False))
        self.assertEqual(self.read()['state'], 'needs_human')

    def test_check_failed_execution_preserves_the_visit_when_no_result_is_found(self):
        from runteams_core.pipelines import pipeline_context

        self.launch_failure(send_admitted=True, pipeline_unresolved=True)
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='failed' WHERE id=?", (self.identifier,))
        provider = SimpleNamespace(reconcile_result=lambda _core, _identifier, **_: False)
        command = self.request('recover')
        with (patch.object(pipeline_context, 'current', return_value=provider),
              patch.object(flow, '_rejected_completed_submission', return_value=None)):
            receipt = flow.command(self.core, command)
            self.assertEqual(receipt, flow.command(self.core, command))
            self.assertEqual(receipt, flow.command(self.core, command, read_only=True))
        current = self.read()
        self.assertEqual(current['state'], 'failed')
        self.assertEqual(current['snapshot']['pipeline_visit'], 4)
        checked = [event for event in self.repo.events('workflow_run:' + str(self.identifier))
                   if event['type'] == 'workflow.result_checked']
        self.assertEqual([event['data_json']['visit'] for event in checked], [4])

    def test_handoff_correction_uses_original_chat_and_is_admitted_once(self):
        proof = {'message_id': 8, 'submission_id': str(uuid.uuid4()), 'error': '缺交接材料',
                 'handoff': {'to': 'review', 'fields': ['brief']}}
        self.launch_failure(send_admitted=True, work_chat_id=17, employee_run_id=12,
                            package={}, pipeline_result_correction={**proof, 'admitted': False})
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='running' WHERE id=?", (self.identifier,))
        self.core._cancel_event = lambda _: None
        calls = []

        def executor(chat_id, prompt, _cancel, _owner):
            calls.append((chat_id, prompt))
            return 'completed', ''

        with (patch.object(flow, '_rejected_completed_submission', return_value=proof),
              patch.object(flow, 'result_schema', return_value={}),
              patch.object(flow, 'finish_turn', return_value='completed')):
            self.assertEqual(flow.correct_rejected_result(self.core, self.identifier, executor), 'completed')
            with self.assertRaises(ContractError):
                flow.correct_rejected_result(self.core, self.identifier, executor)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 17)
        self.assertIn(proof['submission_id'], calls[0][1])
        self.assertIn('不要重新执行上传、发布', calls[0][1])

    def test_material_wait_stays_on_the_original_position_and_accepts_saved_configuration(self):
        snapshot = {**self.snapshot, 'pipeline_input': {'parameters': {}}}
        wait = flow.wait_for_input(snapshot, 'test', {'status': 'completed', 'summary': '缺网址', 'output': {}}, 5)
        snapshot['pipeline_waiting'] = wait
        self.assertEqual((wait['state'], wait['position_key'], wait['source_run_id']), ('needs_human', 'test', 5))
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='needs_human',snapshot_json=? WHERE id=?",
                               (json.dumps(snapshot), self.identifier))
        with self.assertRaises(ContractError):
            flow.command(self.core, self.request('respond', response=''))
        snapshot['pipeline_input']['parameters']['support_url'] = 'https://example.com/support'
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
                               (json.dumps(snapshot), self.identifier))
        command = self.request('respond', response='')
        result = flow.command(self.core, command)
        self.assertEqual(result, flow.command(self.core, command))
        self.assertEqual(self.read()['state'], 'ready')
        self.assertEqual(self.read()['snapshot']['pipeline_visit'], 5)

    def test_configuration_only_wait_rejects_text_as_a_substitute_for_required_fields(self):
        snapshot = {**self.snapshot, 'pipeline_input': {'parameters': {'support_url': 'https://example.com/support'}}}
        snapshot['pipeline_waiting'] = flow.wait_for_input(
            snapshot, 'test', {'status': 'completed', 'output': {}}, 5, ['support_url', 'privacy_url'])
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='needs_human',snapshot_json=? WHERE id=?",
                               (json.dumps(snapshot), self.identifier))
        with self.assertRaisesRegex(ContractError, '本次必需的配置'):
            flow.command(self.core, self.request('respond', response='都准备好了'))
        snapshot['pipeline_input']['parameters']['privacy_url'] = 'https://example.com/privacy'
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
                               (json.dumps(snapshot), self.identifier))
        flow.command(self.core, self.request('respond', response=''))
        self.assertEqual(self.read()['state'], 'ready')
        self.assertIn('已确认本次必需', self.read()['snapshot']['pipeline_response'])

    def test_choice_configuration_and_note_are_validated_and_delivered_together(self):
        snapshot = {**self.snapshot, 'pipeline_input': {'parameters': {'support_url': 'https://example.com/support'}}}
        graph = {'parameters': [
            {'key': key, 'source': 'user', 'display': 'setup', 'type': 'text', 'visible_to': ['test']}
            for key in ('support_url', 'privacy_url')],
            'edges': [{'from': 'test', 'to': flow.PIPELINE_WAIT_FOR_INPUT, 'when': 'outcome:needs_material',
                       'configuration_fields': ['support_url', 'privacy_url']}]}
        snapshot['pipeline_work'] = {**snapshot['pipeline_work'], 'asset': {'pipeline': graph}}
        snapshot['pipeline_waiting']['result']['output']['route'] = 'needs_material'
        snapshot['pipeline_waiting']['human_request'] = {**QUESTION, 'options': [
            QUESTION['options'][0], {**QUESTION['options'][1],
                                    'configuration_fields': ['support_url', 'privacy_url']} ]}
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
                               (json.dumps(snapshot), self.identifier))
        request = flow.feedback_request(snapshot)
        self.assertNotIn('configuration_fields', request['options'][0])
        self.assertEqual(request['options'][1]['configuration_fields'], ['support_url', 'privacy_url'])
        command = self.request('respond', choice='汇总现有结果', response='新政策已发布')
        with self.assertRaisesRegex(ContractError, '本次必需的配置'):
            flow.command(self.core, command)
        snapshot['pipeline_input']['parameters']['privacy_url'] = 'https://example.com/privacy'
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
                               (json.dumps(snapshot), self.identifier))
        flow.command(self.core, command)
        response = self.read()['snapshot']['pipeline_response']
        self.assertIn('选择：汇总现有结果', response)
        self.assertIn('补充：新政策已发布', response)
        self.assertIn('已确认本次必需', response)

    def test_route_configuration_does_not_leak_into_unrelated_choices(self):
        snapshot = {**self.snapshot, 'pipeline_work': {**self.snapshot['pipeline_work'], 'asset': {'pipeline': {
            'edges': [{'from': 'test', 'to': flow.PIPELINE_WAIT_FOR_INPUT, 'when': 'outcome:needs_material',
                       'configuration_fields': ['support_url']}]}}}}
        snapshot['pipeline_waiting'] = {**snapshot['pipeline_waiting'], 'human_request': QUESTION}
        self.assertEqual(flow.feedback_request(snapshot), QUESTION)

    def test_feedback_exposes_only_declared_visible_nonsecret_setup_fields(self):
        fields = [
            {'key': 'support_url', 'label': '支持页面', 'source': 'user', 'display': 'setup', 'type': 'text'},
            {'key': 'token', 'source': 'user', 'display': 'setup', 'type': 'secret'},
            {'key': 'other', 'source': 'user', 'display': 'setup', 'type': 'text', 'visible_to': ['other']},
            {'key': 'reply', 'source': 'user', 'display': 'input', 'type': 'text'},
            {'key': 'generated', 'source': 'employee', 'display': 'setup', 'type': 'text'}]
        context = {'position_key': 'test', 'asset': {'pipeline': {'parameters': fields}}}
        self.assertEqual(flow._feedback_configuration_fields(context), [
            {'key': 'support_url', 'label': '支持页面', 'type': 'text'}])
        with self.assertRaisesRegex(ContractError, '本岗位可用'):
            flow._feedback_fields(context, ['other'])

    def test_selected_option_can_include_a_note(self):
        self.snapshot['pipeline_waiting']['human_request'] = QUESTION
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
                               (json.dumps(self.snapshot), self.identifier))
        flow.command(self.core, self.request('respond', choice='汇总现有结果', response='保留未测记录'))
        self.assertEqual(self.read()['snapshot']['pipeline_response'], '选择：汇总现有结果\n补充：保留未测记录')

    def test_new_submission_requires_explicit_input_but_legacy_receipt_replays(self):
        from runteams_core.foundation.contracts import digest
        operation = str(uuid.uuid4())
        raw = {'status': 'blocked', 'human_request': QUESTION}
        result = flow._result({}, {}, raw)
        frozen = {'package': {}, 'pipeline_work': {}, 'pipeline_visit': 4, 'employee_run_id': 5}
        row = {'id': self.identifier}
        with self.repo.connect() as connection:
            with self.assertRaisesRegex(ContractError, 'input_mode'):
                flow._submission(self.core, connection, row, frozen, operation, raw)
            with self.assertRaisesRegex(ContractError, 'result.human_request'):
                flow._submission(self.core, connection, row, frozen, operation,
                                 {'status': 'blocked', 'output': QUESTION})
            receipt = {'operation_id': operation}
            stream = 'source-pipeline-result:' + operation
            self.repo.event(stream, 'pipeline.result_submitted', {'receipt': receipt, 'request_sha256': digest({
                'operation_id': operation, 'result': result, 'visit': 4, 'workflow_id': self.identifier,
            })}, connection=connection)
            self.assertEqual(flow._submission(self.core, connection, row, frozen, operation, raw), receipt)

    def test_new_human_wait_requires_a_concrete_dependency_before_saving(self):
        operation = str(uuid.uuid4())
        row = {'id': self.identifier}
        frozen = {'package': {}, 'pipeline_work': {'position_key': 'test', 'asset': {'pipeline': {'positions': []}}},
                  'pipeline_visit': 4, 'employee_run_id': 5}
        from runteams_core.work.work_ledger import WorkLedger
        self.core._matching_edge = WorkLedger._matching_edge
        with self.repo.connect() as connection, patch('runteams_core.work.work_reports.catalog', return_value=[]):
            with self.assertRaisesRegex(ContractError, '只有确实需要人工'):
                flow._submission(self.core, connection, row, frozen, operation, {'status': 'needs_human'})
            with self.assertRaisesRegex(ContractError, 'human_request.blocker'):
                flow._submission(self.core, connection, row, frozen, operation,
                                 {'status': 'needs_human', 'human_request': DECISIONS})
            blocker = {'kind': 'information', 'user_action': '提供本次测试设备编号',
                       'reason': '已核对任务资料和设备清单，没有本次测试指定的设备。'}
            with self.assertRaisesRegex(ContractError, '补充所需信息'):
                flow._submission(self.core, connection, row, frozen, operation,
                                 {'status': 'needs_human', 'human_request': {**DECISIONS, 'blocker': blocker}})
            self.assertNotIn('pipeline_submission', frozen)
            request = {'question': '本次用哪台设备？', 'blocker': blocker,
                       'options': [{'label': '提供设备编号', 'input_mode': 'text', 'response_prompt': '填写设备编号'}]}
            result = {'status': 'needs_human', 'human_request': request}
            receipt = flow._submission(self.core, connection, row, frozen, operation, result)
            self.assertEqual(flow._submission(self.core, connection, row, frozen, operation, result), receipt)
        self.assertEqual(frozen['pipeline_submission']['result']['human_request'], request)

    def test_declared_employee_handoff_is_not_a_human_wait(self):
        graph = {'routing_policy': flow.PIPELINE_STATUS_FIRST,
                 'positions': [{'key': 'review', 'kind': 'employee'}, {'key': 'repair', 'kind': 'employee'}],
                 'edges': [{'from': 'review', 'to': 'repair', 'when': 'needs_human'}]}
        context = {'position_key': 'review', 'asset': {'pipeline': graph}}
        result = {'status': 'needs_human', 'output': {}}
        with self.assertRaisesRegex(ContractError, '已有员工接续路线'):
            flow._check_human_dependency(context, {**result, 'human_request': DECISIONS})
        flow._check_human_dependency(context, result)

    def test_wait_for_input_requires_a_question_or_configured_fields(self):
        edge = {'from': 'review', 'to': flow.PIPELINE_WAIT_FOR_INPUT, 'when': 'always'}
        graph = {'routing_policy': flow.PIPELINE_STATUS_FIRST, 'positions': [], 'edges': [edge]}
        context = {'position_key': 'review', 'asset': {'pipeline': graph}}
        result = {'status': 'completed', 'output': {}}
        with self.assertRaisesRegex(ContractError, '只有确实需要人工'):
            flow._check_human_dependency(context, result)
        edge['configuration_fields'] = ['device_name']
        flow._check_human_dependency(context, result)

    def test_typed_wait_requires_the_selected_text_and_preserves_route_fields(self):
        request = {**QUESTION, 'options': [
            {**QUESTION['options'][0], 'input_mode': 'fields_and_text', 'configuration_fields': ['privacy_url'],
             'response_prompt': '说明核验结果'},
            {**QUESTION['options'][1], 'input_mode': 'none'},
        ]}
        snapshot = {**self.snapshot, 'pipeline_input': {'parameters': {'privacy_url': 'https://example.org/privacy'}}}
        graph = {'parameters': [
            {'key': key, 'source': 'user', 'display': 'setup', 'type': 'text'}
            for key in ('privacy_url', 'support_url')]}
        snapshot['pipeline_work'] = {**snapshot['pipeline_work'], 'asset': {'pipeline': graph}}
        snapshot['pipeline_waiting'] = flow.wait_for_input(
            snapshot, 'test', {'status': 'completed', 'human_request': request}, 5, ['support_url'])
        def save():
            with self.repo.connect() as connection:
                connection.execute("UPDATE workflow_runs SET state='needs_human',snapshot_json=? WHERE id=?",
                                   (json.dumps(snapshot), self.identifier))
        save()
        with self.assertRaisesRegex(ContractError, '请选择一项'):
            flow.command(self.core, self.request('respond', response='绕过选项'))
        with self.assertRaisesRegex(ContractError, '说明核验结果'):
            flow.command(self.core, self.request('respond', choice=QUESTION['options'][0]['label'], response='  '))
        with self.assertRaisesRegex(ContractError, '本次必需的配置'):
            flow.command(self.core, self.request('respond', choice=QUESTION['options'][1]['label'], response=''))
        snapshot['pipeline_input']['parameters']['support_url'] = 'https://example.org/support'
        save()
        flow.command(self.core, self.request('respond', choice=QUESTION['options'][0]['label'], response='已核验'))
        self.assertIn('补充：已核验', self.read()['snapshot']['pipeline_response'])

    def test_typed_option_rejects_inconsistent_fields_and_text(self):
        for option in [
            {'label': '给资料', 'input_mode': 'fields'},
            {'label': '给资料', 'input_mode': 'text', 'response_prompt': ' '},
            {'label': '决定', 'input_mode': 'none', 'configuration_fields': ['support_url']},
        ]:
            with self.subTest(option=option), self.assertRaises(ContractError):
                flow._human_request({'question': '怎么继续？', 'options': [option]})

    def test_completed_business_wait_accepts_agent_authored_feedback(self):
        context = {'position_key': 'test', 'asset': {'employees': [{'ref': 'employee'}], 'pipeline': {
            'positions': [{'key': 'test', 'kind': 'employee', 'employee_ref': 'employee', 'skill_key': 'test'}],
            'routing_policy': flow.PIPELINE_STATUS_FIRST,
            'edges': [{'from': 'test', 'to': flow.PIPELINE_WAIT_FOR_INPUT, 'when': 'outcome:needs_material'}]}}}
        result = {'status': 'completed', 'summary': '等待负责人决定',
                  'output': {'route': 'needs_material'}, 'human_request': QUESTION}
        with patch.object(flow, 'declared', return_value=None):
            accepted = flow._result({}, context, result)
        wait = flow.wait_for_input({}, 'test', accepted, 5, ['support_url'])
        self.assertEqual(flow.human_request(wait), QUESTION)
        self.assertNotIn('configuration_fields', wait)
        result['output'] = {'route': 'ready'}
        with self.assertRaisesRegex(ContractError, '只有等待人工回答'):
            flow._result({}, context, result)

    def test_typed_agent_requests_and_legacy_results(self):
        result = flow._result({}, {}, {'status': 'blocked', 'human_request': QUESTION})
        self.assertEqual(flow.human_request({'result': result}), QUESTION)
        self.assertEqual(flow.human_request({'result': {'output': QUESTION}}), QUESTION)
        with self.assertRaises(ContractError):
            flow._result({}, {}, {'status': 'failed', 'human_request': QUESTION})
        with self.assertRaises(ContractError):
            flow._result({}, {}, {'status': 'blocked', 'human_request': {
                **QUESTION, 'options': [{'label': '重复'}, {'label': '重复 '}]}})

    def test_approval_copy_is_saved_without_deciding_and_cannot_invent_routes(self):
        graph = {'edges': [
            {'from': 'approval', 'to': 'done', 'when': 'approved'},
            {'from': 'approval', 'to': 'test', 'when': 'rejected'},
        ]}
        snapshot = {**self.snapshot,
                    'pipeline_work': {**self.snapshot['pipeline_work'], 'asset': {'pipeline': graph}},
                    'pipeline_waiting': {'kind': 'approval', 'position_key': 'approval', 'source_run_id': 5}}
        with self.repo.connect() as connection:
            connection.execute("UPDATE workflow_runs SET state='needs_approval',cursor_key='approval',snapshot_json=? WHERE id=?",
                               (json.dumps(snapshot), self.identifier))
        request = {'question': '发布草稿准备好了，怎么处理？', 'options': [
            {'decision': 'approved', 'label': '确认这次发布草稿'},
            {'decision': 'rejected', 'label': '退回修正截图'},
        ]}
        invented = {**request, 'options': [{**request['options'][0], 'decision': 'publish_now'}, request['options'][1]]}
        with self.assertRaisesRegex(ContractError, '一一对应'):
            flow.command(self.core, self.request('suggest_approval', approval_request=invented))
        command = self.request('suggest_approval', approval_request=request)
        self.assertEqual(flow.command(self.core, command), flow.command(self.core, command))
        state = self.read()
        self.assertEqual(state['state'], 'needs_approval')
        self.assertEqual(state['snapshot']['pipeline_visit'], 4)
        self.assertEqual(state['snapshot']['pipeline_waiting']['approval_request'], request)

    def test_employee_handoff_to_approval_requires_contextual_options(self):
        from runteams_core.work.work_ledger import WorkLedger
        graph = {'routing_policy': flow.PIPELINE_STATUS_FIRST,
                 'positions': [{'key': 'test', 'kind': 'employee', 'employee_ref': 'employee', 'skill_key': 'test'},
                               {'key': 'approval', 'kind': 'approval'}],
                 'edges': [{'from': 'test', 'to': 'approval', 'when': 'completed'},
                           {'from': 'approval', 'to': 'done', 'when': 'approved'}]}
        frozen = {**self.snapshot, 'package': {}, 'employee_run_id': 5,
                  'pipeline_work': {**self.snapshot['pipeline_work'],
                                    'asset': {'pipeline': graph, 'employees': [{'ref': 'employee'}]}}}
        self.core._matching_edge = WorkLedger._matching_edge
        result = {'status': 'completed', 'summary': '截图已备齐', 'output': {}}
        options = {'question': '要确认这批截图吗？',
                   'options': [{'decision': 'approved', 'label': '确认这批截图'}]}
        operation_id = str(uuid.uuid4())
        with self.repo.connect() as connection, patch.object(flow, 'declared', return_value=None), \
                patch('runteams_core.work.work_reports.catalog', return_value=[]):
            row = flow._row(connection, self.identifier)
            with self.assertRaisesRegex(ContractError, 'approval_request'):
                flow._submission(self.core, connection, row, frozen, operation_id, result)
            flow._submission(self.core, connection, row, frozen, operation_id,
                             {**result, 'approval_request': options})
        self.assertEqual(frozen['pipeline_submission']['result']['approval_request'], options)


class PipelineHandoffRecoveryTests(TestCase):
    def test_missing_approval_brief_uses_the_same_validation_for_submission_and_recovery(self):
        from runteams_core.pipelines.source_pipeline_recovery import inspect_terminal

        graph = {'routing_policy': flow.PIPELINE_STATUS_FIRST, 'positions': [{'key': 'accept', 'kind': 'approval'}],
                 'edges': [{'from': 'accept', 'to': 'done', 'when': 'approved'}]}
        frozen = {'package': {}, 'pipeline_work': {'asset': {'pipeline': graph}, 'position_key': 'review'}}
        core = SimpleNamespace(_matching_edge=lambda *_: {'to': 'accept'})
        result = {'status': 'completed', 'output': {}}
        item = {'type': 'dynamicToolCall', 'tool': 'runteams_pipeline_work', 'success': False,
                'status': 'failed', 'arguments': {'operation': 'submit', 'operation_id': str(uuid.uuid4()),
                                                 'result': result}}
        native = {'thread': {'id': 'thread', 'turns': [
            {'id': 'turn', 'status': 'completed', 'itemsView': 'full', 'items': [item]}]}}
        with patch.object(flow, '_result', return_value=result):
            with self.assertRaises(flow.ApprovalBriefMissing) as rejected:
                flow._check_downstream(core, object(), frozen, result)
            item['contentItems'] = [{'type': 'inputText', 'text': str(rejected.exception)}]
            proof = inspect_terminal(core, frozen, native, object())
            self.assertEqual(proof['approval'], {'position': 'accept', 'decisions': ['approved']})
            self.assertEqual(proof['submission_id'], item['arguments']['operation_id'])
            result['approval_request'] = {'question': '提交已核对的版本吗？'}
            self.assertIsNone(inspect_terminal(core, frozen, native, object()))

    def test_native_handoff_rejection_requires_the_recorded_validator_result(self):
        from runteams_core.pipelines.source_pipeline_recovery import inspect_terminal

        definition = {'positions': [
            {'key': 'writer', 'name': '编写资料', 'kind': 'employee'},
            {'key': 'reviewer', 'name': '检查资料', 'kind': 'employee'},
        ], 'parameters': [{'key': 'brief', 'source': 'employee', 'writers': ['writer']}]}
        frozen = {'package': {}, 'pipeline_work': {'asset': {'pipeline': definition}, 'position_key': 'writer'},
                  'pipeline_lineage': [12], 'employee_run_id': 12}
        core = SimpleNamespace(_matching_edge=lambda *_: {'to': 'reviewer'})
        result = {'status': 'completed', 'output': {}}
        recorded = '下游尚不能接收，请由编写资料补齐后再提交：缺少交接材料'
        item = {'type': 'dynamicToolCall', 'tool': 'runteams_pipeline_work', 'success': False,
                'status': 'failed', 'arguments': {'operation': 'submit', 'operation_id': str(uuid.uuid4()),
                                                 'result': result},
                'contentItems': [{'type': 'inputText', 'text': recorded}]}
        native = {'thread': {'id': 'thread', 'turns': [
            {'id': 'turn', 'status': 'completed', 'itemsView': 'full', 'items': [item]}]}}
        connection = object()
        with (patch.object(flow, '_result', return_value=result),
              patch.object(flow, '_lineage'),
              patch.object(flow.control, 'bundle_for_work', return_value={'roles': {'reviewer': {}}}),
              patch.object(flow, 'payload_for',
                           side_effect=flow.work.StageInputError('缺少交接材料', fields=['brief'])) as validate):
            proof = inspect_terminal(core, frozen, native, connection)
            self.assertEqual(proof['submission_id'], item['arguments']['operation_id'])
            self.assertEqual(proof['handoff']['fields'], ['brief'])
            self.assertEqual(proof['handoff']['to'], 'reviewer')
            self.assertEqual(proof['handoff']['responsible_positions'], ['writer'])
            self.assertFalse(proof['handoff']['requires_user_input_or_authorization'])

            item['contentItems'][0]['text'] = '其他原因'
            self.assertIsNone(inspect_terminal(core, frozen, native, connection))
            item['contentItems'][0]['text'] = recorded
            validate.side_effect = ContractError(recorded)
            self.assertIsNone(inspect_terminal(core, frozen, native, connection))
