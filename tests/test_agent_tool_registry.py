# -*- coding: utf-8 -*-
import unittest
from unittest import mock

import agent_tool_registry
import agent_tools_mcp


class AgentToolRegistryTests(unittest.TestCase):
    def choice_arguments(self):
        return {
            "question": "请选择测试范围",
            "options": [
                {"label": "当前流水线", "description": "只检查当前流水线"},
                {"label": "全部流水线", "description": "检查全部流水线"},
            ],
        }

    def test_registry_is_one_source_for_mcp_and_codex(self):
        mcp = agent_tool_registry.mcp_definitions()
        codex = agent_tool_registry.codex_dynamic_definitions()
        self.assertEqual([item["name"] for item in mcp], [
            "runteams_request_choice", "runteams_get_context",
            "runteams_get_bot_context",
            "runteams_list_pipelines", "runteams_get_pipeline",
            "runteams_get_task", "runteams_get_employee",
            "runteams_query_opportunities",
            "runteams_list_documents", "runteams_get_document",
            "runteams_propose_document",
            "runteams_propose_pipeline_change", "runteams_propose_task",
            "runteams_propose_tasks", "runteams_propose_automation",
            "runteams_present_employee_draft",
        ])
        self.assertEqual(codex[0]["type"], "function")
        self.assertEqual(codex[0]["name"], mcp[0]["name"])
        self.assertEqual(codex[0]["inputSchema"], mcp[0]["inputSchema"])
        codex[0]["inputSchema"]["properties"].clear()
        self.assertIn("question", agent_tool_registry.mcp_definitions()[0]["inputSchema"]["properties"])

    def test_bot_context_defaults_task_proposal_to_bound_employee(self):
        class Core:
            def employee(self, employee_id):
                return {"id": employee_id, "name": "分析员", "active_release_id": 7}

            def employee_catalog(self):
                return [self.employee(7)]

        with mock.patch.object(agent_tool_registry, "_core_service", return_value=Core()):
            result = agent_tool_registry.dispatch(
                "runteams_propose_task",
                {"title": "解释最近结果", "objective": "找出失败原因"},
                {"conversation_context": {"context_type": "worker", "intent": "work",
                                             "target_employee_id": 7}})
        self.assertEqual(result.data["actions"][0]["op"], "create_employee_task")
        self.assertEqual(result.data["actions"][0]["employee"], "分析员")

    def test_bot_context_cannot_mutate_pipeline_or_automation_configuration(self):
        context = {"conversation_context": {"context_type": "worker", "intent": "chat",
                                              "target_employee_id": 7}}
        with self.assertRaises(agent_tool_registry.AgentToolError):
            agent_tool_registry.dispatch(
                "runteams_propose_pipeline_change",
                {"operation": "update", "name": "机会分析"}, context)
        with self.assertRaises(agent_tool_registry.AgentToolError):
            agent_tool_registry.dispatch(
                "runteams_propose_automation",
                {"operation": "delete", "name": "每日复盘"}, context)

    def test_employee_bot_read_tools_cannot_cross_employee_boundary(self):
        class Core:
            def employee(self, employee_id):
                return {"id": int(employee_id), "name": "员工{}".format(employee_id),
                        "draft_json": {}, "active_release_id": 1}

            def employee_catalog(self):
                return [self.employee(7), self.employee(8)]

        context = {"conversation_context": {
            "context_type": "worker", "intent": "chat", "target_employee_id": 7,
        }}
        with mock.patch.object(agent_tool_registry, "_core_service", return_value=Core()):
            with self.assertRaises(agent_tool_registry.AgentToolError):
                agent_tool_registry.dispatch(
                    "runteams_get_employee", {"employee_id": 8}, context)

    def test_bot_context_tool_requires_employee_chat_binding(self):
        with self.assertRaises(agent_tool_registry.AgentToolError):
            agent_tool_registry.dispatch(
                "runteams_get_bot_context", {"employee_id": 7},
                {"view_context": {"employee_id": 7},
                 "conversation_context": {"context_type": "pipeline", "intent": "manage"}})

    def test_bot_context_tool_uses_exact_structured_filters(self):
        class Core:
            def employee(self, employee_id):
                return {"id": int(employee_id), "name": "分析员", "draft_json": {},
                        "active_release": None}

            def workflow_catalog(self, limit=100):
                return [{"id": 41, "task_id": 9, "state": "failed",
                         "created_at": "now", "updated_at": "now",
                         "snapshot_json": {"pipeline_id": 2, "pipeline_name": "分析",
                                            "definition": {"positions": [{"employee_id": 7}]},
                                            "task": {"id": 9, "title": "检查", "payload": {}}},
                         "task": {"id": 9, "title": "检查", "payload_json": {}},
                         "employee_runs": []}]

        context = {"conversation_context": {
            "context_type": "worker", "intent": "chat", "target_employee_id": 7,
        }}
        with mock.patch.object(agent_tool_registry, "_core_service", return_value=Core()):
            result = agent_tool_registry.dispatch(
                "runteams_get_bot_context", {"task_id": 9, "state": "failed"}, context)
        self.assertEqual(result.data["retrieval"]["mode"], "structured_exact_scope")
        self.assertEqual(result.data["retrieval"]["filters"]["task_id"], 9)
        self.assertEqual(result.data["recent_workflows"][0]["run_id"], 41)

    def test_employee_bot_context_does_not_project_unrelated_page_objects(self):
        class Core:
            def employee_catalog(self):
                return [{"id": 7, "name": "分析员"}, {"id": 8, "name": "其他员工"}]

            def employee(self, employee_id):
                return {"id": int(employee_id), "name": "员工{}".format(employee_id),
                        "draft_json": {}, "active_release_id": None}

            def pipeline(self, pipeline_id):
                return {"id": int(pipeline_id), "name": "其他流水线",
                        "definition_json": {"positions": [{"employee_id": 8}]}}

            def workflow(self, workflow_id):
                return {"id": int(workflow_id), "state": "completed",
                        "snapshot_json": {"pipeline_id": 3, "pipeline_name": "其他流水线",
                                           "definition": {"positions": [{"employee_id": 8}]},
                                           "task": {"id": 9, "title": "其他任务", "payload": {}}}}

        context = {"view_context": {"pipeline_id": 3, "workflow_id": 41, "employee_id": 8},
                   "conversation_context": {"context_type": "worker", "intent": "chat",
                                              "target_employee_id": 7}}
        with mock.patch.object(agent_tool_registry, "_core_service", return_value=Core()):
            result = agent_tool_registry.dispatch("runteams_get_context", {}, context)
        self.assertNotIn("pipeline", result.data["resolved"])
        self.assertNotIn("task", result.data["resolved"])
        self.assertEqual(result.data["resolved"]["employee"]["id"], 7)
        self.assertEqual(result.data["conversation"]["target_employee_id"], 7)

    def test_read_pipeline_tools_return_compact_structured_data(self):
        class Core:
            def employee_catalog(self):
                return [{"id": 3, "name": "分析员", "draft_json": {"role": "分析"},
                         "active_release_id": 7, "active_release": {"version": 2},
                         "has_unpublished_changes": False}]

            def pipeline_catalog(self):
                return [self.pipeline(9)]

            def pipeline(self, pipeline_id):
                return ({"id": 9, "name": "研究流程", "updated_at": "now",
                         "definition_json": {"positions": [{
                             "key": "research", "name": "研究", "employee_id": 3,
                         }]}} if int(pipeline_id) == 9 else None)

            def workflow_catalog(self, _limit=100):
                return [{
                    "id": 18, "task_id": 22, "state": "completed",
                    "updated_at": "now", "employee_runs": [],
                    "snapshot_json": {
                        "pipeline_id": 9, "pipeline_name": "研究流程",
                        "task": {"id": 22, "title": "账单异常解释", "payload": {
                            "context": {
                                "opportunity_key": "billing-anomaly-explainer",
                                "analysis_decision": "observe",
                                "target_user": "财务负责人", "jtbd": "解释账单异常",
                                "evidence": [{"url": "https://example.com/signal"}],
                            },
                        }},
                    },
                }]

        with mock.patch.object(agent_tool_registry, "_core_service", return_value=Core()):
            result = agent_tool_registry.dispatch(
                "runteams_get_pipeline", {}, {"view_context": {"pipeline_id": 9}})
        self.assertEqual(result.kind, "pipeline")
        self.assertEqual(result.data["pipeline"]["name"], "研究流程")
        self.assertEqual(result.data["pipeline"]["positions"][0]["employee_name"], "分析员")
        self.assertEqual(result.data["recent_tasks"][0]["opportunity_key"],
                         "billing-anomaly-explainer")
        self.assertEqual(result.data["recent_tasks"][0]["analysis_decision"], "observe")

    def test_codex_result_contains_the_structured_tool_payload(self):
        result = agent_tool_registry.AgentToolResult(
            "context", "已读取。", {"surface": "pipeline"})
        content = agent_tool_registry.codex_call_result(result)["contentItems"][0]["text"]
        self.assertIn('"kind":"context"', content)
        self.assertIn('"surface":"pipeline"', content)

    def test_document_tools_read_and_propose_without_direct_mutation(self):
        class Core:
            def document_catalog(self, limit=100, query=""):
                return [{"id": 7, "name": "需求挖掘总览", "document_key": "demand-overview",
                         "source": "agent_chat", "data_view": {"kind": "opportunities"}}]

            def document_detail(self, document_id, include_content=True):
                return {"id": int(document_id), "name": "需求挖掘总览",
                        "content": "# 总览" if include_content else "",
                        "source": "agent_chat", "data_view": {"kind": "opportunities"}}

        with mock.patch.object(agent_tool_registry, "_core_service", return_value=Core()):
            listed = agent_tool_registry.dispatch(
                "runteams_list_documents", {"query": "需求"})
            detail = agent_tool_registry.dispatch(
                "runteams_get_document", {"document_key": "demand-overview"})
        self.assertEqual(listed.kind, "document_list")
        self.assertEqual(listed.data["documents"][0]["id"], 7)
        self.assertEqual(listed.data["documents"][0]["internal_link"],
                         "runteams://document/7")
        self.assertEqual(detail.kind, "document")
        self.assertEqual(detail.data["document"]["content"], "# 总览")
        self.assertEqual(detail.data["document"]["internal_link"],
                         "runteams://document/7")

        proposal = agent_tool_registry.dispatch(
            "runteams_propose_document",
            {"operation": "create", "name": "机会总览",
             "document_key": "opportunity-overview", "content": "# 机会总览",
             "data_view": {"kind": "opportunities"}, "summary": "整理机会结果"},
        )
        self.assertEqual(proposal.kind, "change_proposal")
        self.assertEqual(proposal.data["actions"][0]["op"], "create_document")

    def test_choice_dispatch_returns_transport_neutral_result(self):
        result = agent_tool_registry.dispatch(
            "runteams_request_choice", self.choice_arguments(), {"chat_id": 42})
        self.assertEqual(result.kind, "choice")
        self.assertEqual(result.envelope()["protocol"], "runteams.agent-tool/v1")
        question = result.data["questions"][0]
        self.assertEqual(question["question"], "请选择测试范围")
        self.assertEqual([item["label"] for item in question["options"]],
                         ["当前流水线", "全部流水线"])

    def test_choice_rejects_malformed_or_duplicate_options(self):
        with self.assertRaises(agent_tool_registry.AgentToolError):
            agent_tool_registry.dispatch("runteams_request_choice", {
                "question": "请选择", "options": [{"label": "一个", "description": ""}],
            })

    def test_typed_proposal_creates_pending_action_without_writing(self):
        result = agent_tool_registry.dispatch("runteams_propose_task", {
            "pipeline": "研究流程", "title": "检查结果", "objective": "找出失败原因",
            "context": {"source": "chat"}, "acceptance": ["给出根因"],
        })
        self.assertEqual(result.kind, "change_proposal")
        self.assertEqual(result.data["actions"], [{
            "op": "create_task", "pipeline": "研究流程", "title": "检查结果",
            "objective": "找出失败原因", "context": {"source": "chat"},
            "acceptance": ["给出根因"],
        }])

    def test_task_proposal_can_pin_an_exact_history_run(self):
        result = agent_tool_registry.dispatch("runteams_propose_task", {
            "employee": "记忆分析员", "title": "复核历史结果",
            "objective": "解释指定运行的结果", "source_run_id": 41,
        })
        self.assertEqual(result.data["actions"][0]["source_run_id"], 41)

    def test_batch_task_proposal_keeps_every_discovered_item(self):
        result = agent_tool_registry.dispatch("runteams_propose_tasks", {
            "pipeline": "项目机会发现",
            "tasks": [{
                "title": "账单异常解释",
                "objective": "整理机会大纲",
                "context": {"opportunity_key": "billing-anomaly-explainer"},
                "acceptance": ["证据可追溯"],
                "dedupe_key": "billing-anomaly-explainer",
            }, {
                "title": "审计材料收集",
                "objective": "整理机会大纲",
                "context": {"opportunity_key": "audit-evidence-collector"},
                "acceptance": ["证据可追溯"],
                "dedupe_key": "audit-evidence-collector",
            }],
        })
        self.assertEqual(result.kind, "change_proposal")
        self.assertEqual(len(result.data["actions"]), 2)
        self.assertEqual(result.data["actions"][0]["dedupe_key"],
                         "billing-anomaly-explainer")

    def test_tasks_can_be_assigned_directly_to_one_employee(self):
        result = agent_tool_registry.dispatch("runteams_propose_tasks", {
            "employee": "机会分析员",
            "tasks": [{
                "title": "Jira 审计证据",
                "objective": "保存分析结论并形成机会大纲",
                "context": {"opportunity_key": "jira-audit-evidence"},
                "inputs": [{"name": "brief.md", "content": "# Jira 审计证据"}],
                "acceptance": ["来源可追溯"],
                "dedupe_key": "jira-audit-evidence",
            }],
        })
        self.assertEqual(result.data["actions"], [{
            "op": "create_employee_task", "employee": "机会分析员",
            "title": "Jira 审计证据",
            "objective": "保存分析结论并形成机会大纲",
            "context": {"opportunity_key": "jira-audit-evidence"},
            "inputs": [{"name": "brief.md", "content": "# Jira 审计证据"}],
            "acceptance": ["来源可追溯"],
            "dedupe_key": "jira-audit-evidence",
        }])
        with self.assertRaisesRegex(agent_tool_registry.AgentToolError, "只能提供一个"):
            agent_tool_registry.dispatch("runteams_propose_task", {
                "pipeline": "Forge 应用研发线", "employee": "机会分析员",
                "title": "错误去向", "objective": "不应接受两个去向",
            })

    def test_employee_read_includes_direct_production_work_history(self):
        class Core:
            def employee_catalog(self):
                return [self.employee(7)]

            def employee(self, employee_id):
                return ({"id": 7, "name": "机会分析员", "draft_json": {"role": "分析"},
                         "active_release_id": 20,
                         "active_release": {"version": 3, "role": "分析"},
                         "has_unpublished_changes": False}
                        if int(employee_id) == 7 else None)

            def employee_workflow_catalog(self, employee_id, limit=100):
                self.request = (employee_id, limit)
                return [{
                    "id": 31, "task_id": 41, "state": "completed",
                    "updated_at": "now", "employee_runs": [],
                    "snapshot_json": {"pipeline_id": None, "employee_id": 7,
                                      "task": {"id": 41, "title": "Jira 审计证据",
                                               "payload": {"context": {
                                                   "opportunity_key": "jira-audit-evidence",
                                                   "analysis_decision": "continue",
                                               }}}},
                }]

        core = Core()
        with mock.patch.object(agent_tool_registry, "_core_service", return_value=core):
            result = agent_tool_registry.dispatch("runteams_get_employee", {
                "name": "机会分析员", "task_limit": 500,
            })
        self.assertEqual(core.request, (7, 500))
        self.assertEqual(result.data["recent_tasks"][0]["opportunity_key"],
                         "jira-audit-evidence")

    def test_opportunity_query_reads_complete_result_projection(self):
        class Core:
            def opportunity_catalog(self, query="", limit=0, include_output=False):
                self.request = (query, limit, include_output)
                return [{"opportunity_key": "billing-anomaly-explainer",
                         "analysis_decision": "observe", "documents": []}]

        core = Core()
        with mock.patch.object(agent_tool_registry, "_core_service", return_value=core):
            result = agent_tool_registry.dispatch("runteams_query_opportunities", {
                "query": "账单", "include_output": True,
            })
        self.assertEqual(core.request, ("账单", 0, True))
        self.assertEqual(result.kind, "opportunity_list")
        self.assertTrue(result.data["complete_scan"])
        self.assertEqual(result.data["opportunities"][0]["opportunity_key"],
                         "billing-anomaly-explainer")

        with self.assertRaisesRegex(agent_tool_registry.AgentToolError, "未知参数"):
            agent_tool_registry.dispatch("runteams_query_opportunities", {"sql": "SELECT 1"})

    def test_employee_draft_tool_returns_reviewable_draft(self):
        result = agent_tool_registry.dispatch("runteams_present_employee_draft", {
            "draft": {
                "name": "研究员", "goal": "完成研究", "instructions": "只做事实研究",
                "program": {"objective": "形成结论", "steps": [{
                    "id": "step-1", "name": "研究", "instructions": "核验事实",
                }], "delivery": {"acceptance_criteria": "结论可追溯"},
                    "deliverables": [{"path": "REPORT.md", "name": "研究报告",
                                      "required": True}]},
                "capabilities": [],
                "interface": {"input": {"type": "object"},
                              "output": {"type": "object"}},
                "tests": [{
                    "id": "completed", "name": "正常完成",
                    "work_order": {"objective": "完成研究", "context": {},
                                   "inputs": [], "expected_output": {},
                                   "acceptance": ["结论可追溯"]},
                    "expected_status": "completed",
                    "covers": ["result.completed"],
                }],
            },
        })
        self.assertEqual(result.kind, "employee_draft")
        self.assertTrue(result.data["draft_ready"])
        self.assertEqual(result.data["draft"]["name"], "研究员")
        self.assertEqual(result.data["draft"]["program"]["deliverables"][0]["path"],
                         "REPORT.md")
        with self.assertRaisesRegex(agent_tool_registry.AgentToolError, "input/output"):
            agent_tool_registry.dispatch("runteams_present_employee_draft", {
                "draft": {"name": "不完整员工", "instructions": "研究",
                          "program": {"steps": [{"id": "work"}]},
                          "tests": [{"covers": ["result.completed"]}]},
            })
        with self.assertRaises(agent_tool_registry.AgentToolError):
            agent_tool_registry.dispatch("runteams_request_choice", {
                "question": "请选择", "options": [
                    {"label": "重复", "description": "A"},
                    {"label": "重复", "description": "B"},
                ],
            })

    def test_mcp_transport_lists_and_calls_registered_tool(self):
        listed = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        self.assertEqual(listed["result"]["tools"][0]["name"],
                         "runteams_request_choice")
        called = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "runteams_request_choice",
                       "arguments": self.choice_arguments()},
        })
        result = called["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["kind"], "choice")
        self.assertEqual(result["structuredContent"]["data"]["questions"][0]["id"],
                         "choice")

    def test_mcp_transport_can_limit_tools_for_one_provider_session(self):
        context = {"allowed_tools": ["runteams_get_context"]}
        listed = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {},
        }, context)
        self.assertEqual([item["name"] for item in listed["result"]["tools"]],
                         ["runteams_get_context"])
        blocked = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "runteams_request_choice",
                       "arguments": self.choice_arguments()},
        }, context)
        self.assertTrue(blocked["result"]["isError"])
        self.assertIn("没有启用", blocked["result"]["content"][0]["text"])

    def test_unknown_mcp_tool_is_a_tool_error_not_transport_failure(self):
        called = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "runteams_missing", "arguments": {}},
        })
        self.assertTrue(called["result"]["isError"])
        self.assertIn("不支持工具", called["result"]["content"][0]["text"])

    def test_malformed_mcp_call_does_not_poison_the_next_native_call(self):
        malformed = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "runteams_request_choice",
                       "arguments": {"question": "请选择", "options": []}},
        })
        recovered = agent_tools_mcp.dispatch_rpc({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "runteams_request_choice",
                       "arguments": self.choice_arguments()},
        })

        self.assertTrue(malformed["result"]["isError"])
        self.assertIn("2～5", malformed["result"]["content"][0]["text"])
        self.assertFalse(recovered["result"]["isError"])
        self.assertEqual(recovered["result"]["structuredContent"]["kind"], "choice")


if __name__ == "__main__":
    unittest.main()
