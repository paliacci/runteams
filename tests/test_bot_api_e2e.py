# -*- coding: utf-8 -*-
"""HTTP contract tests for the persistent Employee Bot conversation."""
import copy
import json
import os
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import app
import chat
import core_api
from errors import Cancelled
import local_database
from runner import AgentResult
from scripts.fixture_validation import publish_verified_employee


class _ProcessCrash(BaseException):
    """Simulate a process disappearing after one employee completed."""


class BotApiEndToEndTests(unittest.TestCase):
    """Prove release rollover is observable through the public chat API."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runteams-bot-http-")
        self.old_db = local_database.DB_PATH
        self.old_core_data = os.environ.get("RUNTEAMS_CORE_DATA")
        self.old_controller = app._CORE_CONTROLLER
        self.old_chat_service = chat._CORE_SERVICE
        self.old_chat_service_root = chat._CORE_SERVICE_ROOT
        local_database.DB_PATH = str(Path(self.temporary.name) / "runteams.db")
        os.environ["RUNTEAMS_CORE_DATA"] = str(Path(self.temporary.name) / "core")
        app.store.init_product_db()
        chat._CORE_SERVICE = None
        chat._CORE_SERVICE_ROOT = ""
        self.controller = core_api.CoreController(Path(self.temporary.name) / "core")
        app._CORE_CONTROLLER = self.controller
        self.server = app.Server(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=30)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.controller.stop()
        app._CORE_CONTROLLER = self.old_controller
        chat._CORE_SERVICE = self.old_chat_service
        chat._CORE_SERVICE_ROOT = self.old_chat_service_root
        local_database.DB_PATH = self.old_db
        if self.old_core_data is None:
            os.environ.pop("RUNTEAMS_CORE_DATA", None)
        else:
            os.environ["RUNTEAMS_CORE_DATA"] = self.old_core_data
        self.temporary.cleanup()

    def _request(self, method, path, body=None):
        payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        self.connection.request(
            method, path,
            body=payload if method == "POST" else None,
            headers={"Content-Type": "application/json"},
        )
        response = self.connection.getresponse()
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else {}

    def _stream(self, chat_id, message):
        # Stream responses are NDJSON; issue the request directly to retain
        # every accepted/result envelope instead of decoding only one JSON body.
        payload = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
        self.connection.request(
            "POST", "/api/chat/{}/stream".format(chat_id), body=payload,
            headers={"Content-Type": "application/json"})
        response = self.connection.getresponse()
        events = [json.loads(line) for line in response.read().decode("utf-8").splitlines()]
        self.assertEqual(response.status, 200)
        return events

    def _create_employee(self, name="长期分析 Bot"):
        draft = {
            "role": "分析输入并给出结构化结论",
            "program": {
                "objective": "完成分析",
                "steps": [{"id": "step-1", "instruction": "分析任务"}],
                "acceptance": ["结论清晰"],
            },
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        }
        employee_id = self.controller.core.create_employee(name, draft)
        # Publishing is intentionally performed through the same deterministic
        # verification path as production, so the conversation never references
        # an unverified draft.
        release = publish_verified_employee(self.controller.core, employee_id)
        return employee_id, release

    def _restart_http(self, runtime_factory=None):
        """Replace the controller and HTTP server while keeping the temp stores."""
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.controller.stop()
        self.controller = core_api.CoreController(
            Path(self.temporary.name) / "core", runtime_factory=runtime_factory)
        app._CORE_CONTROLLER = self.controller
        chat._CORE_SERVICE = None
        chat._CORE_SERVICE_ROOT = ""
        self.server = app.Server(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=30)

    def test_employee_bot_http_session_keeps_id_and_records_each_release(self):
        employee_id, first_release = self._create_employee()
        channel = app.store.get_default_channel()
        status, created = self._request("POST", "/api/conversations", {
            "kind": "general",
            "channel_id": channel["id"],
            "context": {
                "context_type": "worker",
                "intent": "chat",
                "target_employee_id": employee_id,
                "scope_type": "global",
            },
            "employee_id": employee_id,
        })
        self.assertEqual(status, 200)
        session = created["session"]
        chat_id = session["id"]
        self.assertEqual(session["subject_type"], "employee")
        self.assertEqual(session["employee_id"], employee_id)
        self.assertEqual(session["employee_release_id"], first_release["release_id"])

        replies = iter(("基于 v1 的回答", "基于 v2 的回答"))
        prompts = []

        def fake_run_agent(*args, **_kwargs):
            prompts.append(args[1])
            return AgentResult(next(replies), {})

        with mock.patch.object(chat.model_channels, "adapter_for", return_value=object()), \
                mock.patch.object(chat, "run_agent", side_effect=fake_run_agent), \
                mock.patch.object(chat, "_generate_missing_title", return_value="长期分析 Bot 对话"):
            first_events = self._stream(chat_id, "解释最近一次结果")
            first_result = next(item for item in first_events if item["type"] == "result")

            current = self.controller.core.employee(employee_id)
            revised = copy.deepcopy(current["draft_json"])
            revised["role"] = "分析输入并给出可执行结论"
            self.controller.core.update_employee(employee_id, current["name"], revised)
            second_release = publish_verified_employee(self.controller.core, employee_id)

            second_events = self._stream(chat_id, "继续解释，并使用最新职责")
            second_result = next(item for item in second_events if item["type"] == "result")

        self.assertNotEqual(first_release["release_id"], second_release["release_id"])
        self.assertGreater(first_result["message_id"], 0)
        self.assertGreater(second_result["message_id"], first_result["message_id"])
        self.assertEqual(
            first_result["employee_bot_release"]["id"], first_release["release_id"])
        self.assertEqual(
            second_result["employee_bot_release"]["id"], second_release["release_id"])
        self.assertIn("分析输入并给出结构化结论", prompts[0])
        self.assertIn("分析输入并给出可执行结论", prompts[1])

        status, reloaded = self._request("GET", "/api/chat/{}".format(chat_id))
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["id"], chat_id)
        self.assertEqual(reloaded["subject_type"], "employee")
        self.assertEqual(reloaded["employee_id"], employee_id)
        self.assertEqual(reloaded["employee_release_id"], second_release["release_id"])
        bot_messages = [item for item in reloaded["messages"] if item["role"] == "bot"]
        self.assertEqual(
            [item["metadata"]["employee_bot_release"]["id"] for item in bot_messages],
            [first_release["release_id"], second_release["release_id"]],
        )

    def test_employee_bot_apply_plan_creates_traceable_handoff_task(self):
        employee_id, _release = self._create_employee()
        channel = app.store.get_default_channel()
        status, created = self._request("POST", "/api/conversations", {
            "kind": "general", "channel_id": channel["id"],
            "context": {"context_type": "worker", "intent": "chat",
                        "target_employee_id": employee_id, "scope_type": "global"},
            "employee_id": employee_id,
        })
        self.assertEqual(status, 200)
        chat_id = created["session"]["id"]
        action = {
            "op": "create_employee_task", "employee": "长期分析 Bot",
            "title": "基于历史结果复核", "objective": "复核最近一次分析结果",
            "context": {"task_type": "memory_chain_validation"},
        }
        plan_result = {
            "reply": "已准备好交办方案", "pending": True,
            "plan": {"count": 1, "actions": [action]},
            "applied": [], "run_cards": [],
        }
        projection = {
            "employee": {"id": employee_id, "name": "长期分析 Bot"},
            "recent_workflows": [{
                "state": "completed", "run_id": 17, "task_id": 16,
                "task_title": "上一项分析", "reference": "workflow_run:17",
                "task_payload": {"context": {
                    "opportunity_key": "source-key", "product": "jira",
                    "analysis_decision": "continue",
                }},
                "employee_runs": [{"state": "completed", "summary": "已完成",
                                    "output": {"decision": "continue"},
                                    "issues": [], "artifacts": []}],
            }],
        }
        with mock.patch.object(app.chat, "run_chat", return_value=plan_result):
            events = self._stream(chat_id, "基于最近结果再做一次复核")
        result = next(item for item in events if item["type"] == "result")
        bot_message_id = result["message_id"]

        with mock.patch.object(chat.bot_context, "build", return_value=projection):
            status, applied = self._request(
                "POST", "/api/chat/{}/apply-plan".format(chat_id),
                {"message_id": bot_message_id})
        self.assertEqual(status, 200)
        self.assertTrue(applied["ok"])
        self.assertTrue(any("交给「长期分析 Bot」并启动任务" in item
                            for item in applied["applied"]))

        core = self.controller.core
        task = next(item for item in core.employee_workflow_catalog(employee_id)
                    if item["task"]["title"] == "基于历史结果复核")
        payload = task["task"]["payload_json"]
        self.assertEqual(payload["context"]["product"], "jira")
        self.assertEqual(payload["context"]["upstream_position"], "employee_bot_memory")
        self.assertEqual(payload["context"]["bot_memory"]["task_id"], 16)
        self.assertTrue(payload["context"]["opportunity_key"].startswith("bot-handoff-16-"))
        self.assertEqual(projection["recent_workflows"][0]["task_payload"]["context"]["opportunity_key"],
                         "source-key")
        workflows = core.workflow_catalog(limit=100)
        self.assertTrue(workflows)
        self.assertTrue(any(int(item.get("task_id") or 0) == int(task["task"]["id"])
                            for item in workflows))

        status, reloaded = self._request("GET", "/api/chat/{}".format(chat_id))
        self.assertEqual(status, 200)
        saved_plan = next(item for item in reloaded["messages"] if item["id"] == bot_message_id)
        self.assertEqual(saved_plan["metadata"]["plan_resolution"], "applied")
        self.assertNotIn("pending", saved_plan["metadata"])

    def test_employee_bot_failed_turn_keeps_failure_trace_and_identity(self):
        employee_id, _release = self._create_employee()
        channel = app.store.get_default_channel()
        status, created = self._request("POST", "/api/conversations", {
            "kind": "general", "channel_id": channel["id"],
            "context": {"context_type": "worker", "intent": "chat",
                        "target_employee_id": employee_id, "scope_type": "global"},
            "employee_id": employee_id,
        })
        self.assertEqual(status, 200)
        chat_id = created["session"]["id"]
        with mock.patch.object(app.chat, "run_chat",
                               side_effect=RuntimeError("模型连接已中断")):
            events = self._stream(chat_id, "解释最近一次结果")
        self.assertTrue(any(item["type"] == "error" for item in events))

        status, reloaded = self._request("GET", "/api/chat/{}".format(chat_id))
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["subject_type"], "employee")
        self.assertEqual(reloaded["employee_id"], employee_id)
        failed = reloaded["messages"][-1]
        self.assertEqual(failed["role"], "bot")
        self.assertTrue(failed["metadata"]["failed"])
        self.assertTrue(failed["metadata"]["trace"]["failed"])
        self.assertTrue(failed["metadata"]["trace"]["complete"])
        self.assertNotIn("pending", failed["metadata"])

    def test_workflow_retry_api_reuses_frozen_run_and_records_transition(self):
        employee_id, release = self._create_employee()
        core = self.controller.core
        pipeline_id = core.create_pipeline("Bot retry flow", {
            "positions": [{"key": "analysis", "name": "分析",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(
            pipeline_id, "失败后重试", {"objective": "执行一次可恢复分析"})
        workflow_id = core.start_workflow(task_id)
        first = core.run_workflow(
            workflow_id,
            lambda *_args: {"status": "failed", "summary": "首次失败",
                            "output": {}, "issues": ["可恢复错误"], "artifacts": []},
            max_attempts=1,
        )
        self.assertEqual(first["status"], "failed")
        before = core.workflow(workflow_id)
        frozen_snapshot = copy.deepcopy(before["snapshot_json"])

        status, retried = self._request(
            "POST", "/api/core/workflows/{}/retry".format(workflow_id))
        self.assertEqual(status, 200)
        self.assertEqual(retried["id"], workflow_id)
        self.assertEqual(retried["state"], "ready")
        self.assertEqual(retried["snapshot_json"], frozen_snapshot)
        self.assertEqual(
            retried["snapshot_json"]["definition"]["positions"][0]["employee_release_id"],
            release["release_id"],
        )
        self.assertTrue(any(item["type"] == "workflow.retry_requested"
                            for item in retried["events"]))

        status, overview = self._request(
            "GET", "/api/core/workflows/{}".format(workflow_id))
        self.assertEqual(status, 200)
        self.assertEqual(overview["id"], workflow_id)
        self.assertEqual(overview["state"], "ready")

    def test_employee_bot_cancel_api_freezes_turn_without_late_result(self):
        employee_id, _release = self._create_employee()
        channel = app.store.get_default_channel()
        status, created = self._request("POST", "/api/conversations", {
            "kind": "general", "channel_id": channel["id"],
            "context": {"context_type": "worker", "intent": "chat",
                        "target_employee_id": employee_id, "scope_type": "global"},
            "employee_id": employee_id,
        })
        self.assertEqual(status, 200)
        chat_id = created["session"]["id"]
        entered = threading.Event()
        stream_output = {}

        def blocked_run_chat(*_args, **kwargs):
            entered.set()
            cancel_event = kwargs["cancel_event"]
            while not cancel_event.is_set():
                cancel_event.wait(0.02)
            raise Cancelled("用户已停止")

        def post_stream():
            connection = HTTPConnection(
                "127.0.0.1", self.server.server_address[1], timeout=30)
            try:
                payload = json.dumps({"message": "开始一项长时间分析"},
                                     ensure_ascii=False).encode("utf-8")
                connection.request("POST", "/api/chat/{}/stream".format(chat_id),
                                   body=payload,
                                   headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                stream_output["status"] = response.status
                stream_output["events"] = [
                    json.loads(line)
                    for line in response.read().decode("utf-8").splitlines()
                ]
            finally:
                connection.close()

        with mock.patch.object(app.chat, "run_chat", side_effect=blocked_run_chat):
            worker = threading.Thread(target=post_stream, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(5), "stream did not enter the Bot runtime")
            status, cancelled = self._request(
                "POST", "/api/chat/{}/cancel".format(chat_id))
            self.assertEqual(status, 200)
            self.assertTrue(cancelled["cancelled"])
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(stream_output["status"], 200)
        self.assertTrue(any(item["type"] == "accepted"
                            for item in stream_output["events"]))
        self.assertTrue(any(item["type"] == "cancelled"
                            for item in stream_output["events"]))
        self.assertFalse(any(item["type"] == "result"
                             for item in stream_output["events"]))

        status, reloaded = self._request("GET", "/api/chat/{}".format(chat_id))
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["subject_type"], "employee")
        stopped = reloaded["messages"][-1]
        self.assertTrue(stopped["metadata"]["trace"]["cancelled"])
        self.assertTrue(stopped["metadata"]["stopped"])

    def test_employee_bot_session_survives_http_controller_restart(self):
        employee_id, _release = self._create_employee()
        channel = app.store.get_default_channel()
        status, created = self._request("POST", "/api/conversations", {
            "kind": "general", "channel_id": channel["id"],
            "context": {"context_type": "worker", "intent": "chat",
                        "target_employee_id": employee_id, "scope_type": "global"},
            "employee_id": employee_id,
        })
        self.assertEqual(status, 200)
        chat_id = created["session"]["id"]
        with mock.patch.object(chat.model_channels, "adapter_for", return_value=object()), \
                mock.patch.object(chat, "run_agent",
                                   return_value=AgentResult("重启前回答", {})), \
                mock.patch.object(chat, "_generate_missing_title",
                                   return_value="长期分析 Bot 对话"):
            first_events = self._stream(chat_id, "重启前的问题")
        self.assertTrue(any(item["type"] == "result" for item in first_events))

        self._restart_http()
        with mock.patch.object(chat.model_channels, "adapter_for", return_value=object()), \
                mock.patch.object(chat, "run_agent",
                                   return_value=AgentResult("重启后回答", {})):
            second_events = self._stream(chat_id, "重启后的追问")
        self.assertTrue(any(item["type"] == "result" for item in second_events))
        status, reloaded = self._request("GET", "/api/chat/{}".format(chat_id))
        self.assertEqual(status, 200)
        self.assertEqual(reloaded["id"], chat_id)
        self.assertEqual(reloaded["employee_id"], employee_id)
        self.assertEqual([item["text"] for item in reloaded["messages"]],
                         ["重启前的问题", "重启前回答", "重启后的追问", "重启后回答"])

    def test_workflow_recovery_after_controller_restart_is_visible_over_http(self):
        employee_id, release = self._create_employee()
        core = self.controller.core
        pipeline_id = core.create_pipeline("重启恢复流程", {
            "positions": [{"key": "analysis", "name": "分析",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(pipeline_id, "中断任务", {"objective": "恢复执行"})
        workflow_id = core.start_workflow(task_id)
        self.assertEqual(core.claim_workflow(workflow_id), workflow_id)
        before = core.workflow(workflow_id)
        self.assertEqual(before["state"], "running")

        self._restart_http()
        recovered = self.controller.core.recover_interrupted_workflows()
        self.assertEqual(recovered, [workflow_id])
        status, workflow = self._request(
            "GET", "/api/core/workflows/{}".format(workflow_id))
        self.assertEqual(status, 200)
        self.assertEqual(workflow["id"], workflow_id)
        self.assertEqual(workflow["state"], "ready")
        self.assertEqual(
            workflow["snapshot_json"]["definition"]["positions"][0]["employee_release_id"],
            release["release_id"],
        )
        self.assertTrue(any(item["type"] == "workflow.recovered"
                            for item in workflow["events"]))

    def test_executor_restart_resumes_only_the_interrupted_employee_over_http(self):
        first_id, first_release = self._create_employee("研究 Bot")
        second_id, second_release = self._create_employee("写作 Bot")
        core = self.controller.core
        pipeline_id = core.create_pipeline("执行器恢复流程", {
            "positions": [
                {"key": "research", "name": "研究", "employee_id": first_id},
                {"key": "write", "name": "写作", "employee_id": second_id},
            ],
            "edges": [{"from": "research", "to": "write"}],
        })
        task_id = core.create_task(pipeline_id, "中断后续跑", {
            "objective": "先研究再写作", "context": {"source": "restart-test"},
        })
        workflow_id = core.start_workflow(task_id)
        calls_before_restart = []

        def crash_after_first(employee, _work_order, _emit):
            calls_before_restart.append(employee["name"])
            if employee["name"] == "写作 Bot":
                raise _ProcessCrash("executor process disappeared")
            return {"status": "completed", "summary": employee["name"] + " 完成",
                    "output": {"employee": employee["name"]},
                    "artifacts": [], "issues": []}

        with self.assertRaises(_ProcessCrash):
            core.run_workflow(workflow_id, crash_after_first)
        crashed = core.workflow(workflow_id)
        self.assertEqual(crashed["state"], "running")
        self.assertEqual(calls_before_restart, ["研究 Bot", "写作 Bot"])
        self.assertEqual([item["state"] for item in crashed["employee_runs"]],
                         ["completed", "running"])

        resumed_calls = []

        def resume_runtime(employee, _work_order, _emit):
            resumed_calls.append(employee["name"])
            return {"status": "completed", "summary": employee["name"] + " 恢复完成",
                    "output": {"employee": employee["name"]},
                    "artifacts": [], "issues": []}

        self._restart_http(runtime_factory=lambda: resume_runtime)
        self.controller.start()
        workflow = None
        for _attempt in range(200):
            status, candidate = self._request(
                "GET", "/api/core/workflows/{}".format(workflow_id))
            self.assertEqual(status, 200)
            workflow = candidate
            if candidate["state"] == "completed":
                break
            time.sleep(0.05)
        self.assertIsNotNone(workflow)
        self.assertEqual(workflow["state"], "completed")
        self.assertEqual(resumed_calls, ["写作 Bot"])
        self.assertEqual([item["state"] for item in workflow["employee_runs"]],
                         ["completed", "interrupted", "completed"])
        self.assertEqual(
            workflow["snapshot_json"]["definition"]["positions"][0]["employee_release_id"],
            first_release["release_id"],
        )
        self.assertEqual(
            workflow["snapshot_json"]["definition"]["positions"][1]["employee_release_id"],
            second_release["release_id"],
        )
        self.assertTrue(any(item["type"] == "workflow.recovered"
                            for item in workflow["events"]))


if __name__ == "__main__":
    unittest.main()
