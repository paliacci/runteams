import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from runteams_core.employees.mcp.device_employee_mcp import EmployeeMCPWork
from runteams_core.foundation.regular_files import storage_path
from runteams_core.pipelines import device_pipeline_mcp as pipelines


class PipelineDiscoveryTests(unittest.TestCase):
    def test_deep_library_can_open_and_find_the_same_program_workspace(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, storage_path(folder))
        host = object.__new__(pipelines.PipelineMCPWork)
        # Cross MAX_PATH while keeping each component within 255 UTF-8 bytes.
        directories = [('中文资料库' * 13), ('团队资料' * 17)] * 2
        host.root = folder.joinpath(*directories)
        host.check = Mock()
        host.core_factory = Mock()
        reference = {'source_id': 'a' * 64, 'pipeline_source': 'pipelines/main.json'}
        bundle = {'asset': {'programs': []}, 'revision': reference['source_id'], 'generation': 1}
        self.enterContext(patch.object(pipelines.pipeline_chat_binding, 'reference', return_value=reference))
        self.enterContext(patch.object(pipelines.control, 'read', return_value={'bundle': bundle}))
        self.enterContext(patch.object(pipelines, '_applied_catalog', return_value={}))
        self.enterContext(patch.object(pipelines.device_data, 'epoch', return_value='chat-epoch'))

        own, _, base = host.load(37)
        record = {key: own[key] for key in ('reference', 'revision', 'generation', 'release_digest')}
        record['schema'] = 'runteams.pipeline-mcp-work/1'
        (base / '.runteams' / pipelines.FILE).write_text(json.dumps(record), encoding='utf-8')
        self.assertEqual(host.close_directories(37), [base])
        self.assertEqual(host.load(37)[2], base)

    def test_only_an_applied_team_without_programs_skips_package_inspection(self):
        host = object.__new__(pipelines.PipelineMCPWork)
        host.core_factory = Mock()
        with patch.object(pipelines.pipeline_chat_binding, 'reference', return_value={'source_id': 'team'}) as owner, \
                patch.object(pipelines.control, 'read') as ledger, \
                patch.object(EmployeeMCPWork, 'discover_for_chat', return_value={'items': ['verified']}) as discover:
            ledger.return_value = {'bundle': {'asset': {'programs': []}}}
            self.assertEqual(host.discover_for_chat(37), {'items': [], 'authority': 'device-owned-mcp-work', 'chat_id': 37})
            owner.assert_called_once_with(37)
            host.core_factory.return_value._actor.assert_called_once()
            ledger.assert_called_once_with(host.core_factory.return_value, owner.return_value)
            discover.assert_not_called()
            for bundle in (None, {'asset': {'programs': [{'key': 'app'}]}}):
                ledger.return_value = {'bundle': bundle}
                self.assertEqual(host.discover_for_chat(37), discover.return_value)
            self.assertEqual(discover.call_count, 2)
