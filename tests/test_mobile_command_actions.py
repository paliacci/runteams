import os
import tempfile
import unittest

import app
import automation_store as automations
import core_api
import local_database
import product_store as store
from scripts.fixture_validation import publish_verified_employee


class MobileCommandActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-mobile-actions-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "test.db")
        store.init_product_db()
        self.old_controller = app._CORE_CONTROLLER
        app._CORE_CONTROLLER = core_api.CoreController(os.path.join(self.tmp.name, "core"))

    def tearDown(self):
        app._CORE_CONTROLLER.stop()
        app._CORE_CONTROLLER = self.old_controller
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def core_workflow(self, result):
        core = app._CORE_CONTROLLER.core
        employee_id = core.create_employee("Mobile employee", {
            "role": "Complete work",
            "program": {"objective": "Complete work", "steps": [
                {"id": "work", "instruction": "Complete work"}],
                "acceptance": ["Return a result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        pipeline_id = core.create_pipeline("Mobile core", {
            "positions": [{"key": "work", "name": "Work",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(pipeline_id, "Mobile task", {"objective": "Complete"})
        workflow_id = core.start_workflow(task_id)
        core.run_workflow(workflow_id, lambda *_args: result)
        return core, workflow_id

    def test_mobile_response_requeues_same_core_workflow(self):
        core, workflow_id = self.core_workflow({
            "status": "needs_human", "summary": "", "issues": [], "artifacts": [],
            "output": {"question": "Which audience?"},
        })

        result = app._execute_mobile_command({
            "action": "intervention.perform",
            "target_id": "workflow:{}".format(workflow_id),
            "action_id": "respond",
            "response": "Founders",
        }, "1" * 32)

        self.assertTrue(result["ok"])
        self.assertEqual(core.workflow(workflow_id)["state"], "ready")

    def test_mobile_retry_revalidates_current_core_attention_actions(self):
        core, workflow_id = self.core_workflow({
            "status": "blocked", "summary": "", "issues": ["Missing source"],
            "artifacts": [], "output": {"reason": "Missing source"},
        })

        result = app._execute_mobile_command({
            "action": "intervention.perform",
            "target_id": "workflow:{}".format(workflow_id),
            "action_id": "retry",
        }, "1" * 32)

        self.assertTrue(result["ok"])
        self.assertEqual(core.workflow(workflow_id)["state"], "ready")
        with self.assertRaisesRegex(Exception, "已经完成"):
            app._execute_mobile_command({
                "action": "intervention.perform",
                "target_id": "workflow:{}".format(workflow_id),
                "action_id": "terminate",
            }, "1" * 32)

    def test_mobile_automation_retry_uses_failed_run_and_rejects_stale_target(self):
        channel = store.get_default_channel()
        automation = automations.save_automation({
            "name": "Mobile schedule", "prompt": "Run scheduled work",
            "channel_id": channel["id"], "model": "agent-test",
        })
        failed = automations.run_automation_now(automation["id"])
        automations.finish_automation_run(failed["id"], "failed", "Provider unavailable")
        target = "automation-intervention:{}".format(failed["id"])

        result = app._execute_mobile_command({
            "action": "intervention.perform",
            "target_id": target,
            "action_id": "retry",
        }, "1" * 32)

        self.assertTrue(result["ok"])
        self.assertTrue(result["run_id"].startswith("automation:"))
        self.assertEqual(automations.automation_attention_catalog(), [])
        with self.assertRaisesRegex(Exception, "已经完成"):
            app._execute_mobile_command({
                "action": "intervention.perform",
                "target_id": target,
                "action_id": "pause_automation",
            }, "1" * 32)

    def test_mobile_automation_pause_hides_derived_attention(self):
        automation = automations.save_automation({
            "name": "Pause schedule", "prompt": "Run scheduled work",
        })
        failed = automations.run_automation_now(automation["id"])
        automations.finish_automation_run(failed["id"], "failed", "Needs configuration")

        result = app._execute_mobile_command({
            "action": "intervention.perform",
            "target_id": "automation-intervention:{}".format(failed["id"]),
            "action_id": "pause_automation",
        }, "1" * 32)

        self.assertTrue(result["ok"])
        self.assertFalse(automations.get_automation(automation["id"])["enabled"])
        self.assertEqual(automations.automation_attention_catalog(), [])

    def test_mobile_core_workflow_cancel_is_atomic(self):
        core, workflow_id = self.core_workflow({
            "status": "needs_human", "summary": "", "issues": [], "artifacts": [],
            "output": {"question": "Continue?"},
        })

        result = app._execute_mobile_command({
            "action": "run.control",
            "target_id": "workflow:{}".format(workflow_id),
            "action_id": "cancel",
        }, "1" * 32)

        self.assertTrue(result["ok"])
        self.assertEqual(core.workflow(workflow_id)["state"], "canceled")


if __name__ == "__main__":
    unittest.main()
