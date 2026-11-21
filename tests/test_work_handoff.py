from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from runteams_core.foundation.contracts import ContractError
from runteams_core.work.work_reports import _operate, _output_bytes


class WorkHandoffTests(unittest.TestCase):
    def test_author_workspace_routes_only_bound_delivery_to_current_work(self):
        from runteams_core.documents.native_document_tools import dispatch
        from runteams_core.agents.tools.agent_tool_registry import AgentToolError
        session = {'kind':'employee_design', 'context':{'creator_employee_source':'employees/one.json'}}
        context = {'chat_id':123}
        values = {'operation':'create', 'name':'任务清单', 'content':'- [ ] 修正链接'}
        with patch('runteams_core.storage.device_data.enabled',return_value=True), \
                patch('runteams_core.storage.device_data.personal',return_value=True), \
                patch('runteams_core.storage.product_store.device_chat',return_value=True), \
                patch('runteams_core.storage.product_store.get_chat',return_value=session), \
                patch('runteams_core.agents.tools.agent_tool_registry._work_report') as save:
            dispatch('runteams_propose_document',values,context)
            save.assert_called_once_with({'operation':'write','base_revision':0,'title':'任务清单','content':values['content']},context)
            with self.assertRaises(AgentToolError):
                dispatch('runteams_propose_document',{**values,'document_id':9},context)
            session['context'].clear()
            with self.assertRaises(AgentToolError):
                dispatch('runteams_propose_document',values,context)
            self.assertEqual(save.call_count,1)

    def test_import_is_readable_and_retries_keep_the_original_document(self):
        from runteams_core.documents.document_service import Documents
        from runteams_core.storage import device_data
        from runteams_core.storage.repository import Repository
        from runteams_core.work.device_work import DeviceWorkStorage
        scope = {'storage_kind':'local','library_id':'test','storage_namespace':'test'}
        with TemporaryDirectory() as directory, patch.object(device_data,'root',return_value=Path(directory)), \
                patch.object(device_data,'identity',return_value=scope), patch.object(device_data,'personal',return_value=True):
            storage = DeviceWorkStorage()
            core = Documents()
            core.root = Path(directory)/'work'
            core.repository = Repository(storage.path,storage=storage)
            root = Path(directory)
            (root/'output').mkdir()
            (root/'output/check.md').write_text('# 执行清单\n\n完整内容')
            binding = {'schema':'runteams.work-report/v1','workflow_id':7}
            args = {'operation':'write','path':'output/check.md','base_revision':0,'title':'交接'}
            first = _operate(core,args,binding,output_directory=root)
            repeat = _operate(core,args,binding,output_directory=root)
            self.assertEqual(first['report_id'],repeat['report_id'])
            read = _operate(core,{'operation':'read','report_id':first['report_id']},binding)
            self.assertEqual(read['document']['content'],'# 执行清单\n\n完整内容')
            self.assertEqual(read['document']['revision'],1)

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
