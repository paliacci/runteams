import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from runteams_core.application.http.local_document_http import dispatch
from runteams_core.documents import rich_documents
from runteams_core.foundation.contracts import ContractError
from runteams_core.work.work_reports import _operate, _output_bytes


class WorkHandoffTests(unittest.TestCase):
    def test_saved_download_keeps_markdown_and_original_export(self):
        from unittest.mock import Mock
        core = Mock()
        text = '# 审核\n\n- [ ] 修复 [定价页](https://example.com/pricing)\n'
        core.document_detail.return_value = dict(id=1, name='检查.md', content_model='rich-document',
                                                content=rich_documents.encode(rich_documents.from_markdown(text)))
        path = '/api/device/work/documents/1/download'
        file = dispatch(core, 'GET', path, {'format': 'markdown'})
        self.assertEqual((file.filename, file.payload), ('检查.md', text.encode()))
        self.assertTrue(dispatch(core, 'GET', path, {}).mime.startswith('application/json'))
        core.document_detail.return_value = None
        self.assertEqual(dispatch(core, 'GET', path, {'format':'markdown'}).status, 404)

    def test_download_keeps_nested_evidence_links_and_media(self):
        from unittest.mock import Mock
        core = Mock()
        doc = rich_documents.from_markdown('# 成果')
        asset = 'a' * 64
        doc['blocks'][0]['children'] = [
            {'id':'one','type':'paragraph','content':[{'type':'link','href':'https://example.com','content':[{'text':'依据'}]}]},
            {'id':'two','type':'jsonData','props':{'source':'receipt','title':'复核'}},
            {'id':'three','type':'image','props':{'assetId':asset,'name':'proof.png','mime':'image/png'}}]
        doc['sources']['receipt'] = {'label':'检查','data':{'observed':0,'unknown':None}}
        core.document_detail.return_value = dict(id=1,name='内容/检查',content_model='rich-document',content=rich_documents.encode(doc))
        with patch('runteams_core.documents.rich_document_assets.read', return_value={'data':'data:image/png;base64,'+base64.b64encode(b'image').decode()}):
            file = dispatch(core, 'GET', '/api/device/work/documents/1/download', {'format':'markdown'})
        self.assertEqual(file.filename, '内容_检查.zip')
        with ZipFile(BytesIO(file.payload)) as z:
            body = z.read('内容_检查.md').decode()
            self.assertIn('[依据](<https://example.com>)', body)
            self.assertIn('"unknown": null', body)
            relative = 'assets/'+asset+'/proof.png'
            self.assertIn(relative, body)
            self.assertEqual(z.read(relative), b'image')

    def test_import_checks_work_folder_scope_and_input(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'output').mkdir()
            (root/'output/check.md').write_text('result')
            (root/'outside.md').write_text('other')
            (root/'output/link.md').symlink_to(root/'outside.md')
            (root/'output/sub').symlink_to(root,target_is_directory=True)
            self.assertEqual(_output_bytes(root, 'output/check.md', 6)[1], b'result')
            for path in ('output/../outside.md', 'outside.md', 'output/link.md', 'output/sub/outside.md'):
                with self.subTest(path=path), self.assertRaises(ContractError):
                    _output_bytes(root, path, 100)
            with self.assertRaises(ContractError):
                _output_bytes(root, 'output/check.md', 5)
            args = {'operation':'write','path':'output/check.md','title':'检查','base_revision':0}
            with self.assertRaises(ContractError):
                _operate(None,args,{})
            with self.assertRaises(ContractError):
                _operate(None,{**args,'content':'different'},{},output_directory=root)
