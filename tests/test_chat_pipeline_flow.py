from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import test_pipeline_feedback
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import chat_pipeline_flow as chat
from runteams_core.pipelines import source_pipeline_flow as flow


class ChatPipelineFlowTests(TestCase):
    def setUp(self):
        test_pipeline_feedback.PipelineFeedbackTests.setUp(self)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.core.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.snapshot['package'] = {}
        self.snapshot['pipeline_generation'] = 1
        self.snapshot['pipeline_input'] = {'objective': '验收'}
        self.snapshot['pipeline_work']['asset'] = {'pipeline': {
            'positions': [{'key': 'test', 'kind': 'employee', 'name': '验收岗'},
                          {'key': 'approval', 'kind': 'approval', 'name': '审批岗'}],
            'states': [{'key': 'done', 'kind': 'done', 'name': '完成'}],
            'edges': [{'from': 'approval', 'to': 'done', 'when': 'approved'},
                      {'from': 'approval', 'to': 'test', 'when': 'returned'}],
        }}
        self.state()
        self.stack.enter_context(patch.object(chat.access.work, 'verify_context'))
        self.stack.enter_context(patch.object(chat.access, 'bound', return_value=self.ref))
        self.stack.enter_context(patch.object(chat.device_data, 'epoch', return_value='epoch-1'))
        self.message = {'role': 'user', 'text': '请退回验收，也请用本次附件补充第二项验收。', 'attachments': []}
        self.stack.enter_context(patch.object(chat.product_store, 'get_chat_message', return_value=self.message))
        self.confirm = Mock(side_effect=lambda questions: {
            'answers': {questions[0]['id']: {'answers': [questions[0]['options'][0]['label']]}}})
        self.wake = Mock()
        self.context = {'chat_id': 99, 'actor_id': 'feedback-test'}
        self.assertTrue(chat.bind_turn(self.context, 7, Event(), self.confirm, lambda: (), self.wake))
        self.turn = self.context['pipeline_flow_turn']

    move = staticmethod(test_pipeline_feedback.PipelineFeedbackTests.move)
    read = test_pipeline_feedback.PipelineFeedbackTests.read

    def state(self, state='blocked', cursor='test'):
        with self.repo.connect() as connection:
            connection.execute('UPDATE workflow_runs SET state=?,cursor_key=?,snapshot_json=? WHERE id=?',
                               (state, cursor, json.dumps(self.snapshot), self.identifier))

    def inspect(self):
        return chat._execute(self.core, self.turn, {'operation': 'inspect', 'workflow_id': self.identifier})

    def args(self, operation, **fields):
        return {'operation': operation, 'workflow_id': self.identifier, 'revision': self.inspect()['revision'],
                'intent': self.message['text'], **fields}

    def approval(self):
        self.snapshot['pipeline_waiting'] = {
            'kind': 'approval', 'position_key': 'approval', 'source_run_id': 5,
            'approval_request': {'options': [{'decision': 'approved', 'label': '通过验收'},
                                              {'decision': 'returned', 'label': '退回验收'}]},
        }
        self.state('needs_approval', 'approval')
        self.core._matching_edge = lambda graph, cursor, result: next(
            (edge for edge in graph['edges'] if edge['from'] == cursor and edge['when'] == result['status']), None)
        self.core._route_workflow = Mock()

    def queued(self):
        self.snapshot.pop('pipeline_waiting', None)
        self.snapshot['pipeline_visit'] = 1
        self.snapshot['pipeline_input']['parameters'] = {'region': '华东', 'setup': 'old'}
        self.snapshot['pipeline_work']['asset']['pipeline']['parameters'] = [
            {'key': 'region', 'type': 'select', 'source': 'user', 'options': ['华东', '华南']},
            {'key': 'setup', 'type': 'text', 'source': 'user', 'display': 'setup'},
            {'key': 'derived', 'type': 'text', 'source': 'employee'},
            {'key': 'password', 'type': 'secret', 'source': 'user'},
        ]
        self.state('ready')
        self.message['text'] = '暂缓原工作，目标改为核查第二批，地区改为华南，再继续。'

    def test_pause_edit_and_resume_keep_original_work_and_previous_inputs(self):
        self.queued()
        self.turn.active_ids = lambda: (self.identifier,)
        task_id = self.inspect()['task_id']
        self.assertIn('pause', self.inspect()['actions'])
        pause_args = self.args('pause')
        held = chat._execute(self.core, self.turn, pause_args)
        self.assertEqual(held['work']['state'], 'paused')
        self.assertEqual(chat._execute(self.core, self.turn, pause_args), held)
        self.assertEqual(self.inspect()['editable_input']['parameters'], {'region': '华东'})
        with patch.object(flow, 'payload_for', side_effect=lambda core, c, snapshot, role: snapshot['pipeline_input']):
            for updates in ({'derived': 'x'}, {'password':'x'}, {'setup':'x'}, {'region':'未知'}):
                with self.subTest(updates=updates), self.assertRaises(ContractError):
                    chat._execute(self.core, self.turn, self.args('edit_queued', parameters=updates))
            args = self.args('edit_queued', objective='核查第二批', parameters={'region': '华南'})
            edited = chat._execute(self.core, self.turn, args)
            self.assertEqual(chat._execute(self.core, self.turn, args), edited)
            with self.assertRaisesRegex(ContractError, '原结果'):
                chat._execute(self.core, self.turn, {**args, 'parameters': {'region': '华东'}})
        self.assertEqual(edited['work']['state'], 'paused')
        self.assertEqual(self.read()['snapshot']['initial_pipeline_input']['parameters']['region'], '华东')
        self.assertEqual(self.read()['snapshot']['pipeline_input']['parameters'], {'region':'华南', 'setup':'old'})
        self.wake.assert_not_called()
        with patch.dict('os.environ', {'RUNTEAMS_AUTOMATION_DISPATCH': '0'}):
            resumed = chat._execute(self.core, self.turn, self.args('resume'))
        self.wake.assert_called_once_with(self.identifier)
        self.assertEqual((resumed['work']['task_id'], resumed['work']['workflow_id'],
                          resumed['work']['visit'], resumed['work']['state']),
                         (task_id, self.identifier, held['work']['visit'], 'ready'))
        with self.repo.read_snapshot() as connection:
            events = connection.execute("SELECT data_json FROM events WHERE type='workflow.queued_input_edited'").fetchall()
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0][0])['parameters_before'], {'region': '华东'})

    def test_replace_only_selected_attachment_and_keep_original_snapshot(self):
        self.queued()
        task = self.inspect()['task_id']
        previous = {'kind': 'file', 'id': 'a'*24, 'name': 'old.txt',
                    'ref': f"device-input://{task}/{'a'*24}/{'b'*64}"}
        retained = {'kind': 'file', 'id': 'c'*24, 'name': 'keep.txt',
                    'ref': f"device-input://{task}/{'c'*24}/{'d'*64}"}
        granted = {'name': 'authorized folder', 'asset_grant_id': '27'}
        self.snapshot['pipeline_input']['inputs'] = [previous, retained, granted]
        self.state('ready')
        self.message['text'] = '暂缓后，把旧附件换成本轮新附件。'
        uploaded = {'kind':'file', 'id':'e'*24, 'name':'new.txt'}
        self.message['attachments'] = [uploaded]
        chat._execute(self.core, self.turn, self.args('pause'))
        editable = self.inspect()['editable_input']['attachments']
        self.assertEqual([item['id'] for item in editable], [previous['id'], retained['id']])
        self.assertTrue(all('ref' not in item for item in editable))
        new = {'kind':'file', 'id':'f'*24, 'name':'new.txt',
               'ref':f"device-input://{task}/{'f'*24}/{'e'*64}"}
        pair = {'input_id':previous['id'], 'attachment_id':uploaded['id']}
        with patch.object(flow, 'payload_for', side_effect=lambda core, c, snap, role: snap['pipeline_input']), \
                patch('runteams_core.work.task_inputs.copy_chat_attachment', return_value=new) as copy:
            for pairs, expected in (
                ([{**pair, 'attachment_id':'old-upload'}], PermissionError),
                ([{**pair, 'input_id':'foreign-input'}], ContractError),
                ([pair, {**pair, 'input_id':retained['id']}], ContractError),
            ):
                with self.subTest(pairs=pairs), self.assertRaises(expected):
                    chat._execute(self.core, self.turn, self.args('edit_queued', replace_attachments=pairs))
            stale = self.args('edit_queued', replace_attachments=[pair])
            late = {'kind':'file', 'id':'1'*24, 'name':'appended.txt',
                    'ref':f"device-input://{task}/{'1'*24}/{'2'*64}"}
            with self.repo.connect() as connection:
                connection.execute('UPDATE tasks SET payload_json=? WHERE id=?',
                                   (json.dumps({'inputs':[previous, retained, granted, late]}), task))
            with self.assertRaises(ContractError):
                chat._execute(self.core, self.turn, stale)
            copy.assert_not_called()
            args = self.args('edit_queued', replace_attachments=[pair])
            edited = chat._execute(self.core, self.turn, args)
            self.assertEqual(chat._execute(self.core, self.turn, args), edited)
            with self.assertRaisesRegex(ContractError, '原结果'):
                chat._execute(self.core, self.turn,
                              {**args, 'replace_attachments':[{**pair, 'input_id':retained['id']}]})
            copy.assert_called_once_with(self.core.root, task, self.turn.chat_id, uploaded,
                                         operation_id=self.turn.operation_id(self.identifier, 'edit_queued'))
        self.assertEqual(edited['work']['state'], 'paused')
        frozen = self.read()['snapshot']
        self.assertEqual(frozen['initial_pipeline_input']['inputs'], [previous, retained, granted])
        self.assertEqual(frozen['pipeline_input']['inputs'], [new, retained, granted, late])
        self.assertEqual(frozen['queued_pipeline_input']['inputs'], [new, retained, granted, late])
        with self.repo.read_snapshot() as connection:
            events = connection.execute(
                "SELECT data_json FROM events WHERE type='workflow.queued_input_edited'").fetchall()
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0][0])['attachment_replacements'], [{'before':previous, 'after':new}])
        resumed = chat._execute(self.core, self.turn, self.args('resume'))
        self.assertEqual((resumed['work']['workflow_id'], resumed['work']['task_id']), (self.identifier,task))

    def test_previously_delivered_work_can_hold_but_cannot_edit_the_original_inputs(self):
        self.queued()
        self.snapshot['pipeline_visit'] = 2
        self.state('ready')
        held = chat._execute(self.core, self.turn, self.args('pause'))
        self.assertEqual(held['work']['state'], 'paused')
        self.assertNotIn('edit_queued', self.inspect()['actions'])
        with self.assertRaises(ContractError):
            chat._execute(self.core, self.turn, self.args('edit_queued', parameters={'region': '华南'}))

    def test_previous_attempt_in_same_visit_prevents_an_edit(self):
        self.queued()
        chat._execute(self.core, self.turn, self.args('pause'))
        with self.repo.connect() as connection:
            connection.execute(
                "INSERT INTO employee_runs(workflow_run_id,position_key,employee_release_id,attempt,state,"
                "input_json,output_json,created_at,updated_at) VALUES (?,'test',NULL,1,'completed','{}','{}','','')",
                (self.identifier,))
        self.assertNotIn('edit_queued', self.inspect()['actions'])

    def test_claim_between_inspect_and_pause_cannot_change_running_work(self):
        self.queued()
        command = chat.cards.command

        def worker_claims(*args, **kwargs):
            self.state('running')
            return command(*args, **kwargs)

        args = self.args('pause')
        with patch.object(chat.cards, 'command', side_effect=worker_claims):
            with self.assertRaises(flow.WorkflowVisitChanged):
                chat._execute(self.core, self.turn, args)
        self.assertEqual(self.read()['state'], 'running')
        self.assertNotIn('pause', self.inspect()['actions'])
        self.assertNotIn('edit_queued', self.inspect()['actions'])

    def test_decision_waits_for_native_choice_then_commits_once(self):
        self.approval()
        args = self.args('decide', decision='returned')
        result = chat._execute(self.core, self.turn, args)
        self.assertEqual(result['receipt']['action'], 'decide')
        self.assertEqual(result['work']['position']['key'], 'test')
        prompt = self.confirm.call_args.args[0][0]
        self.assertIn('退回验收', prompt['question'])
        self.assertIn('验收岗', prompt['options'][0]['description'])
        self.assertEqual(chat._execute(self.core, self.turn, args), result)
        self.confirm.assert_called_once()
        self.core._route_workflow.assert_called_once()
        with self.assertRaisesRegex(ContractError, '原结果'):
            chat._execute(self.core, self.turn, {**args, 'decision': 'approved'})
        lookup = {'operation': 'receipt', 'workflow_id': self.identifier, 'action': 'decide'}
        self.assertEqual(chat._execute(self.core, self.turn, lookup), result)
        self.assertEqual(chat._execute(self.core, self.turn, {**lookup, 'action': 'retry'})['status'], 'unknown')
        self.assertEqual(chat._execute(self.core, self.turn, {**lookup, 'workflow_id': self.identifier + 1})['status'], 'unknown')

    def test_decline_or_wrong_action_does_not_move(self):
        self.approval()
        with self.assertRaises(ContractError):
            chat._execute(self.core, self.turn, self.args('decide', decision='invented'))
        self.confirm.assert_not_called()
        self.confirm.side_effect = None
        self.confirm.return_value = {'answers': {'pipeline-action': {'answers': ['取消']}}}
        result = chat._execute(self.core, self.turn, self.args('decide', decision='returned'))
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.read()['state'], 'needs_approval')
        self.wake.assert_not_called()

    def test_stale_native_confirmation_cannot_decide_new_visit(self):
        self.approval()
        args = self.args('decide', decision='returned')
        normal_answer = self.confirm.side_effect

        def changed(questions):
            self.snapshot['pipeline_visit'] = 5
            self.state('needs_approval', 'approval')
            return normal_answer(questions)

        self.confirm.side_effect = changed
        with self.assertRaises(flow.WorkflowVisitChanged):
            chat._execute(self.core, self.turn, args)
        self.core._route_workflow.assert_not_called()

    def test_attachment_scope_and_task_snapshot(self):
        from runteams_core.conversations import chat_attachments
        from runteams_core.work import task_inputs

        identifier = 'a' * 24
        item = {'id': identifier, 'name': 'evidence.txt', 'kind': 'file',
                'stored_name': f'{identifier}/original.txt'}
        self.message['attachments'] = [item]
        chat_dir = self.core.root / 'chat'
        source = chat_dir / item['stored_name']
        source.parent.mkdir(parents=True)
        source.write_bytes(b'raw accepted evidence')
        with patch.object(chat_attachments, '_chat_dir', return_value=chat_dir), \
                patch.object(chat_attachments, '_storage'), \
                patch.object(task_inputs, '_device_storage', return_value=self.repo.storage):
            with self.assertRaises(PermissionError):
                chat._execute(self.core, self.turn, self.args('respond', attachment_ids=['wrong-id']))
            result = chat._execute(self.core, self.turn, self.args('respond', attachment_ids=[identifier]))
            self.assertEqual(result['work']['visit'], 5)
            inputs = self.read()['snapshot']['pipeline_input']['inputs']
            source.unlink()
            resolved = task_inputs.source_for_item(self.core.root, result['work']['task_id'], inputs[0])
            self.assertEqual(resolved.read_bytes(), b'raw accepted evidence')
            self.assertNotEqual(resolved, source)
        self.confirm.assert_not_called()

    def test_upload_tree_refuses_links_and_mismatched_replay(self):
        from runteams_core.conversations import chat_attachments
        from runteams_core.work import task_inputs

        identifier = 'b' * 24
        item = {'id': identifier, 'name': 'evidence.txt', 'kind': 'file',
                'stored_name': f'{identifier}/original.txt'}
        chat_dir = self.core.root / 'chat'
        source = chat_dir / item['stored_name']
        source.parent.mkdir(parents=True)
        source.write_bytes(b'evidence')
        forbidden = self.core.root / 'outside'
        forbidden.write_bytes(b'external secret')
        link = source.parent / 'attack.txt'
        link.symlink_to(forbidden)
        task_id = self.inspect()['task_id']
        operation = self.turn.operation_id(self.identifier, 'respond')
        with patch.object(chat_attachments, '_chat_dir', return_value=chat_dir), \
                patch.object(chat_attachments, '_storage'), \
                patch.object(task_inputs, '_device_storage', return_value=self.repo.storage):
            with self.assertRaisesRegex(ContractError, '符号链接'):
                task_inputs.copy_chat_attachment(self.core.root, task_id, 99, item, operation_id=operation)
            link.unlink()
            first = task_inputs.copy_chat_attachment(self.core.root, task_id, 99, item, operation_id=operation)
            self.assertEqual(task_inputs.copy_chat_attachment(self.core.root, task_id, 99, item,
                                                              operation_id=operation), first)
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ContractError, '内容校验失败'):
                task_inputs.copy_chat_attachment(self.core.root, task_id, 99, item, operation_id=operation)
