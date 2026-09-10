"""Opt-in real subscription test for the new employee handoff kernel."""

import os
import json
import tempfile
import unittest

from adapter_codex import resolve_codex
from adapter_claude import resolve_claude
from runteams_core import RunTeamsCore
from runteams_core.agent_runtime import AgentEmployeeRuntime
from scripts.fixture_validation import publish_verified_employee


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draft(role, instruction, package_id, channel="codex"):
    return {
        "role": role,
        "program": {
            "objective": role,
            "steps": [{"id": "deliver", "instruction": instruction}],
            "acceptance": ["brief.json contains non-empty objective and context",
                           "The required verifier passes after the final edit"],
        },
        "capabilities": [{"package_id": package_id,
                          "capability_id": "brief-validator"},
                         {"package_id": package_id,
                          "capability_id": "validate-brief"}],
        "runtime": {"channel": channel, "model": "", "effort": "low"},
    }


@unittest.skipUnless(os.environ.get("RUNTEAMS_REAL_CODEX_TEST") == "1",
                     "set RUNTEAMS_REAL_CODEX_TEST=1 to use the logged-in Codex subscription")
class CoreCodexEndToEndTests(unittest.TestCase):
    def test_two_real_codex_employees_handoff_verified_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="runteams-real-codex-") as directory:
            core = RunTeamsCore(directory)
            package = core.import_package(
                "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
            researcher = core.create_employee("Researcher", draft(
                "Create a factual research handoff for the writer.",
                "Use the supplied task facts to create brief.json with objective, context and facts; "
                "run the required verifier on it, publish it, then submit a structured result.",
                package["package_id"]))
            writer = core.create_employee("Writer", draft(
                "Turn the upstream research into a concise final product brief.",
                "Read the upstream handoff, create a new brief.json with objective, context and final_copy; "
                "run the required verifier on it, publish it, then submit a structured result.",
                package["package_id"]))
            publish_verified_employee(core, researcher)
            publish_verified_employee(core, writer)
            pipeline_id = core.create_pipeline("Research to writing", {
                "positions": [{"key": "research", "employee_id": researcher},
                              {"key": "writing", "employee_id": writer}],
                "edges": [{"from": "research", "to": "writing"}],
            })
            task_id = core.create_task(pipeline_id, "Explain RunTeams", {
                "objective": "Write a concise brief explaining RunTeams",
                "context": {"facts": [
                    "RunTeams organizes complete Agent Runtimes into reusable employees and workflows.",
                    "It uses structured work orders for employee handoffs.",
                    "Employee releases freeze exact capability package revisions."]},
                "acceptance": ["Use only the supplied facts", "Return a concise final brief"],
            })
            workflow_run_id = core.start_workflow(task_id)
            result = core.run_workflow(
                workflow_run_id,
                AgentEmployeeRuntime(
                    directory, timeout_sec=300,
                    channel_resolver=lambda provider: {
                        "provider": provider, "enabled": 1,
                        "executable": resolve_codex(), "config_dir": "",
                    }))
            workflow = core.workflow(workflow_run_id)
            self.assertEqual(result["status"], "completed", workflow)
            self.assertEqual(workflow["state"], "completed")
            self.assertEqual([item["state"] for item in workflow["employee_runs"]],
                             ["completed", "completed"])
            with core.repository.connect() as connection:
                artifacts = connection.execute("SELECT * FROM artifacts ORDER BY id").fetchall()
                verifier_events = connection.execute(
                    "SELECT stream,data_json FROM events WHERE type='capability.executed' ORDER BY id"
                ).fetchall()
            self.assertEqual(len(artifacts), 2)
            evidence_by_run = {}
            for event in verifier_events:
                evidence_by_run.setdefault(event["stream"], []).append(json.loads(event["data_json"]))
            expected_streams = {"employee_run:{}".format(item["id"])
                                for item in workflow["employee_runs"]}
            self.assertEqual(set(evidence_by_run), expected_streams)
            for evidence in evidence_by_run.values():
                self.assertEqual(evidence[-1]["result"]["evaluation"]["status"], "passed")


@unittest.skipUnless(os.environ.get("RUNTEAMS_REAL_MIXED_TEST") == "1",
                     "set RUNTEAMS_REAL_MIXED_TEST=1 to use both logged-in subscriptions")
class CoreMixedAgentEndToEndTests(unittest.TestCase):
    def test_real_codex_employee_hands_verified_artifact_to_claude_employee(self):
        with tempfile.TemporaryDirectory(prefix="runteams-real-mixed-") as directory:
            core = RunTeamsCore(directory)
            package = core.import_package(
                "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
            researcher = core.create_employee("Codex Researcher", draft(
                "Create a factual handoff for another employee.",
                "Create brief.json from the supplied facts, verify it, publish it and complete.",
                package["package_id"], channel="codex"))
            writer = core.create_employee("Claude Writer", draft(
                "Turn the upstream handoff into the final concise brief.",
                "Read the handoff, create a final brief.json, verify it, publish it and complete.",
                package["package_id"], channel="claude-code"))
            publish_verified_employee(core, researcher)
            publish_verified_employee(core, writer)
            pipeline_id = core.create_pipeline("Claude to Codex", {
                "positions": [{"key": "research", "employee_id": researcher},
                              {"key": "writing", "employee_id": writer}],
                "edges": [{"from": "research", "to": "writing"}],
            })
            task_id = core.create_task(pipeline_id, "Mixed channel handoff", {
                "objective": "Create a concise factual RunTeams brief",
                "context": {"facts": [
                    "RunTeams organizes complete Agent Runtimes into reusable employees.",
                    "Employees exchange structured WorkOrders, WorkResults and Artifacts.",
                ]},
            })
            workflow_run_id = core.start_workflow(task_id)
            executables = {"claude-code": resolve_claude(), "codex": resolve_codex()}
            runtime = AgentEmployeeRuntime(
                directory, timeout_sec=300,
                channel_resolver=lambda provider: {
                    "provider": provider, "enabled": 1,
                    "executable": executables[provider], "config_dir": "",
                })
            result = core.run_workflow(workflow_run_id, runtime)
            workflow = core.workflow(workflow_run_id)
            if result["status"] == "waiting_retry" and result.get("reason") == "quota":
                self.assertEqual([item["state"] for item in workflow["employee_runs"]],
                                 ["completed", "interrupted"])
                self.assertEqual(sum(len(item["artifacts"])
                                     for item in workflow["employee_runs"]), 1)
                self.assertTrue(workflow["available_at"])
                self.skipTest("Claude subscription quota is waiting for its declared reset")
            self.assertEqual(result["status"], "completed", workflow)
            self.assertEqual(workflow["state"], "completed")
            self.assertEqual([item["state"] for item in workflow["employee_runs"]],
                             ["completed", "completed"])
            self.assertEqual([item["position_key"] for item in workflow["employee_runs"]],
                             ["research", "writing"])
            self.assertEqual(sum(len(item["artifacts"])
                                 for item in workflow["employee_runs"]), 2)


if __name__ == "__main__":
    unittest.main()
