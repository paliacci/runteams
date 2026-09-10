from pathlib import Path
import tempfile
import unittest
from unittest import mock

import agent_tool_registry
from employee_repair import AgentEmployeeRepairRuntime


class EmployeeRepairRuntimeTests(unittest.TestCase):
    def test_codex_repair_is_headless_and_returns_only_the_native_draft(self):
        with tempfile.TemporaryDirectory(prefix="runteams-repair-") as root:
            employee = {
                "id": 7, "name": "Reviewer",
                "draft_json": {
                    "role": "Review work",
                    "program": {"objective": "Review work", "steps": [{
                        "id": "work", "instruction": "Review the result",
                    }], "acceptance": ["Correct"]},
                    "interface": {"input": {"type": "object"},
                                  "output": {"type": "object"}},
                    "capabilities": [],
                    "runtime": {"channel": "codex", "model": "gpt-test",
                                "effort": "high"},
                    "tests": [{"id": "completed", "name": "Completes",
                               "work_order": {"objective": "Review"},
                               "expected_status": "completed",
                               "covers": ["result.completed"]}],
                },
            }
            repaired = {
                "name": "Reviewer", "instructions": "Review and verify work",
                "program": {"objective": "Review work", "steps": [{
                    "id": "work", "name": "Review", "instructions":
                    "Review and verify the result",
                }], "delivery": {"acceptance_criteria": "Correct"}},
                "interface": employee["draft_json"]["interface"],
                "capabilities": [], "tests": employee["draft_json"]["tests"],
            }
            envelope = {"protocol": agent_tool_registry.PROTOCOL,
                        "kind": "employee_draft",
                        "data": {"draft": repaired}}
            channel = {"provider": "codex", "enabled": 1,
                       "executable": str(Path(root) / "codex")}
            runtime = AgentEmployeeRepairRuntime(root, channel_resolver=lambda _key: channel)
            with mock.patch("employee_repair.model_channels.normalize_selection",
                            return_value=("gpt-test", "high")), mock.patch(
                                "employee_repair.codex_threads.run_turn",
                                return_value={"native_tool_results": [envelope]}) as run_turn:
                result = runtime(
                    employee,
                    [{"test": employee["draft_json"]["tests"][0],
                      "failed_samples": []}],
                    [{"test": {"id": "already-passing"},
                      "passing_samples": [{"actual_status": "completed"}]}])

            self.assertEqual(result, repaired)
            arguments, keywords = run_turn.call_args
            self.assertEqual(arguments[1], "")
            self.assertFalse(keywords["extensions_enabled"])
            self.assertEqual(keywords["tool_names"],
                             ["runteams_present_employee_draft"])
            self.assertFalse(keywords["require_final_text"])
            self.assertIn("已通过场景与真实样本", arguments[3])
            self.assertIn("already-passing", arguments[3])
            self.assertIn("callable_tools", arguments[3])
            self.assertIn("skill 是说明和资源", arguments[3])
            self.assertNotIn("on_thread", keywords)
            self.assertIsNone(keywords["tool_context"]["chat_id"])


if __name__ == "__main__":
    unittest.main()
