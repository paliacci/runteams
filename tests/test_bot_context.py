# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import bot_context
import local_database
import product_store


class _FakeRepository:
    def connect(self):
        raise AssertionError("测试不应读取未绑定的发布版本")


class _FakeCore:
    repository = _FakeRepository()

    def employee(self, employee_id):
        return {
            "id": employee_id, "name": "分析员", "avatar": "a1",
            "draft_json": {"role": "分析", "program": {"objective": "找出原因"}},
            "active_release": {"id": 7, "version": 2, "digest": "release-digest",
                               "employee_id": employee_id},
        }

    def workflow_catalog(self, limit=100):
        return [{
            "id": 41, "state": "failed", "created_at": "2026-09-01",
            "updated_at": "2026-09-02", "snapshot_json": {
                "pipeline_id": 3, "pipeline_name": "机会分析",
                "definition": {"positions": [{"employee_id": 12}]},
            },
            "task": {"id": 9, "title": "检查机会"},
            "employee_runs": [{
                "id": 51, "position_key": "analysis", "employee_release_id": 7,
                "attempt": 1, "state": "failed", "output_json": {
                    "summary": "输入缺少证据", "issues": ["没有来源"],
                }, "artifacts": [],
            }],
        }]

    def pipeline(self, pipeline_id):
        return {"id": pipeline_id, "name": "机会分析"}


class _EvidenceRepository:
    def events_for_streams(self, streams):
        return [{
            "id": 88, "stream": "employee_run:51", "type": "agent.runtime_finished",
            "created_at": "2026-09-02", "actor_id": None,
            "correlation_id": "req-1", "source": "http",
            "data_json": {
                "transcript_ref": ".runteams/agent-transcript-51.jsonl",
                "transcript_sha256": "digest", "transcript_bytes": 42,
                "prompt_sha256": "prompt", "ignored": "not projected",
            },
        }]

    def verify_event_chain(self):
        return {"valid": True, "event_count": 88, "invalid_ids": []}


class _EvidenceCore(_FakeCore):
    repository = _EvidenceRepository()


