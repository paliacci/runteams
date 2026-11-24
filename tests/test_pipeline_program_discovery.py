import unittest
from unittest.mock import Mock, patch

from runteams_core.employees.mcp.device_employee_mcp import EmployeeMCPWork
from runteams_core.pipelines import device_pipeline_mcp as pipelines


class PipelineDiscoveryTests(unittest.TestCase):
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
