# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

import employee_sessions
import local_database
import product_store as store
from runteams_core import RunTeamsCore


class EmployeeSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-employee-session-tests-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        store.init_product_db()
        self.channel = dict(store.get_default_channel())
        self.runtime = {"channel_id": self.channel["id"], "model": "test-model",
                        "reasoning_effort": "high"}

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def _runtime_patch(self):
        return mock.patch.object(
            employee_sessions.model_channels, "normalize_selection",
            return_value=("test-model", "high"))

    def test_session_uses_explicit_employee_kind_and_hides_frozen_snapshot(self):
        with self._runtime_patch():
            session = employee_sessions.create_session(self.runtime)
        self.assertEqual(session["kind"], "employee_design")
        self.assertIn("snapshot", session["context"])
        self.assertNotIn("snapshot", employee_sessions.public_session(session)["context"])

    def test_employee_goal_never_falls_back_to_role(self):
        draft = employee_sessions._employee_draft({
            "name": "核查员",
            "draft_json": {"role": "逐项核查事实", "program": {}},
        })
        self.assertEqual(draft["instructions"], "逐项核查事实")
        self.assertEqual(draft["goal"], "")
        self.assertEqual(draft["program"]["objective"], "")
        self.assertFalse(employee_sessions._complete_draft({
            **draft,
            "interface": {"input": {}, "output": {}},
        }))

    def test_employee_design_prompt_separates_goal_from_role(self):
        instructions = employee_sessions._instructions({
            "context": {"phase": "design", "snapshot": "{}"}, "draft": {},
        }, [])
        self.assertIn("目标回答“最终要取得什么结果”", instructions)
        self.assertIn("不得把同一段文字复制到两者", instructions)

    def test_validation_generation_gets_the_long_running_timeout(self):
        self.assertEqual(employee_sessions._turn_timeout(
            {"context": {"phase": "validation"}}, []), 900)
        self.assertEqual(employee_sessions._turn_timeout(
            {"context": {"phase": "design"}}, []), employee_sessions.TIMEOUT_SEC)

    def test_ready_draft_applies_to_core_employee_only(self):
        response = json.dumps({
            "reply": "员工草稿已经整理好。", "draft_ready": True,
            "draft": {
                "name": "证据核查员", "goal": "形成可复核结论",
                "instructions": "逐项核实声明并附上来源。",
                "program": {
                    "objective": "核实声明",
                    "steps": [{"id": "verify", "name": "逐项核实",
                               "instructions": "逐项检查并记录来源"}],
                    "delivery": {"acceptance_criteria": "每项有结论\n每项有来源"},
                    "deliverables": [{"path": "REPORT.md", "name": "核查报告",
                                      "required": True}],
                },
                "capabilities": [],
                "interface": {"input": {"type": "object"},
                              "output": {"type": "object"}},
                "tests": [{
                    "id": "completed", "name": "正常完成",
                    "work_order": {"objective": "核实声明", "context": {},
                                   "inputs": [], "expected_output": {},
                                   "acceptance": ["每项有结论"]},
                    "expected_status": "completed",
                    "covers": ["result.completed"],
                }],
            },
        }, ensure_ascii=False)
        with self._runtime_patch():
            session = employee_sessions.create_session(self.runtime)
            with mock.patch.object(employee_sessions, "run_agent",
                                   return_value=SimpleNamespace(text=response, meta={})):
                result = employee_sessions.run_turn(session["id"], "创建一名核查员工")
            applied = employee_sessions.apply_ready_draft(session["id"], result["draft"])

        employee = RunTeamsCore(store.core_data_root()).employee(applied["employee_id"])
        self.assertTrue(result["draft_ready"])
        self.assertEqual(employee["name"], "证据核查员")
        self.assertEqual(employee["draft_json"]["program"]["steps"][0]["id"], "verify")
        self.assertEqual(employee["draft_json"]["program"]["deliverables"], [{
            "path": "REPORT.md", "name": "核查报告", "required": True,
        }])

    def test_native_employee_draft_uses_existing_review_and_apply_flow(self):
        draft = {
            "name": "原生工具研究员", "goal": "形成结论",
            "instructions": "核实事实并给出来源。",
            "program": {
                "objective": "形成可复核结论",
                "steps": [{"id": "research", "name": "研究",
                           "instructions": "读取材料并核验"}],
                "delivery": {"acceptance_criteria": "结论可复核"},
            },
            "interface": {
                "input": {"type": "object", "required": ["objective"]},
                "output": {"type": "object"},
            },
            "capabilities": [],
            "tests": [{
                "id": "completed", "name": "正常完成",
                "work_order": {"objective": "形成结论", "context": {},
                               "inputs": [], "expected_output": {},
                               "acceptance": ["结论可复核"]},
                "expected_status": "completed",
                "covers": ["result.completed"],
            }],
        }
        envelope = {
            "protocol": "runteams.agent-tool/v1", "kind": "employee_draft",
            "message": "草稿已准备好。",
            "data": {"reply": "草稿已准备好。", "draft": draft,
                     "draft_ready": True},
        }
        with self._runtime_patch():
            session = employee_sessions.create_session(self.runtime)
            with mock.patch.object(employee_sessions, "run_agent", return_value=SimpleNamespace(
                    text='{"reply":"草稿已准备好","draft_ready":false}',
                    meta={"native_tool_results": [envelope]})):
                result = employee_sessions.run_turn(session["id"], "创建研究员工")

        self.assertTrue(result["draft_ready"])
        self.assertEqual(result["draft"]["name"], "原生工具研究员")
        self.assertEqual(store.get_chat(session["id"])["status"], "ready")

    def test_ai_employee_design_does_not_persist_validation_cases(self):
        draft = {
            "name": "测试设计员", "goal": "稳定完成交付",
            "instructions": "根据工作单完成结构化交付。",
            "program": {
                "objective": "完成工作",
                "steps": [{"id": "work", "name": "处理", "instructions": "处理工作单"}],
                "delivery": {"acceptance_criteria": "结果可交接"},
            },
            "capabilities": [],
            "interface": {"input": {"type": "object"},
                          "output": {"type": "object"}},
            "tests": [{
                "id": "missing-input", "name": "缺少信息",
                "work_order": {"objective": "处理不完整输入", "context": {},
                               "inputs": [], "expected_output": {},
                               "acceptance": ["信息不足时请求补充"]},
                "expected_status": "needs_human",
                "covers": ["result.needs_human", "handoff.upstream.missing"],
            }],
        }
        envelope = {
            "protocol": "runteams.agent-tool/v1", "kind": "employee_draft",
            "message": "草稿已准备好。",
            "data": {"reply": "已补充验证用例。", "draft": draft,
                     "draft_ready": True},
        }
        with self._runtime_patch():
            session = employee_sessions.create_session(self.runtime)
            with mock.patch.object(employee_sessions, "run_agent", return_value=SimpleNamespace(
                    text="", meta={"native_tool_results": [envelope]})):
                result = employee_sessions.run_turn(session["id"], "补充测试用例")
            applied = employee_sessions.apply_ready_draft(session["id"], result["draft"])

        employee = RunTeamsCore(store.core_data_root()).employee(applied["employee_id"])
        self.assertEqual(result["draft"]["tests"][0]["expected_status"], "needs_human")
        self.assertEqual(employee["draft_json"]["tests"], [])

    def test_validation_phase_only_applies_tests_to_finalized_employee(self):
        core = RunTeamsCore(store.core_data_root())
        employee_id = core.create_employee("交付员", {
            "role": "按最终契约完成交付。",
            "program": {"objective": "完成交付", "steps": [{
                "id": "work", "instruction": "处理并交付",
            }], "acceptance": ["结果可交接"]},
            "interface": {"input": {"type": "object"},
                          "output": {"type": "object"}},
            "capabilities": [], "tests": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        with self._runtime_patch():
            session = employee_sessions.create_session(
                self.runtime, employee_id, phase="validation")
        draft = employee_sessions._employee_draft(core.employee(employee_id), include_tests=False)
        draft["instructions"] = "验证 Agent 不得写入这项修改。"
        draft["tests"] = [{
            "id": "completed", "name": "正常完成",
            "work_order": {"objective": "完成交付", "context": {
                "upstream_position": "source", "upstream_output": {"ready": True}},
                "inputs": [], "expected_output": {}, "acceptance": ["结果可交接"]},
            "expected_status": "completed",
            "covers": ["input.valid", "output.valid", "program.work",
                       "result.completed", "handoff.upstream.valid",
                       "handoff.output.valid"],
        }, {
            "id": "blocked", "name": "业务阻塞",
            "work_order": {"objective": "处理阻塞", "context": {}, "inputs": [],
                           "expected_output": {}, "acceptance": []},
            "expected_status": "blocked",
            "covers": ["result.blocked", "handoff.upstream.missing"],
        }, {
            "id": "needs-human", "name": "无效上游",
            "work_order": {"objective": "请求补充", "context": {
                "upstream_position": "source"}, "inputs": [],
                "expected_output": {}, "acceptance": []},
            "expected_status": "needs_human",
            "covers": ["result.needs_human", "handoff.upstream.invalid"],
        }, {
            "id": "failed", "name": "运行失败",
            "work_order": {"objective": "触发失败", "context": {}, "inputs": [],
                           "expected_output": {}, "acceptance": []},
            "expected_status": "failed", "covers": ["result.failed"],
        }]
        store.update_agent_session_draft(session["id"], draft, "ready")
        applied = employee_sessions.apply_ready_draft(session["id"], draft)

        employee = core.employee(applied["employee_id"])
        self.assertEqual(employee["draft_json"]["role"], "按最终契约完成交付。")
        self.assertEqual(len(employee["draft_json"]["tests"]), 4)

        with self._runtime_patch():
            stale_session = employee_sessions.create_session(
                self.runtime, employee_id, phase="validation")
        stale_draft = employee_sessions._employee_draft(
            core.employee(employee_id), include_tests=True)
        changed = dict(core.employee(employee_id)["draft_json"])
        changed["role"] = "定稿已经变更。"
        core.update_employee(employee_id, "交付员", changed)
        store.update_agent_session_draft(stale_session["id"], stale_draft, "ready")
        with self.assertRaisesRegex(ValueError, "定稿已变更"):
            employee_sessions.apply_ready_draft(stale_session["id"], stale_draft)


if __name__ == "__main__":
    unittest.main()
