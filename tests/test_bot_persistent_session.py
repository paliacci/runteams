# -*- coding: utf-8 -*-
import copy
import os
import tempfile
import unittest

import bot_context
import local_database
import product_store
from runteams_core import RunTeamsCore
from scripts.fixture_validation import publish_verified_employee


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BotPersistentSessionTests(unittest.TestCase):
    def setUp(self):
        self.core_tmp = tempfile.TemporaryDirectory(prefix="runteams-bot-e2e-core-")
        self.store_tmp = tempfile.TemporaryDirectory(prefix="runteams-bot-e2e-store-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.store_tmp.name, "runteams.db")
        self.core = RunTeamsCore(self.core_tmp.name)
        self.package = self.core.import_package(
            "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
        product_store.init_product_db()

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        self.store_tmp.cleanup()
        self.core_tmp.cleanup()

    def _create_employee(self, objective):
        return self.core.create_employee("长期分析 Bot", {
            "role": objective,
            "program": {"objective": objective,
                         "steps": [{"id": "work", "instruction": "完成并交付结构化结果"}],
                         "acceptance": ["结果可追溯"]},
            "capabilities": [{"package_id": self.package["package_id"],
                               "capability_id": "validate-brief"}],
            "runtime": {"channel": "codex", "model": "gpt-test", "effort": "high"},
        })

    def _run_pipeline_work(self, employee_id, title):
        pipeline_id = self.core.create_pipeline("Bot 长期记忆验收", {
            "positions": [{"key": "work", "employee_id": employee_id}],
            "edges": [],
        })
        task_id = self.core.create_task(
            pipeline_id, title, {"objective": title, "context": {"source": "e2e"}})
        workflow_id = self.core.start_workflow(task_id)
        self.core.run_workflow(
            workflow_id,
            lambda _employee, _order, _emit: {
                "status": "completed", "summary": "已完成", "output": {"title": title},
                "artifacts": [], "issues": [],
            },
            max_attempts=1,
        )
        return pipeline_id, task_id, workflow_id

    def test_same_bot_chat_survives_release_rollover_and_preserves_run_provenance(self):
        employee_id = self._create_employee("解释历史结果 v1")
        release_v1 = publish_verified_employee(self.core, employee_id)
        _pipeline_id, _task_id, workflow_v1 = self._run_pipeline_work(
            employee_id, "解释第一次结果")
        frozen_v1 = copy.deepcopy(self.core.workflow(workflow_v1)["snapshot_json"])

        channel = product_store.get_default_channel()
        chat_id = product_store.create_chat(
            channel["id"], "model", "low",
            context={"context_type": "worker", "intent": "chat",
                     "target_employee_id": employee_id},
            subject_type="employee", employee_id=employee_id,
            employee_release_id=release_v1["release_id"],
            employee_release_digest=release_v1["digest"],
        )
        first = bot_context.build(self.core, employee_id,
                                  release_id=release_v1["release_id"])
        self.assertIn(workflow_v1, [item["run_id"] for item in first["recent_workflows"]])
        self.assertEqual(first["recent_workflows"][0]["employee_runs"][0]["employee_release_id"],
                         release_v1["release_id"])

        employee = self.core.employee(employee_id)
        employee["draft_json"]["role"] = "解释历史结果 v2"
        employee["draft_json"]["program"]["objective"] = "解释历史结果 v2"
        self.core.update_employee(employee_id, employee["name"], employee["draft_json"])
        release_v2 = publish_verified_employee(self.core, employee_id)
        self.assertNotEqual(release_v1["release_id"], release_v2["release_id"])

        product_store.set_chat_employee_release(
            chat_id, release_v2["release_id"], release_v2["digest"])
        same_chat = product_store.get_chat(chat_id)
        self.assertEqual(same_chat["id"], chat_id)
        self.assertEqual(same_chat["employee_id"], employee_id)
        self.assertEqual(same_chat["employee_release_id"], release_v2["release_id"])

        second = bot_context.build(self.core, employee_id,
                                   release_id=release_v2["release_id"])
        history = {item["run_id"]: item for item in second["recent_workflows"]}
        self.assertIn(workflow_v1, history)
        self.assertEqual(history[workflow_v1]["employee_runs"][0]["employee_release_id"],
                         release_v1["release_id"])

        _new_pipeline_id, _new_task_id, workflow_v2 = self._run_pipeline_work(
            employee_id, "使用当前版本重新处理")
        snapshot_v2 = self.core.workflow(workflow_v2)["snapshot_json"]
        self.assertEqual(snapshot_v2["definition"]["positions"][0]["employee_release_id"],
                         release_v2["release_id"])
        self.assertEqual(self.core.workflow(workflow_v1)["snapshot_json"], frozen_v1)


if __name__ == "__main__":
    unittest.main()
