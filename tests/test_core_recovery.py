import datetime
import os
import tempfile
import threading
import unittest

from errors import Cancelled, RateLimited, Transient
from runteams_core import ContractError, RunTeamsCore
from scripts.fixture_validation import publish_verified_employee


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draft(role, package_id):
    return {
        "role": role,
        "program": {
            "objective": role,
            "steps": [{"id": "work", "instruction": "完成工作并提交结构化结果"}],
            "acceptance": ["结果可以交给下一名员工"],
        },
        "capabilities": [{"package_id": package_id,
                          "capability_id": "brief-validator"}],
        "runtime": {"channel": "codex", "model": "", "effort": "low"},
    }


class SimulatedProcessCrash(BaseException):
    pass


class CoreRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-recovery-")
        self.core = RunTeamsCore(self.tmp.name)
        package = self.core.import_package(
            "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
        self.package_id = package["package_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def make_workflow(self, roles):
        employees = []
        for role in roles:
            employee_id = self.core.create_employee(role, draft(role, self.package_id))
            publish_verified_employee(self.core, employee_id)
            employees.append(employee_id)
        positions = [{"key": "position-{}".format(index + 1),
                      "name": role, "employee_id": employee_id}
                     for index, (role, employee_id) in enumerate(zip(roles, employees))]
        edges = [{"from": positions[index]["key"], "to": positions[index + 1]["key"]}
                 for index in range(len(positions) - 1)]
        pipeline_id = self.core.create_pipeline(
            " to ".join(roles), {"positions": positions, "edges": edges})
        task_id = self.core.create_task(
            pipeline_id, "Durable task", {"objective": "Complete durable work",
                                           "context": {"source": "test"}})
        return task_id, self.core.start_workflow(task_id)

    @staticmethod
    def completed(employee, work_order, emit):
        emit("agent.progress", {"employee": employee["name"]})
        return {"status": "completed", "summary": "{} done".format(employee["name"]),
                "output": {"employee": employee["name"]}, "artifacts": [], "issues": []}

    def test_submission_is_idempotent_and_claim_is_atomic(self):
        task_id, workflow_run_id = self.make_workflow(["Researcher"])
        self.assertEqual(self.core.start_workflow(task_id), workflow_run_id)
        second = RunTeamsCore(self.tmp.name)
        barrier = threading.Barrier(3)
        claims = []

        def claim(core):
            barrier.wait()
            claims.append(core.claim_workflow(workflow_run_id))

        threads = [threading.Thread(target=claim, args=(core,))
                   for core in (self.core, second)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(sorted(item for item in claims if item is not None), [workflow_run_id])
        self.assertEqual(claims.count(None), 1)
        self.assertEqual(self.core.workflow(workflow_run_id)["state"], "running")

    def test_scoped_executor_recovery_does_not_requeue_other_running_work(self):
        _first_task, first_workflow_id = self.make_workflow(["First worker"])
        _second_task, second_workflow_id = self.make_workflow(["Second worker"])
        self.assertEqual(self.core.claim_workflow(first_workflow_id), first_workflow_id)
        self.assertEqual(self.core.claim_workflow(second_workflow_id), second_workflow_id)

        self.assertTrue(self.core.recover_interrupted_workflow(first_workflow_id))

        self.assertEqual(self.core.workflow(first_workflow_id)["state"], "ready")
        self.assertEqual(self.core.workflow(second_workflow_id)["state"], "running")

    def test_failed_attempt_is_persisted_and_next_attempt_gets_recovery_context(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])

        def fail(_employee, _work_order, _emit):
            raise RuntimeError("connection dropped")

        first = self.core.run_workflow(
            workflow_run_id, fail, max_attempts=3, retry_delay_sec=0)
        waiting = self.core.workflow(workflow_run_id)
        self.assertEqual(first["status"], "failed")
        self.assertEqual(waiting["state"], "waiting_retry")
        self.assertIsNotNone(waiting["available_at"])
        received = []

        def recover(employee, work_order, emit):
            received.append(work_order)
            return self.completed(employee, work_order, emit)

        second = RunTeamsCore(self.tmp.name)
        result = second.run_next(recover, max_attempts=3, retry_delay_sec=0)
        workflow = second.workflow(workflow_run_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(workflow["state"], "completed")
        self.assertEqual([item["attempt"] for item in workflow["employee_runs"]], [1, 2])
        recovery = received[0]["context"]["recovery_context"]
        self.assertEqual(recovery["state"], "failed")
        self.assertEqual(recovery["attempt"], 1)
        self.assertIn("connection dropped", recovery["issues"])

    def test_rate_limit_waits_for_declared_reset_without_consuming_failure_budget(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])
        reset = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        reset_label = reset.strftime("%b %d")

        def limited(_employee, _work_order, _emit):
            raise RateLimited(
                "You've hit your weekly limit · resets {} at 4pm (America/New_York)".format(
                    reset_label))

        result = self.core.run_workflow(
            workflow_run_id, limited, max_attempts=2, retry_delay_sec=0)
        waiting = self.core.workflow(workflow_run_id)
        self.assertEqual(result["status"], "waiting_retry")
        self.assertEqual(waiting["state"], "waiting_retry")
        self.assertEqual(waiting["employee_runs"][0]["state"], "interrupted")
        self.assertIn(reset.strftime("%Y-%m-%d"), waiting["available_at"])
        self.assertTrue(any(item["type"] == "workflow.quota_waiting"
                            for item in waiting["events"]))
        self.assertIn("weekly limit", self.core.failure_reasons()[0])

        self.core.retry_workflow(workflow_run_id)
        failed = self.core.run_workflow(
            workflow_run_id, lambda *_args: (_ for _ in ()).throw(RuntimeError("hard fail")),
            max_attempts=2, retry_delay_sec=0)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.core.workflow(workflow_run_id)["state"], "waiting_retry")

    def test_transient_disconnect_is_deferred_without_becoming_employee_failure(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])

        def disconnected(_employee, _work_order, _emit):
            raise Transient("connection reset")

        result = self.core.run_workflow(workflow_run_id, disconnected)
        workflow = self.core.workflow(workflow_run_id)
        self.assertEqual(result["status"], "waiting_retry")
        self.assertEqual(workflow["state"], "waiting_retry")
        self.assertEqual(workflow["employee_runs"][0]["state"], "interrupted")
        self.assertTrue(any(item["type"] == "workflow.transient_waiting"
                            for item in workflow["events"]))
        self.assertIn("connection reset", self.core.failure_reasons()[0])

    def test_retry_due_time_survives_restart_and_manual_retry_makes_it_claimable(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])

        def fail(_employee, _work_order, _emit):
            raise RuntimeError("temporary failure")

        self.core.run_workflow(workflow_run_id, fail, retry_delay_sec=60)
        restarted = RunTeamsCore(self.tmp.name)
        self.assertIsNone(restarted.claim_workflow(workflow_run_id))
        restarted.retry_workflow(workflow_run_id)
        self.assertEqual(restarted.claim_workflow(workflow_run_id), workflow_run_id)

    def test_human_response_resumes_same_position_with_explicit_context(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])

        def ask(_employee, _work_order, _emit):
            return {"status": "needs_human", "summary": "", "issues": [], "artifacts": [],
                    "output": {"question": "Which audience should I use?",
                               "context": "The draft supports founders or operators."}}

        self.core.run_workflow(workflow_run_id, ask)
        self.assertEqual(self.core.workflow(workflow_run_id)["state"], "needs_human")
        with self.assertRaisesRegex(ContractError, "请先回复"):
            self.core.retry_workflow(workflow_run_id)

        resumed = self.core.respond_to_human(workflow_run_id, "Use startup founders.")
        self.assertEqual(resumed["state"], "ready")
        received = []

        def continue_after_reply(employee, work_order, emit):
            received.append(work_order)
            return self.completed(employee, work_order, emit)

        result = self.core.run_workflow(workflow_run_id, continue_after_reply)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(received[0]["context"]["human_response"], {
            "question": "Which audience should I use?",
            "context": "The draft supports founders or operators.",
            "response": "Use startup founders.",
        })
        self.assertIn({
            "name": "human-response.txt",
            "content": "Use startup founders.",
            "source": "human",
        }, received[0]["inputs"])
        workflow = self.core.workflow(workflow_run_id)
        self.assertEqual([item["state"] for item in workflow["employee_runs"]],
                         ["needs_human", "completed"])
        response_event = next(item for item in workflow["events"]
                              if item["type"] == "workflow.human_responded")
        self.assertEqual(response_event["data_json"]["employee_run_id"],
                         workflow["employee_runs"][0]["id"])

    def test_conditional_route_selects_one_declared_downstream(self):
        employees = []
        for role in ("Router", "Recovery", "Delivery"):
            employee_id = self.core.create_employee(role, draft(role, self.package_id))
            publish_verified_employee(self.core, employee_id)
            employees.append(employee_id)
        pipeline_id = self.core.create_pipeline("Conditional", {
            "positions": [
                {"key": "router", "employee_id": employees[0]},
                {"key": "recovery", "employee_id": employees[1]},
                {"key": "delivery", "employee_id": employees[2]},
            ],
            "edges": [
                {"from": "router", "to": "recovery", "when": "failed"},
                {"from": "router", "to": "delivery"},
                {"from": "recovery", "to": "delivery"},
            ],
        })
        task_id = self.core.create_task(
            pipeline_id, "Choose route", {"objective": "Deliver"})
        workflow_id = self.core.start_workflow(task_id)
        called = []

        def runtime(employee, work_order, emit):
            called.append(employee["name"])
            return self.completed(employee, work_order, emit)

        result = self.core.run_workflow(workflow_id, runtime)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(called, ["Router", "Delivery"])
        self.assertEqual(self.core.workflow(workflow_id)["cursor_key"], "delivery")

    def test_fixed_approval_can_rework_upstream_then_continue(self):
        employees = []
        for role in ("Maker", "Publisher"):
            employee_id = self.core.create_employee(role, draft(role, self.package_id))
            publish_verified_employee(self.core, employee_id)
            employees.append(employee_id)
        pipeline_id = self.core.create_pipeline("Approval loop", {
            "positions": [
                {"key": "maker", "employee_id": employees[0]},
                {"key": "approval", "name": "Owner approval", "kind": "approval"},
                {"key": "publisher", "employee_id": employees[1]},
            ],
            "edges": [
                {"from": "maker", "to": "approval"},
                {"from": "approval", "to": "publisher", "when": "approved"},
                {"from": "approval", "to": "maker", "when": "rejected"},
            ],
        })
        task_id = self.core.create_task(
            pipeline_id, "Review loop", {"objective": "Publish"})
        workflow_id = self.core.start_workflow(task_id)
        called = []

        def runtime(employee, work_order, emit):
            called.append(employee["name"])
            return self.completed(employee, work_order, emit)

        self.assertEqual(self.core.run_workflow(workflow_id, runtime)["status"],
                         "needs_approval")
        rejected = self.core.decide_workflow_approval(workflow_id, False, "Revise it")
        self.assertEqual(rejected["state"], "ready")
        self.assertEqual(self.core.run_workflow(workflow_id, runtime)["status"],
                         "needs_approval")
        approved = self.core.decide_workflow_approval(workflow_id, True)
        self.assertEqual(approved["state"], "ready")
        self.core.run_workflow(workflow_id, runtime)
        self.assertEqual(called, ["Maker", "Maker", "Publisher"])
        self.assertEqual(self.core.workflow(workflow_id)["state"], "completed")

    def test_pipeline_pause_and_resume_preserve_the_work_cursor(self):
        _task_id, workflow_id = self.make_workflow(["Researcher", "Writer"])
        workflow = self.core.workflow(workflow_id)
        pipeline_id = workflow["snapshot_json"]["pipeline_id"]
        paused = self.core.pause_pipeline(pipeline_id)
        self.assertIsNotNone(paused["paused_at"])
        self.assertIsNone(self.core.claim_workflow(workflow_id))
        self.assertEqual(self.core.workflow(workflow_id)["state"], "paused")
        resumed = self.core.resume_pipeline(pipeline_id)
        self.assertIsNone(resumed["paused_at"])
        self.assertEqual(self.core.workflow(workflow_id)["state"], "ready")
        self.assertEqual(self.core.claim_workflow(workflow_id), workflow_id)

    def test_blocked_retry_preserves_reason_and_recovery_instruction(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])

        def blocked(_employee, _work_order, _emit):
            return {"status": "blocked", "summary": "", "artifacts": [],
                    "issues": ["Source file is missing"],
                    "output": {"reason": "Source file is missing",
                               "recovery": "Check the newly supplied source file."}}

        self.core.run_workflow(workflow_run_id, blocked)
        self.core.retry_workflow(workflow_run_id)
        received = []

        def recover(employee, work_order, emit):
            received.append(work_order)
            return self.completed(employee, work_order, emit)

        self.core.run_workflow(workflow_run_id, recover)
        self.assertEqual(received[0]["context"]["recovery_context"], {
            "state": "blocked", "attempt": 1,
            "issues": ["Source file is missing"],
            "instruction": "Check the newly supplied source file.",
        })

    def test_unmodified_retry_resumes_failed_position_without_repeating_upstream(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher", "Writer"])

        def first_pass(employee, work_order, emit):
            if employee["name"] == "Researcher":
                return self.completed(employee, work_order, emit)
            return {"status": "failed", "summary": "draft failed", "output": {},
                    "artifacts": [], "issues": ["temporary draft failure"]}

        self.core.run_workflow(workflow_run_id, first_pass, max_attempts=1)
        self.core.retry_workflow(workflow_run_id)
        rerun = []

        def second_pass(employee, work_order, emit):
            rerun.append((employee["name"], work_order))
            return self.completed(employee, work_order, emit)

        self.core.run_workflow(workflow_run_id, second_pass, max_attempts=1)
        self.assertEqual([name for name, _order in rerun], ["Writer"])
        self.assertEqual(rerun[0][1]["context"]["recovery_context"]["issues"],
                         ["temporary draft failure"])

    def test_edited_task_is_recompiled_on_retry_and_restarts_the_full_pipeline(self):
        task_id, workflow_run_id = self.make_workflow(["Researcher", "Writer"])

        def first_pass(employee, work_order, emit):
            if employee["name"] == "Researcher":
                return self.completed(employee, work_order, emit)
            return {"status": "failed", "summary": "old draft failed", "output": {},
                    "artifacts": [], "issues": ["old task failure"]}

        self.core.run_workflow(workflow_run_id, first_pass, max_attempts=1)
        before = self.core.workflow(workflow_run_id)
        self.assertEqual([item["state"] for item in before["employee_runs"]],
                         ["completed", "failed"])

        self.core.update_workflow_task(
            workflow_run_id, "Revised durable task", "Complete the revised work")
        self.core.retry_workflow(workflow_run_id)
        restarted = self.core.workflow(workflow_run_id)
        self.assertEqual(restarted["snapshot_json"]["task"]["title"],
                         "Revised durable task")
        self.assertEqual(restarted["snapshot_json"]["task"]["payload"]["objective"],
                         "Complete the revised work")
        self.assertEqual([item["state"] for item in restarted["employee_runs"]],
                         ["completed", "failed"])
        self.assertEqual(self.core._workflow_board_column(restarted), "position-1")
        recompiled = [event for event in restarted["events"]
                      if event["type"] == "workflow.task_recompiled"]
        self.assertEqual(len(recompiled), 1)
        self.assertEqual(recompiled[0]["data_json"]["after_employee_run_id"],
                         restarted["employee_runs"][-1]["id"])

        rerun = []

        def second_pass(employee, work_order, emit):
            rerun.append((employee["name"], work_order))
            return self.completed(employee, work_order, emit)

        self.core.run_workflow(workflow_run_id, second_pass, max_attempts=1)
        final = self.core.workflow(workflow_run_id)
        self.assertEqual([name for name, _order in rerun], ["Researcher", "Writer"])
        self.assertEqual(rerun[0][1]["objective"], "Complete the revised work")
        self.assertNotIn("recovery_context", rerun[0][1]["context"])
        self.assertEqual(final["state"], "completed")
        self.assertEqual([item["state"] for item in final["employee_runs"]],
                         ["completed", "failed", "completed", "completed"])
        self.assertEqual(final["employee_runs"][0]["input_json"]["objective"],
                         "Complete durable work")
        self.assertEqual(final["employee_runs"][2]["input_json"]["objective"],
                         "Complete the revised work")
        self.assertEqual(self.core.task(task_id)["state"], "completed")

    def test_attention_catalog_is_a_projection_of_current_workflow_state(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])
        self.core.run_workflow(workflow_run_id, lambda *_args: {
            "status": "needs_human", "summary": "", "issues": [], "artifacts": [],
            "output": {"question": "Which audience?", "context": {"options": 2}},
        })

        attention = self.core.attention_catalog()

        self.assertEqual(len(attention), 1)
        self.assertEqual(attention[0]["id"], "workflow:{}".format(workflow_run_id))
        self.assertEqual(attention[0]["target_type"], "workflow")
        self.assertEqual(attention[0]["reason"], "Which audience?")
        self.assertEqual(attention[0]["context"], '{"options": 2}')
        self.assertEqual(attention[0]["attempted"], [
            "Researcher：第 1 次运行，需要处理",
        ])
        self.assertEqual(
            attention[0]["resume_from"],
            "回复后从「Researcher」继续；已完成的上游岗位不会重新运行。")
        self.assertEqual([item["id"] for item in attention[0]["actions"]],
                         ["respond", "terminate"])

        self.core.respond_to_human(workflow_run_id, "Founders")
        self.assertEqual(self.core.attention_catalog(), [])

    def test_waiting_human_workflow_can_be_explicitly_terminated(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])

        self.core.run_workflow(workflow_run_id, lambda *_args: {
            "status": "needs_human", "summary": "", "issues": [], "artifacts": [],
            "output": {"question": "Continue?"},
        })
        canceled = self.core.cancel_workflow(workflow_run_id)
        self.assertEqual(canceled["state"], "canceled")
        self.assertEqual(self.core.task(canceled["task_id"])["state"], "canceled")

    def test_restart_skips_completed_employee_and_requeues_interrupted_position(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher", "Writer"])
        calls = []

        def crash_on_second(employee, work_order, emit):
            calls.append(employee["name"])
            if employee["name"] == "Writer":
                raise SimulatedProcessCrash("app disappeared")
            return self.completed(employee, work_order, emit)

        with self.assertRaises(SimulatedProcessCrash):
            self.core.run_workflow(workflow_run_id, crash_on_second)
        crashed = self.core.workflow(workflow_run_id)
        self.assertEqual(crashed["state"], "running")
        self.assertEqual([item["state"] for item in crashed["employee_runs"]],
                         ["completed", "running"])

        restarted = RunTeamsCore(self.tmp.name)
        self.assertEqual(restarted.recover_interrupted_workflows(), [workflow_run_id])
        resumed_calls = []
        resumed_orders = []

        def resume(employee, work_order, emit):
            resumed_calls.append(employee["name"])
            resumed_orders.append(work_order)
            return self.completed(employee, work_order, emit)

        result = restarted.run_next(resume)
        workflow = restarted.workflow(workflow_run_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(calls, ["Researcher", "Writer"])
        self.assertEqual(resumed_calls, ["Writer"])
        self.assertEqual([item["state"] for item in workflow["employee_runs"]],
                         ["completed", "interrupted", "completed"])
        self.assertEqual(resumed_orders[0]["context"]["upstream_position"], "position-1")
        self.assertEqual(resumed_orders[0]["context"]["upstream_output"]["employee"],
                         "Researcher")
        self.assertEqual(resumed_orders[0]["context"]["recovery_context"]["state"],
                         "interrupted")

    def test_active_cancellation_stops_runtime_and_cannot_be_overwritten(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])
        started = threading.Event()
        outcome = []

        class WaitingRuntime:
            def run(_self, _employee, _work_order, _emit, *, employee_run_id, database,
                    cancel_event):
                self.assertGreater(employee_run_id, 0)
                self.assertTrue(database.endswith("runteams.db"))
                started.set()
                cancel_event.wait(5)
                raise Cancelled("stopped")

        thread = threading.Thread(
            target=lambda: outcome.append(self.core.run_workflow(
                workflow_run_id, WaitingRuntime(), retry_delay_sec=0)))
        thread.start()
        self.assertTrue(started.wait(5))
        canceled = self.core.cancel_workflow(workflow_run_id)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(canceled["state"], "canceled")
        self.assertEqual(outcome[0]["status"], "canceled")
        final = self.core.workflow(workflow_run_id)
        self.assertEqual(final["state"], "canceled")
        self.assertEqual(final["employee_runs"][0]["state"], "canceled")

    def test_completed_workflow_is_idempotent_and_runtime_is_not_called_again(self):
        _task_id, workflow_run_id = self.make_workflow(["Researcher"])
        first = self.core.run_workflow(workflow_run_id, self.completed)

        def should_not_run(*_args):
            raise AssertionError("completed workflow ran twice")

        second = self.core.run_workflow(workflow_run_id, should_not_run)
        self.assertEqual(second, first)
        self.assertEqual(len(self.core.workflow(workflow_run_id)["employee_runs"]), 1)


if __name__ == "__main__":
    unittest.main()
