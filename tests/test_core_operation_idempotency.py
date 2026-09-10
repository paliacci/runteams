import json
from pathlib import Path
import tempfile
import unittest

from runteams_core import RunTeamsCore
from runteams_core.protocol import EmployeeProtocol, tool_definitions
from scripts.fixture_validation import publish_verified_employee


class SimulatedReceiptLoss(BaseException):
    pass


class CoreOperationIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runteams-operation-")
        self.root = Path(self.temporary.name)
        self.core = RunTeamsCore(self.root)
        package = self._import_operation_package()
        employee_id = self.core.create_employee("Publisher", {
            "role": "Perform one controlled external operation",
            "program": {
                "objective": "Perform the requested operation once",
                "steps": [{"id": "publish", "instruction": "Publish once"}],
                "acceptance": ["The external operation happened exactly once"],
            },
            "capabilities": [{"package_id": package["package_id"],
                              "capability_id": "publish-record"}],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline("Publish flow", {
            "positions": [{"key": "publish", "employee_id": employee_id}], "edges": [],
        })
        task_id = self.core.create_task(
            pipeline_id, "Publish", {"objective": "Publish the record"})
        self.workflow_run_id = self.core.start_workflow(task_id)
        self.workspace = self.root / "operation-workspace"
        self.counter = self.workspace / "operation-count.txt"
        self.child_invocation = self.workspace / "operation-invocation.txt"

    def tearDown(self):
        self.temporary.cleanup()

    def _import_operation_package(self):
        source = self.root / "operation-package"
        (source / "scripts").mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: operation-package\ndescription: Test one durable operation.\n---\n",
            encoding="utf-8")
        (source / "runteams.json").write_text(json.dumps({
            "schema": "runteams.package-extension/v1",
            "capabilities": [{
                "id": "publish-record", "name": "Publish record",
                "entry": "scripts/publish.py",
                "runtime": {"version": 2, "runner": "python", "effect": "operation",
                            "dependencies": [],
                            "healthcheck": {
                                "cases": [{"arguments": ["--self-check"],
                                           "expected": "passed"}]}},
            }],
        }), encoding="utf-8")
        (source / "scripts" / "publish.py").write_text(
            "import json, os, pathlib, sys\n"
            "if '--self-check' in sys.argv:\n"
            "    count = 0\n"
            "else:\n"
            "    target = pathlib.Path('operation-count.txt')\n"
            "    count = int(target.read_text() if target.exists() else '0') + 1\n"
            "    target.write_text(str(count))\n"
            "    pathlib.Path('operation-invocation.txt').write_text("
            "os.environ.get('RUNTEAMS_INVOCATION_ID', ''))\n"
            "print(json.dumps({'schema':'runteams.tool-result/v1',"
            "'execution':{'status':'completed','exit_code':0},"
            "'evaluation':{'status':'passed','owner':'none','code':'passed','summary':'ok'},"
            "'evidence':{'output':str(count),'artifacts':[],'truncated':False}}))\n",
            encoding="utf-8")
        return self.core.import_package("operation-package", source)

    def test_completed_operation_is_reused_by_invocation_id_across_protocol_instances(self):
        test = self

        class Runtime:
            def run(_self, _employee, _work_order, _emit, *, employee_run_id, database):
                test.workspace.mkdir(parents=True, exist_ok=True)
                first_protocol = EmployeeProtocol(database, employee_run_id, test.workspace)
                task = first_protocol.call("get_task", {})["structuredContent"]
                operation = next(item for item in task["capabilities"]
                                 if item["ref"] == "operation-package/publish-record")
                test.assertEqual(operation["effect"], "operation")
                run_tool = next(item for item in tool_definitions(first_protocol)
                                if item["name"] == "run_capability")
                test.assertIn("invocation_id", run_tool["inputSchema"]["properties"])
                missing_id = first_protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"],
                })
                test.assertTrue(missing_id["isError"])
                test.assertFalse(test.counter.exists())
                first = first_protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"], "invocation_id": "publish-record-1",
                })
                test.assertFalse(first["isError"])
                test.assertEqual(test.child_invocation.read_text(encoding="utf-8"),
                                 "publish-record-1")

                restarted_protocol = EmployeeProtocol(database, employee_run_id, test.workspace)
                repeated = restarted_protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"], "invocation_id": "publish-record-1",
                })
                test.assertFalse(repeated["isError"])
                test.assertTrue(repeated["structuredContent"]["reused"])
                conflict = restarted_protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-b"], "invocation_id": "publish-record-1",
                })
                test.assertTrue(conflict["isError"])
                test.assertEqual(test.counter.read_text(encoding="utf-8"), "1")
                restarted_protocol.call(
                    "advance_step", {"step_id": "publish", "summary": "published"})
                completed = restarted_protocol.call(
                    "complete", {"summary": "published once", "output": {}})
                return completed["structuredContent"]["result"]

        result = self.core.run_workflow(self.workflow_run_id, Runtime())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.counter.read_text(encoding="utf-8"), "1")

    def test_receipt_loss_is_in_doubt_and_never_blindly_replays_after_restart(self):
        test = self

        class CrashingRuntime:
            def run(_self, _employee, _work_order, _emit, *, employee_run_id, database):
                test.workspace.mkdir(parents=True, exist_ok=True)
                protocol = EmployeeProtocol(database, employee_run_id, test.workspace)
                original_event = protocol.repository.event

                def lose_receipt(stream, event_type, data, connection=None):
                    if event_type == "capability.invocation_completed":
                        raise SimulatedReceiptLoss("process disappeared before receipt commit")
                    return original_event(stream, event_type, data, connection=connection)

                protocol.repository.event = lose_receipt
                protocol.call("get_task", {})
                protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"], "invocation_id": "publish-record-1",
                })

        with self.assertRaises(SimulatedReceiptLoss):
            self.core.run_workflow(self.workflow_run_id, CrashingRuntime())
        self.assertEqual(self.counter.read_text(encoding="utf-8"), "1")
        self.assertEqual(self.child_invocation.read_text(encoding="utf-8"),
                         "publish-record-1")

        restarted = RunTeamsCore(self.root)
        self.assertEqual(restarted.recover_interrupted_workflows(), [self.workflow_run_id])

        class RecoveryRuntime:
            def run(_self, _employee, _work_order, _emit, *, employee_run_id, database):
                protocol = EmployeeProtocol(database, employee_run_id, test.workspace)
                task = protocol.call("get_task", {})["structuredContent"]
                test.assertEqual(task["checkpoint"]["operation_invocations"], [{
                    "invocation_id": "publish-record-1",
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"],
                    "state": "in_doubt",
                }])
                same = protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"], "invocation_id": "publish-record-1",
                })
                test.assertTrue(same["isError"])
                different = protocol.call("run_capability", {
                    "capability_ref": "operation-package/publish-record",
                    "arguments": ["record-a"], "invocation_id": "publish-record-2",
                })
                test.assertTrue(different["isError"])
                test.assertIn("禁止自动重放", different["structuredContent"]["message"])
                return {"status": "blocked", "summary": "", "artifacts": [],
                        "issues": ["operation result is unknown"],
                        "output": {"reason": "operation result is unknown",
                                   "recovery": "verify the external system"}}

        result = restarted.run_next(RecoveryRuntime())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.counter.read_text(encoding="utf-8"), "1")


if __name__ == "__main__":
    unittest.main()
