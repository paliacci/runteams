"""Task reports have one durable identity and preserve stage report history."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runteams_core.documents import rich_document_assets, rich_documents
from runteams_core.documents.document_export import export_document
from runteams_core.documents.document_service import Documents
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_task_report, source_pipeline_flow
from runteams_core.storage import device_data
from runteams_core.storage.repository import Repository
from runteams_core.work import device_work


class PipelineTaskReportTests(unittest.TestCase):
    def test_failed_completion_projection_keeps_accepted_work(self):
        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE saved(kind TEXT)')
            connection.execute("INSERT INTO saved VALUES('accepted result')")
            def project(*args, **kwargs):
                connection.execute("INSERT INTO saved VALUES('incomplete report')")
                raise ContractError('Saved delivery file is unavailable')
            def event(stream, kind, payload, *, connection):
                connection.execute('INSERT INTO saved VALUES(?)', (kind,))
            core = SimpleNamespace(repository=SimpleNamespace(event=event))
            with patch.object(pipeline_task_report, 'sync', side_effect=project):
                pipeline_task_report.save_completion(core, connection, 1)
            self.assertEqual(connection.execute('SELECT kind FROM saved').fetchall(),
                             [('accepted result',), ('workflow.report_unavailable',)])

    def test_followup_distinguishes_zero_from_a_missing_metric(self):
        update = {'observed_at': '2026-11-20T15:00:00Z', 'source_url': 'https://example.com/post',
                  'content': 'Public observation', 'metrics': {'comments': 0, 'views': None}}
        document = pipeline_task_report.add_followup({'blocks': []}, update, {})
        text = document['blocks'][0]['props']['text']
        self.assertIn('comments · 0', text)
        self.assertIn('views · —', text)

    def test_forwarding_a_report_keeps_the_original_producers_exact_version(self):
        from runteams_core.pipelines.pipeline_task_delivery import _report
        pin = {'report_id': 20, 'artifact_id': 21, 'revision': 2, 'sha256': 'expected'}
        published = {**pin, 'id': 20}
        other = {**published, 'id': 31, 'artifact_id': 31}
        runs = [(10, {'output': {'receipt': pin}, 'report_references': [published]}),
                (11, {'output': {'receipt': pin}, 'report_references': [other]})]
        self.assertEqual(_report({'output': 'receipt'}, runs), (10, published))
        runs[-1][1]['output']['receipt'] = {**pin, 'sha256': 'changed'}
        self.assertIsNone(_report({'output': 'receipt'}, runs))

    def test_completed_delivery_uses_one_document_with_exact_accepted_content(self):
        png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jkf8AAAAASUVORK5CYII='
        reference = {'local_test': 'pipeline'}
        scope = {'storage_kind': 'local', 'library_id': 'test', 'storage_namespace': 'test'}
        policy = {'parameter': 'goal', 'goals': {'package': ['cover']},
                  'sections': {'cover': {'title': '头图', 'output': 'cover.report'}}}
        for existing in (False, True):
            with self.subTest(existing=existing), TemporaryDirectory() as directory, \
                    patch.object(device_data, 'root', return_value=Path(directory)), \
                    patch.object(device_data, 'identity', return_value=scope), \
                    patch.object(device_data, 'personal', return_value=True), \
                    patch.object(pipeline_task_report.pipeline_references, 'checked_reference', side_effect=lambda value: value):
                storage = device_work.DeviceWorkStorage()
                core = Documents()
                core.root = Path(directory) / 'work'
                core.repository = Repository(storage.path, storage=storage)
                frozen = {'employee_reference': {}, 'pipeline_work': {'reference': reference, 'asset': {'pipeline': {
                    'positions': [{'key': 'design', 'name': '设计'}], 'delivery': policy}}},
                    'pipeline_input': {'parameters': {'goal': 'package'}}}
                timestamp = '2026-11-06T06:00:00+00:00'
                with core.repository.connect() as connection:
                    task = connection.execute('INSERT INTO tasks(employee_reference,title,payload_json,state,created_at,updated_at) '
                        "VALUES('{}','最终交付','{}','ready',?,?)", (timestamp, timestamp)).lastrowid
                    workflow = connection.execute('INSERT INTO workflow_runs(task_id,state,cursor_key,snapshot_json,created_at,updated_at) '
                        "VALUES(?,'ready','design',?,?,?)", (task, json.dumps(frozen), timestamp, timestamp)).lastrowid
                original = pipeline_task_report.open_report(core, reference, workflow) if existing else None
                stage = core.create_agent_document('阶段汇报', '验收稿')
                attachment = {'name': 'cover.png', 'type': 'image/png', 'data': png}
                png_id = rich_document_assets.upload(core, stage['id'], attachment)['id']
                doc = rich_documents.from_markdown('验收稿。 [退修单](runteams://document/123)')
                doc['blocks'].append({'id': 'image', 'type': 'image', 'props': {'assetId': png_id}, 'children': []})
                accepted = rich_documents.write(core, name=stage['name'], document=doc,
                    document_id=stage['id'], base_revision=stage['revision'], author='agent')
                with core.repository.connect() as connection:
                    for attempt in (1, 2):
                        run = connection.execute('INSERT INTO employee_runs(workflow_run_id,position_key,attempt,state,input_json,'
                            "output_json,created_at,updated_at) VALUES(?,'design',?,'completed','{}','{}',?,?)",
                            (workflow, attempt, timestamp, timestamp)).lastrowid
                    meta = json.loads(connection.execute('SELECT meta_json FROM artifacts WHERE id=?', (accepted['id'],)).fetchone()[0])
                    meta['work_report'] = {'workflow_id': workflow, 'employee_run_id': run}
                    connection.execute('UPDATE artifacts SET meta_json=? WHERE id=?', (json.dumps(meta), accepted['id']))
                    ref = {'report_id': stage['id'], 'artifact_id': accepted['id'],
                           'revision': accepted['revision'], 'sha256': meta['sha256']}
                    output = {'output': {'cover': {'report': ref}}, 'report_references': [{**ref, 'id': stage['id']}]}
                    connection.execute('UPDATE employee_runs SET output_json=? WHERE id=?', (json.dumps(output), run))
                    frozen['pipeline_lineage'] = [run]
                    row = source_pipeline_flow._row(connection, workflow)
                    source_pipeline_flow._save(core, connection, row, frozen, 'completed')
                persisted = pipeline_task_report.final_delivery_reference(core, {'task_id': task, 'task': {'title': '最终交付'}})
                self.assertIsNotNone(persisted)
                materialized = core.document_detail(persisted['id'], refresh_task_report=False)
                self.assertIn('验收稿', materialized['content'])
                receipt = pipeline_task_report.open_report(core, reference, workflow)
                self.assertEqual(receipt['revision'], materialized['revision'])
                self.assertEqual(pipeline_task_report.open_report(core, reference, workflow), receipt)
                self.assertEqual(pipeline_task_report.final_delivery_reference(core, {'task_id': task, 'task': {'title': '最终交付'}}),
                                 {'id': receipt['document_id'], 'name': '最终交付'})
                if original:
                    self.assertEqual(receipt['document_id'], original['document_id'])
                final = core.document_detail(receipt['document_id'])
                self.assertFalse(final['editable'])
                data, name, _ = export_document(core, final)
                exported = json.loads(data)
                self.assertEqual(name, '最终交付.json')
                self.assertIn('验收稿', data.decode())
                self.assertNotIn('runteams://document/123', data.decode())
                self.assertEqual(list(exported['assets'].values()), [attachment])
                self.assertNotIn(png_id, exported['assets'])

                # A team without a declared delivery layout uses the same root and pinned file.
                del frozen['pipeline_work']['asset']['pipeline']['delivery']
                with core.repository.connect() as connection:
                    connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (json.dumps(frozen), workflow))
                merged = pipeline_task_report.open_report(core, reference, workflow)
                self.assertEqual(merged['document_id'], receipt['document_id'])
                self.assertGreater(merged['revision'], receipt['revision'])
                structured = core.document_detail(merged['document_id'])
                data, _, _ = export_document(core, structured)
                self.assertIn('验收稿', data.decode())
                self.assertEqual(list(json.loads(data)['assets'].values()), [attachment])
                self.assertEqual(merged, pipeline_task_report.open_report(core, reference, workflow))

    def test_repeat_open_revision_and_cleanup(self):
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
        reference = {'local_test': 'pipeline'}
        frozen = {'pipeline_work': {'reference': reference, 'asset': {'pipeline': {
            'positions': [{'key': 'reviewer', 'name': '审查员'}]}}},
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
        self.assertIn('Ready' if english else '等待开始', body)
        self.assertIn('审查交付物', body)
        self.assertIn('审查员', body)
        self.assertEqual(report['name'], '验证任务')
        self.assertNotIn(f'runteams://document/{stage}', body)
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
