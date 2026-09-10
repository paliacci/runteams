import tempfile
import unittest

from runteams_core import RunTeamsCore
from scripts import core_agent_dogfood


class CoreAgentDogfoodTests(unittest.TestCase):
    def test_prepare_selects_three_real_flows_and_reuses_frozen_employees(self):
        with tempfile.TemporaryDirectory(prefix="runteams-dogfood-test-") as directory:
            core = RunTeamsCore(directory)
            state = core_agent_dogfood.prepare(core)
            pipelines = {key: core.pipeline(value)
                         for key, value in state["pipeline_ids"].items()}
            channels = {}
            for key, pipeline in pipelines.items():
                channels[key] = [
                    core.employee(position["employee_id"])["active_release"]["snapshot_json"]
                    ["runtime"]["channel"]
                    for position in pipeline["definition_json"]["positions"]]
        self.assertEqual(channels, {
            "research_brief": ["codex"],
            "decision_memo": ["codex"],
            "handoff_delivery": ["codex", "codex"],
        })
        self.assertEqual(len(core_agent_dogfood.FLOW_SPECS), 3)
        self.assertEqual(state["config_version"], core_agent_dogfood.CONFIG_VERSION)

    def test_report_uses_latest_fact_per_workflow_and_computes_gate_rates(self):
        records = [
            {"workflow_id": 1, "flow": "research_brief", "state": "waiting_retry",
             "qualifying": False, "interrupted_attempts": 1},
            {"workflow_id": 1, "flow": "research_brief", "state": "completed",
             "qualifying": True, "interrupted_attempts": 1},
            {"workflow_id": 2, "flow": "decision_memo", "state": "failed",
             "qualifying": False, "interrupted_attempts": 0},
        ]
        report = core_agent_dogfood.summarize(records, target=30)
        self.assertEqual(report["overall"], {"runs": 2, "qualifying": 1, "rate": 0.5})
        self.assertEqual(report["recovery"], {"opportunities": 1, "successful": 1})
        self.assertEqual(report["flows"][0]["runs"], 1)
        self.assertEqual(report["flows"][0]["target"], 30)


if __name__ == "__main__":
    unittest.main()
