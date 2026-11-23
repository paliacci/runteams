"""Portable automation stays versioned and only enters schedules by opt-in."""
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from runteams_core.automation import automation_template_contract as template_contract
from runteams_core.automation import device_employee_schedules, portable_automations as templates
from runteams_core.automation.source_pipeline_schedules import PipelineSchedules
from runteams_core.authoring.creator_contracts import canonical, compile_source, strict_json
from runteams_core.authoring.creator_definitions import compile_definitions
from runteams_core.authoring.source import creator_source_archive, selected_asset
from runteams_core.storage import local_database, storage_context
from runteams_core.storage.local_library import LocalLibrary
from test_employee_starter_limits import project


def save(backend, reference, value):
    return backend.command({'operation_id': str(uuid.uuid4()), 'action': 'save', 'reference': reference,
                            'id': None, 'expected_revision': None, 'value': value})


def instruction(**values):
    return {'name': 'Daily review', 'objective': 'Summarize new work.', 'enabled': True,
            'schedule_kind': 'weekly', 'interval_sec': 3600,
            'schedule': {'time': '08:00', 'weekdays': [3, 1], 'timezone': 'Asia/Shanghai'}, **values}


class PortableTemplatesTest(unittest.TestCase):
    def test_selected_release_contains_only_its_owner_templates(self):
        files = project([])
        manifest = strict_json(files['project.json'])
        manifest['entrypoints']['employees'].append('other.json')
        files['project.json'] = canonical(manifest)
        files['other.json'] = canonical({**strict_json(files['employee.json']), 'key': 'other'})
        value = {key: item for key, item in instruction(schedule_kind='interval',
                schedule={'timezone': 'UTC'}).items() if key != 'enabled'}
        first = {**value, 'id': str(uuid.uuid4()), 'skill_key': 'project'}
        second = {**value, 'id': str(uuid.uuid4()), 'name': 'Other plan'}
        files = template_contract.put(template_contract.put(files, 'employee.json', [first]), 'other.json', [second])
        selected = selected_asset.selected_source(files, 'employee', 'employee.json')
        round_trip = creator_source_archive.inspect(creator_source_archive.pack(selected))
        self.assertEqual(template_contract.index(round_trip), {'employee.json': [first]})
        assets = compile_definitions(round_trip, compile_source(round_trip))['employees']
        self.assertEqual(assets['employee.json'][template_contract.FIELD], [first])
        self.assertNotIn('other.json', assets)
        with self.assertRaisesRegex(ValueError, '未提供的技能'):
            invalid = template_contract.put(selected, 'employee.json', [{**first, 'skill_key': 'unlisted'}])
            compile_definitions(invalid, compile_source(invalid))
        with self.assertRaisesRegex(ValueError, '凭据与本机路径'):
            template_contract.put(files, 'employee.json', [{**first, 'objective': 'Read /Users/alex/report.txt.'}])
        for change in ({'parameters': {'password': 'redacted'}}, {'enabled': True}, {'runs': []}):
            with self.assertRaises(ValueError):
                template_contract.put(files, 'employee.json', [{**first, **change}])

    def test_real_employee_store_retries_without_enabling_or_copying_history(self):
        with TemporaryDirectory() as folder, patch.object(local_database, 'DB_PATH', str(Path(folder) / 'local.db')), \
                storage_context.using(LocalLibrary()), patch.object(device_employee_schedules, 'employee') as employee:
            author = templates.source_reference('a' * 64, 'employee', 'employee.json')
            recipient = templates.source_reference('b' * 64, 'employee', 'employee.json')
            backend = device_employee_schedules.EmployeeSchedules(lambda: None)
            host = SimpleNamespace(backend=lambda kind: backend)
            employee.side_effect = lambda identifier, ref: {'active_release': {'digest': 'sha'},
                'native_asset': {'employee_reference': ref}, 'runtime_source': {'skills': []}}
            plan = save(backend, author, instruction())
            with backend.connection(write=True) as connection:
                row = connection.execute('SELECT * FROM schedules WHERE id=?', (plan['id'],)).fetchone()
                backend.fire(connection, row, 'manual:test')
            selected = templates.export_selected(host, author, [plan['id']])
            self.assertEqual(selected, templates.export_selected(host, author, [plan['id']]))
            self.assertEqual(set(selected[0]), {'id', 'name', 'objective', 'schedule_kind', 'interval_sec', 'schedule'})
            self.assertEqual(selected[0]['schedule']['weekdays'], [1, 3])
            identifier = selected[0]['id']
            self.assertEqual(templates.imported_ids(host, recipient, selected), [])
            first = templates.import_selected(host, recipient, selected, [identifier])
            self.assertEqual(templates.import_selected(host, recipient, selected, [identifier]), first)
            self.assertEqual(templates.imported_ids(host, recipient, selected), [identifier])
            with backend.connection() as connection:
                row = connection.execute('SELECT * FROM schedules WHERE id=?', (first[0]['id'],)).fetchone()
                result = backend.record(connection, row)
            self.assertFalse(result['enabled'])
            self.assertEqual(result['next_run_at'], '')
            self.assertEqual(result['runs'], [])
            self.assertEqual(result['reference'], recipient)
            self.assertEqual(result['payload']['objective'], selected[0]['objective'])

    def test_team_import_requires_recipient_inputs_and_keeps_start_column(self):
        with TemporaryDirectory() as folder, patch.object(local_database, 'DB_PATH', str(Path(folder) / 'local.db')), \
                storage_context.using(LocalLibrary()):
            author = templates.source_reference('a' * 64, 'pipeline', 'team.json')
            recipient = templates.source_reference('b' * 64, 'pipeline', 'team.json')
            backend = PipelineSchedules(lambda: SimpleNamespace(core=None))
            host = SimpleNamespace(backend=lambda kind: backend)
            contract = {'input_schema': {'type': 'object', 'required': ['subject'],
                                         'properties': {'subject': {'type': 'string'}}}}
            with patch.object(backend, 'contract', return_value=contract) as check:
                saved = save(backend, author, instruction(start_column_key='summarize',
                             parameters={'subject': "private author's topic"}))
                chosen = templates.export_selected(host, author, [saved['id']])
                identifier = chosen[0]['id']
                self.assertNotIn('parameters', chosen[0])
                with self.assertRaisesRegex(ValueError, '工作输入不符合'):
                    templates.import_selected(host, recipient, chosen, [identifier])
                self.assertEqual(templates.imported_ids(host, recipient, chosen), [])
                result = templates.import_selected(host, recipient, chosen, [identifier],
                    parameters={identifier: {'subject': 'recipient topic'}})
                check.assert_called_with(recipient, 'summarize')
            with backend.connection() as connection:
                row = connection.execute('SELECT * FROM schedules WHERE id=?', (result[0]['id'],)).fetchone()
                row = backend.record(connection, row)
            self.assertFalse(row['enabled'])
            self.assertEqual(row['reference'], recipient)
            self.assertEqual(row['payload']['parameters'], {'subject': 'recipient topic'})
            self.assertEqual(row['payload']['start_column_key'], 'summarize')
