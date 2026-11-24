"""Chat automation commands share scope, revisions and receipts with device settings."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from runteams_core.automation import chat_automations, device_employee_schedules
from runteams_core.automation.portable_automations import source_reference
from runteams_core.automation.source_pipeline_schedules import PipelineSchedules
from runteams_core.storage import local_database, storage_context
from runteams_core.storage.local_library import LocalLibrary

PARAMETER_SCHEMA = {
    'type': 'object',
    'properties': {'topic': {'type': 'string'}, 'limit': {'type': 'integer'}},
    'required': ['topic', 'limit'],
    'additionalProperties': False,
}


class ChatAutomationTest(unittest.TestCase):
    def test_commands_use_durable_receipts_and_preserve_saved_payload(self):
        for kind in ('employee', 'pipeline'):
            with self.subTest(kind=kind), TemporaryDirectory() as folder, \
                    patch.object(local_database, 'DB_PATH', str(Path(folder) / 'local.db')), \
                    storage_context.using(LocalLibrary()), \
                    patch.object(device_employee_schedules, 'employee') as employee, \
                    patch('runteams_core.employees.source_employee_runtime._extension',
                          return_value={'work': {'input_schema': PARAMETER_SCHEMA}}):
                reference = source_reference('a' * 64, kind, 'asset.json')
                elsewhere = source_reference('b' * 64, kind, 'asset.json')
                employee.side_effect = lambda identifier, ref: {'active_release': {'digest': 'sha'},
                    'native_asset': {'employee_reference': ref},
                    'runtime_source': {'asset': {'skill_bundles': [{'package_key': 'review'}]}}}
                controller = lambda: SimpleNamespace(core=None)
                if kind == 'employee':
                    backend = device_employee_schedules.EmployeeSchedules(controller)
                    backend.admitted = Mock(return_value=None)
                    choices = {'skill_key': 'review', 'parameters': {'topic': 'Weekly notes', 'limit': 4}}
                else:
                    backend = PipelineSchedules(controller)
                    backend._receipt = Mock(return_value=None)
                    backend.contract = Mock(return_value={'input_schema': PARAMETER_SCHEMA,
                        'position_key': 'summarize', 'position_name': 'Summarize'})
                    choices = {'start_column_key': 'summarize', 'parameters': {'topic': 'Weekly notes', 'limit': 4}}
                host = SimpleNamespace(backend=lambda name: backend, start=Mock())

                def execute(turn, operation, arguments, ref=reference):
                    return chat_automations.execute(host, kind=kind, reference=ref, turn_key=turn,
                                                    operation=operation, arguments=arguments)

                def saved_record():
                    with backend.connection() as connection:
                        row = connection.execute('SELECT * FROM schedules WHERE id=?', (identifier,)).fetchone()
                        return backend.record(connection, row)

                create = {'value': {'name': 'Weekly review', 'objective': 'Summarize the notes.',
                    'enabled': True, 'schedule_kind': 'weekly', 'interval_sec': 3600,
                    'schedule': {'time': '8:00', 'weekdays': [3, 1], 'timezone': 'Asia/Shanghai'}, **choices}}
                first = execute('user-1', 'create', create)
                identifier = first['id']
                self.assertEqual(execute('user-1', 'create', create), first)
                before = saved_record()
                target = {'id': identifier, 'expected_revision': before['revision']}
                reschedule = {**target, 'schedule_kind': 'daily', 'interval_sec': 3600,
                              'schedule': {'time': '11:30', 'timezone': 'Asia/Shanghai'}}
                with self.assertRaisesRegex(ValueError, '已变化'):
                    execute('spoof', 'reschedule', reschedule, elsewhere)
                result = execute('user-2', 'reschedule', reschedule)
                self.assertEqual(execute('user-2', 'reschedule', reschedule), result)
                updated = saved_record()
                for key in ('name', 'payload', 'reference', 'release_digest', 'enabled'):
                    self.assertEqual(updated[key], before[key])
                self.assertEqual(updated['revision'], before['revision'] + 1)
                self.assertEqual(updated['schedule']['time'], '11:30')
                with self.assertRaisesRegex(ValueError, '已变化'):
                    execute('stale', 'pause', target)
                target['expected_revision'] = updated['revision']
                execute('user-3', 'pause', target)
                self.assertFalse(saved_record()['enabled'])
                target['expected_revision'] += 1
                execute('user-4', 'resume', target)
                self.assertTrue(saved_record()['enabled'])
                target['expected_revision'] += 1
                with patch('runteams_core.automation.source_pipeline_schedules.control.read',
                           return_value={'status': 'running'}):
                    first = execute('user-5', 'run', target)
                    self.assertEqual(execute('user-5', 'run', target), first)
                with backend.connection(write=True) as connection:
                    connection.execute("UPDATE occurrences SET status='completed' WHERE schedule_id=?", (identifier,))
                before_edit = saved_record()
                with self.assertRaisesRegex(ValueError, '不符合'):
                    execute('bad-type', 'edit', {**target, 'changes': {'parameters': {'limit': 'one'}}})
                self.assertEqual(saved_record(), before_edit)
                if kind == 'pipeline':
                    self.assertEqual(execute('inputs', 'start_input', {'start_column_key': 'summarize'}),
                                     backend.contract.return_value)
                edit = {**target, 'changes': {'objective': 'Use the updated notes.', 'parameters': {'topic': 'New'}}}
                with self.assertRaisesRegex(ValueError, '已变化'):
                    execute('other-asset', 'edit', edit, elsewhere)
                first_edit = execute('edit', 'edit', edit)
                self.assertEqual(execute('edit', 'edit', edit), first_edit)
                with self.assertRaises(ValueError):
                    execute('edit', 'edit', {**edit, 'changes': {'name': 'A different name'}})
                with self.assertRaisesRegex(ValueError, '已变化'):
                    execute('stale-edit', 'edit', edit)
                after_edit = saved_record()
                self.assertEqual(after_edit['payload'], {**before_edit['payload'],
                    'objective': 'Use the updated notes.', 'parameters': {'topic': 'New', 'limit': 4}})
                self.assertEqual({k: v for k, v in after_edit.items() if k not in ('payload', 'revision')},
                                 {k: v for k, v in before_edit.items() if k not in ('payload', 'revision')})
                target['expected_revision'] += 1
                with patch('runteams_core.automation.source_pipeline_schedules.control.read',
                           return_value={'status': 'running'}):
                    execute('run-edit', 'run', target)
                self.assertEqual(len(saved_record()['runs']), 2)
                with backend.connection() as connection:
                    snapshots = connection.execute(
                        'SELECT snapshot FROM occurrences WHERE schedule_id=? ORDER BY id', (identifier,)).fetchall()
                for snapshot, expected in zip(snapshots, (before_edit, after_edit), strict=True):
                    payload = json.loads(snapshot[0])['payload']
                    if kind == 'employee':
                        payload = json.loads(payload)
                    self.assertEqual(payload['parameters'], expected['payload']['parameters'])
                    self.assertEqual(payload['objective'], expected['payload']['objective'])
                first = execute('user-6', 'delete', target)
                self.assertEqual(execute('user-6', 'delete', target), first)
                with backend.connection() as connection:
                    self.assertEqual(connection.execute('SELECT deleted FROM schedules').fetchone()[0], 1)
                host.start.assert_called_with(kind)
