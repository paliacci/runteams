import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runteams_core.agents import runtime_capabilities as capabilities


class CapabilityMenuTests(unittest.TestCase):
    def test_menu_reads_only_its_directory_and_ranks_before_paging(self):
        with tempfile.TemporaryDirectory() as profile:
            channel = {"id": 2, "enabled": True, "provider": "codex", "config_dir": profile}
            directory = {
                "installed": [{"id": "writer", "name": "Writer", "description": "PDF export", "enabled": True}],
                "available": [
                    {"id": "000", "name": "000 Tools"}, {"id": "reader", "name": "Reader PDF"},
                    {"id": "pdf-tools", "name": "PDF Tools"}, {"id": "pdf", "name": "PDF"},
                ],
            }
            with patch.object(capabilities.model_channels, "resolve_channel_executable", return_value=sys.executable), \
                 patch.object(capabilities.model_channels, "probe", return_value={
                     "status": "ready", "authenticated": True, "installed": True}), \
                 patch.object(capabilities, "_read_plugin_json", return_value=(
                     directory, subprocess.CompletedProcess([], 0))) as read, \
                 patch.object(capabilities, "_run_json", side_effect=AssertionError("unrelated CLI read")):
                first = capabilities.capability_page(channel, limit=1)
                self.assertEqual(first["items"][0]["id"], "writer")
                second = capabilities.capability_page(channel, after=first["next_cursor"], limit=1)
                self.assertEqual(second["items"][0]["id"], "pdf")
                results = capabilities.capability_page(channel, query="pdf")["items"]
                self.assertEqual([row["id"] for row in results], ["pdf", "pdf-tools", "reader", "writer"])
                self.assertEqual(read.call_count, 1)
            capabilities.invalidate_channel(channel)
