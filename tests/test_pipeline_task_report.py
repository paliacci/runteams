"""Task reports have one durable identity and preserve stage report history."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from runteams_core.documents import rich_documents
from runteams_core.documents.document_service import Documents
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_task_report
from runteams_core.storage import device_data
from runteams_core.storage.repository import Repository
from runteams_core.work import device_work


class PipelineTaskReportTests(unittest.TestCase):
    def test_upgrade_repeat_open_revision_and_cleanup(self):
        self.check_report_language(False)

    def test_english_report_preserves_asset_names_and_original_objective(self):
        self.check_report_language(True)

    def check_report_language(self, english):
        with TemporaryDirectory() as directory:
            scope = {'storage_kind': 'local', 'library_id': 'test', 'storage_namespace': 'test'}
            root = Path(directory)
            with patch.object(device_data, 'root', return_value=root), \
                    patch.object(device_data, 'identity', return_value=scope), \
                    patch.object(device_data, 'personal', return_value=True):
                self.verify_report(root, english)

    def verify_report(self, root, english):
        storage = device_work.DeviceWorkStorage()
        storage.initialize()
        core = Documents()
        core.root = root / 'work'
        core.repository = Repository(storage.path, storage=storage)
        with sqlite3.connect(storage.path) as connection:
            for kind, name in device_work.TASK_REPORT_STRUCTURE:
                connection.execute(f'DROP {kind} {name}')
            connection.execute(f'PRAGMA user_version={device_work.PREVIOUS_VERSION}')

        reference = {'local_test': 'pipeline'}
        frozen = {'pipeline_work': {'reference': reference, 'asset': {'pipeline': {
            'positions': [{'key': 'reviewer', 'name': '审查员'}], 'states': []}}},
            'pipeline_input': {'objective': '审查交付物'}}
        if english:
            frozen['language_policy'] = {'communication_language': 'en'}
        timestamp = '2026-11-06T06:00:00+00:00'
        with core.repository.connect() as connection:
            task = connection.execute('INSERT INTO tasks(employee_id,title,payload_json,state,created_at,updated_at) '
                "VALUES(1,'验证任务','{}','ready',?,?)", (timestamp, timestamp)).lastrowid
            workflow = connection.execute('INSERT INTO workflow_runs(task_id,state,cursor_key,snapshot_json,created_at,updated_at) '
                "VALUES(?,'ready','reviewer',?,?,?)", (task, json.dumps(frozen), timestamp, timestamp)).lastrowid
            stage = connection.execute('INSERT INTO artifacts(name,ref,meta_json,created_at) VALUES(?,?,?,?)',
                ('审查记录', 'fixture.md', json.dumps({'work_report': {'schema': 'runteams.work-report/v1',
                 'workflow_id': workflow}, 'purpose': 'document'}), timestamp)).lastrowid

        with patch.object(pipeline_task_report.pipeline_references, 'checked_reference', side_effect=lambda value: value):
            with ThreadPoolExecutor(max_workers=3) as pool:
                receipts = list(pool.map(lambda _: pipeline_task_report.open_report(core, reference, workflow), range(3)))
            report_id = receipts[0]['document_id']
            self.assertTrue(all(receipt == {'document_id': report_id, 'revision': 1} for receipt in receipts))
            with self.assertRaises(PermissionError):
                pipeline_task_report.open_report(core, {'different': True}, workflow)

        report = core.document_detail(report_id)
        self.assertFalse(report['editable'])
        self.assertEqual(report['source'], rich_documents.TASK_REPORT_SOURCE)
        body = json.loads(report['content'])['blocks'][0]['props']['text']
        self.assertIn('Task created' if english else '创建任务', body)
        self.assertIn('审查交付物', body)
        self.assertIn('审查员', body)
        self.assertIn('Task report' if english else '任务汇报', report['name'])
        self.assertIn(f'runteams://document/{stage}', body)
        with self.assertRaises(ContractError):
            rich_documents.write(core, name='覆盖', document=rich_documents.from_markdown('覆盖'),
                                 document_id=report_id, base_revision=1)
        with self.assertRaises(ContractError):
            core.trash_document(report_id)

        with core.repository.connect() as connection:
            marker = {'task_id': task, 'workflow_id': workflow}
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO artifacts(id,name,ref,meta_json,created_at) VALUES(?,?,?,?,?)',
                    (report_id + 1, '重复汇报', 'duplicate.json', json.dumps({'source': rich_documents.TASK_REPORT_SOURCE,
                      'pipeline_task_report': marker, 'revision_of': report_id + 1}), timestamp))
            connection.execute("UPDATE workflow_runs SET state='completed' WHERE id=?", (workflow,))
        revised = core.document_detail(report_id)
        self.assertEqual((revised['document_root_id'], revised['revision']), (report_id, 2))
        self.assertIn('Completed' if english else '已完成', revised['content'])
        self.assertEqual(core.document_detail(report_id)['revision'], 2)
        self.assertIn('Ready' if english else '等待开始', core.historical_document_detail(report_id)['content'])
        with core.repository.connect() as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], device_work.VERSION)
            connection.execute('DELETE FROM workflow_runs WHERE id=?', (workflow,))
            connection.execute('DELETE FROM tasks WHERE id=?', (task,))
            self.assertFalse(connection.execute('SELECT 1 FROM artifacts WHERE id IN (?,?)',
                                                (report_id, revised['id'])).fetchone())
            self.assertTrue(connection.execute('SELECT 1 FROM artifacts WHERE id=?', (stage,)).fetchone())


if __name__ == '__main__':
    unittest.main()
