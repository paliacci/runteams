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

    def test_tools_inventory_checks_connection_on_cache_hit_and_refreshes_all_lists(self):
        with tempfile.TemporaryDirectory() as profile:
            channel = {"id": 2, "enabled": True, "provider": "codex", "config_dir": profile}
            ready = {"status": "ready", "installed": True, "authenticated": True}
            with patch.object(capabilities.model_channels, "resolve_channel_executable", return_value=sys.executable), \
                 patch.object(capabilities.model_channels, "probe", return_value=ready) as probe, \
                 patch.object(capabilities, "_read_plugin_json") as plugins, \
                 patch.object(capabilities, "_run_json") as mcp, \
                 patch.object(capabilities, "_skills") as skills:
                for version in ("first", "second"):
                    plugins.return_value = ({"installed": [{"id": version}]}, None)
                    mcp.return_value = ([{"name": version}], None)
                    skills.return_value = [{"id": version}]
                    result = capabilities.environment_summary(
                        [channel], refresh=version == "second", tools_only=True)
                    for section, field in (("plugins", "id"), ("mcp_servers", "name"), ("skills", "id")):
                        self.assertEqual([row[field] for row in result[section]], [version])
                    self.assertEqual(mcp.call_args.args[0][1:], ["mcp", "list", "--json"])
                self.assertEqual(mcp.call_count, 2)
                probe.return_value = {**ready, "authenticated": False, "status": "login_required"}
                denied = capabilities.environment_summary([channel], tools_only=True)
                self.assertEqual(denied["counts"]["ready_channels"], 0)
                for section in ("plugins", "mcp_servers", "skills"):
                    self.assertEqual(denied[section], [])
                probe.assert_called_with(channel, account_summary=False)
                self.assertEqual(plugins.call_count, 2)
            capabilities.invalidate_channel(channel)

    def test_tools_rechecks_a_disappearing_market_and_accepts_confirmed_removal(self):
        prior = {"plugins": [{"marketplace": "remote"}]}
        local = {"installed": [], "_marketplaces": ["local"]}
        complete = {"installed": [{"id": "p"}], "_marketplaces": ["local", "remote"]}
        for confirmation, expected in ((local, local), (complete, complete),
                                       ({"installed": []}, {"installed": [], "_read_state": "partial"})):
            with self.subTest(confirmation=confirmation), patch.object(
                    capabilities, "_read_plugin_json", side_effect=[(local, None), (confirmation, None)]) as read:
                data, _ = capabilities._read_tools_plugin_json({}, "codex", {}, 15, None, False, prior)
                self.assertEqual(data, expected)
                self.assertEqual([call.kwargs["force_refetch"] for call in read.call_args_list], [False, True])

    def test_tools_manual_refresh_accepts_uninstall_in_reported_market(self):
        data = {"installed": [], "_marketplaces": ["remote"]}
        with patch.object(capabilities, "_read_plugin_json", return_value=(data, None)) as read:
            found, _ = capabilities._read_tools_plugin_json(
                {}, "codex", {}, 15, None, True, {"plugins": [{"marketplace": "remote"}]})
            self.assertEqual(found, data)
            read.assert_called_once_with({}, "codex", {}, 15, None, force_refetch=True)
