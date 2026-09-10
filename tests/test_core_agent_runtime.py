import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from runteams_core import RunTeamsCore
from runteams_core import task_inputs
from runteams_core.agent_runtime import (AgentEmployeeRuntime,
                                         _channel_executable_dirs,
                                         _host_tool_dirs,
                                         _managed_executable_dirs,
                                         _materialize_trial_fixtures,
                                         _trial_executable_dirs)
from runteams_core.contracts import ContractError
from runteams_core.protocol import EmployeeProtocol, trial_unavailable_capability
from scripts.fixture_validation import publish_verified_employee


class CoreAgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runteams-agent-runtime-")

    def tearDown(self):
        self.temporary.cleanup()

    def test_frozen_employee_channel_selects_the_matching_adapter(self):
        root = Path(self.temporary.name)
        codex_path, claude_path = root / "codex", root / "claude"
        for path in (codex_path, claude_path):
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        channels = {
            "codex": {"provider": "codex", "enabled": 1,
                      "executable": str(codex_path), "config_dir": "/tmp/codex-home"},
            "claude-code": {"provider": "claude-code", "enabled": 1,
                            "executable": str(claude_path), "config_dir": "/tmp/claude-home"},
        }
        runtime = AgentEmployeeRuntime(
            self.temporary.name, channel_resolver=channels.get)
        codex = runtime._adapter({"runtime": {"channel": "codex"}})
        claude = runtime._adapter({"runtime": {"channel": "claude-code"}})
        self.assertEqual((codex.name, codex.executable, codex.config_dir),
                         ("codex", str(codex_path), "/tmp/codex-home"))
        self.assertEqual((claude.name, claude.executable, claude.config_dir),
                         ("claude-code", str(claude_path), "/tmp/claude-home"))

    def test_claude_receives_only_the_explicit_runteams_mcp(self):
        runtime = AgentEmployeeRuntime(self.temporary.name)
        arguments = runtime._mcp_arguments(
            "claude-code", "/tmp/python", ["server.py", "db", "7", "workspace"],
            {"PYTHONNOUSERSITE": "1"})
        self.assertEqual(arguments[-1], "--strict-mcp-config")
        config = json.loads(arguments[arguments.index("--mcp-config") + 1])
        self.assertEqual(list(config["mcpServers"]), ["runteams"])
        self.assertEqual(config["mcpServers"]["runteams"]["command"], "/tmp/python")
        self.assertEqual(config["mcpServers"]["runteams"]["args"][2], "7")

    def test_trial_executable_fixture_is_executable_and_scoped_to_agent_path(self):
        root = Path(self.temporary.name)
        workspace = root / "workspace"
        executable_dirs = _materialize_trial_fixtures([{
            "path": "bin/forge", "content": "#!/bin/sh\nexit 0\n",
            "executable": True,
        }], workspace)
        target = workspace / "bin" / "forge"
        self.assertTrue(os.access(str(target), os.X_OK))
        self.assertEqual(executable_dirs, [str((workspace / "bin").resolve())])
        self.assertEqual(_trial_executable_dirs([{
            "path": "bin/forge", "content": "ignored", "executable": True,
        }], workspace), executable_dirs)

    def test_managed_runtime_executables_are_discovered_inside_core_root(self):
        root = Path(self.temporary.name)
        node_bin = root / "runtime" / "node" / "node_modules" / ".bin"
        node_bin.mkdir(parents=True)
        self.assertEqual(_managed_executable_dirs(root), [str(node_bin.resolve())])

    def test_agent_channel_sibling_tools_are_available_to_the_employee(self):
        root = Path(self.temporary.name)
        executable = root / "channel" / "codex"
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        adapter = mock.Mock(executable=str(executable))
        self.assertEqual(_channel_executable_dirs(adapter),
                         [str(executable.parent.resolve())])
        self.assertEqual(_channel_executable_dirs(mock.Mock(executable="")), [])

    def test_host_node_toolchain_does_not_depend_on_login_shell_path(self):
        root = Path(self.temporary.name) / "homebrew-bin"
        root.mkdir()
        node = root / "node"
        node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        node.chmod(0o755)
        with mock.patch(
                "runteams_core.agent_runtime._HOST_TOOL_DIRECTORIES", (str(root),)):
            with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
                self.assertEqual(_host_tool_dirs(), [str(root.resolve())])

    def test_employee_runtime_loads_only_frozen_native_extensions(self):
        root = Path(self.temporary.name)
        executable = root / "codex"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        channel = {"provider": "codex", "enabled": 1,
                   "executable": str(executable), "config_dir": "/tmp/codex-home"}
        dependency = {
            "provider": "codex", "plugin_id": "figma@official",
            "name": "Figma", "version": "1", "fingerprint": "fixed",
            "runtime": {"plugin_dir": "/tmp/figma",
                        "marketplace": "official",
                        "marketplace_root": "/tmp/official"},
        }
        runtime = AgentEmployeeRuntime(
            self.temporary.name, channel_resolver=lambda _provider: channel,
            native_dependency_resolver=lambda _provider, _plugin_id: dependency)
        adapter = runtime._adapter({
            "runtime": {"channel": "codex"},
            "capabilities": [{"provider": "codex", "plugin_id": "figma@official",
                              "name": "Figma", "fingerprint": "fixed"}],
        })
        self.assertTrue(adapter.requirements["isolated_native"])
        self.assertEqual(adapter.requirements["plugins"], ["figma@official"])
        self.assertEqual(adapter.requirements["codex_marketplaces"], [
            {"name": "official", "source": "/tmp/official"}])

        changed = dict(dependency, fingerprint="changed")
        with self.assertRaisesRegex(ContractError, "发生变化"):
            AgentEmployeeRuntime(
                self.temporary.name, channel_resolver=lambda _provider: channel,
                native_dependency_resolver=lambda _provider, _plugin_id: changed,
            )._adapter({
                "runtime": {"channel": "codex"},
                "capabilities": [{"provider": "codex", "plugin_id": "figma@official",
                                  "name": "Figma", "fingerprint": "fixed"}],
            })

    def test_disabled_or_unknown_frozen_channel_is_rejected(self):
        disabled = lambda _provider: {"provider": "claude-code", "enabled": 0}
        with self.assertRaisesRegex(ContractError, "未启用"):
            AgentEmployeeRuntime(
                self.temporary.name, channel_resolver=disabled)._adapter(
                    {"runtime": {"channel": "claude-code"}})
        with self.assertRaisesRegex(ContractError, "不支持"):
            AgentEmployeeRuntime(self.temporary.name)._adapter(
                    {"runtime": {"channel": "unknown"}})

    def test_capability_unavailable_signal_only_applies_to_the_trial_subject(self):
        employee = {"capabilities": [{
            "package_key": "brief-validator",
            "capability": {"id": "brief-validator"},
        }]}
        snapshot = {"trial": {"test_id": "capability-unavailable"}, "task": {
            "payload": {"context": {"test_signal": {
                "capability_ref": "brief-validator/brief-validator",
                "state": "unavailable",
            }}},
        }}

        self.assertEqual(
            trial_unavailable_capability(snapshot, "subject", employee),
            "brief-validator/brief-validator")
        self.assertEqual(trial_unavailable_capability(snapshot, "downstream", employee), "")
        self.assertEqual(trial_unavailable_capability(
            {**snapshot, "trial": None}, "subject", employee), "")

    def test_report_failed_is_a_valid_agent_protocol_terminal(self):
        core = RunTeamsCore(Path(self.temporary.name) / "core")
        employee_id = core.create_employee("Failure reporter", {
            "role": "Report technical failures",
            "program": {"objective": "Report failures", "steps": [{
                "id": "work", "instruction": "Attempt the work",
            }], "acceptance": ["Report the failure"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
            "tests": [{
                "id": "failed", "name": "Technical failure",
                "work_order": {"objective": "Attempt unavailable work"},
                "expected_status": "failed", "covers": ["result.failed"],
            }],
        })
        trial = core.start_employee_trial(employee_id, "failed")

        def commit_failure(*_args, **kwargs):
            with core.repository.connect() as connection:
                employee_run_id = connection.execute(
                    "SELECT id FROM employee_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
            protocol = EmployeeProtocol(
                core.repository.path, employee_run_id, Path(kwargs["cwd"]))
            protocol.call("get_task", {})
            protocol.call("report_failed", {
                "reason": "required capability unavailable",
                "recovery": "restore the capability",
            })

        runtime = AgentEmployeeRuntime(core.root)
        with mock.patch("runteams_core.agent_runtime.run_agent",
                        side_effect=commit_failure):
            result = core.run_workflow(trial["id"], runtime, max_attempts=1)

        self.assertEqual(result["status"], "failed")
        self.assertIn("required capability unavailable", result["issues"][0])
        self.assertNotIn("Agent 未通过", result["issues"][0])
        with core.repository.connect() as connection:
            employee_run_id = connection.execute(
                "SELECT id FROM employee_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
        envelopes = [event for event in core.repository.events(
            "employee_run:{}".format(employee_run_id))
                     if event["type"] == "agent.runtime_finished"]
        self.assertEqual(len(envelopes), 1)
        envelope = envelopes[0]["data_json"]
        self.assertTrue(envelope["prompt_sha256"])
        self.assertTrue(envelope["transcript_ref"].endswith(
            "agent-transcript-{}.jsonl".format(employee_run_id)))
        self.assertEqual(envelope["transcript_bytes"], 0)

    def test_task_input_snapshot_is_materialized_and_exposed_by_protocol(self):
        core = RunTeamsCore(Path(self.temporary.name) / "core-input")
        employee_id = core.create_employee("Input reader", {
            "role": "Read supplied files",
            "program": {"objective": "Read files", "steps": [{
                "id": "read", "instruction": "Read the supplied file",
            }], "acceptance": ["Report whether it was readable"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
            "tests": [{
                "id": "failed", "name": "Input probe",
                "work_order": {"objective": "Read the supplied file"},
                "expected_status": "failed", "covers": ["result.failed"],
            }],
        })
        trial = core.start_employee_trial(employee_id, "failed")
        task_id = trial["snapshot_json"]["task"]["id"]
        input_id = "d" * 24
        stored = task_inputs.task_root(core.root, task_id) / input_id
        stored.mkdir()
        (stored / "original.md").write_text("employee can read this", encoding="utf-8")
        item = {"id": input_id, "name": "instructions.md", "kind": "file", "size": 22,
                "ref": "task-input://{}/{}".format(task_id, input_id)}
        snapshot = trial["snapshot_json"]
        snapshot["task"]["payload"]["inputs"] = [item]
        with core.repository.connect() as connection:
            connection.execute(
                "UPDATE workflow_runs SET snapshot_json=? WHERE id=?",
                (json.dumps(snapshot, ensure_ascii=False), trial["id"]))
            task = connection.execute(
                "SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()
            payload = json.loads(task["payload_json"])
            payload["inputs"] = [item]
            connection.execute(
                "UPDATE tasks SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), task_id))

        observed = {}

        def inspect_materialized_input(*_args, **kwargs):
            with core.repository.connect() as connection:
                employee_run_id = connection.execute(
                    "SELECT id FROM employee_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
            workspace = Path(kwargs["cwd"])
            protocol = EmployeeProtocol(core.repository.path, employee_run_id, workspace)
            task = protocol.call("get_task", {})["structuredContent"]
            observed["input"] = task["work_order"]["inputs"][0]
            observed["content"] = (workspace / observed["input"]["path"]).read_text(
                encoding="utf-8")
            protocol.call("report_failed", {
                "reason": "probe complete", "recovery": "none",
            })

        runtime = AgentEmployeeRuntime(core.root)
        with mock.patch("runteams_core.agent_runtime.run_agent",
                        side_effect=inspect_materialized_input):
            result = core.run_workflow(trial["id"], runtime, max_attempts=1)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(observed, result)
        self.assertEqual(observed["content"], "employee can read this")
        self.assertEqual(observed["input"]["path"],
                         ".runteams/inputs/instructions.md")

    def test_trial_fixture_files_are_isolated_and_materialized_before_agent_runs(self):
        core = RunTeamsCore(Path(self.temporary.name) / "core-fixture")
        employee_id = core.create_employee("Fixture reader", {
            "role": "Read the validation fixture",
            "program": {"objective": "Read a fixture", "steps": [{
                "id": "read", "instruction": "Read fixtures/example/input.md",
            }], "acceptance": ["Fixture is readable"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
            "tests": [{
                "id": "fixture", "name": "Materialized fixture",
                "work_order": {"objective": "Read the fixture"},
                "fixtures": [{"path": "fixtures/example/input.md",
                              "content": "isolated validation content"}],
                "expected_status": "failed", "covers": ["result.failed"],
            }],
        })
        trial = core.start_employee_trial(employee_id, "fixture")
        self.assertEqual(
            trial["snapshot_json"]["trial"]["fixtures"][0]["path"],
            "fixtures/example/input.md")
        observed = {}

        def inspect_fixture(*_args, **kwargs):
            with core.repository.connect() as connection:
                employee_run_id = connection.execute(
                    "SELECT id FROM employee_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
            workspace = Path(kwargs["cwd"])
            observed["content"] = (workspace / "fixtures/example/input.md").read_text(
                encoding="utf-8")
            protocol = EmployeeProtocol(core.repository.path, employee_run_id, workspace)
            protocol.call("get_task", {})
            protocol.call("report_failed", {"reason": "probe complete", "recovery": "none"})

        runtime = AgentEmployeeRuntime(core.root)
        with mock.patch("runteams_core.agent_runtime.run_agent", side_effect=inspect_fixture):
            result = core.run_workflow(trial["id"], runtime, max_attempts=1)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(observed["content"], "isolated validation content")

    def test_trial_fixture_rejects_paths_outside_the_workspace(self):
        core = RunTeamsCore(Path(self.temporary.name) / "core-unsafe-fixture")
        with self.assertRaisesRegex(ContractError, "位于用例工作区内"):
            core.create_employee("Unsafe fixture", {
                "role": "Read a fixture",
                "program": {"objective": "Read", "steps": [{
                    "id": "read", "instruction": "Read the fixture",
                }], "acceptance": ["Readable"]},
                "capabilities": [],
                "runtime": {"channel": "codex", "model": "", "effort": "low"},
                "tests": [{
                    "id": "unsafe", "name": "Unsafe fixture",
                    "work_order": {"objective": "Read"},
                    "fixtures": [{"path": "../outside.md", "content": "no"}],
                    "expected_status": "failed", "covers": ["result.failed"],
                }],
            })

    def test_positions_in_one_workflow_share_the_task_workspace(self):
        core = RunTeamsCore(Path(self.temporary.name) / "core-shared-workspace")

        def employee(name, instruction):
            employee_id = core.create_employee(name, {
                "role": instruction,
                "program": {"objective": instruction, "steps": [{
                    "id": "work", "instruction": instruction,
                }], "acceptance": ["Work completed"]},
                "capabilities": [],
                "runtime": {"channel": "codex", "model": "", "effort": "low"},
            })
            publish_verified_employee(core, employee_id)
            return employee_id

        writer = employee("Writer", "Create shared.txt")
        reviewer = employee("Reviewer", "Read shared.txt and create review.txt")
        reader = employee("Reader", "Read both shared files")
        pipeline_id = core.create_pipeline("Shared task workspace", {
            "positions": [{"key": "write", "employee_id": writer},
                          {"key": "review", "employee_id": reviewer},
                          {"key": "read", "employee_id": reader}],
            "edges": [{"from": "write", "to": "review"},
                      {"from": "review", "to": "read"}],
        })
        task_id = core.create_task(pipeline_id, "Share one task directory", {
            "objective": "Create then read the same file",
        })
        workflow_id = core.start_workflow(task_id)
        observed_workspaces = []

        def run_position(*_args, **kwargs):
            with core.repository.connect() as connection:
                employee_run_id = connection.execute(
                    "SELECT id FROM employee_runs WHERE state='running' "
                    "ORDER BY id DESC LIMIT 1").fetchone()[0]
            workspace = Path(kwargs["cwd"])
            observed_workspaces.append(workspace)
            protocol = EmployeeProtocol(core.repository.path, employee_run_id, workspace)
            task = protocol.call("get_task", {})["structuredContent"]
            if len(observed_workspaces) == 1:
                (workspace / "shared.txt").write_text("from writer", encoding="utf-8")
                protocol.call("publish_artifact", {"path": "shared.txt", "title": "Shared"})
            elif len(observed_workspaces) == 2:
                self.assertEqual((workspace / "shared.txt").read_text(encoding="utf-8"),
                                 "from writer")
                (workspace / "review.txt").write_text("from reviewer", encoding="utf-8")
                protocol.call("publish_artifact", {"path": "review.txt", "title": "Review"})
            else:
                self.assertEqual((workspace / "shared.txt").read_text(encoding="utf-8"),
                                 "from writer")
                self.assertEqual((workspace / "review.txt").read_text(encoding="utf-8"),
                                 "from reviewer")
                self.assertEqual(
                    [item["path"] for item in task["work_order"]["inputs"]],
                    ["shared.txt", "review.txt"])
            protocol.call("advance_step", {"step_id": "work", "summary": "done"})
            protocol.call("complete", {"summary": "done", "output": {}})

        runtime = AgentEmployeeRuntime(core.root)
        with mock.patch("runteams_core.agent_runtime.run_agent", side_effect=run_position):
            result = core.run_workflow(workflow_id, runtime, max_attempts=1)

        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(observed_workspaces), 3)
        self.assertEqual(len(set(observed_workspaces)), 1)


if __name__ == "__main__":
    unittest.main()
