# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from adapter_codex import CodexAdapter
from adapter_base import EXECUTION_INTERNAL_ANALYSIS
import runtime_capabilities
import plugin_brands


class RuntimeCapabilityTests(unittest.TestCase):
    def setUp(self):
        runtime_capabilities._CACHE.clear()
        runtime_capabilities._PLUGIN_DEPENDENCIES.clear()
        runtime_capabilities._PLUGIN_ICONS.clear()
        runtime_capabilities._PLUGIN_RESOURCES.clear()
        self.channel = {"id": 7, "provider": "codex", "name": "Codex", "enabled": 1,
                        "config_dir": "", "executable": ""}

    def inventory(self):
        plugin_data = {"installed": [
            {"pluginId": "github@official", "name": "github", "version": "1.2.3",
             "installed": True, "enabled": True}],
            "available": [{"pluginId": "figma@official", "name": "figma", "installed": False}]}
        mcp_data = [{"name": "github", "enabled": True,
                     "transport": {"type": "streamable_http"}, "auth_status": "authenticated"}]
        doctor_data = {"checks": {"sandbox.helpers": {"status": "ok", "summary": "sandbox ready"}}}

        def cli(argv, _env, _timeout=12):
            if "plugin" in argv:
                return plugin_data, None
            if "mcp" in argv:
                return mcp_data, None
            return doctor_data, None

        with mock.patch.object(runtime_capabilities.model_channels, "resolve_channel_executable", return_value=sys.executable), \
                mock.patch.object(runtime_capabilities.model_channels, "probe", return_value={
                    "installed": True, "authenticated": True, "status": "ready",
                    "version": "codex-test", "executable": sys.executable}), \
                mock.patch.object(runtime_capabilities, "_run_json", side_effect=cli):
            return runtime_capabilities.inventory(self.channel, refresh=True)

    def test_codex_inventory_is_normalized_and_redacted(self):
        found = self.inventory()
        self.assertEqual(found["status"], "ready")
        self.assertEqual(found["plugins"][0]["id"], "github@official")
        self.assertEqual(found["mcp_servers"][0]["name"], "github")
        self.assertEqual(found["diagnostics"][0]["id"], "sandbox.helpers")
        self.assertNotIn("details", found["diagnostics"][0])

    def test_employee_plugin_dependency_has_content_fingerprint_and_private_runtime(self):
        with tempfile.TemporaryDirectory(prefix="runteams-plugin-") as root:
            marketplace = os.path.join(root, "marketplace")
            source = os.path.join(marketplace, "plugins", "figma")
            os.makedirs(source)
            with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("first")
            plugin_data = {"installed": [{
                "pluginId": "figma@official", "name": "figma", "version": "1.2.3",
                "installed": True, "enabled": True,
                "source": {"path": source},
                "marketplaceName": "official",
                "marketplaceSource": {"source": marketplace},
            }]}
            with mock.patch.object(runtime_capabilities.model_channels,
                                   "resolve_channel_executable", return_value="/tmp/codex"), \
                    mock.patch.object(runtime_capabilities, "_run_json",
                                      return_value=(plugin_data, None)):
                first = runtime_capabilities.plugin_dependency(
                    self.channel, "figma@official", refresh=True)
                with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as handle:
                    handle.write("second")
                second = runtime_capabilities.plugin_dependency(
                    self.channel, "figma@official", refresh=True)
        self.assertEqual(first["plugin_id"], "figma@official")
        self.assertEqual(first["runtime"]["marketplace_root"], marketplace)
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_install_plugin_uses_discovered_id_and_controlled_argv(self):
        available = {"id": "figma@official", "name": "figma", "installed": False}
        installed = dict(available, installed=True, enabled=True)
        inventories = [
            {"plugins": [], "available_plugins": [available]},
            {"plugins": [installed], "available_plugins": []},
        ]
        completed = subprocess.CompletedProcess([], 0, stdout="installed", stderr="")
        with mock.patch.object(runtime_capabilities, "inventory", side_effect=inventories), \
                mock.patch.object(runtime_capabilities.model_channels, "resolve_channel_executable",
                                  return_value="/tmp/codex"), \
                mock.patch.object(runtime_capabilities.model_channels, "_probe_env", return_value={}), \
                mock.patch.object(runtime_capabilities.model_channels, "_run",
                                  return_value=completed) as run:
            result = runtime_capabilities.install_plugin(self.channel, "figma")
        self.assertEqual(result["plugin"]["id"], "figma@official")
        self.assertFalse(result["already_installed"])
        run.assert_called_once_with(
            ["/tmp/codex", "plugin", "add", "figma@official"], {}, timeout=180)

    def test_install_plugin_rejects_items_missing_from_provider_catalog(self):
        with mock.patch.object(runtime_capabilities, "inventory", return_value={
                "plugins": [], "available_plugins": []}):
            with self.assertRaisesRegex(ValueError, "找不到"):
                runtime_capabilities.install_plugin(self.channel, "unknown@untrusted")

    def test_claude_official_catalog_is_discoverable_before_marketplace_setup(self):
        with tempfile.TemporaryDirectory(prefix="runteams-claude-catalog-") as root:
            cache = os.path.join(root, "plugins", "plugin-catalog-cache.json")
            os.makedirs(os.path.dirname(cache))
            with open(cache, "w", encoding="utf-8") as handle:
                json.dump({"catalog": {"plugins": {
                    "figma@claude-plugins-official": {
                        "plugin": "figma", "version": "2.2.95", "unique_installs": 172661,
                        "source": "figma@claude-plugins-official",
                        "components": {"skills": [{"name": "figma-use"}],
                                       "mcpServers": ["figma"]},
                        "marketplace_entry": {
                            "name": "Figma", "description": "Use Figma from Claude Code",
                            "category": "design", "homepage": "https://example.com/figma",
                            "author": {"name": "Figma"},
                        },
                    },
                }}}, handle)
            channel = dict(self.channel, provider="claude-code", config_dir=root)

            def cli(argv, _env, _timeout, _cwd=None):
                if "plugin" in argv:
                    return {"installed": [], "available": []}, None
                return [], None

            with mock.patch.object(runtime_capabilities.model_channels,
                                   "resolve_channel_executable", return_value="/tmp/claude"), \
                    mock.patch.object(runtime_capabilities.model_channels, "probe", return_value={
                        "installed": True, "authenticated": True, "status": "ready",
                        "version": "claude-test", "executable": "/tmp/claude"}), \
                    mock.patch.object(runtime_capabilities, "_run_json", side_effect=cli):
                found = runtime_capabilities.inventory(channel, refresh=True)

        self.assertEqual(len(found["available_plugins"]), 1)
        plugin = found["available_plugins"][0]
        self.assertEqual(plugin["id"], "figma@claude-plugins-official")
        self.assertEqual(plugin["marketplace"], "claude-plugins-official")
        self.assertEqual(plugin["description"], "Use Figma from Claude Code")
        self.assertEqual(plugin["developer_name"], "Figma")
        self.assertEqual(plugin["components"], ["skills", "mcpServers"])
        self.assertNotIn(root, str(plugin))

    def test_claude_install_initializes_official_marketplace_then_installs(self):
        channel = dict(self.channel, provider="claude-code")
        available = {"id": "figma@claude-plugins-official", "name": "figma",
                     "marketplace": "claude-plugins-official", "installed": False}
        installed = dict(available, installed=True, enabled=True)
        inventories = [
            {"plugins": [], "available_plugins": [available]},
            {"plugins": [installed], "available_plugins": []},
        ]
        completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
        with mock.patch.object(runtime_capabilities, "inventory", side_effect=inventories), \
                mock.patch.object(runtime_capabilities, "_run_json", return_value=([], None)), \
                mock.patch.object(runtime_capabilities.model_channels,
                                  "resolve_channel_executable", return_value="/tmp/claude"), \
                mock.patch.object(runtime_capabilities.model_channels, "_probe_env", return_value={}), \
                mock.patch.object(runtime_capabilities.model_channels, "_run",
                                  return_value=completed) as run:
            result = runtime_capabilities.install_plugin(channel, "figma")

        self.assertFalse(result["already_installed"])
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ["/tmp/claude", "plugin", "marketplace", "add", "anthropics/claude-plugins-official"],
            ["/tmp/claude", "plugin", "install", "figma@claude-plugins-official"],
        ])

    def test_skills_are_discovered_with_plugin_and_personal_ownership(self):
        with tempfile.TemporaryDirectory(prefix="runteams-skills-") as root:
            plugin = os.path.join(root, "plugin")
            personal = os.path.join(root, "channel")
            os.makedirs(os.path.join(plugin, "skills", "review"))
            os.makedirs(os.path.join(plugin, ".codex-plugin"))
            os.makedirs(os.path.join(personal, "skills", "research"))
            with open(os.path.join(plugin, ".codex-plugin", "plugin.json"), "w", encoding="utf-8") as handle:
                handle.write('{"name":"quality","description":"Safer reviews",'
                             '"interface":{"displayName":"Quality Review","category":"Developer Tools"}}')
            with open(os.path.join(plugin, "skills", "review", "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: Review code\ndescription: Review changes safely.\n---\n")
            with open(os.path.join(personal, "skills", "research", "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: Research\ndescription: Find primary sources.\n---\n")
            channel = dict(self.channel, config_dir=personal)
            data = {"installed": [{"pluginId": "quality@official", "name": "quality",
                                     "installed": True, "enabled": True,
                                     "source": {"path": plugin}}]}
            found = runtime_capabilities._skills(channel, data)
            plugins, _ = runtime_capabilities._plugins(data)
        self.assertEqual({item["scope"] for item in found}, {"plugin", "personal"})
        bundled = next(item for item in found if item["scope"] == "plugin")
        self.assertEqual(bundled["plugin_id"], "quality@official")
        self.assertEqual(bundled["manage_mode"], "plugin")
        self.assertNotIn(root, str(bundled))
        self.assertEqual(plugins[0]["display_name"], "Quality Review")
        self.assertEqual(plugins[0]["description"], "Safer reviews")

    def test_personal_skill_icon_uses_safe_local_asset_reference(self):
        with tempfile.TemporaryDirectory(prefix="runteams-skill-icon-") as root:
            skill = os.path.join(root, "skills", "research")
            os.makedirs(skill)
            with open(os.path.join(skill, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: Research\nicon: icon.png\n---\n")
            with open(os.path.join(skill, "icon.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\nmock")
            found = runtime_capabilities._scan_skill_directory(os.path.join(root, "skills"), "personal")
            self.assertRegex(found[0]["icon_url"], r"^/api/environment/plugin-icon/[a-f0-9]{24}$")

    def test_project_skills_follow_selected_workspace_and_provider(self):
        with tempfile.TemporaryDirectory(prefix="runteams-project-skills-") as root:
            codex_skill = os.path.join(root, ".agents", "skills", "release")
            claude_skill = os.path.join(root, ".claude", "skills", "deploy")
            os.makedirs(codex_skill)
            os.makedirs(claude_skill)
            with open(os.path.join(codex_skill, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: Release\ndescription: Prepare a release.\n---\n")
            with open(os.path.join(claude_skill, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: Deploy\ndescription: Deploy safely.\n---\n")
            codex = runtime_capabilities._skills(self.channel, {}, root)
            claude = runtime_capabilities._skills(dict(self.channel, provider="claude-code"), {}, root)
        self.assertEqual([item["name"] for item in codex if item["scope"] == "project"], ["Release"])
        self.assertEqual([item["name"] for item in claude if item["scope"] == "project"], ["Deploy"])

    def test_plugin_icons_use_safe_local_asset_references(self):
        with tempfile.TemporaryDirectory(prefix="runteams-plugin-icon-") as root:
            plugin = os.path.join(root, "plugin")
            os.makedirs(os.path.join(plugin, ".codex-plugin"))
            os.makedirs(os.path.join(plugin, "assets"))
            icon_path = os.path.join(plugin, "assets", "icon.png")
            with open(icon_path, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\nmock")
            with open(os.path.join(plugin, ".codex-plugin", "plugin.json"), "w", encoding="utf-8") as handle:
                handle.write('{"name":"quality","interface":{"displayName":"Quality",'
                             '"logo":"./assets/icon.png"}}')
            plugins, _ = runtime_capabilities._plugins({"installed": [{
                "pluginId": "quality@official", "name": "quality", "installed": True,
                "source": {"path": plugin},
            }]})
            icon_url = plugins[0]["icon_url"]
            self.assertRegex(icon_url, r"^/api/environment/plugin-icon/[a-f0-9]{24}$")
            token = icon_url.rsplit("/", 1)[-1]
            self.assertEqual(runtime_capabilities.plugin_icon(token), (os.path.realpath(icon_path), "image/png"))
            self.assertNotIn(root, str(plugins[0]))

    def test_installed_plugin_resources_are_lazy_and_path_safe(self):
        with tempfile.TemporaryDirectory(prefix="runteams-plugin-resources-") as root:
            plugin = os.path.join(root, "plugin")
            os.makedirs(os.path.join(plugin, "skills", "review"))
            os.makedirs(os.path.join(plugin, "node_modules", "ignored"))
            with open(os.path.join(plugin, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("# Review\n")
            with open(os.path.join(plugin, "skills", "review", "guide.md"), "w", encoding="utf-8") as handle:
                handle.write("Use evidence.\n")
            with open(os.path.join(plugin, "asset.bin"), "wb") as handle:
                handle.write(b"\x00\x01")
            with open(os.path.join(plugin, "preview.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\nmock")
            with open(os.path.join(plugin, ".env"), "w", encoding="utf-8") as handle:
                handle.write("SECRET=hidden\n")
            with open(os.path.join(plugin, "node_modules", "ignored", "index.js"), "w", encoding="utf-8") as handle:
                handle.write("ignored")
            data = {"installed": [{"pluginId": "review@official", "name": "review",
                                    "installed": True, "source": {"path": plugin}}]}
            with mock.patch.object(runtime_capabilities.model_channels,
                                   "resolve_channel_executable", return_value="/tmp/codex"), \
                    mock.patch.object(runtime_capabilities.model_channels,
                                      "_probe_env", return_value={}), \
                    mock.patch.object(runtime_capabilities, "_run_json",
                                      return_value=(data, None)):
                listing = runtime_capabilities.plugin_resources(
                    self.channel, "review@official")
            paths = [item["path"] for item in listing["files"]]
            self.assertEqual(listing["active_file"], "SKILL.md")
            self.assertIn("skills/review/guide.md", paths)
            self.assertNotIn(".env", paths)
            self.assertFalse(any(path.startswith("node_modules/") for path in paths))
            text = runtime_capabilities.plugin_resource_file(listing["token"], "SKILL.md")
            binary = runtime_capabilities.plugin_resource_file(listing["token"], "asset.bin")
            image = runtime_capabilities.plugin_resource_file(listing["token"], "preview.png")
            self.assertEqual(text["content"], "# Review\n")
            self.assertEqual(binary["kind"], "binary")
            self.assertEqual(image["kind"], "image")
            self.assertEqual(image["media_type"], "image/png")
            self.assertTrue(image["content"].startswith("iVBOR"))
            with self.assertRaisesRegex(ValueError, "路径无效"):
                runtime_capabilities.plugin_resource_file(listing["token"], "../secret")

    def test_plugin_homepage_registers_cached_favicon_with_existing_placeholder_fallback(self):
        with tempfile.TemporaryDirectory(prefix="runteams-favicon-") as root:
            previous = runtime_capabilities._PLUGIN_ICON_CACHE_DIR
            runtime_capabilities.configure_plugin_icon_cache(root)
            try:
                _installed, available = runtime_capabilities._plugins({"available": [{
                    "pluginId": "airtable@official", "name": "airtable",
                    "homepage": "https://www.airtable.com/product", "installed": False,
                }]})
                icon_url = available[0]["icon_url"]
                token = icon_url.rsplit("/", 1)[-1]
                response = mock.MagicMock()
                response.read.return_value = b"\x89PNG\r\n\x1a\nmock"
                response.__enter__.return_value = response
                with mock.patch.object(runtime_capabilities.urllib.request, "urlopen",
                                       return_value=response) as fetch:
                    first = runtime_capabilities.plugin_icon(token)
                    second = runtime_capabilities.plugin_icon(token)
                self.assertEqual(first, second)
                self.assertEqual(first[1], "image/png")
                self.assertTrue(os.path.isfile(first[0]))
                fetch.assert_called_once()
            finally:
                runtime_capabilities._PLUGIN_ICON_CACHE_DIR = previous

    def test_plugin_homepage_icon_rejects_local_or_non_http_addresses(self):
        for homepage in ("http://127.0.0.1/logo", "http://localhost/icon",
                         "file:///tmp/icon.png", "https://printer.local/icon"):
            self.assertEqual(runtime_capabilities._register_homepage_icon(homepage), "")

    def test_github_plugin_homepages_use_distinct_publisher_avatars(self):
        anthropic = runtime_capabilities._register_homepage_icon(
            "https://github.com/anthropics/claude-plugins/tree/main/plugins/review")
        community = runtime_capabilities._register_homepage_icon(
            "https://github.com/obra/superpowers.git")
        self.assertNotEqual(anthropic, community)
        first = runtime_capabilities._PLUGIN_ICONS[anthropic.rsplit("/", 1)[-1]]
        second = runtime_capabilities._PLUGIN_ICONS[community.rsplit("/", 1)[-1]]
        self.assertEqual(first["github_owner"], "anthropics")
        self.assertEqual(second["github_owner"], "obra")

    def test_mirrored_official_integrations_use_their_own_brand_homepages(self):
        self.assertEqual(plugin_brands.homepage("github"), "https://github.com")
        self.assertEqual(plugin_brands.homepage("context7@claude-plugins-official"),
                         "https://upstash.com")
        self.assertEqual(plugin_brands.homepage("code-review"), "")

    def test_plugin_details_come_from_public_manifest_metadata(self):
        with tempfile.TemporaryDirectory(prefix="runteams-plugin-details-") as root:
            os.makedirs(os.path.join(root, ".codex-plugin"))
            with open(os.path.join(root, ".codex-plugin", "plugin.json"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "name": "quality", "license": "MIT", "homepage": "https://example.com",
                    "author": {"name": "Example Inc.", "url": "https://example.com/about"},
                    "skills": "./skills", "commands": "./commands", "agents": "./agents",
                    "mcpServers": "./mcp.json", "lspServers": "./lsp.json",
                    "hooks": "./hooks.json", "apps": "./app.json",
                    "interface": {"displayName": "Quality", "shortDescription": "Review safely",
                                  "longDescription": "A longer, useful explanation.",
                                  "capabilities": ["Read", "Write"],
                                  "defaultPrompt": ["Review this change"],
                                  "privacyPolicyURL": "https://example.com/privacy",
                                  "termsOfServiceURL": "https://example.com/terms"},
                }))
            plugins, _ = runtime_capabilities._plugins({"installed": [{
                "pluginId": "quality@example", "name": "quality", "installed": True,
                "authPolicy": "ON_USE", "source": {"path": root},
            }]})
        plugin = plugins[0]
        self.assertEqual(plugin["developer_name"], "Example Inc.")
        self.assertEqual(plugin["long_description"], "A longer, useful explanation.")
        self.assertEqual(plugin["capabilities"], ["Read", "Write"])
        self.assertEqual(plugin["default_prompts"], ["Review this change"])
        self.assertEqual(plugin["components"], [
            "skills", "commands", "agents", "mcpServers", "lspServers", "hooks", "apps",
        ])
        self.assertEqual(plugin["auth_policy"], "ON_USE")

    def test_plugin_icons_can_be_warmed_before_environment_inventory(self):
        with tempfile.TemporaryDirectory(prefix="runteams-icon-warm-") as root:
            os.makedirs(os.path.join(root, ".codex-plugin"))
            os.makedirs(os.path.join(root, "assets"))
            with open(os.path.join(root, "assets", "icon.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\nmock")
            with open(os.path.join(root, ".codex-plugin", "plugin.json"), "w", encoding="utf-8") as handle:
                handle.write('{"name":"warm","interface":{"logo":"./assets/icon.png"}}')
            data = {"installed": [{"pluginId": "warm@official", "name": "warm",
                                      "installed": True, "source": {"path": root}}]}
            with mock.patch.object(runtime_capabilities.model_channels, "resolve_channel_executable",
                                   return_value="/tmp/codex"), \
                    mock.patch.object(runtime_capabilities.model_channels, "_probe_env", return_value={}), \
                    mock.patch.object(runtime_capabilities, "_run_json", return_value=(data, None)):
                count = runtime_capabilities.warm_plugin_icons([self.channel])
        self.assertEqual(count, 1)

    def test_codex_only_inherits_user_configuration_for_declared_native_dependencies(self):
        adapter = CodexAdapter(executable="/tmp/codex")
        isolated = adapter.build_argv(
            "task", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="", reasoning_effort="")
        self.assertIn("--ignore-user-config", isolated)
        adapter.configure_requirements({"inherit_native": True})
        native = adapter.build_argv(
            "task", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
            mode="judge", model="", reasoning_effort="")
        self.assertNotIn("--ignore-user-config", native)
        self.assertIn("--enable", native)
        self.assertIn("plugins", native)


    def test_environment_summary_reports_channel_assets_without_legacy_worker_usage(self):
        inventory = {"status": "ready", "runtime": {"installed": True, "authenticated": True, "version": "1"},
                     "plugins": [{"id": "github@official", "name": "github", "installed": True, "enabled": True}],
                     "skills": [{"id": "github@official:review", "name": "Review", "scope": "plugin",
                                 "plugin_id": "github@official", "enabled": True}],
                     "available_plugins": [], "mcp_servers": [{"name": "github", "enabled": True,
                     "auth_status": "authenticated", "status": "connected"}], "diagnostics": []}
        with mock.patch.object(runtime_capabilities, "inventory", return_value=inventory):
            report = runtime_capabilities.environment_summary([self.channel])
        self.assertTrue(report["ready"])
        self.assertEqual(report["counts"]["plugins"], 1)
        self.assertEqual(report["counts"]["skills"], 1)
        self.assertEqual(report["channels"][0]["skill_count"], 1)
        self.assertEqual(report["skills"][0]["channel_id"], 7)
        self.assertEqual(report["plugins"][0]["used_by"], [])
        self.assertEqual(report["mcp_servers"][0]["used_by"], [])

    def test_environment_summary_blocks_an_authenticated_incompatible_cli(self):
        inventory = {
            "status": "incompatible",
            "runtime": {"installed": True, "authenticated": True, "compatible": False,
                        "version": "codex-cli 0.1.0",
                        "detail": "Codex CLI 与 RunTeams 不兼容：缺少 --ignore-user-config"},
            "plugins": [], "skills": [], "available_plugins": [],
            "mcp_servers": [], "diagnostics": [],
        }
        with mock.patch.object(runtime_capabilities, "inventory", return_value=inventory):
            report = runtime_capabilities.environment_summary([self.channel])
        self.assertFalse(report["ready"])
        self.assertEqual(report["counts"]["ready_channels"], 0)
        self.assertFalse(report["channels"][0]["ready"])
        self.assertEqual(report["issues"][0]["detail"],
                         "Agent CLI 版本与 RunTeams 不兼容")
        self.assertIn("--ignore-user-config", report["issues"][0]["remediation"])




if __name__ == "__main__":
    unittest.main()
