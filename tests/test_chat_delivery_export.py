import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from runteams_core.application.http import local_document_http
from runteams_core.application.local_work_core import LocalWorkCore
from runteams_core.configuration.chat_setup import SetupTurn
from runteams_core.employees import employee_chat_work
from runteams_core.employees.employee_work_contracts import SCHEMA
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import chat_delivery_export as export
from runteams_core.storage import device_data
from runteams_core.work import work_reports


class SubmittedDeliveryExportTest(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.scope = {'storage_kind': 'local', 'library_id': 'test', 'storage_namespace': 'test'}
        self.employee = {'schema': 'employee', 'id': 'owned'}
        self.turn = SetupTurn(10, 15, 'epoch', self.scope, 'employee', self.employee, None)
        self.enterContext(patch.object(device_data, 'root', return_value=Path(directory)))
        self.enterContext(patch.object(device_data, 'identity', return_value=self.scope))
        self.enterContext(patch.object(device_data, 'epoch', return_value='epoch'))
        self.enterContext(patch('runteams_core.employees.employee_references.same', side_effect=lambda a, b: a == b))
        self.enterContext(patch('runteams_core.configuration.chat_setup._current_message', return_value='打包交付'))
        self.enterContext(patch('runteams_core.configuration.chat_setup._binding',
                                return_value=('employee', self.employee)))
        self.core = LocalWorkCore()

    def work(self, employee, title):
        with self.core.repository.connect() as conn:
            now = '2026-01-01T00:00:00+00:00'
            task = conn.execute(
                "INSERT INTO tasks(employee_reference,title,payload_json,state,created_at,updated_at) "
                "VALUES(?,?,'{}','running',?,?)", (json.dumps(employee), title, now, now)).lastrowid
            workflow = conn.execute(
                "INSERT INTO workflow_runs(task_id,state,snapshot_json,created_at,updated_at) "
                "VALUES(?,'running','{}',?,?)", (task, now, now)).lastrowid
            attempt = conn.execute(
                "INSERT INTO employee_runs(workflow_run_id,position_key,attempt,state,input_json,output_json,created_at,updated_at) "
                "VALUES(?,'employee',1,'running','{}','{}',?,?)", (workflow, now, now)).lastrowid
            frozen = {'schema': SCHEMA, 'employee_reference': employee, 'work_chat_id': 90, 'employee_run_id': attempt}
            conn.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (json.dumps(frozen), workflow))
        return workflow

    def test_local_route_exports_frozen_work_and_reports_missing_files(self):
        work_id = self.work(self.employee, 'Original assignment')
        foreign = self.work({'schema': 'employee', 'id': 'other'}, 'Foreign assignment')
        empty = self.work(self.employee, 'Unsubmitted assignment')
        binding = {'schema': work_reports.SCHEMA, 'employee_reference': self.employee,
                   'workflow_id': work_id, 'chat_id': 90, 'message_id': 1}
        saved = work_reports._operate(self.core, {'operation': 'write', 'title': 'Formal report',
            'content': 'Submitted body', 'base_revision': 0}, binding)
        self.assertEqual(employee_chat_work.finish(self.core, work_id, 'completed'), 'completed')
        work_reports._operate(self.core, {'operation': 'write', 'report_id': saved['report_id'],
            'content': 'Later body', 'base_revision': 1}, binding)
        self.assertEqual(employee_chat_work.finish(self.core, work_id, 'completed'), 'completed')
        self.core.create_agent_document('Personal note', 'Personal body')

        matches = export._execute(self.core, self.turn, {'operation': 'list', 'query': 'assignment'})
        self.assertEqual({row['workflow_id'] for row in matches['workflows']}, {work_id, empty})
        with self.assertRaises(PermissionError):
            export._execute(self.core, self.turn, {'operation': 'export', 'workflow_ids': [work_id, foreign]})
        with self.assertRaises(ContractError):
            export._execute(self.core, self.turn, {'operation': 'export'})
        arguments = {'operation': 'export', 'workflow_ids': [work_id, empty]}
        result = export._execute(self.core, self.turn, arguments)
        self.assertEqual(result, export._execute(self.core, self.turn, arguments))
        url = result['download_link']
        self.assertTrue(local_document_http.handles(url))
        first = local_document_http.dispatch(self.core, 'GET', url, {})
        second = local_document_http.dispatch(self.core, 'GET', url, {})
        self.assertEqual(first.mime, 'application/zip')
        self.assertEqual(first.payload, second.payload)
        with ZipFile(BytesIO(first.payload)) as archive:
            manifest = json.loads(archive.read('交付清单.json'))
            report = next(row for row in manifest['workflows'] if row['workflow_id'] == work_id)
            omitted = next(row for row in manifest['workflows'] if row['workflow_id'] == empty)
            self.assertEqual(report['files'][0]['revision'], 1)
            self.assertIn(b'Submitted body', archive.read(report['files'][0]['path']))
            contents = b'\n'.join(archive.read(name) for name in archive.namelist())
            self.assertNotIn(b'Later body', contents)
            self.assertNotIn(b'Personal body', contents)
            self.assertTrue(omitted['missing'])
        with self.assertRaises(PermissionError):
            local_document_http.dispatch(self.core, 'GET', url.replace('/chats/10/', '/chats/11/'), {})
