import base64
import json
import os
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import time
import unittest
import shutil
from urllib.parse import quote
from unittest import mock

import app
import chat_attachments
import core_api
from scripts.fixture_validation import publish_verified_employee, verify_employee


ROOT = Path(__file__).parents[1]


class CoreAppApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runteams-core-http-")
        self.old_db = app.local_database.DB_PATH
        self.old_controller = app._CORE_CONTROLLER
        app.local_database.DB_PATH = str(Path(self.temporary.name) / "runteams.db")
        app.store.init_product_db()
        self.artifact_path = Path(self.temporary.name) / "core" / "artifacts" / "result.txt"
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text("verified result", encoding="utf-8")

        def runtime_factory():
            def runtime(employee, work_order, emit):
                emit("agent.progress", {"message": "working"})
                return {"status": "completed", "summary": employee["name"] + " completed",
                        "output": {"objective": work_order["objective"]},
                        "artifacts": [{"name": "result.txt", "ref": str(self.artifact_path)}],
                        "issues": []}
            return runtime

        self.controller = core_api.CoreController(
            Path(self.temporary.name) / "core", runtime_factory=runtime_factory,
            poll_seconds=0.02)
        app._CORE_CONTROLLER = self.controller
        self.controller.start()
        self.server = app.Server(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)

    def tearDown(self):
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.controller.stop()
        app._CORE_CONTROLLER = self.old_controller
        app.local_database.DB_PATH = self.old_db
        self.temporary.cleanup()

    def request(self, method, path, body=None):
        payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        self.connection.request(method, path, body=payload if method == "POST" else None,
                                headers={"Content-Type": "application/json"})
        response = self.connection.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        return response.status, data

    def import_package(self, key="brief-validator", path=None):
        path = path or os.path.join(ROOT, "examples", "brief-validator")
        status, preview = self.request(
            "POST", "/api/core/packages/inspect", {"path": path})
        self.assertEqual(status, 200)
        return self.request("POST", "/api/core/packages/import", {
            "key": key, "path": path, "confirmed_digest": preview["digest"],
        })

    def test_agent_document_api_exposes_content_and_updates_revision(self):
        status, created = self.request("POST", "/api/core/documents", {
            "name": "需求挖掘总览", "document_key": "demand-overview",
            "content": "# 需求挖掘总览\n\n实时汇总。",
            "data_view": {"kind": "opportunities", "columns": ["title"]},
        })
        self.assertEqual(status, 201)
        self.assertEqual(created["source"], "agent_chat")
        status, detail = self.request(
            "GET", "/api/core/documents/{}".format(created["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(detail["content"], "# 需求挖掘总览\n\n实时汇总。")
        self.assertEqual(detail["data_view"]["kind"], "opportunities")
        status, revised = self.request(
            "POST", "/api/core/documents/{}".format(created["id"]),
            {"content": "# 需求挖掘总览\n\n已更新。"})
        self.assertEqual(status, 200)
        self.assertEqual(revised["revision"], 2)
        status, catalog = self.request(
            "GET", "/api/core/documents?q={}".format(quote("需求挖掘")))
        self.assertEqual(status, 200)
        self.assertEqual(len(catalog["documents"]), 1)
        self.assertEqual(catalog["documents"][0]["id"], revised["id"])

    def test_pipeline_position_trash_routes_are_recoverable(self):
        status, package = self.import_package()
        self.assertEqual(status, 201)
        draft = {
            "role": "Research a supplied topic",
            "program": {"objective": "Produce a structured research handoff",
                        "steps": [{"id": "research",
                                   "instruction": "Research and hand off"}],
                        "acceptance": ["The handoff is structured"]},
            "capabilities": [{"package_id": package["package_id"],
                              "capability_id": "brief-validator"}],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        }
        employee_id = self.controller.core.create_employee("Validator", draft)
        self.controller.stop()
        publish_verified_employee(self.controller.core, employee_id)
        self.controller.start()
        pipeline_id = self.controller.core.create_pipeline("Recover a position", {
            "positions": [
                {"key": "first", "name": "First", "employee_id": employee_id},
                {"key": "second", "name": "Second", "employee_id": employee_id},
            ],
            "edges": [{"from": "first", "to": "second"}],
        })

        status, trashed = self.request(
            "POST", "/api/core/pipelines/{}/positions/trash".format(pipeline_id),
            {"position_key": "first"})
        self.assertEqual(status, 200)
        self.assertEqual(trashed["kind"], "position")
        status, trash = self.request("GET", "/api/trash")
        self.assertEqual(status, 200)
        self.assertEqual(trash["items"][0]["kind"], "position")

        status, restored = self.request(
            "POST", "/api/core/pipeline-positions/{}/restore".format(trashed["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(
            [item["key"] for item in restored["definition_json"]["positions"]],
            ["first", "second"])

    def test_complete_core_http_vertical_slice(self):
        status, package = self.import_package()
        self.assertEqual(status, 201)
        self.assertEqual(package["version"], 1)

        draft = {
            "role": "Research a supplied topic",
            "program": {
                "objective": "Produce a structured research handoff",
                "steps": [{"id": "research", "instruction": "Research and hand off"}],
                "acceptance": ["The handoff is structured"],
            },
            "capabilities": [{"package_id": package["package_id"],
                              "capability_id": "brief-validator"}],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        }
        status, employee = self.request("POST", "/api/core/employees", {
            "name": "Researcher", "draft": draft})
        self.assertEqual(status, 201)
        status, release = self.request(
            "POST", "/api/core/employees/{}/publish".format(employee["id"]))
        self.assertEqual(status, 400)
        self.assertIn("发布前必须完成员工验证", release["error"])
        self.controller.stop()
        verify_employee(self.controller.core, employee["id"])
        self.controller.start()
        status, release = self.request(
            "POST", "/api/core/employees/{}/publish".format(employee["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(release["version"], 1)

        status, pipeline = self.request("POST", "/api/core/pipelines", {
            "name": "Research line",
            "definition": {"positions": [{"key": "research",
                                             "employee_id": employee["id"]}], "edges": []},
        })
        self.assertEqual(status, 201)
        status, pipeline = self.request(
            "POST", "/api/core/pipelines/{}".format(pipeline["id"]), {
                "name": "Research handoff line",
                "definition": {"positions": [{"key": "research", "name": "Research",
                                                 "employee_id": employee["id"]}],
                               "edges": []},
            })
        self.assertEqual(status, 200)
        self.assertEqual(pipeline["name"], "Research handoff line")
        self.assertEqual(pipeline["definition_json"]["positions"][0]["name"], "Research")
        input_source = Path(self.temporary.name) / "research-brief.md"
        input_source.write_text("frozen task material", encoding="utf-8")
        with mock.patch.object(
                chat_attachments, "_selection_root",
                return_value=str(Path(self.temporary.name) / "attachment-staging")):
            staged_inputs = chat_attachments._stage_native_paths([input_source])
        status, submitted = self.request("POST", "/api/core/tasks", {
            "pipeline_id": pipeline["id"], "title": "Research RunTeams",
            "payload": {"objective": "Explain RunTeams", "context": {
                "opportunity_key": "runteams-result-surface",
                "product": "RunTeams", "analysis_decision": "continue",
                "decision_reason": "结果可追溯", "evidence": [{
                    "title": "本地验证", "url": "https://example.com/result"}],
            }},
            "input_tokens": [staged_inputs[0]["token"]],
        })

        self.assertEqual(status, 201)
        task_inputs = submitted["task"]["payload_json"]["inputs"]
        self.assertEqual(task_inputs[0]["name"], "research-brief.md")
        self.assertTrue(task_inputs[0]["ref"].startswith(
            "task-input://{}/".format(submitted["task"]["id"])))
        self.assertEqual(
            submitted["workflow"]["snapshot_json"]["task"]["payload"]["inputs"],
            task_inputs)
        workflow_id = submitted["workflow"]["id"]

        deadline = time.time() + 5
        workflow = None
        while time.time() < deadline:
            status, workflow = self.request("GET", "/api/core/workflows/{}".format(workflow_id))
            if workflow.get("state") == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(status, 200)
        self.assertEqual(workflow["state"], "completed")
        self.assertEqual(workflow["employee_runs"][0]["state"], "completed")
        attempt = workflow["employee_runs"][0]
        self.assertEqual(attempt["output_json"]["artifacts"][0]["ref"], "artifact://1")
        self.assertEqual(attempt["artifacts"][0]["ref"], "artifact://1")
        self.assertNotIn(str(self.artifact_path), json.dumps(workflow, ensure_ascii=False))
        self.assertTrue(any(item["type"] == "workflow.claimed" for item in workflow["events"]))

        status, opportunities = self.request(
            "GET", "/api/core/opportunities?limit=0")
        self.assertEqual(status, 200)
        self.assertEqual(len(opportunities["opportunities"]), 1)
        self.assertEqual(opportunities["count"], 1)
        self.assertTrue(opportunities["complete_scan"])
        self.assertEqual(opportunities["opportunities"][0]["opportunity_key"],
                         "runteams-result-surface")
        status, opportunity = self.request(
            "GET", "/api/core/opportunity?key=runteams-result-surface")
        self.assertEqual(status, 200)
        self.assertEqual(opportunity["analysis_decision"], "continue")
        self.assertEqual(opportunity["documents"][0]["ref"], "artifact://1")

        self.connection.request("GET", "/api/core/artifacts/1/content")
        artifact_response = self.connection.getresponse()
        self.assertEqual(artifact_response.status, 200)
        self.assertEqual(artifact_response.getheader("Content-Type"),
                         "text/plain; charset=utf-8")
        self.assertTrue(artifact_response.getheader("Content-Disposition").startswith("inline;"))
        self.assertEqual(artifact_response.read(), b"verified result")

        with mock.patch.object(app, "_open_local_path") as open_local:
            status, opened = self.request("POST", "/api/core/artifacts/1/open")
        self.assertEqual(status, 200)
        self.assertTrue(opened["ok"])
        open_local.assert_called_once_with(str(self.artifact_path.resolve()))

        exported_path = str(Path(self.temporary.name) / "result-exported.txt")
        with mock.patch.object(app, "_export_local_file", return_value=exported_path) as export:
            status, exported = self.request("POST", "/api/core/artifacts/1/export")
        self.assertEqual(status, 200)
        self.assertEqual(exported["path"], exported_path)
        export.assert_called_once_with(str(self.artifact_path.resolve()), "result.txt")

        status, overview = self.request("GET", "/api/core/overview")
        self.assertEqual(status, 200)
        self.assertEqual([item["key"] for item in overview["packages"]], ["brief-validator"])
        self.assertEqual([item["name"] for item in overview["employees"]], ["Researcher"])
        self.assertEqual(overview["workflows"][0]["state"], "completed")

        status, board = self.request("GET", "/api/core/board-overview")
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in board["employees"]], ["Researcher"])
        self.assertTrue(board["employees"][0]["summary_only"])
        self.assertNotIn("validation", board["employees"][0])
        self.assertEqual(board["workflows"][0]["state"], "completed")

        status, trashed = self.request(
            "POST", "/api/core/pipelines/{}/trash".format(pipeline["id"]))
        self.assertEqual(status, 200)
        self.assertIsNotNone(trashed["trashed_at"])
        status, trash = self.request("GET", "/api/trash")
        self.assertEqual(status, 200)
        self.assertEqual(trash["items"][0]["kind"], "pipeline")
        status, restored = self.request(
            "POST", "/api/core/pipelines/{}/restore".format(pipeline["id"]))
        self.assertEqual(status, 200)
        self.assertIsNone(restored["trashed_at"])
        status, _ = self.request(
            "POST", "/api/core/pipelines/{}/trash".format(pipeline["id"]))
        self.assertEqual(status, 200)
        # 名下有文档时，第一次删除只报数不动手；确认份数后才真的删。
        status, blocked = self.request(
            "POST", "/api/core/pipelines/{}/delete".format(pipeline["id"]))
        self.assertEqual(status, 409)
        self.assertTrue(blocked["requires_confirmation"])
        self.assertEqual(blocked["documents"], 1)
        self.assertIn("1 份文档", blocked["error"])
        self.assertTrue(self.artifact_path.exists())
        status, deleted = self.request(
            "POST", "/api/core/pipelines/{}/delete".format(pipeline["id"]),
            {"acknowledged_documents": 1})
        self.assertEqual(status, 200)
        self.assertTrue(deleted["ok"])
        self.assertFalse(self.artifact_path.exists())

        status, failure_stats = self.request("GET", "/api/failure-stats")
        self.assertEqual(status, 200)
        self.assertEqual(failure_stats, {"total": 0, "reasons": []})

    def test_employee_avatar_is_persisted_as_mutable_identity(self):
        draft = {
            "role": "Produce a handoff",
            "program": {
                "objective": "Produce a structured handoff",
                "steps": [{"id": "handoff", "instruction": "Create the handoff"}],
                "acceptance": ["The handoff is usable"],
            },
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        }
        status, employee = self.request("POST", "/api/core/employees", {
            "name": "Handoff owner", "avatar": "preset:bottts:ada", "draft": draft,
        })
        self.assertEqual(status, 201)
        self.assertEqual(employee["avatar"], "preset:bottts:ada")

        status, updated = self.request(
            "POST", "/api/core/employees/{}".format(employee["id"]), {
                "name": employee["name"], "avatar": "preset:bottts:grace",
                "draft": employee["draft_json"],
            })
        self.assertEqual(status, 200)
        self.assertEqual(updated["avatar"], "preset:bottts:grace")
        self.assertNotIn("avatar", updated["draft_json"])

        status, invalid = self.request(
            "POST", "/api/core/employees/{}".format(employee["id"]), {
                "name": employee["name"], "avatar": "https://example.com/avatar.png",
                "draft": employee["draft_json"],
            })
        self.assertEqual(status, 400)
        self.assertIn("员工头像无效", invalid["error"])

    def test_invalid_package_path_is_a_clear_client_error(self):
        status, result = self.request("POST", "/api/core/packages/import", {
            "key": "missing", "path": ""})
        self.assertEqual(status, 400)
        self.assertIn("选择", result["error"])

    def test_package_inspection_is_read_only_and_confirmation_is_digest_bound(self):
        source = Path(self.temporary.name) / "inspect-only"
        (source / "scripts").mkdir(parents=True)
        marker = Path(self.temporary.name) / "executed.txt"
        (source / "SKILL.md").write_text(
            "---\nname: inspect-only\ndescription: Prove inspection is read only.\n---\n",
            encoding="utf-8")
        (source / "scripts" / "probe.py").write_text(
            "import json, pathlib\n"
            "pathlib.Path({!r}).write_text('executed')\n"
            "print(json.dumps({{'schema':'runteams.tool-result/v1',"
            "'execution':{{'status':'completed','exit_code':0}},"
            "'evaluation':{{'status':'passed'}}}}))\n".format(str(marker)),
            encoding="utf-8")
        (source / "runteams.json").write_text(json.dumps({
            "schema": "runteams.package-extension/v1", "capabilities": [{
                "id": "probe", "entry": "scripts/probe.py",
                "runtime": {"version": 2, "runner": "python", "effect": "diagnostic",
                            "dependencies": [], "healthcheck": {
                                "cases": [{"arguments": [], "expected": "passed"}]}}}],
        }), encoding="utf-8")

        status, preview = self.request(
            "POST", "/api/core/packages/inspect", {"path": str(source)})
        self.assertEqual(status, 200)
        self.assertFalse(marker.exists())

        (source / "SKILL.md").write_text(
            "---\nname: inspect-only\ndescription: Content changed after review.\n---\n",
            encoding="utf-8")
        status, result = self.request("POST", "/api/core/packages/import", {
            "key": "inspect-only", "path": str(source),
            "confirmed_digest": preview["digest"],
        })
        self.assertEqual(status, 400)
        self.assertIn("内容已变化", result["error"])
        self.assertFalse(marker.exists())

    def test_package_behavior_case_must_match_structured_result(self):
        source = Path(self.temporary.name) / "lying-verifier"
        (source / "scripts").mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: lying-verifier\ndescription: A verifier with an incorrect result.\n---\n",
            encoding="utf-8")
        (source / "scripts" / "verify.py").write_text(
            "import json\nprint(json.dumps({'schema':'runteams.tool-result/v1',"
            "'execution':{'status':'completed','exit_code':0},"
            "'evaluation':{'status':'passed'}}))\n", encoding="utf-8")
        (source / "runteams.json").write_text(json.dumps({
            "schema": "runteams.package-extension/v1", "capabilities": [{
                "id": "verify", "entry": "scripts/verify.py",
                "runtime": {"version": 2, "runner": "python", "effect": "verifier",
                            "dependencies": [], "healthcheck": {"cases": [
                                {"arguments": ["valid"], "expected": "passed"},
                                {"arguments": ["invalid"], "expected": "failed"},
                            ]}}}],
        }), encoding="utf-8")
        status, preview = self.request(
            "POST", "/api/core/packages/inspect", {"path": str(source)})
        self.assertEqual(status, 200)
        status, result = self.request("POST", "/api/core/packages/import", {
            "key": "lying-verifier", "path": str(source),
            "confirmed_digest": preview["digest"],
        })
        self.assertEqual(status, 400)
        self.assertIn("行为验证失败", result["error"])

    def test_unpublished_employee_trial_endpoints_use_the_normal_executor(self):
        status, employee = self.request("POST", "/api/core/employees", {
            "name": "Trial employee",
            "draft": {
                "role": "Handle a test work order",
                "program": {"objective": "Handle work", "steps": [{
                    "id": "work", "instruction": "Complete the work",
                }], "acceptance": ["Return a structured result"]},
                "capabilities": [],
                "runtime": {"channel": "codex", "model": "", "effort": "low"},
                "tests": [{
                    "id": "happy-path", "name": "Happy path",
                    "work_order": {"objective": "Complete this trial", "context": {},
                                   "inputs": [], "expected_output": {},
                                   "acceptance": ["Complete"]},
                    "expected_status": "completed",
                    "covers": ["input.valid", "output.valid", "result.completed",
                               "handoff.upstream.missing", "handoff.output.valid"],
                }],
            },
        })
        self.assertEqual(status, 201)
        employee_id = employee["id"]

        status, started = self.request(
            "POST", "/api/core/employees/{}/trials/run-all".format(employee_id))
        self.assertEqual(status, 201)
        self.assertEqual(len(started["trials"]), 3)

        deadline = time.time() + 5
        trials = []
        while time.time() < deadline:
            status, payload = self.request(
                "GET", "/api/core/employees/{}/trials".format(employee_id))
            trials = payload.get("trials") or []
            if len(trials) == 3 and all(item.get("state") == "completed" for item in trials):
                break
            time.sleep(0.02)
        self.assertEqual(status, 200)
        self.assertEqual(trials[0]["trial_result"]["verdict"], "matched")
        self.assertIsNone(trials[0]["employee_runs"][0]["employee_release_id"])
        self.assertEqual(trials[0]["snapshot_json"]["pipeline_id"], None)
        self.assertEqual(payload["coverage"]["covered"], 5)
        self.assertEqual(payload["coverage"]["verified"], 5)
        self.assertFalse(payload["coverage"]["complete"])

    def test_repeated_trial_batch_requests_do_not_duplicate_active_samples(self):
        self.controller.stop()
        employee_id = self.controller.core.create_employee("Idempotent trial employee", {
            "role": "Handle a test work order",
            "program": {"objective": "Handle work", "steps": [{
                "id": "work", "instruction": "Complete the work",
            }], "acceptance": ["Return a structured result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
            "tests": [{
                "id": "happy-path", "name": "Happy path",
                "work_order": {"objective": "Complete this trial"},
                "expected_status": "completed", "covers": [],
            }],
        })

        barrier = threading.Barrier(3)
        results = []

        def start_batch():
            barrier.wait(timeout=2)
            results.append(self.controller.core.start_all_employee_trials(employee_id))

        threads = [threading.Thread(target=start_batch) for _index in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=3)

        self.assertEqual(len(results), 2)
        self.assertEqual(len(results[0]), 3)
        self.assertEqual({item["id"] for item in results[0]},
                         {item["id"] for item in results[1]})
        self.assertEqual(len(self.controller.core.employee_trials(employee_id)), 3)

    def test_failed_validation_can_queue_one_headless_ai_repair_through_http(self):
        self.controller.stop()
        employee_id = self.controller.core.create_employee("Repair API employee", {
            "role": "Complete work reliably",
            "program": {"objective": "Complete work", "steps": [{
                "id": "work", "instruction": "Complete the work",
            }], "acceptance": ["Done"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
            "tests": [{
                "id": "completed", "name": "Completes",
                "work_order": {"objective": "Complete this work"},
                "expected_status": "completed", "covers": [],
            }],
        })
        for trial in self.controller.core.start_employee_trial_samples(
                employee_id, "completed", fresh=True):
            self.controller.core.run_workflow(trial["id"], lambda *_args: {
                "status": "blocked", "summary": "", "output": {},
                "artifacts": [], "issues": ["not completed"],
            }, max_attempts=1)

        path = "/api/core/employees/{}/repair".format(employee_id)
        status, queued = self.request("POST", path)
        self.assertEqual(status, 202)
        self.assertEqual(queued["state"], "queued")
        duplicate_status, duplicate = self.request("POST", path)
        self.assertEqual(duplicate_status, 202)
        self.assertEqual(duplicate["id"], queued["id"])
        blocked_status, blocked = self.request(
            "POST", "/api/core/employees/{}/trials/run-all".format(employee_id))
        self.assertEqual(blocked_status, 400)
        self.assertIn("AI 正在修复员工", blocked["error"])
        blocked_status, blocked = self.request(
            "POST", "/api/core/employees/{}/trials/completed".format(employee_id))
        self.assertEqual(blocked_status, 400)
        self.assertIn("AI 正在修复员工", blocked["error"])
        status, payload = self.request(
            "GET", "/api/core/employees/{}/trials".format(employee_id))
        self.assertEqual(status, 200)
        self.assertEqual(payload["repair"]["id"], queued["id"])
        self.assertEqual(payload["repair"]["state"], "queued")

        claimed = self.controller.core.claim_employee_repair()
        staged = self.controller.core.execute_employee_repair(
            claimed, lambda _employee, _failures, _protected: {
                "instructions": "Candidate behavior",
                "program": {"objective": "Candidate objective", "steps": [{
                    "id": "work", "instructions": "Candidate work",
                }]},
            })
        self.assertEqual(staged["phase"], "targeted")
        status, payload = self.request(
            "GET", "/api/core/employees/{}/trials".format(employee_id))
        self.assertEqual(status, 200)
        self.assertEqual(payload["repair"]["phase"], "targeted")
        self.assertNotIn("candidate_draft", payload["repair"])
        candidate_trials = [trial for trial in payload["trials"]
                            if not (trial.get("trial_result") or {}).get("stale")]
        self.assertEqual(len(candidate_trials), 3)
        self.assertEqual(
            self.controller.core.employee(employee_id)["draft_json"]["role"],
            "Complete work reliably")

    def test_employee_trials_run_in_parallel_with_a_bounded_worker_pool(self):
        self.controller.stop()
        active = 0
        maximum = 0
        lock = threading.Lock()
        ten_started = threading.Event()

        def runtime_factory():
            def runtime(_employee, work_order, _emit):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                    if active >= 10:
                        ten_started.set()
                try:
                    ten_started.wait(timeout=3)
                    return {"status": "completed", "summary": "completed",
                            "output": {"objective": work_order["objective"]},
                            "artifacts": [], "issues": []}
                finally:
                    with lock:
                        active -= 1
            return runtime

        self.controller.runtime_factory = runtime_factory
        tests = [{
            "id": "parallel-{}".format(index),
            "name": "Parallel case {}".format(index),
            "work_order": {"objective": "Run case {}".format(index)},
            "expected_status": "completed",
            "covers": [],
        } for index in range(1, 5)]
        employee_id = self.controller.core.create_employee("Parallel employee", {
            "role": "Run independent validation cases",
            "program": {"objective": "Validate work", "steps": [{
                "id": "work", "instruction": "Complete the case",
            }], "acceptance": ["Return a result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
            "tests": tests,
        })
        started = self.controller.core.start_all_employee_trials(employee_id)
        self.assertEqual(len(started), 12)

        self.controller.start()
        self.assertTrue(ten_started.wait(timeout=3))
        deadline = time.time() + 5
        trials = []
        while time.time() < deadline:
            trials = self.controller.core.employee_trials(employee_id)
            if trials and all(item["state"] == "completed" for item in trials):
                break
            time.sleep(0.02)

        self.assertEqual(maximum, 10)
        self.assertTrue(all(item["state"] == "completed" for item in trials))
        self.assertEqual(self.controller.worker_count, 10)

    def test_employee_lifecycle_endpoints_and_trash_catalog(self):
        status, employee = self.request("POST", "/api/core/employees", {
            "name": "Lifecycle employee",
            "draft": {"role": "Published role", "program": {
                "objective": "Published role",
                "steps": [{"id": "work", "instruction": "Work"}],
                "acceptance": ["Done"],
            }, "capabilities": [],
                "runtime": {"channel": "codex", "model": "", "effort": "low"}},
        })
        self.assertEqual(status, 201)
        employee_id = employee["id"]
        self.controller.stop()
        verify_employee(self.controller.core, employee_id)
        self.controller.start()
        status, _release = self.request(
            "POST", "/api/core/employees/{}/publish".format(employee_id))
        self.assertEqual(status, 200)

        status, duplicate = self.request(
            "POST", "/api/core/employees/{}/duplicate".format(employee_id))
        self.assertEqual(status, 201)
        self.assertEqual(duplicate["name"], "Lifecycle employee 副本")

        changed = dict(employee["draft_json"])
        changed["role"] = "Unpublished role"
        status, _employee = self.request(
            "POST", "/api/core/employees/{}".format(employee_id),
            {"name": "Changed name", "draft": changed})
        self.assertEqual(status, 200)
        status, discarded = self.request(
            "POST", "/api/core/employees/{}/discard".format(employee_id))
        self.assertEqual(status, 200)
        self.assertEqual(discarded["name"], "Lifecycle employee")
        self.assertEqual(discarded["draft_json"]["role"], "Published role")

        chat_id = app.store.create_agent_session(
            "employee_design", "Employee design", None, "", "low", None,
            {"target_employee_id": duplicate["id"]})
        status, trashed = self.request(
            "POST", "/api/core/employees/{}/trash".format(duplicate["id"]))
        self.assertEqual(status, 200)
        self.assertIsNotNone(trashed["trashed_at"])
        status, trash = self.request("GET", "/api/trash")
        self.assertEqual(status, 200)
        self.assertEqual(trash["items"][0]["kind"], "employee")
        status, restored = self.request(
            "POST", "/api/core/employees/{}/restore".format(duplicate["id"]))
        self.assertEqual(status, 200)
        self.assertIsNone(restored["trashed_at"])

        self.request("POST", "/api/core/employees/{}/trash".format(duplicate["id"]))
        status, deleted = self.request(
            "POST", "/api/core/employees/{}/delete".format(duplicate["id"]))
        self.assertEqual(status, 200)
        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["employee_conversations"], 1)
        self.assertIsNone(app.store.get_chat(chat_id))

    def test_package_file_endpoint_reads_only_manifest_files_from_immutable_object(self):
        status, imported = self.import_package()
        self.assertEqual(status, 201)
        package_id = imported["package_id"]

        status, skill = self.request(
            "GET", "/api/core/packages/{}/file?path=SKILL.md".format(package_id))
        self.assertEqual(status, 200)
        self.assertEqual(skill["path"], "SKILL.md")
        self.assertEqual(skill["kind"], "text")
        self.assertIn("brief-validator", skill["content"])
        self.assertEqual(len(skill["sha256"]), 64)
        self.assertFalse(skill["truncated"])

        status, script = self.request(
            "GET", "/api/core/packages/{}/file?path=scripts%2Fvalidate_brief.py".format(
                package_id))
        self.assertEqual(status, 200)
        self.assertIn("def ", script["content"])

        status, missing = self.request(
            "GET", "/api/core/packages/{}/file?path=..%2Fsecret.txt".format(package_id))
        self.assertEqual(status, 400)
        self.assertIn("不存在", missing["error"])

        with tempfile.TemporaryDirectory(prefix="runteams-image-package-") as root:
            source = os.path.join(root, "brief-validator")
            shutil.copytree(os.path.join(ROOT, "examples", "brief-validator"), source)
            with open(os.path.join(source, "preview.png"), "wb") as handle:
                handle.write(base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
            status, image_package = self.import_package(
                key="brief-validator-image", path=source)
        self.assertEqual(status, 201)
        status, image = self.request(
            "GET", "/api/core/packages/{}/file?path=preview.png".format(
                image_package["package_id"]))
        self.assertEqual(status, 200)
        self.assertEqual(image["kind"], "image")
        self.assertEqual(image["media_type"], "image/png")
        self.assertTrue(image["content"].startswith("iVBOR"))

    def test_package_impact_disable_and_reenable_endpoints(self):
        status, imported = self.import_package()
        self.assertEqual(status, 201)
        package_id = imported["package_id"]

        status, impact = self.request(
            "GET", "/api/core/packages/{}/impact".format(package_id))
        self.assertEqual(status, 200)
        self.assertTrue(impact["can_disable"])

        status, disabled = self.request(
            "POST", "/api/core/packages/{}/disable".format(package_id))
        self.assertEqual(status, 200)
        self.assertFalse(disabled["enabled"])
        status, packages = self.request("GET", "/api/core/packages")
        self.assertEqual(status, 200)
        self.assertFalse(packages["packages"][0]["enabled"])
        self.assertEqual(packages["packages"][0]["manifest_json"]["name"],
                         "brief-validator")
        status, failed = self.request(
            "POST", "/api/core/packages/{}/verify".format(package_id))
        self.assertEqual(status, 400)
        self.assertIn("已停用", failed["error"])

        status, enabled = self.request(
            "POST", "/api/core/packages/{}/enable".format(package_id))
        self.assertEqual(status, 200)
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["verification"]["status"], "verified")

    def test_human_response_endpoint_requeues_the_same_core_workflow(self):
        self.controller.stop()
        core = self.controller.core
        employee_id = core.create_employee("Human-aware analyst", {
            "role": "Ask when a product decision is missing",
            "program": {"objective": "Complete analysis", "steps": [{
                "id": "analyze", "instruction": "Analyze the task",
            }], "acceptance": ["Use the selected audience"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        pipeline_id = core.create_pipeline("Human response flow", {
            "positions": [{"key": "analysis", "name": "Analysis",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(
            pipeline_id, "Choose audience", {"objective": "Write an audience-specific brief"})
        workflow_id = core.start_workflow(task_id)
        core.run_workflow(workflow_id, lambda *_args: {
            "status": "needs_human", "summary": "", "issues": [], "artifacts": [],
            "output": {"question": "Which audience should I use?"},
        })

        status, workflow = self.request(
            "POST", "/api/core/workflows/{}/respond".format(workflow_id),
            {"response": "Use startup founders."})

        self.assertEqual(status, 200)
        self.assertEqual(workflow["state"], "ready")
        response_event = next(item for item in workflow["events"]
                              if item["type"] == "workflow.human_responded")
        self.assertEqual(response_event["data_json"]["response"], "Use startup founders.")

    def test_workflow_trash_is_recoverable_and_delete_only_works_from_trash(self):
        self.controller.stop()
        core = self.controller.core
        employee_id = core.create_employee("Disposable worker", {
            "role": "Complete disposable work",
            "program": {"objective": "Complete work", "steps": [{
                "id": "work", "instruction": "Complete work",
            }], "acceptance": ["Return a result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        pipeline_id = core.create_pipeline("Disposable flow", {
            "positions": [{"key": "work", "name": "Work",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(
            pipeline_id, "Disposable task", {
                "objective": "Complete once",
                "context": {"source": "original brief"},
                "acceptance": ["Return a result"],
            })
        workflow_id = core.start_workflow(task_id)

        status, trashed = self.request(
            "POST", "/api/core/workflows/{}/trash".format(workflow_id))
        self.assertEqual(status, 200)
        self.assertEqual(trashed["state"], "canceled")
        self.assertNotIn(workflow_id, [item["id"] for item in core.workflow_catalog()])
        self.assertIn(workflow_id, [item["id"] for item in core.task_trash_catalog()])

        status, restored = self.request(
            "POST", "/api/core/workflows/{}/restore".format(workflow_id))
        self.assertEqual(status, 200)
        self.assertEqual(restored["id"], workflow_id)
        self.assertIn(workflow_id, [item["id"] for item in core.workflow_catalog()])

        status, renamed = self.request(
            "POST", "/api/core/workflows/{}/rename".format(workflow_id),
            {"title": "Renamed task"})
        self.assertEqual(status, 200)
        self.assertEqual(renamed["task"]["title"], "Renamed task")
        self.assertEqual(renamed["snapshot_json"]["task"]["title"], "Disposable task")

        status, updated = self.request(
            "POST", "/api/core/workflows/{}/update".format(workflow_id),
            {"title": "Edited task", "objective": "Complete the edited brief",
             "parameters": {"customer_name": "Acme"}})
        self.assertEqual(status, 200)
        self.assertEqual(updated["task"]["title"], "Edited task")
        self.assertEqual(
            updated["task"]["payload_json"]["objective"], "Complete the edited brief")
        self.assertEqual(
            updated["task"]["payload_json"]["context"], {"source": "original brief"})
        self.assertEqual(
            updated["task"]["payload_json"]["acceptance"], ["Return a result"])
        self.assertEqual(
            updated["task"]["payload_json"]["parameters"],
            {"customer_name": "Acme"})
        self.assertEqual(updated["snapshot_json"]["task"]["title"], "Disposable task")
        self.assertEqual(
            updated["snapshot_json"]["task"]["payload"]["objective"], "Complete once")

        status, moved = self.request(
            "POST", "/api/core/workflows/{}/move".format(workflow_id),
            {"column_key": "__completed"})
        self.assertEqual(status, 200)
        self.assertEqual(moved["state"], "completed")
        self.assertEqual(moved["manual_column_key"], "__completed")

        status, reopened = self.request(
            "POST", "/api/core/workflows/{}/move".format(workflow_id),
            {"column_key": "work"})
        self.assertEqual(status, 200)
        self.assertEqual(reopened["state"], "ready")
        self.assertEqual(reopened["manual_column_key"], "work")
        self.assertEqual(reopened["snapshot_json"]["task"]["title"], "Edited task")
        self.assertEqual(
            reopened["snapshot_json"]["task"]["payload"]["objective"],
            "Complete the edited brief")

        status, rejected = self.request(
            "POST", "/api/core/workflows/{}/delete".format(workflow_id))
        self.assertEqual(status, 400)
        self.assertIn("垃圾箱", rejected["error"])

        self.request("POST", "/api/core/workflows/{}/trash".format(workflow_id))
        status, deleted = self.request(
            "POST", "/api/core/workflows/{}/delete".format(workflow_id))
        self.assertEqual(status, 200)
        self.assertTrue(deleted["ok"])
        status, missing = self.request(
            "GET", "/api/core/workflows/{}".format(workflow_id))
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"], "运行不存在")
        self.assertIsNone(core.task(task_id))

    def test_default_attention_endpoint_projects_core_workflow(self):
        self.controller.stop()
        core = self.controller.core
        employee_id = core.create_employee("Question asker", {
            "role": "Ask for missing context",
            "program": {"objective": "Complete work", "steps": [
                {"id": "work", "instruction": "Complete work"}],
                "acceptance": ["Return a result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        pipeline_id = core.create_pipeline("Attention flow", {
            "positions": [{"key": "work", "name": "Work",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(pipeline_id, "Needs a choice", {"objective": "Choose"})
        workflow_id = core.start_workflow(task_id)
        core.run_workflow(workflow_id, lambda *_args: {
            "status": "needs_human", "summary": "", "issues": [], "artifacts": [],
            "output": {"question": "Which option?"},
        })

        status, payload = self.request("GET", "/api/interventions")

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["id"], "workflow:{}".format(workflow_id))
        self.assertEqual(payload["items"][0]["pipeline_id"], pipeline_id)

    def test_retired_studio_assets_are_not_served(self):
        for path in ("/studio", "/studio.css", "/studio.js"):
            self.connection.request("GET", path)
            response = self.connection.getresponse()
            response.read()
            self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
