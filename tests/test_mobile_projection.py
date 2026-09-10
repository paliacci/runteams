# -*- coding: utf-8 -*-
import json
import http.client
import os
import tempfile
import threading
import unittest
from unittest import mock
from jsonschema import Draft202012Validator

import app
import automation_store as automations
import mobile_projection
import local_database
import product_store as store
from runteams_core import RunTeamsCore
from scripts.fixture_validation import publish_verified_employee


class MobileProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-mobile-projection-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        store.init_product_db()
        self.secret = "ULTRA_PRIVATE_VALUE"
        self.core = RunTeamsCore(store.core_data_root())
        employee_id = self.core.create_employee("Mobile analyst", {
            "role": "Ask for missing decisions",
            "program": {"objective": "Complete the task", "steps": [
                {"id": "work", "instruction": "Complete the task"}],
                "acceptance": ["Return a structured result"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(self.core, employee_id)
        self.core_pipeline_id = self.core.create_pipeline("Core mobile flow", {
            "positions": [{"key": "analysis", "name": "Analysis",
                           "employee_id": employee_id}], "edges": [],
        })
        task_id = self.core.create_task(
            self.core_pipeline_id, "Core attention", {"objective": "Choose an audience"})
        self.workflow_id = self.core.start_workflow(task_id)
        self.core.run_workflow(self.workflow_id, lambda *_args: {
            "status": "needs_human", "summary": "Safe summary for mobile", "issues": [],
            "artifacts": [{"name": "report.md", "ref": "safe-report"}],
            "output": {"question": "password=" + self.secret,
                       "context": "The detailed context remains local"},
        })

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_projection_uses_allowlisted_fields_and_redacts_secrets(self):
        snapshot = mobile_projection.build_dashboard_snapshot(
            app_version="test",
            generated_at="2026-08-02T09:00:00Z",
            snapshot_version=42,
        )
        self.assertEqual(
            set(snapshot),
            {
                "schema_version", "snapshot_version", "account", "host", "interventions",
                "workflows", "pipelines", "activity", "synced_at",
            },
        )
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["snapshot_version"], 42)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn(self.secret, serialized)
        self.assertNotIn("workspace_path", serialized)
        self.assertNotIn("storage_key", serialized)
        self.assertNotIn('"facts"', serialized)
        self.assertNotIn('"body"', serialized)
        self.assertIn("[已隐藏]", serialized)

        pipeline = next(item for item in snapshot["pipelines"]
                        if item["id"] == "pipeline:{}".format(self.core_pipeline_id))
        self.assertEqual(pipeline["access"], "read_only")
        cards = [card for column in pipeline["positions"] for card in column["tasks"]]
        card = next(item for item in cards
                    if item["id"] == "workflow:{}".format(self.workflow_id))
        self.assertEqual(card["summary"], "Safe summary for mobile")
        self.assertEqual(card["artifact_count"], 1)
        self.assertEqual(card["records"][0]["detail"], "Safe summary for mobile")
        attention = snapshot["interventions"][0]
        self.assertEqual(attention["id"], "workflow:{}".format(self.workflow_id))
        self.assertEqual(attention["target_type"], "workflow")
        action_ids = [action["id"] for action in attention["actions"]]
        self.assertNotIn("edit_continue", action_ids)

    def test_current_progress_ignores_attempts_before_task_recompile(self):
        workflow = {
            "state": "running",
            "snapshot_json": {"definition": {
                "positions": [{"key": "research"}, {"key": "write"}],
                "edges": [{"from": "research", "to": "write"}],
            }},
            "employee_runs": [
                {"id": 10, "position_key": "research", "state": "completed"},
                {"id": 11, "position_key": "write", "state": "failed"},
                {"id": 12, "position_key": "research", "state": "running"},
            ],
            "events": [{"type": "workflow.task_recompiled",
                        "data_json": {"after_employee_run_id": 11}}],
        }
        self.assertEqual(mobile_projection._current_position_key(workflow), "research")
        self.assertEqual(mobile_projection._workflow_progress(workflow), 0.0)

    def test_automation_attention_is_projected_without_a_fake_card(self):
        automation = automations.save_automation({"name": "Scheduled audit", "prompt": "执行审计"})
        run = automations.run_automation_now(automation["id"])
        automations.finish_automation_run(run["id"], "failed", "Agent failed")
        snapshot = mobile_projection.build_dashboard_snapshot(snapshot_version=43)
        item = next(value for value in snapshot["interventions"]
                    if value.get("target_type") == "automation")
        self.assertEqual(item["id"], "automation-intervention:{}".format(run["id"]))
        self.assertEqual(item["automation_id"], automation["id"])
        self.assertNotIn("card_id", item)
        self.assertEqual([action["id"] for action in item["actions"]],
                         ["retry", "pause_automation"])

    def test_shared_example_matches_projection_root_contract(self):
        fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "contracts", "mobile_dashboard_v1.example.json"
        )
        with open(fixture_path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        snapshot = mobile_projection.build_dashboard_snapshot(snapshot_version=1)
        self.assertEqual(set(fixture), set(snapshot))
        self.assertEqual(fixture["schema_version"], mobile_projection.SCHEMA_VERSION)
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "contracts",
            "mobile_dashboard_v1.schema.json")
        with open(schema_path, "r", encoding="utf-8") as handle:
            validator = Draft202012Validator(json.load(handle))
        validator.validate(fixture)
        validator.validate(snapshot)

    def test_content_hash_ignores_transport_fields_but_detects_visible_changes(self):
        first = mobile_projection.build_dashboard_snapshot(
            generated_at="2026-08-02T09:00:00Z", snapshot_version=100
        )
        second = mobile_projection.build_dashboard_snapshot(
            generated_at="2026-08-02T09:01:00Z", snapshot_version=101
        )
        self.assertEqual(
            mobile_projection.snapshot_content_hash(first),
            mobile_projection.snapshot_content_hash(second),
        )
        second["pipelines"][0]["name"] = "Visible rename"
        self.assertNotEqual(
            mobile_projection.snapshot_content_hash(first),
            mobile_projection.snapshot_content_hash(second),
        )

    def test_entitlements_are_allowlisted_into_the_encrypted_mobile_snapshot(self):
        snapshot = mobile_projection.build_dashboard_snapshot(
            snapshot_version=202,
            account={
                "name": "Alex",
                "email": "alex@example.com",
                "plan": "Pro",
                "entitlements": {
                    "schema_version": 1,
                    "revision": 4,
                    "plan": "paid",
                    "granted_plan": "paid",
                    "display_name": "Pro",
                    "status": "active",
                    "source": "simulation",
                    "is_active": True,
                    "updated_at": "2026-08-03T12:00:00Z",
                    "features": {"mobile.app": True, "mobile.control": True, "private.future": True},
                    "limits": {"mobile.devices": 5, "private.secret": 99},
                },
            },
        )
        entitlements = snapshot["account"]["entitlements"]
        self.assertEqual(entitlements["plan"], "paid")
        self.assertTrue(entitlements["features"]["mobile.app"])
        self.assertTrue(entitlements["features"]["mobile.control"])
        self.assertNotIn("private.future", entitlements["features"])
        self.assertNotIn("private.secret", entitlements["limits"])

    def test_quota_wait_reason_is_visible_without_exposing_provider_error(self):
        task_id = self.core.create_task(
            self.core_pipeline_id, "Quota waiting task", {"objective": "Retry safely"})
        workflow_id = self.core.start_workflow(task_id)
        self.core.run_workflow(workflow_id, lambda *_args: {
            "status": "failed", "summary": "", "artifacts": [],
            "issues": ["provider raw error must stay local"], "output": {},
        }, retry_delay_sec=60)

        snapshot = mobile_projection.build_dashboard_snapshot(snapshot_version=43)
        run = next(item for item in snapshot["workflows"]
                   if item["id"] == "workflow:{}".format(workflow_id))
        self.assertEqual(run["status"], "retry_wait")
        self.assertIn("详细错误仅保留在桌面端", run["recent_update"])
        pipeline = next(
            item for item in snapshot["pipelines"]
            if item["id"] == "pipeline:{}".format(self.core_pipeline_id)
        )
        card = next(
            item for column in pipeline["positions"] for item in column["tasks"]
            if item["id"] == "workflow:{}".format(workflow_id)
        )
        self.assertIn("详细错误仅保留在桌面端", card["summary"])
        self.assertNotIn("provider raw error", json.dumps(snapshot, ensure_ascii=False))

    def test_push_events_are_coalesced_and_initial_state_is_silent(self):
        snapshot = {
            "interventions": [{"id": 10}, {"id": 11}],
            "workflows": [
                {"id": "run-ok", "status": "succeeded"},
                {"id": "run-failed", "status": "failed"},
                {"id": "run-active", "status": "running"},
            ],
        }
        current = mobile_projection.build_push_state(snapshot)
        self.assertEqual(mobile_projection.new_push_events("", current), [])
        previous = mobile_projection.encode_push_state({
            "attention": ["10"], "completed": [], "failed": []
        })
        events = mobile_projection.new_push_events(previous, current)
        self.assertEqual([item["kind"] for item in events], ["attention", "failed", "completed"])
        self.assertEqual(events[0]["object_ids"], ["11"])

    def test_live_activity_transitions_are_generic_and_idempotent(self):
        first = {
            "interventions": [],
            "workflows": [{
                "id": "workflow:7", "status": "running",
                "started_at": "2026-08-03T12:00:00Z",
            }],
        }
        initial = mobile_projection.build_push_state(first)
        self.assertEqual(mobile_projection.new_live_activity_events("", initial, first), [])

        baseline = mobile_projection.encode_push_state({
            "attention": [], "completed": [], "failed": [], "live": {}
        })
        started = mobile_projection.new_live_activity_events(baseline, initial, first)
        self.assertEqual(started[0]["operation"], "start")
        self.assertEqual(started[0]["status"], "running")

        retry_snapshot = {
            "interventions": [],
            "workflows": [{
                "id": "workflow:7", "status": "retry_wait",
                "started_at": "2026-08-03T12:00:00Z",
            }],
        }
        retrying = mobile_projection.build_push_state(retry_snapshot)
        updated = mobile_projection.new_live_activity_events(
            mobile_projection.encode_push_state(initial), retrying, retry_snapshot
        )
        self.assertEqual([(item["operation"], item["status"]) for item in updated], [
            ("update", "retry_wait")
        ])

        finished_snapshot = {
            "interventions": [],
            "workflows": [{
                "id": "workflow:7", "status": "succeeded",
                "started_at": "2026-08-03T12:00:00Z",
            }],
        }
        finished = mobile_projection.build_push_state(finished_snapshot)
        ended = mobile_projection.new_live_activity_events(
            mobile_projection.encode_push_state(retrying), finished, finished_snapshot
        )
        self.assertEqual([(item["operation"], item["status"]) for item in ended], [
            ("update", "completed")
        ])
        self.assertEqual(ended[0]["active_count"], 0)
        self.assertEqual(ended[0]["items"][0]["status"], "completed")

    def test_live_activity_groups_working_tasks_by_stable_position(self):
        snapshot = {
            "interventions": [],
            "workflows": [
                {
                    "id": "workflow:1", "status": "running", "position_id": "7:11",
                    "pipeline_name": "产品流水线", "position_name": "需求分析",
                    "started_at": "2026-08-03T12:00:00Z",
                },
                {
                    "id": "workflow:2", "status": "running", "position_id": "7:11",
                    "pipeline_name": "产品流水线", "position_name": "需求分析",
                    "started_at": "2026-08-03T12:00:01Z",
                },
                {
                    "id": "workflow:3", "status": "running", "position_id": "7:12",
                    "pipeline_name": "产品流水线", "position_name": "iOS 开发",
                    "started_at": "2026-08-03T12:00:02Z",
                },
                {
                    "id": "workflow:4", "status": "queued", "position_id": "7:13",
                    "pipeline_name": "产品流水线", "position_name": "等待岗位",
                    "started_at": "2026-08-03T12:00:03Z",
                },
            ],
        }
        state = mobile_projection.build_push_state(snapshot)
        previous = mobile_projection.encode_push_state({
            "attention": [], "completed": [], "failed": [], "live_schema": 3, "live": {}
        })

        event = mobile_projection.new_live_activity_events(previous, state, snapshot)[0]

        positions = [item for item in event["items"] if item["kind"] == "position"]
        self.assertEqual(len(positions), 2)
        analysis = next(item for item in positions if item["position_name"] == "需求分析")
        self.assertEqual(analysis["task_count"], 2)
        self.assertEqual(analysis["status"], "running")
        self.assertTrue(any(item["position_name"] == "iOS 开发" for item in positions))
        self.assertEqual(event["active_count"], 4)

    def test_live_activity_updates_when_a_running_task_moves_position(self):
        before_snapshot = {
            "interventions": [],
            "workflows": [{
                "id": "workflow:1", "status": "running", "position_id": "7:11",
                "pipeline_name": "产品流水线", "position_name": "需求分析",
                "started_at": "2026-08-03T12:00:00Z",
            }],
        }
        after_snapshot = {
            "interventions": [],
            "workflows": [{
                "id": "workflow:1", "status": "running", "position_id": "7:12",
                "pipeline_name": "产品流水线", "position_name": "iOS 开发",
                "started_at": "2026-08-03T12:00:00Z",
            }],
        }
        before = mobile_projection.build_push_state(before_snapshot)
        after = mobile_projection.build_push_state(after_snapshot)

        event = mobile_projection.new_live_activity_events(
            mobile_projection.encode_push_state(before), after, after_snapshot
        )[0]

        self.assertEqual(event["operation"], "update")
        self.assertEqual(event["items"][0]["position_name"], "iOS 开发")

    def test_notification_target_ref_is_host_scoped_and_opaque(self):
        first = mobile_projection.notification_target_ref("host-a", "attention", "11")
        repeated = mobile_projection.notification_target_ref("host-a", "attention", "11")
        other_host = mobile_projection.notification_target_ref("host-b", "attention", "11")

        self.assertEqual(first, repeated)
        self.assertEqual(len(first), 64)
        self.assertNotIn("11", first)
        self.assertNotEqual(first, other_host)

    def test_local_preview_endpoint_returns_mobile_contract(self):
        entitlement_patch = mock.patch(
            "app.relay_sync.enrich_account", side_effect=lambda account: account
        )
        session_patch = mock.patch(
            "app.account_auth.session",
            return_value={"signed_in": False, "name": "RunTeams 用户", "plan": "Free"},
        )
        entitlement_patch.start()
        session_patch.start()
        server = app.Server(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/mobile-preview")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(payload["schema_version"], 1)
            self.assertTrue(payload["pipelines"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            entitlement_patch.stop()
            session_patch.stop()


if __name__ == "__main__":
    unittest.main()
