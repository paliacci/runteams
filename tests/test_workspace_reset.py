# -*- coding: utf-8 -*-
import os
from pathlib import Path
import tempfile
import unittest

import app
import app_secrets
import local_database
import product_store as store
from scripts.fixture_validation import publish_verified_employee


class WorkspaceResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-reset-")
        self.old_db = local_database.DB_PATH
        self.old_data = os.environ.get("RUNTEAMS_DATA")
        self.old_controller = app._CORE_CONTROLLER
        if self.old_controller is not None:
            self.old_controller.stop()
        os.environ["RUNTEAMS_DATA"] = self.tmp.name
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        store.init_product_db()
        app._CORE_CONTROLLER = None

    def tearDown(self):
        if app._CORE_CONTROLLER is not None:
            app._CORE_CONTROLLER.stop()
        app._CORE_CONTROLLER = self.old_controller
        local_database.DB_PATH = self.old_db
        if self.old_data is None:
            os.environ.pop("RUNTEAMS_DATA", None)
        else:
            os.environ["RUNTEAMS_DATA"] = self.old_data
        self.tmp.cleanup()

    @staticmethod
    def _employee_draft():
        return {
            "role": "完成工作并结构化交付。",
            "program": {"objective": "完成工作",
                        "steps": [{"id": "work", "instruction": "执行并交付"}],
                        "acceptance": ["结果可被下一名员工使用"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "gpt-test", "effort": "high"},
        }

    def _core_fixture(self, active=False):
        core = app.core_controller().core
        employee_id = core.create_employee("交付员", self._employee_draft())
        publish_verified_employee(core, employee_id)
        pipeline_id = core.create_pipeline("核心流水线", {
            "positions": [{"key": "position-1", "name": "交付",
                           "employee_id": employee_id}], "edges": []})
        task_id = core.create_task(pipeline_id, "核心任务", {"objective": "完成验证"})
        workflow_id = core.start_workflow(task_id)
        if not active:
            with core.repository.connect() as connection:
                connection.execute("UPDATE workflow_runs SET state='completed' WHERE id=?",
                                   (workflow_id,))
                connection.execute("UPDATE tasks SET state='completed' WHERE id=?", (task_id,))
        artifact_dir = Path(core.root) / "artifacts" / "fixture"
        workspace_dir = Path(core.root) / "workspaces" / "workflow-fixture"
        artifact_dir.mkdir(parents=True)
        workspace_dir.mkdir(parents=True)
        (artifact_dir / "result.txt").write_text("remove", encoding="utf-8")
        (workspace_dir / "work.txt").write_text("remove", encoding="utf-8")
        return core, pipeline_id

    def test_reset_removes_core_assets_and_preserves_global_configuration(self):
        core, pipeline_id = self._core_fixture()
        channel = store.get_default_channel()
        general_id = store.create_chat(
            channel["id"], "gpt-test", "high", pipeline_id, False,
            context={"context_type": "pipeline", "pipeline_id": pipeline_id})
        store.add_chat_message(general_id, "user", "保留普通对话")
        employee_session_id = store.create_agent_session(
            "employee_design", "员工设计", channel["id"], "gpt-test", "high", None,
            {"context_type": "worker", "target_employee_id": 1})
        store.add_chat_message(employee_session_id, "user", "删除员工设计对话")
        app_secrets.set_secret("GLOBAL_KEEP", "global-value")

        result = app.reset_workspace_data("清空工作区")

        self.assertTrue(result["ok"])
        self.assertEqual(result["removed"]["employees"], 1)
        self.assertEqual(result["removed"]["pipelines"], 1)
        self.assertEqual(result["removed"]["workflows"], 1)
        self.assertEqual(result["employee_conversations"], 1)
        self.assertEqual(core.package_catalog(), [])
        self.assertEqual(core.employee_catalog(), [])
        self.assertEqual(core.pipeline_catalog(), [])
        self.assertEqual(core.workflow_catalog(), [])
        self.assertFalse((Path(core.root) / "artifacts" / "fixture").exists())
        self.assertFalse((Path(core.root) / "workspaces" / "workflow-fixture").exists())
        self.assertTrue((Path(core.root) / "packages" / "objects").is_dir())
        preserved = store.get_chat(general_id)
        self.assertEqual(preserved["messages"][0]["text"], "保留普通对话")
        self.assertIsNone(preserved["scope_pipeline_id"])
        self.assertEqual(preserved["context"], {})
        self.assertIsNone(store.get_chat(employee_session_id))
        self.assertGreater(len(store.list_channels()), 0)
        self.assertIn("GLOBAL_KEEP", app_secrets.list_masked())

    def test_reset_rejects_nonterminal_core_workflow_without_deleting_assets(self):
        core, _pipeline_id = self._core_fixture(active=True)
        with self.assertRaisesRegex(RuntimeError, "仍有运行中的任务"):
            app.reset_workspace_data("清空工作区")
        self.assertEqual(len(core.employee_catalog()), 1)
        self.assertEqual(len(core.pipeline_catalog()), 1)
        self.assertEqual(len(core.workflow_catalog()), 1)

    def test_reset_requires_exact_confirmation(self):
        with self.assertRaisesRegex(ValueError, "确认文本"):
            app.reset_workspace_data("yes")

    def test_reset_is_available_as_a_guarded_user_operation(self):
        source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("清空工作区", source)
        self.assertIn("永久删除可执行技能、员工、流水线、任务、运行记录和交付文件", source)
        self.assertIn("员工设计对话、运行记录、交付文件和对应工作目录", source)
        self.assertIn("账号、普通对话、自动化、模型渠道和全局凭据会保留", source)
        self.assertIn("onclick=\"resetWorkspaceFromSettings()\"", source)
        self.assertIn("function resetWorkspaceFromSettings()", source)
        self.assertIn("const phrase='清空工作区'", source)
        self.assertIn("id=\"workspace_reset_submit\" disabled", source)
        self.assertIn("user_confirmation:confirmation", source)


if __name__ == "__main__":
    unittest.main()
