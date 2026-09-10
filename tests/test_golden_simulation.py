# -*- coding: utf-8 -*-
import unittest

from golden_simulation import simulate_golden_pipeline


class GoldenSimulationTests(unittest.TestCase):
    def test_non_code_pipeline_reaches_human_gate_and_final_delivery(self):
        report = simulate_golden_pipeline()

        self.assertEqual(report["first_workflow_status"], "needs_human")
        self.assertEqual(report["human_gate"]["position"], "初稿产出")
        self.assertEqual(report["human_gate"]["open_items"], 1)
        self.assertEqual(report["human_gate"]["kind"], "information")
        self.assertEqual(report["resumed_workflow_status"], "completed")
        self.assertEqual(report["final_position"], "最终交付")
        self.assertEqual(report["final_status"], "completed")
        self.assertEqual(report["open_attention_after_completion"], 0)

        self.assertEqual(report["employee_run_count"], 5)
        self.assertEqual([item["state"] for item in report["timeline"]],
                         ["completed", "completed", "needs_human", "completed", "completed"])
        self.assertEqual(report["artifact_count"], 1)

        self.assertEqual([item["position"] for item in report["handoff_trace"]],
                         ["需求拆解", "调研执行", "初稿产出", "初稿产出", "最终交付"])
        self.assertTrue(report["handoff_trace"][3]["has_human_response"])
        self.assertTrue(all(item["has_upstream"] for item in report["handoff_trace"][1:3]))
        self.assertIn("有条件推进", report["final_delivery"])


if __name__ == "__main__":
    unittest.main()
