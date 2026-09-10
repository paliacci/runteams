import tempfile
import unittest
from pathlib import Path

from runteams_core import RunTeamsCore
from runteams_core.repository import Repository, audit_context


class AuditTrailTests(unittest.TestCase):
    def test_event_ledger_is_hash_chained_and_verifiable(self):
        root = Path(tempfile.mkdtemp())
        repository = Repository(root / "runteams.db")
        repository.initialize()
        first = repository.event("test", "created", {"value": 1},
                                 actor_id="user-1", correlation_id="req-1",
                                 source="test")
        second = repository.event("test", "updated", {"value": 2},
                                  actor_id="user-1", correlation_id="req-1",
                                  source="test")
        self.assertLess(first, second)
        report = repository.verify_event_chain()
        self.assertTrue(report["valid"])
        self.assertEqual(report["event_count"], 2)
        events = repository.events("test")
        self.assertEqual(events[1]["prev_hash"], events[0]["event_hash"])
        self.assertEqual(events[0]["actor_id"], "user-1")
        self.assertEqual(events[0]["correlation_id"], "req-1")

    def test_context_provenance_is_inherited_by_events(self):
        root = Path(tempfile.mkdtemp())
        repository = Repository(root / "runteams.db")
        repository.initialize()
        with audit_context(actor_id="user-2", correlation_id="request-2",
                           source="http"):
            repository.event("test", "created", {"value": 1})
        event = repository.events("test")[0]
        self.assertEqual(event["actor_id"], "user-2")
        self.assertEqual(event["correlation_id"], "request-2")
        self.assertEqual(event["source"], "http")

    def test_pipeline_and_task_changes_have_before_after_timeline(self):
        root = Path(tempfile.mkdtemp())
        core = RunTeamsCore(root)
        employee_id = core.create_employee("审核员", {
            "role": "审核", "program": {"objective": "审核", "steps": [{"instruction": "检查"}]},
            "interface": {}, "capabilities": [], "tests": [],
            "runtime": {"channel": "codex"},
        })
        pipeline_id = core.create_pipeline("审核流水线", {
            "positions": [{"key": "review", "employee_id": employee_id}],
            "edges": [],
        })
        task_id = core.create_task(pipeline_id, "初始任务", {"objective": "检查"})
        core.repository.event(
            "employee_run:77", "agent.runtime_finished",
            {"employee_run_id": 77, "workflow_run_id": 12,
             "employee_id": employee_id, "transcript_sha256": "abc"})
        core.update_pipeline(pipeline_id, "更新流水线", {
            "positions": [{"key": "review", "employee_id": employee_id}],
            "edges": [],
        })
        timeline = core.audit_timeline("task", task_id)
        self.assertEqual(timeline["subject"]["pipeline_id"], pipeline_id)
        types = [event["type"] for event in timeline["events"]]
        self.assertIn("task.created", types)
        employee_timeline = core.audit_timeline("employee", employee_id)
        self.assertIn("employee_run:77",
                      [event["stream"] for event in employee_timeline["events"]])
        self.assertIn("pipeline.updated", core.repository.events("pipeline:%d" % pipeline_id)[-1]["type"])
        self.assertTrue(timeline["integrity"]["valid"])

    def test_unstarted_task_is_tombstoned_instead_of_hard_deleted(self):
        root = Path(tempfile.mkdtemp())
        core = RunTeamsCore(root)
        employee_id = core.create_employee("执行员", {
            "role": "执行", "program": {"objective": "执行", "steps": [{"instruction": "执行"}]},
            "interface": {}, "capabilities": [], "tests": [],
            "runtime": {"channel": "codex"},
        })
        pipeline_id = core.create_pipeline("执行流水线", {
            "positions": [{"key": "run", "employee_id": employee_id}],
            "edges": [],
        })
        task_id = core.create_task(pipeline_id, "待删除", {"objective": "暂不做"})
        core.delete_unstarted_task(task_id)
        task = core.task(task_id)
        self.assertEqual(task["state"], "canceled")
        self.assertIsNotNone(task["trashed_at"])
        self.assertEqual(core.repository.events("task:%d" % task_id)[-1]["type"],
                         "task.trashed")

    def test_purged_workflow_remains_auditable_from_tombstones(self):
        root = Path(tempfile.mkdtemp())
        core = RunTeamsCore(root)
        employee_id = core.create_employee("执行员", {
            "role": "执行", "program": {"objective": "执行",
            "steps": [{"instruction": "执行"}]}, "interface": {},
            "capabilities": [], "tests": [], "runtime": {"channel": "codex"},
        })
        pipeline_id = core.create_pipeline("可追溯流水线", {
            "positions": [{"key": "run", "employee_id": employee_id}], "edges": [],
        })
        task_id = core.create_task(pipeline_id, "待清理", {"objective": "记录"})
        workflow_id = 991
        core.repository.event(
            "workflow_run:{}".format(workflow_id), "workflow.compiled",
            {"task_id": task_id, "pipeline_id": pipeline_id})
        core.repository.event(
            "task:{}".format(task_id), "task.workflow_compiled",
            {"task_id": task_id, "workflow_run_id": workflow_id,
             "pipeline_id": pipeline_id})
        core.repository.event(
            "workflow_run:{}".format(workflow_id), "workflow.deleted",
            {"workflow_run_id": workflow_id, "task_id": task_id})

        timeline = core.audit_timeline("workflow", workflow_id)
        self.assertIsNotNone(timeline)
        self.assertEqual(timeline["subject"]["task_id"], task_id)
        self.assertIn("workflow.deleted",
                      [event["type"] for event in timeline["events"]])
        pipeline_timeline = core.audit_timeline("pipeline", pipeline_id)
        self.assertIn(task_id, pipeline_timeline["subject"]["task_ids"])
        self.assertIn(workflow_id, pipeline_timeline["subject"]["workflow_run_ids"])


if __name__ == "__main__":
    unittest.main()
