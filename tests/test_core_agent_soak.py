import tempfile
import unittest
from pathlib import Path
import json

from runteams_core import RunTeamsCore
from scripts import core_agent_soak


class CoreAgentSoakTests(unittest.TestCase):
    def test_prepare_freezes_both_channels_and_evidence_is_minimal(self):
        with tempfile.TemporaryDirectory(prefix="runteams-soak-test-") as directory:
            core = RunTeamsCore(directory)
            state = core_agent_soak.prepare(core)
            pipeline = core.pipeline(state["pipeline_id"])
            task_id = core.create_task(state["pipeline_id"], "smoke", {
                "objective": "smoke"})
            workflow_id = core.start_workflow(task_id)
            workflow = core.workflow(workflow_id)
            record = core_agent_soak.evidence(
                workflow, "normal", {"status": "waiting_retry"})
            employee_channels = [
                core.employee(item["employee_id"])["active_release"]["snapshot_json"]["runtime"]["channel"]
                for item in pipeline["definition_json"]["positions"]]
        self.assertEqual(employee_channels, ["codex", "codex"])
        self.assertEqual(record["channels"], ["codex", "codex"])
        self.assertEqual(state["config_version"], core_agent_soak.CONFIG_VERSION)
        self.assertEqual(record["artifact_count"], 0)
        self.assertNotIn("snapshot", record)

    def test_status_reads_resumable_progress_without_running_agents(self):
        with tempfile.TemporaryDirectory(prefix="runteams-soak-status-") as directory:
            root = Path(directory)
            (root / "soak-state.json").write_text(
                json.dumps({"cycle": 3, "active_seconds": 42}), encoding="utf-8")
            (root / "soak-evidence.jsonl").write_text("{}\n{}\n", encoding="utf-8")
            result = core_agent_soak.status(root)
        self.assertEqual(result["state"]["cycle"], 3)
        self.assertEqual(result["evidence_records"], 2)


if __name__ == "__main__":
    unittest.main()
