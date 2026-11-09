import unittest
from threading import Thread
from types import SimpleNamespace

from runteams_core.pipelines import pipeline_execution_activity as activity


class PipelineExecutionActivityTests(unittest.TestCase):
    def setUp(self):
        self.core = SimpleNamespace(repository=SimpleNamespace(path='/fixture/library'))
        self.frozen = {'pipeline_work': {'position_key': 'review'}, 'employee_run_id': 2, 'work_chat_id': 3}

    def test_observations_are_bounded_scoped_and_cleared_at_turn_end(self):
        with activity.capture(self.core, 1, self.frozen):
            turn = activity.current_turn(3)
            self.assertIsNone(activity.current_turn(4))
            turn.record({'kind': 'work_delta', 'id': 'note', 'delta': 'Checked '})
            turn.record({'kind': 'work_delta', 'id': 'note', 'delta': 'the requirements.'})
            turn.record({'kind': 'reasoning_delta', 'delta': 'private reasoning'})
            turn.record({'kind': 'step', 'id': 's', 'step_kind': 'command', 'status': 'running',
                         'label': 'secret command', 'output': 'private output'})
            turn.record({'kind': 'step', 'id': 's', 'step_kind': 'command', 'status': 'completed'})
            value = activity.read(self.core, 1, 2, 3)
            self.assertEqual(value['notes'], ['Checked the requirements.'])
            self.assertEqual(value['steps'], [{'kind': 'command', 'status': 'completed'}])
            self.assertIsNone(activity.read(self.core, 1, 4, 3))
            other = SimpleNamespace(repository=SimpleNamespace(path='/fixture/other-library'))
            self.assertIsNone(activity.read(other, 1, 2, 3))
            for i in range(12):
                turn.record({'kind': 'work_delta', 'id': str(i), 'delta': 'x' * 700})
            self.assertEqual(activity.read(self.core, 1, 2, 3)['notes'], ['x' * 600] * 8)
        self.assertIsNone(activity.current_turn(3))
        self.assertIsNone(activity.read(self.core, 1, 2, 3))

    def test_observer_updates_during_the_same_message_and_ends_with_the_run(self):
        received = []
        with activity.capture(self.core, 1, self.frozen):
            turn = activity.current_turn(3)
            events = activity.observe(self.core, 1, 2, 3).events()
            self.assertEqual(next(events), {'type': 'work_activity', 'activity': None})
            turn.record({'kind': 'work_delta', 'id': 'note', 'delta': 'Checked '})
            self.assertEqual(next(events)['activity']['notes'], ['Checked'])
            self.assertEqual(list(activity.observe(self.core, 1, 4, 3).events()), [])
            other = SimpleNamespace(repository=SimpleNamespace(path='/fixture/other-library'))
            self.assertEqual(list(activity.observe(other, 1, 2, 3).events()), [])

            reader = Thread(target=lambda: received.append(next(events, None)), daemon=True)
            reader.start()
            turn.record({'kind': 'work_delta', 'id': 'note', 'delta': 'the requirements.'})
            reader.join(1)
            self.assertFalse(reader.is_alive())
            self.assertEqual(received[0]['activity']['notes'], ['Checked the requirements.'])
        self.assertEqual(list(events), [])

    def test_answers_and_approvals_clear_without_exposing_answer_or_parameters(self):
        pending = True
        with activity.capture(self.core, 1, self.frozen):
            turn = activity.current_turn(3)
            turn.record({'kind': 'user_input', 'request': {'id': 'request', 'questions': [
                {'question': 'Private prompt', 'isSecret': True}]}})
            turn.record({'kind': 'employee_mcp_approval', 'params': {'secret': 'private'}}, lambda: pending)
            self.assertEqual(activity.read(self.core, 1, 2, 3),
                             {'notes': [], 'steps': [], 'questions': [''], 'approval_pending': True})
            turn.record({'kind': 'user_input_resolved', 'id': 'request', 'answers': 'private'})
            pending = False
            self.assertIsNone(activity.read(self.core, 1, 2, 3))
