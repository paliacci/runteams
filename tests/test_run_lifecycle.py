# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import app
import automation_store as automations
from adapter_base import EXECUTION_INTERNAL_ANALYSIS
from errors import Cancelled
from runner import run_agent
import scheduler
import local_database
import product_store as store
from scripts.fixture_validation import publish_verified_employee


class _SlowAdapter:
    name = "slow-test"

    def build_argv(self, prompt, **_kwargs):
        code = "import time\nprint('started', flush=True)\ntime.sleep(30)\nprint('done', flush=True)"
        return [sys.executable, "-u", "-c", code]

    def env(self, env):
        return env

    def consume(self, lines, on_activity):
        out = []
        for line in lines:
            out.append(line)
            on_activity.on_event({"kind": "work_delta", "id": "slow",
                                  "delta": line.strip()})
        return "".join(out), False, {}

    def classify_error(self, _blob, _is_error, _returncode):
        return None


class RunLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-runs-")
        self.old_db = local_database.DB_PATH
        self.old_data = os.environ.get("RUNTEAMS_DATA")
        os.environ["RUNTEAMS_DATA"] = self.tmp.name
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        store.init_product_db()

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        if self.old_data is None:
            os.environ.pop("RUNTEAMS_DATA", None)
        else:
            os.environ["RUNTEAMS_DATA"] = self.old_data
        self.tmp.cleanup()




























    def test_automation_persists_only_prompt_runtime_and_schedule(self):
        self.assertFalse(hasattr(store, "save_automation"))
        self.assertFalse(hasattr(store, "DB_PATH"))
        self.assertNotIn("store", automations.__dict__)
        self.assertIs(automations.conn, local_database.conn)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS automations", store.PRODUCT_SCHEMA)
        channel = store.get_default_channel()
        automation = automations.save_automation({
            "name": "Daily brief", "prompt": "汇总 {{date}} 的产品活动",
            "schedule_kind": "daily", "schedule": {"time": "08:30"},
            "channel_id": channel["id"], "model": "gpt-test", "reasoning_effort": "high",
        })
        self.assertEqual(automation["prompt"], "汇总 {{date}} 的产品活动")
        self.assertEqual(automation["schedule"], {"time": "08:30"})
        self.assertEqual(automation["channel_id"], channel["id"])
        self.assertNotIn("pipeline_id", automation)
        self.assertNotIn("task_title", automation)

    def test_due_automation_queues_immutable_agent_snapshot(self):
        automation = automations.save_automation({
            "name": "Demand patrol", "prompt": "检查 {{date}} 的机会池", "interval_sec": 60,
        })
        with store.conn() as connection:
            connection.execute("UPDATE automations SET next_run_at='2000-01-01 00:00:00' WHERE id=?",
                               (automation["id"],))
        queued = automations.materialize_due_automations()
        self.assertEqual(queued[0]["status"], "queued")
        job = automations.claim_next_automation_run()
        self.assertEqual(job["name"], "Demand patrol")
        self.assertRegex(job["prompt"], r"检查 \d{4}-\d{2}-\d{2} 的机会池")
        automations.save_automation({**automation, "prompt": "后来修改的内容"}, automation["id"])
        self.assertNotEqual(job["prompt"], "后来修改的内容")

    def test_automation_rejects_overlapping_occurrences(self):
        automation = automations.save_automation({
            "name": "Every occurrence", "prompt": "检查产品状态",
            "schedule_kind": "weekly", "schedule": {"time": "09:00", "weekdays": [0, 4]},
        })
        first = automations.run_automation_now(automation["id"])
        self.assertEqual(first["status"], "queued")
        with self.assertRaisesRegex(ValueError, "上一项自动化工作尚未结束"):
            automations.run_automation_now(automation["id"])


    def test_core_open_work_callback_blocks_the_next_occurrence(self):
        automation = automations.save_automation({
            "name": "No duplicate core work", "prompt": "创建一项核心工作", "interval_sec": 60,
        })
        with store.conn() as connection:
            connection.execute("UPDATE automations SET next_run_at='2000-01-01 00:00:00' WHERE id=?",
                               (automation["id"],))
        occurrence = automations.materialize_due_automations(
            has_open_work=lambda automation_id: automation_id == automation["id"])[0]
        self.assertEqual(occurrence["status"], "skipped")
        self.assertEqual(automations.get_automation(automation["id"])["runs"][0]["reason"],
                         "上一项自动化工作尚未结束")
        with self.assertRaisesRegex(ValueError, "上一项自动化工作尚未结束"):
            automations.run_automation_now(automation["id"], has_open_work=lambda _automation_id: True)


    def test_automation_trash_restore_and_permanent_delete_preserve_then_remove_history(self):
        automation = automations.save_automation({"name": "Recoverable", "prompt": "执行一次"})
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()
        chat_id = store.create_chat(kind="automation")
        automations.set_automation_run_chat(job["id"], chat_id)
        automations.add_automation_run_event(job["id"], "agent_event", {
            "kind": "work_delta", "id": "work", "delta": "正在工作"})
        automations.finish_automation_run(job["id"], "completed", "已完成")

        self.assertTrue(automations.trash_automation(automation["id"]))
        self.assertIsNone(automations.get_automation(automation["id"]))
        trashed = automations.list_trashed_automations()[0]
        self.assertEqual(trashed["count"], 1)
        self.assertIsNotNone(store.get_chat(chat_id))

        self.assertTrue(automations.restore_automation(automation["id"]))
        restored = automations.get_automation(automation["id"])
        self.assertEqual(restored["runs"][0]["event_count"], 1)
        self.assertEqual(automations.get_automation_run(job["id"])["events"][0]["content"]["delta"],
                         "正在工作")

        self.assertTrue(automations.trash_automation(automation["id"]))
        self.assertTrue(automations.delete_trashed_automation(automation["id"]))
        self.assertIsNone(automations.get_automation_run(job["id"]))
        self.assertIsNone(store.get_chat(chat_id))

    def test_deleting_automation_removes_internal_chat_history(self):
        automation = automations.save_automation({"name": "Disposable", "prompt": "执行一次"})
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()
        chat_id = store.create_chat(kind="automation")
        store.add_chat_message(chat_id, "user", "secret scheduled prompt")
        automations.set_automation_run_chat(job["id"], chat_id)
        automations.finish_automation_run(job["id"], "completed")
        self.assertTrue(automations.delete_automation(automation["id"]))
        self.assertIsNone(store.get_chat(chat_id))

    def test_automation_scheduler_cancels_active_agent(self):
        automation = automations.save_automation({"name": "Cancellable", "prompt": "长时间运行"})
        automations.run_automation_now(automation["id"])
        started = threading.Event()

        def execute(_job, cancel_event):
            started.set()
            self.assertTrue(cancel_event.wait(2))
            raise Cancelled("自动化已暂停")

        service = scheduler.AutomationScheduler(execute, max_concurrency=1, poll_interval=0.01)
        service.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertTrue(service.cancel_automation(
                automation["id"], "自动化已暂停", wait_timeout=2))
            deadline = time.time() + 2
            while time.time() < deadline:
                if automations.get_automation(automation["id"])["runs"][0]["status"] == "cancelled":
                    break
                time.sleep(0.01)
            saved = automations.get_automation(automation["id"])["runs"][0]
            self.assertEqual(saved["status"], "cancelled")
        finally:
            service.stop()

    def test_pausing_schedule_does_not_cancel_active_occurrence(self):
        automation = automations.save_automation({"name": "Independent schedule", "prompt": "长时间运行"})
        automations.run_automation_now(automation["id"])
        started = threading.Event()
        release = threading.Event()

        def execute(job, cancel_event):
            started.set()
            self.assertFalse(cancel_event.wait(0.2))
            self.assertTrue(release.wait(2))
            automations.finish_automation_run(job["id"], "completed", "本轮完成")

        service = scheduler.AutomationScheduler(execute, max_concurrency=1, poll_interval=0.01)
        service.start()
        try:
            self.assertTrue(started.wait(2))
            automations.save_automation({**automation, "enabled": False}, automation["id"])
            self.assertFalse(automations.get_automation(automation["id"])["enabled"])
            release.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                if automations.get_automation(automation["id"])["runs"][0]["status"] == "completed":
                    break
                time.sleep(0.01)
            self.assertEqual(automations.get_automation(automation["id"])["runs"][0]["status"],
                             "completed")
        finally:
            release.set()
            service.stop()

    def test_automation_scheduler_failure_creates_actionable_attention_and_work_log(self):
        automation = automations.save_automation({"name": "Broken patrol", "prompt": "执行检查"})
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()

        def fail(_job, _cancel_event):
            raise RuntimeError("provider unavailable")

        state_change = mock.Mock()
        service = scheduler.AutomationScheduler(
            fail, max_concurrency=1, on_state_change=state_change)
        service._run(job, threading.Event())
        state_change.assert_called_once_with()
        run = automations.get_automation_run(job["id"])
        self.assertEqual(run["status"], "failed")
        self.assertEqual([event["kind"] for event in run["events"]], ["system", "error"])
        intervention = automations.automation_attention_catalog()[0]
        self.assertEqual(intervention["kind"], "automation")
        self.assertEqual(intervention["automation_id"], automation["id"])
        self.assertEqual(intervention["source_id"], job["id"])
        self.assertEqual(intervention["attempted"], [
            "本次运行记录了 2 条工作事件，最终未完成。",
        ])
        self.assertEqual(
            intervention["resume_from"],
            "立即重试会创建一次新运行；本次失败记录会保留。")
        self.assertEqual([action["id"] for action in intervention["actions"]],
                         ["retry", "pause_automation"])
        self.assertEqual(automations.failure_reasons(), ["provider unavailable"])

    def test_interrupted_automation_with_chat_is_not_automatically_replayed(self):
        automation = automations.save_automation({"name": "At-most-once recovery", "prompt": "创建任务"})
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()
        chat_id = store.create_chat(kind="automation")
        automations.set_automation_run_chat(job["id"], chat_id)

        self.assertEqual(automations.recover_automation_runs(), 1)
        self.assertIsNone(automations.claim_next_automation_run())
        recovered = automations.get_automation_run(job["id"])
        self.assertEqual(recovered["status"], "failed")
        self.assertIn("避免重复执行", recovered["reason"])
        intervention = automations.automation_attention_catalog()[0]
        self.assertEqual(intervention["automation_id"], automation["id"])

    def test_automation_run_links_chat_and_finishes(self):
        automation = automations.save_automation({"name": "Follow up", "prompt": "查看最近活动"})
        occurrence = automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()
        chat_id = store.create_chat()
        automations.set_automation_run_chat(job["id"], chat_id)
        automations.finish_automation_run(job["id"], "completed", "已完成")
        saved = automations.get_automation(automation["id"])["runs"][0]
        self.assertEqual(saved["chat_id"], chat_id)
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["reason"], "已完成")
        self.assertEqual(store.get_chat(chat_id)["kind"], "automation")
        with store.conn() as connection:
            trigger = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                "AND name='trg_automation_run_chat_internal'").fetchone()
        self.assertIsNotNone(trigger)

    def test_automation_work_record_keeps_large_structured_event_valid(self):
        automation = automations.save_automation({"name": "Verbose", "prompt": "执行检查"})
        run = automations.run_automation_now(automation["id"])
        detail = "证据" * 10000
        automations.add_automation_run_event(run["id"], "agent_event", {
            "kind": "step", "id": "large", "status": "completed", "output": detail,
        })
        event = automations.get_automation_run(run["id"])["events"][0]
        self.assertEqual(event["content"]["output"], detail)

    def test_scheduled_automation_reuses_the_ordinary_chat_agent_path(self):
        channel = store.get_default_channel()
        automation = automations.save_automation({
            "name": "Daily brief", "prompt": "读取产品数据并完成简报",
            "channel_id": channel["id"], "model": "agent-test",
        })
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()
        with mock.patch.object(app.chat, "run_chat", return_value={
                "reply": "简报已完成", "applied": ["读取了当前状态"],
                "run_cards": [], "focus_pid": None,
        }) as run_chat:
            app._execute_automation(job)
        run_chat.assert_called_once()
        self.assertTrue(run_chat.call_args.kwargs["auto_apply"])
        self.assertEqual(run_chat.call_args.kwargs["action_context"],
                         {"automation_id": automation["id"], "automation_run_id": job["id"]})
        saved = automations.get_automation(automation["id"])["runs"][0]
        self.assertEqual(saved["status"], "completed")
        chat_session = store.get_chat(saved["chat_id"])
        self.assertEqual(chat_session["kind"], "automation")
        self.assertEqual(chat_session["context"]["automation_id"], automation["id"])
        self.assertEqual(chat_session["context"]["automation_run_id"], job["id"])
        self.assertEqual(chat_session["context"]["automation_name"], "Daily brief")
        self.assertEqual([message["role"] for message in chat_session["messages"]],
                         ["user", "assistant"])
        self.assertEqual(chat_session["messages"][0]["text"], "读取产品数据并完成简报")
        self.assertNotIn(saved["chat_id"], [item["id"] for item in store.list_chats()])
        record = automations.get_automation_run(job["id"])
        self.assertEqual([event["kind"] for event in record["events"]], ["actions", "system"])

    def test_scheduled_automation_can_start_a_core_workflow(self):
        core = app.chat._core_service()
        employee_id = core.create_employee("Scheduled analyst", {
            "role": "Handle scheduled analysis",
            "program": {"objective": "Complete analysis", "steps": [{
                "id": "analyze", "instruction": "Analyze the scheduled task",
            }], "acceptance": ["Deliver a clear result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        pipeline_id = core.create_pipeline("Scheduled core pipeline", {
            "positions": [{"key": "analysis", "name": "Analysis",
                           "employee_id": employee_id}],
            "edges": [],
        })
        channel = store.get_default_channel()
        automation = automations.save_automation({
            "name": "Core dispatch", "prompt": "创建核心分析任务",
            "channel_id": channel["id"], "model": "agent-test",
        })
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()

        def run_core_agent(_prompt, _attachments, _config, **kwargs):
            applied, run_cards, focus = app.chat.apply_actions([{
                "op": "create_task", "pipeline": "Scheduled core pipeline",
                "title": "Scheduled core task", "objective": "Complete the analysis",
            }], action_context=kwargs["action_context"])
            return {"reply": "已创建核心任务", "applied": applied,
                    "run_cards": run_cards, "focus_pid": focus}

        with mock.patch.object(app.chat, "run_chat", side_effect=run_core_agent):
            app._execute_automation(job)

        workflow = core.workflow_catalog(1)[0]
        self.assertEqual(workflow["state"], "ready")
        self.assertEqual(workflow["snapshot_json"]["pipeline_id"], pipeline_id)
        self.assertTrue(core.automation_has_open_work(automation["id"]))
        record = automations.get_automation_run(job["id"])
        self.assertEqual(record["status"], "completed")
        self.assertEqual([event["kind"] for event in record["events"]],
                         ["workflow", "actions", "system"])
        self.assertEqual(record["events"][0]["content"]["task_title"],
                         "Scheduled core task")

    def test_scheduled_automation_never_falls_back_from_missing_saved_model(self):
        automation = automations.save_automation({"name": "Unconfigured", "prompt": "执行检查"})
        automations.run_automation_now(automation["id"])
        job = automations.claim_next_automation_run()
        with self.assertRaisesRegex(ValueError, "保存的 Agent 渠道不可用"):
            app._execute_automation(job)
        self.assertIsNone(automations.get_automation(automation["id"])["runs"][0]["chat_id"])
















    def test_runner_cancellation_kills_process_group(self):
        cancelled = threading.Event()
        timer = threading.Timer(0.2, cancelled.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(Cancelled):
                run_agent(_SlowAdapter(), "", execution_profile=EXECUTION_INTERNAL_ANALYSIS,
                           model="test", timeout_sec=20,
                           cancel_event=cancelled)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
