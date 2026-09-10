import subprocess
import unittest
from unittest import mock

import cli_compatibility
import model_channels
import runner
from adapter_base import EXECUTION_INTERNAL_ANALYSIS
from adapter_codex import CodexAdapter


class CliCompatibilityTests(unittest.TestCase):
    def test_required_option_matrix_accepts_current_and_rejects_legacy_help(self):
        cases = [
            ("codex", " ".join(cli_compatibility.required_options("codex")), True),
            ("codex", "--json --ephemeral --sandbox", False),
            ("claude-code", " ".join(
                cli_compatibility.required_options("claude-code")), True),
            ("claude-code", "--output-format --verbose --permission-mode", False),
        ]
        for provider, help_text, expected in cases:
            with self.subTest(provider=provider, compatible=expected):
                completed = subprocess.CompletedProcess(
                    ["/tmp/cli", "--help"], 0, stdout=help_text, stderr="")
                with mock.patch.object(cli_compatibility, "_run", return_value=completed):
                    result = cli_compatibility.check(provider, "/tmp/cli", {})
                self.assertEqual(result["compatible"], expected)
                self.assertEqual(result["protocol"],
                                 "codex-jsonl" if provider == "codex" else "claude-stream-json")
                self.assertEqual(bool(result["missing_options"]), not expected)

    def test_probe_marks_authenticated_but_incompatible_cli_as_incompatible(self):
        def command(argv, _env, timeout=8, cwd=None):
            del timeout, cwd
            if argv[-1] == "--version":
                return subprocess.CompletedProcess(argv, 0, "codex-cli 0.1.0\n", "")
            if argv[1:] == ["exec", "--help"]:
                return subprocess.CompletedProcess(argv, 0, "--json --ephemeral --sandbox", "")
            if argv[1:] == ["login", "status"]:
                return subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
            raise AssertionError(argv)

        channel = {"provider": "codex", "executable": "/tmp/codex", "config_dir": ""}
        with mock.patch.object(model_channels, "resolve_channel_executable",
                               return_value="/tmp/codex"), \
                mock.patch.object(model_channels, "_run", side_effect=command), \
                mock.patch.object(model_channels, "_codex_account", return_value={}):
            result = model_channels.probe(channel)

        self.assertTrue(result["installed"])
        self.assertTrue(result["authenticated"])
        self.assertFalse(result["compatible"])
        self.assertEqual(result["status"], "incompatible")
        self.assertIn("--ignore-user-config", result["detail"])

    def test_runner_refuses_incompatible_cli_before_starting_agent(self):
        adapter = CodexAdapter(executable="/tmp/codex")
        incompatible = {"compatible": False, "protocol": "codex-jsonl",
                        "missing_options": ["--json"],
                        "detail": "Codex CLI 与 RunTeams 不兼容：缺少 --json"}
        with mock.patch.object(runner.cli_compatibility, "check",
                               return_value=incompatible), \
                mock.patch.object(runner.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "缺少 --json"):
                runner.run_agent(
                    adapter, "hello", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
                    model="", timeout_sec=10)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
