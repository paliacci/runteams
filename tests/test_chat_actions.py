# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import automation_store as automations
import chat
import local_database
import product_store
from scripts.fixture_validation import publish_verified_employee


class ChatActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-chat-actions-")
        self.old_db = local_database.DB_PATH
        self.old_core = os.environ.get("RUNTEAMS_CORE_DATA")
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        os.environ["RUNTEAMS_CORE_DATA"] = os.path.join(self.tmp.name, "core")
        product_store.init_product_db()
        chat._CORE_SERVICE = None
        chat._CORE_SERVICE_ROOT = ""

    def tearDown(self):
        chat._CORE_SERVICE = None
        chat._CORE_SERVICE_ROOT = ""
        local_database.DB_PATH = self.old_db
        if self.old_core is None:
            os.environ.pop("RUNTEAMS_CORE_DATA", None)
        else:
            os.environ["RUNTEAMS_CORE_DATA"] = self.old_core
        self.tmp.cleanup()

    def _published_employee(self, name="核心分析员"):
        core = chat._core_service()
        employee_id = core.create_employee(name, {
            "role": "分析输入并给出结构化结论",
            "program": {
                "objective": "完成分析",
                "steps": [{"id": "step-1", "instruction": "分析任务"}],
                "acceptance": ["结论清晰"],
            },
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        return employee_id

    def test_claude_agent_tools_merge_without_hiding_native_extensions(self):
        context = chat._agent_tool_context(
            12, 9, {"surface": "pipeline", "pipeline_id": 9},
            {"context_type": "pipeline", "intent": "manage"})
        args = chat._claude_agent_tool_args(
            context, ["runteams_get_context", "runteams_get_pipeline"])
        self.assertEqual(args[0], "--mcp-config")
        self.assertNotIn("--strict-mcp-config", args)
        config = json.loads(args[1])
        server = config["mcpServers"]["runteams-agent"]
        supplied = json.loads(server["env"]["RUNTEAMS_AGENT_TOOL_CONTEXT"])
        self.assertEqual(supplied["scope_pipeline_id"], 9)
        self.assertEqual(supplied["allowed_tools"],
                         ["runteams_get_context", "runteams_get_pipeline"])

    def test_one_agent_turn_keeps_every_change_proposal(self):
        envelope = lambda summary, action: {
            "protocol": "runteams.agent-tool/v1", "kind": "change_proposal",
            "message": summary,
            "data": {"summary": summary, "actions": [action], "count": 1},
        }
        merged = chat._native_change_proposal([
            envelope("保存全部机会", {"op": "create_employee_task"}),
            {"protocol": "runteams.agent-tool/v1", "kind": "context", "data": {}},
            envelope("继续项进入研发", {"op": "create_task"}),
        ])
        self.assertEqual([item["op"] for item in merged["data"]["actions"]],
                         ["create_employee_task", "create_task"])
        self.assertEqual(merged["data"]["count"], 2)

    def test_conversation_context_guidance_keeps_workflow_out_of_visible_starters(self):
        pipeline_create = chat._conversation_context_guidance({
            "context": {"context_type": "pipeline", "intent": "create"},
        })
        self.assertIn("要持续完成什么", pipeline_create)
        self.assertIn("最小可运行", pipeline_create)
        pipeline_manage = chat._conversation_context_guidance({
            "context": {"context_type": "pipeline", "intent": "manage"},
        })
        self.assertIn("管理现有流水线", pipeline_manage)
        self.assertIn("只改动实现用户目标所需的部分", pipeline_manage)
        self.assertIn("核对其 input interface", pipeline_manage)
        self.assertIn("禁止提交一个已知会在第一岗立即 needs_human/blocked", pipeline_manage)
        general = chat._conversation_context_guidance({
            "context": {"context_type": "general", "intent": "general"},
        })
        self.assertIn("创建员工", general)
        self.assertIn("一次性工作", general)
        automation_run = chat._conversation_context_guidance({
            "context": {"context_type": "automation", "intent": "run"},
        })
        self.assertIn("自动应用", automation_run)
        self.assertIn("不要要求用户再次确认", automation_run)

    def test_core_chat_actions_compose_published_employees_and_start_tasks(self):
        self._published_employee()
        core = chat._core_service()
        applied, _, pipeline_id = chat.apply_actions([{
            "op": "create_pipeline", "name": "核心分析流程",
            "positions": [{"name": "分析", "employee": "核心分析员"}],
        }])
        self.assertIn("新建流水线", applied[0])
        self.assertEqual(core.pipeline(pipeline_id)["name"], "核心分析流程")

        automation = automations.save_automation({
            "name": "核心定时分析", "prompt": "创建分析任务",
        })
        automation_run = automations.run_automation_now(automation["id"])
        applied, _, focus = chat.apply_actions([{
            "op": "create_task", "pipeline": "核心分析流程", "title": "分析样例",
            "objective": "分析这份样例", "context": "用于核心动作测试",
            "acceptance": ["输出清晰"],
        }], action_context={
            "automation_id": automation["id"],
            "automation_run_id": automation_run["id"],
        })
        self.assertEqual(focus, pipeline_id)
        self.assertIn("创建并启动任务", applied[0])
        self.assertEqual(core.workflow_catalog(1)[0]["state"], "ready")
        self.assertTrue(core.automation_has_open_work(automation["id"]))
        event = automations.get_automation_run(automation_run["id"])["events"][0]
        self.assertEqual(event["kind"], "workflow")
        self.assertEqual(event["content"]["pipeline_name"], "核心分析流程")

    def test_chat_core_service_can_validate_native_pipeline_extensions(self):
        """Chat/automation task creation must share the HTTP core's resolver."""
        core = chat._core_service()
        self.assertIsNotNone(core.native_dependency_resolver)
        self.assertIsNotNone(core.credential_names_provider)

    def test_agent_chat_document_actions_share_the_core_store(self):
        core = chat._core_service()
        applied, _, _ = chat.apply_actions([{
            "op": "create_document", "name": "需求挖掘总览",
            "document_key": "demand-overview",
            "content": "# 需求挖掘总览\n\n整理事实。",
            "data_view": {"kind": "opportunities"},
        }])
        self.assertIn("创建文档", applied[0])
        created = core.document_catalog(limit=20, query="demand-overview")[0]
        applied, _, _ = chat.apply_actions([{
            "op": "update_document", "document_key": "demand-overview",
            "content": "# 需求挖掘总览\n\n整理最新事实。",
        }])
        self.assertIn("更新文档", applied[0])
        current = core.document_catalog(limit=20, query="demand-overview")[0]
        self.assertEqual(current["revision"], 2)
        self.assertNotEqual(current["id"], created["id"])

    def test_recurring_tasks_skip_an_existing_dedupe_key(self):
        self._published_employee()
        core = chat._core_service()
        chat.apply_actions([{
            "op": "create_pipeline", "name": "机会发现",
            "positions": [{"name": "记录", "employee": "核心分析员"}],
        }])
        action = {
            "op": "create_task", "pipeline": "机会发现", "title": "账单异常解释",
            "objective": "整理机会大纲",
            "context": {"opportunity_key": "billing-anomaly-explainer"},
            "acceptance": ["生成大纲"],
            "dedupe_key": "billing-anomaly-explainer",
        }
        first, _, _ = chat.apply_actions([action])
        second, _, _ = chat.apply_actions([action])
        self.assertIn("创建并启动任务", first[0])
        self.assertIn("跳过重复机会", second[0])
        self.assertEqual(len(core.workflow_catalog()), 1)

    def test_automation_can_assign_deduplicated_work_directly_to_employee(self):
        employee_id = self._published_employee("机会分析员")
        core = chat._core_service()
        automation = automations.save_automation({
            "name": "机会挖掘", "prompt": "发现并保存机会",
        })
        automation_run = automations.run_automation_now(automation["id"])
        action = {
            "op": "create_employee_task", "employee": "机会分析员",
            "title": "Jira 审计证据", "objective": "保存分析结论并形成机会大纲",
            "context": {"opportunity_key": "jira-audit-evidence",
                        "analysis_decision": "continue"},
            "acceptance": ["来源可追溯"], "dedupe_key": "jira-audit-evidence",
        }
        first, _, focus = chat.apply_actions([action], action_context={
            "automation_id": automation["id"],
            "automation_run_id": automation_run["id"],
        })
        second, _, _ = chat.apply_actions([action])

        self.assertIsNone(focus)
        self.assertIn("交给「机会分析员」并启动任务", first[0])
        self.assertIn("跳过重复机会", second[0])
        workflow = core.employee_workflow_catalog(employee_id)[0]
        self.assertIsNone(workflow["snapshot_json"]["pipeline_id"])
        event = automations.get_automation_run(automation_run["id"])["events"][0]
        self.assertEqual(event["content"]["employee_name"], "机会分析员")

    def test_bot_handoff_hydrates_new_employee_work_order_from_history(self):
        employee_id = self._published_employee("记忆分析员")
        core = chat._core_service()
        projection = {
            "employee": {"id": employee_id, "name": "记忆分析员"},
            "recent_workflows": [{
                "state": "completed", "run_id": 17, "task_id": 16,
                "task_title": "上一项分析", "reference": "workflow_run:17",
                "task_payload": {"context": {
                    "opportunity_key": "source-key", "product": "jira",
                    "evidence": [{"title": "来源", "url": "https://example.com"}],
                    "analysis_decision": "continue",
                }},
                "employee_runs": [{"state": "completed", "summary": "已完成",
                                    "output": {"decision": "continue"},
                                    "issues": [], "artifacts": []}],
            }],
        }
        action = {
            "op": "create_employee_task", "employee": "记忆分析员",
            "title": "基于历史复核", "objective": "复核最近结果",
            "context": {"task_type": "memory_chain_validation"},
            "source_run_id": 17,
        }
        with patch.object(chat.bot_context, "build", return_value=projection):
            applied, _, _ = chat.apply_actions([action], action_context={
                "conversation_context": {"context_type": "worker", "intent": "work",
                                          "employee_release_id": 1},
            })
        self.assertIn("交给「记忆分析员」并启动任务", applied[0])
        task = core.task(next(item["id"] for item in core.employee_workflow_catalog(employee_id)
                               if item["task"]["title"] == "基于历史复核"))
        self.assertEqual(task["payload_json"]["context"]["product"], "jira")
        self.assertEqual(task["payload_json"]["context"]["upstream_position"],
                         "employee_bot_memory")
        self.assertEqual(task["payload_json"]["context"]["bot_memory"]["task_id"], 16)

    def test_pipeline_update_rebuilds_only_the_compact_position_array(self):
        first_id = self._published_employee("研究员")
        second_id = self._published_employee("审核员")
        core = chat._core_service()
        chat.apply_actions([{
            "op": "create_pipeline", "name": "研究流程",
            "positions": [{"name": "研究", "employee": "研究员"}],
        }])
        created = next(item for item in core.pipeline_catalog()
                       if item["name"] == "研究流程")
        definition = created["definition_json"]
        definition["states"] = [
            {"key": "state-pool-1", "name": "待定", "kind": "pool"},
            {"key": "state-done-2", "name": "完成", "kind": "done"},
        ]
        core.update_pipeline(created["id"], created["name"], definition)
        applied, _, focus = chat.apply_actions([{
            "op": "update_pipeline", "name": "研究流程", "to": "研究与审核",
            "positions": [
                {"name": "研究", "employee": "研究员"},
                {"name": "审核", "employee": "审核员"},
            ],
        }])
        pipeline = core.pipeline(focus)
        self.assertIn("更新流水线", applied[0])
        self.assertEqual(pipeline["name"], "研究与审核")
        self.assertEqual(
            [position["employee_id"] for position in pipeline["definition_json"]["positions"]],
            [first_id, second_id],
        )
        self.assertEqual(pipeline["definition_json"]["edges"], [{
            "from": "position-1", "to": "position-2",
        }])
        self.assertEqual(pipeline["definition_json"]["states"], [
            {"key": "state-pool-1", "name": "待定", "kind": "pool"},
            {"key": "state-done-2", "name": "完成", "kind": "done"},
        ])

    def test_product_action_gate_rejects_unknown_operations(self):
        applied, run_cards, focus = chat.apply_actions([{"op": "unsupported_operation"}])
        self.assertIn("当前核心不支持动作", applied[0])
        self.assertEqual(run_cards, [])
        self.assertIsNone(focus)

    def test_pipeline_requires_a_published_employee(self):
        core = chat._core_service()
        core.create_employee("未发布员工", {
            "role": "尚未发布",
            "program": {"objective": "处理任务", "steps": [{
                "id": "step-1", "instruction": "完成处理",
            }], "acceptance": ["处理完成"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        applied, _, focus = chat.apply_actions([{
            "op": "create_pipeline", "name": "无效流程",
            "positions": [{"name": "处理", "employee": "未发布员工"}],
        }])
        self.assertIn("尚未发布", applied[0])
        self.assertIsNone(focus)
        self.assertEqual(core.pipeline_catalog(), [])

    def test_core_business_writes_require_interactive_confirmation(self):
        for op in ("create_pipeline", "update_pipeline", "create_task",
                   "create_employee_task",
                   "upsert_automation", "delete_automation"):
            self.assertTrue(chat._consequential([{"op": op}]))

    def test_automation_actions_remain_in_the_formal_contract(self):
        action = {
            "op": "upsert_automation", "name": "每日机会复盘",
            "prompt": "读取最近工作并整理简报。", "schedule_kind": "daily",
            "schedule": {"time": "08:00"}, "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
        }
        applied, run_cards, focus = chat.apply_actions([action])
        self.assertIn("创建自动化", applied[0])
        self.assertEqual(run_cards, [])
        self.assertIsNone(focus)
        self.assertEqual(automations.list_automations()[0]["schedule"], {"time": "08:00"})
        applied, _, _ = chat.apply_actions([{
            "op": "delete_automation", "name": "每日机会复盘",
        }])
        self.assertIn("已移到垃圾箱", applied[0])
        self.assertEqual(automations.list_automations(), [])

    def test_core_state_context_contains_only_core_assets_and_automations(self):
        self._published_employee("上下文员工")
        chat.apply_actions([{
            "op": "create_pipeline", "name": "上下文流程",
            "positions": [{"name": "处理", "employee": "上下文员工"}],
        }])
        automations.save_automation({"name": "上下文自动化", "prompt": "执行工作"})
        context = chat._core_state_context()
        self.assertIn("上下文员工", context)
        self.assertIn("上下文流程", context)
        self.assertIn("上下文自动化", context)
        self.assertNotIn("旧 Card", context)
