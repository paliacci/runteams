"""Folder placement survives revisions and upgrades of an existing local library."""
from io import BytesIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from runteams_core.documents import document_folders, rich_documents
from runteams_core.documents.document_export import export_documents
from runteams_core.documents.local_documents import LocalDocuments
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data
from runteams_core.work import device_work


class DocumentFolderTests(unittest.TestCase):
    def test_upgrade_move_and_revision(self):
        scope = {'storage_kind': 'local', 'library_id': 'test', 'storage_namespace': 'test'}
        with TemporaryDirectory() as directory, \
                patch.object(device_data, 'root', return_value=Path(directory)), \
                patch.object(device_data, 'identity', return_value=scope), \
                patch.object(device_data, 'personal', return_value=True):
            core = LocalDocuments()
            document = rich_documents.write(core, name='Notes', document_key='notes',
                                            document=rich_documents.from_markdown('Original'))
            with sqlite3.connect(core.repository.path) as connection:
                for kind, name in reversed(device_work.DOCUMENT_FOLDER_STRUCTURE):
                    connection.execute(f'DROP {kind} {name}')
                connection.execute('PRAGMA user_version=5')
            core = LocalDocuments()
            self.assertEqual(self.ids(core, ''), [document['id']])

            parent, child = str(uuid4()), str(uuid4())
            document_folders.mutate(core, {'action': 'create', 'folder': parent, 'parent': '', 'name': 'Project'})
            document_folders.mutate(core, {'action': 'create', 'folder': child, 'parent': parent, 'name': 'Notes'})
            document_folders.mutate(core, {'action': 'move_document', 'document': document['id'], 'folder': child})
            revision = rich_documents.write(core, name='Notes', document_id=document['id'], base_revision=1,
                                            document=rich_documents.from_markdown('Revised'))
            self.assertEqual(self.ids(core, child), [revision['id']])
            self.assertEqual(self.ids(core, ''), [])
            self.assertEqual(self.ids(core, '', query='Revised'), [revision['id']])
            with self.assertRaises(ContractError):
                document_folders.mutate(core, {'action': 'delete', 'folder': child})

            document_folders.mutate(core, {'action': 'move_document', 'document': revision['id'], 'folder': ''})
            document_folders.mutate(core, {'action': 'delete', 'folder': child})
            self.assertEqual(self.ids(core, ''), [revision['id']])
            self.assertTrue(document_folders.page(core, child)['folder_missing'])

    def ids(self, core, folder, **options):
        return [document['id'] for document in document_folders.page(core, folder, **options)['documents']]

    def test_batch_move_rolls_back_and_export_preserves_duplicate_names(self):
        scope = {'storage_kind': 'local', 'library_id': 'test', 'storage_namespace': 'test'}
        with TemporaryDirectory() as directory, \
                patch.object(device_data, 'root', return_value=Path(directory)), \
                patch.object(device_data, 'identity', return_value=scope), \
                patch.object(device_data, 'personal', return_value=True):
            core = LocalDocuments()
            documents = [rich_documents.write(core, name='Notes', document_key=f'notes-{index}',
                         document=rich_documents.from_markdown(text))['id']
                         for index, text in enumerate(('First', 'Second'))]
            folder = str(uuid4())
            document_folders.mutate(core, {'action': 'create', 'folder': folder, 'parent': '', 'name': 'Project'})
            move = {'action': 'move_documents', 'folder': folder, 'documents': [*documents, 1]}
            with self.assertRaises(ContractError):
                document_folders.mutate(core, move)
            self.assertEqual(self.ids(core, folder), [])
            self.assertCountEqual(self.ids(core, ''), documents)
            document_folders.mutate(core, {**move, 'documents': documents})
            self.assertCountEqual(self.ids(core, folder), documents)

            content, _, mime = export_documents(core, ','.join(map(str, documents)))
            self.assertEqual(mime, 'application/zip')
            with ZipFile(BytesIO(content)) as archive:
                self.assertEqual(archive.namelist(), ['Notes.json', 'Notes (2).json'])
                self.assertIn(b'First', archive.read('Notes.json'))
                self.assertIn(b'Second', archive.read('Notes (2).json'))