class BotContextTests(unittest.TestCase):
    def test_latest_completed_work_is_a_compact_handoff(self):
        handoff = bot_context.latest_completed_work({
            "employee": {"id": 12, "name": "分析员"},
            "recent_workflows": [
                {"state": "running", "run_id": 42, "employee_runs": []},
                {"state": "completed", "run_id": 41, "task_id": 9,
                 "task_title": "检查机会", "reference": "workflow_run:41",
                 "evidence": {"reference": "audit:workflow:41",
                              "events": [{"reference": "event:88"}],
                              "integrity": {"valid": True}},
                 "task_payload": {"context": {"opportunity_key": "x", "product": "jira"}},
                 "employee_runs": [{"state": "completed", "summary": "完成",
                                    "output": {"decision": "continue"},
                                    "issues": [], "artifacts": []}]},
            ],
        })
        self.assertEqual(handoff["source"], "employee_bot_history")
        self.assertEqual(handoff["task_context"]["product"], "jira")
        self.assertEqual(handoff["result"]["output"]["decision"], "continue")
        self.assertIsNone(handoff["result"]["employee_release_id"])
        self.assertEqual(handoff["source_evidence"]["audit_ref"], "audit:workflow:41")

    def test_projection_is_bounded_and_read_only(self):
        projection = bot_context.build(_FakeCore(), 12)
        self.assertEqual(projection["schema"], "runteams.bot-context/v1")
        self.assertEqual(projection["employee"]["active_release"]["id"], 7)
        self.assertEqual(projection["recent_workflows"][0]["run_id"], 41)
        self.assertEqual(projection["recent_workflows"][0]["employee_runs"][0]["summary"],
                         "输入缺少证据")
        self.assertEqual(projection["access"]["write"], [])
        self.assertIn("credentials", projection["access"]["excluded"])

    def test_projection_includes_bounded_execution_evidence(self):
        projection = bot_context.build(_EvidenceCore(), 12)
        evidence = projection["recent_workflows"][0]["evidence"]
        self.assertTrue(evidence["integrity"]["valid"])
        self.assertEqual(evidence["events"][0]["type"], "agent.runtime_finished")
        self.assertEqual(evidence["events"][0]["data"]["transcript_bytes"], 42)
        self.assertNotIn("ignored", evidence["events"][0]["data"])

    def test_projection_keeps_history_across_employee_releases(self):
        class HistoryCore(_FakeCore):
            def workflow_catalog(self, limit=100):
                workflow = super().workflow_catalog(limit)[0]
                workflow["snapshot_json"]["definition"]["positions"][0]["key"] = "analysis"
                workflow["employee_runs"] = [
                    dict(workflow["employee_runs"][0], employee_release_id=4,
                         output_json={"summary": "旧版本结果", "output": {"version": 1}}),
                    dict(workflow["employee_runs"][0], employee_release_id=7,
                         output_json={"summary": "当前版本结果", "output": {"version": 2}}),
                ]
                return [workflow]

        projection = bot_context.build(HistoryCore(), 12)
        self.assertEqual(
            [item["summary"] for item in projection["recent_workflows"][0]["employee_runs"]],
            ["旧版本结果", "当前版本结果"])

    def test_structured_memory_filters_are_exact_and_scoped(self):
        class MemoryCore(_FakeCore):
            def workflow(self, workflow_id):
                return next((item for item in self.workflow_catalog()
                             if int(item["id"]) == int(workflow_id)), None)

        with self.assertRaisesRegex(ValueError, "运行作用域"):
            bot_context.build(MemoryCore(), 12, scope_type="run")
        with self.assertRaisesRegex(ValueError, "流水线作用域"):
            bot_context.build(MemoryCore(), 12, scope_type="pipeline")
        projection = bot_context.build(
            MemoryCore(), 12, scope_type="run", run_id=41,
            task_id=9, state="failed")
        self.assertEqual([item["run_id"] for item in projection["recent_workflows"]], [41])
        self.assertEqual(projection["scope"]["task_id"], 9)
        self.assertEqual(projection["retrieval"]["mode"], "structured_exact_scope")
        self.assertEqual(projection["retrieval"]["filters"]["state"], "failed")

    def test_product_store_persists_employee_binding(self):
        tmp = tempfile.TemporaryDirectory(prefix="runteams-bot-chat-")
        old_db = local_database.DB_PATH
        try:
            local_database.DB_PATH = os.path.join(tmp.name, "runteams.db")
            product_store.init_product_db()
            channel = product_store.get_default_channel()
            chat_id = product_store.create_chat(
                channel["id"], "model", "low", context={"context_type": "worker"},
                subject_type="employee", employee_id=12,
                employee_release_id=7, employee_release_digest="abc",
                scope_type="run", scope_run_id=41)
            saved = product_store.get_chat(chat_id)
            self.assertEqual(saved["subject_type"], "employee")
            self.assertEqual(saved["employee_id"], 12)
            self.assertEqual(saved["employee_release_digest"], "abc")
            self.assertEqual(saved["scope_type"], "run")
            self.assertEqual(saved["scope_run_id"], 41)
            product_store.update_chat_config(
                chat_id, channel["id"], "next-model", "medium", scope_pipeline_id=99)
            updated = product_store.get_chat(chat_id)
            self.assertEqual(updated["scope_type"], "run")
            self.assertEqual(updated["scope_run_id"], 41)
            self.assertIsNone(updated["scope_pipeline_id"])
            product_store.set_chat_employee_release(chat_id, 8, "new-digest")
            observed = product_store.get_chat(chat_id)
            self.assertEqual(observed["employee_release_id"], 8)
            self.assertEqual(observed["employee_release_digest"], "new-digest")
        finally:
            local_database.DB_PATH = old_db
            tmp.cleanup()

    def test_product_store_rejects_incomplete_employee_scope(self):
        tmp = tempfile.TemporaryDirectory(prefix="runteams-bot-scope-")
        old_db = local_database.DB_PATH
        try:
            local_database.DB_PATH = os.path.join(tmp.name, "runteams.db")
            product_store.init_product_db()
            channel = product_store.get_default_channel()
            with self.assertRaisesRegex(ValueError, "流水线作用域"):
                product_store.create_chat(
                    channel["id"], subject_type="employee", employee_id=12,
                    scope_type="pipeline")
            with self.assertRaisesRegex(ValueError, "运行作用域"):
                product_store.create_chat(
                    channel["id"], subject_type="employee", employee_id=12,
                    scope_type="run")
            chat_id = product_store.create_chat(
                channel["id"], subject_type="employee", employee_id=12,
                scope_type="global", scope_pipeline_id=99, scope_run_id=41)
            saved = product_store.get_chat(chat_id)
            self.assertIsNone(saved["scope_pipeline_id"])
            self.assertIsNone(saved["scope_run_id"])
        finally:
            local_database.DB_PATH = old_db
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
