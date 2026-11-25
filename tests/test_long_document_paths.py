"""Document bodies and attachments survive Windows-length library paths."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from runteams_core.application.local_application import LocalApplication
from runteams_core.documents import rich_document_assets, rich_documents
from runteams_core.documents.document_export import export_document
from runteams_core.foundation.regular_files import storage_path


class LongDocumentPathTests(unittest.TestCase):
    def test_delete_and_restore_document_with_attachment(self):
        temporary = self.enterContext(TemporaryDirectory())
        library = Path(temporary) / ('资料库 ' + 'ab' * 25)
        self.addCleanup(shutil.rmtree, storage_path(library))
        subprocess.run([sys.executable, '-B', '-c',
            'import runpy, sys; runpy.run_path(sys.argv[1])["LongDocumentPathTests"]("round_trip").debug()',
            __file__], check=True, timeout=120,
            env={**os.environ, 'RUNTEAMS_DATA': str(library), 'RUNTEAMS_AUTOMATION_DISPATCH': '0'})

    def round_trip(self):
        library = Path(os.environ['RUNTEAMS_DATA'])
        app = LocalApplication(library)
        self.addCleanup(app.close)
        body = rich_documents.from_markdown('长路径正文')
        file = {'name': '离线样例.txt', 'type': 'text/plain', 'data': 'data:text/plain;base64,QUJD'}
        with app.runtime.scope():
            core = app.runtime.work_core()
            doc = rich_documents.write(core, name='正文', document_key='document-' + 'a' * 96, document=body)
            identifier = doc['id']
            asset = rich_document_assets.upload(core, identifier, file)
            body['blocks'].append({'id': 'attachment', 'type': 'file', 'props': {'assetId': asset['id']}, 'children': []})
            doc = rich_documents.write(core, name='正文', document_id=identifier, base_revision=1, document=body)
            actual = core.document_detail(doc['id'])
            original, _, _ = export_document(core, actual)
            self.assertEqual(json.loads(original)['assets'][asset['id']], file)
        backup_id = str(uuid4())
        app.backups.create(app, backup_id)
        archive = app.backups.download(backup_id)
        with archive.open('rb') as stream:
            uploaded = app.backups.upload(stream, archive.stat().st_size, str(uuid4()))
        with app.runtime.scope():
            core.trash_document(identifier)
            core.delete_trashed_document(identifier)
            artifacts = storage_path(core.root) / 'artifacts'
            self.assertFalse(any(path.is_file() for path in artifacts.rglob('*')))
        app.backups.restore(app, str(uuid4()), uploaded['import_id'])
        app.close()
        reopened = LocalApplication(library)
        self.addCleanup(reopened.close)
        with reopened.runtime.scope():
            core = reopened.runtime.work_core()
            restored, _, _ = export_document(core, core.document_detail(doc['id']))
            self.assertEqual(json.loads(restored), json.loads(original))
