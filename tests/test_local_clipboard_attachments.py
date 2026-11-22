"""Clipboard folders follow the native picker snapshot and reference rules."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from runteams_core.application.local_application import LocalApplication
from runteams_core.conversations import chat_attachments
from runteams_core.storage import local_database


class LocalClipboardAttachmentsTests(unittest.TestCase):
    def test_local_routes_stage_only_native_folder_selections(self):
        with ExitStack() as stack:
            root = Path(stack.enter_context(TemporaryDirectory()))
            library = root / 'library'
            stack.enter_context(patch.object(local_database, 'DB_PATH', str(library / 'runteams.db')))
            app = LocalApplication(library)
            stack.callback(app.close)
            folder = root / '项目.txt'
            folder.mkdir()
            (folder / '说明.txt').write_text('folder content', encoding='utf-8')
            (folder / '.env').write_text('excluded', encoding='utf-8')
            file = root / '补充.txt'
            file.write_text('separate file', encoding='utf-8')

            with patch.object(chat_attachments, 'native_picker_path', return_value=''):
                self.assertEqual(app.dispatch('POST', '/api/attachments/paste', {}), {'items': []})
            with patch.object(chat_attachments, 'native_picker_path', return_value='/picker'), \
                 patch.object(chat_attachments, 'native_reference_paths', return_value=[str(file)]) as read:
                with self.assertRaisesRegex(ValueError, '附件粘贴请求无效'):
                    app.dispatch('POST', '/api/attachments/paste', {'paths': [str(folder)]})
                read.assert_not_called()
                self.assertEqual(app.dispatch('POST', '/api/attachments/paste', {}), {'items': []})
                read.return_value = [str(folder), str(file)]
                items = app.dispatch('POST', '/api/attachments/paste', {})['items']
                self.assertEqual([(item['kind'], item['name'], item['file_count']) for item in items],
                                 [('folder', folder.name, 1), ('file', file.name, 1)])
                self.assertTrue(all('path' not in item for item in items))
                snapshot = Path(chat_attachments._SELECTIONS[items[0]['token']]['path'])
                self.assertEqual((snapshot / '说明.txt').read_text(), 'folder content')
                self.assertFalse((snapshot / '.env').exists())
                for action in ('paste', 'drop'):
                    read.return_value = [str(folder)]
                    result = app.dispatch('POST', '/api/local-references/' + action, {})
                    read.assert_called_with(action)
                    self.assertEqual(result['pending'][0]['path'], str(folder.resolve()))
