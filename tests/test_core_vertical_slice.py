import os
import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from runteams_core import ContractError, DocumentLossError, RunTeamsCore
from runteams_core.contracts import (
    employee_coverage_targets,
    normalize_employee_draft,
    work_order_payload,
)
from runteams_core.protocol import EmployeeProtocol
from scripts.fixture_validation import publish_verified_employee, verify_employee


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def employee_draft(role, package_id, capability_id):
    return {
        "role": role,
        "program": {"objective": role,
                    "steps": [{"id": "work", "instruction": "完成工作并结构化交付"}],
                    "acceptance": ["结果可被下一名员工使用"]},
        "capabilities": [{"package_id": package_id, "capability_id": capability_id}],
        "runtime": {"channel": "codex", "model": "gpt-test", "effort": "high"},
    }


class CoreVerticalSliceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-core-")
        self.core = RunTeamsCore(self.tmp.name)
        self.package = self.core.import_package(
            "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_chat_document_uses_shared_revision_store_and_live_view(self):
        created = self.core.create_agent_document(
            "需求挖掘总览",
            "# 需求挖掘总览\n\n按机会逐条整理市场信号和结论。",
            document_key="demand-overview",
            data_view={"kind": "opportunities", "columns": [
                "title", "analysis_decision", "evidence_count"]},
            note="由 Agent Chat 整理",
        )
        self.assertEqual(created["source"], "agent_chat")
        self.assertEqual(created["document_key"], "demand-overview")
        self.assertEqual(created["revision"], 1)
        detail = self.core.document_detail(created["id"])
        self.assertEqual(detail["employee_run_id"], 0)
        self.assertEqual(detail["employee_name"], "Agent Chat")
        self.assertIn("市场信号", detail["content"])
        self.assertEqual(detail["data_view"]["kind"], "opportunities")
        self.assertIn("opportunities", detail["data"])

        revised = self.core.update_agent_document(
            created["id"], content="# 需求挖掘总览\n\n已补充证据和下一步建议。")
        self.assertNotEqual(revised["id"], created["id"])
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["revision_count"], 2)
        self.assertEqual(
            [item["revision"] for item in self.core.document_revisions(revised["id"])],
            [1, 2],
        )
        catalog = self.core.document_catalog(limit=50, query="需求挖掘总览")
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["id"], revised["id"])
        self.assertEqual(catalog[0]["source"], "agent_chat")
        self.assertEqual(len(self.core.document_catalog(limit=50, query="demand-overview")), 1)
        with self.assertRaises(ContractError):
            self.core.create_agent_document(
                "不安全视图", "内容", document_key="unsafe-view",
                data_view={"kind": "sql", "query": "select * from artifacts"})

        chinese = self.core.create_agent_document("市场机会总览", "# 市场机会总览\n\n内容")
        self.assertTrue(chinese["document_key"].startswith("doc-"))

    def test_platform_work_order_fields_do_not_pollute_employee_input_contract(self):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["objective", "context", "inputs", "expected_output", "acceptance"],
            "properties": {
                "objective": {"type": "string"},
                "context": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"project": {"type": "string"}},
                },
                "inputs": {"type": "array"},
                "expected_output": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"format": {"type": "string"}},
                },
                "acceptance": {"type": "array"},
            },
        }
        payload = work_order_payload({
            "schema": "runteams.work-order/v1",
            "objective": "Ship",
            "context": {
                "project": "Forge", "team_parameters": [{"key": "locale"}],
                "team_standards": [{"key": "quality"}],
            },
            "inputs": [],
            "expected_output": {
                "format": "markdown",
                "documents": [{"path": "PRD.md", "required": True}],
                "team_parameters": [{"key": "approval"}],
            },
            "acceptance": [],
        }, schema)
        self.assertEqual(payload["context"], {"project": "Forge"})
        self.assertEqual(payload["expected_output"], {"format": "markdown"})

    def _import_credential_tool(self):
        parent = tempfile.mkdtemp(prefix="credential-package-")
        self.addCleanup(shutil.rmtree, parent, True)
        source = Path(parent) / "credential-probe"
        (source / "scripts").mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: credential-probe\ndescription: Probe explicit credential injection.\n---\n",
            encoding="utf-8")
        (source / "runteams.json").write_text(json.dumps({
            "schema": "runteams.package-extension/v1",
            "capabilities": [{
                "id": "probe-service", "name": "Credential probe",
                "entry": "scripts/probe.py", "credentials": ["SERVICE_TOKEN"],
                "runtime": {"version": 2, "runner": "python", "effect": "diagnostic",
                            "dependencies": [],
                            "healthcheck": {
                                "cases": [{"arguments": ["--self-check"],
                                           "expected": "passed"}]}},
            }],
        }), encoding="utf-8")
        (source / "scripts" / "probe.py").write_text(
            "import json, os, sys\n"
            "selfcheck = '--self-check' in sys.argv\n"
            "evidence = {'declared': bool(os.environ.get('SERVICE_TOKEN')), "
            "'undeclared': bool(os.environ.get('UNDECLARED_TEST_SECRET')), "
            "'echo': os.environ.get('SERVICE_TOKEN', ''), "
            "'keys': {os.environ.get('SERVICE_TOKEN', ''): True}}\n"
            "print(json.dumps({'schema':'runteams.tool-result/v1',"
            "'execution':{'status':'completed','exit_code':0},"
            "'evaluation':{'status':'passed','owner':'none','code':'passed','summary':'ok'},"
            "'evidence':{'output':json.dumps(evidence),'artifacts':[],'truncated':False}}))\n",
            encoding="utf-8")
        return self.core.import_package("credential-probe", source)

    def test_native_extension_reference_is_frozen_without_local_paths(self):
        dependency = {
            "provider": "codex", "plugin_id": "figma@official", "name": "Figma",
            "version": "1.2.3", "fingerprint": "content-digest",
            "runtime": {"plugin_dir": "/private/plugin", "marketplace": "official",
                        "marketplace_root": "/private/marketplace"},
        }
        core = RunTeamsCore(
            Path(self.tmp.name) / "native",
            native_dependency_resolver=lambda _provider, _plugin_id: dependency)
        employee_id = core.create_employee("Designer", {
            "role": "Design interfaces",
            "program": {"objective": "Deliver UI", "steps": [{
                "id": "design", "instruction": "Design the interface",
            }], "acceptance": ["UI is reviewable"]},
            "capabilities": [{"provider": "codex", "plugin_id": "figma@official"}],
            "runtime": {"channel": "codex", "model": "gpt-test", "effort": "high"},
        })
        snapshot, checks = core._release_snapshot(core.employee(employee_id), verify=True)
        self.assertEqual(snapshot["capabilities"], [{
            "provider": "codex", "plugin_id": "figma@official", "name": "Figma",
            "version": "1.2.3", "fingerprint": "content-digest",
        }])
        self.assertNotIn("runtime", snapshot["capabilities"][0])
        self.assertEqual(checks[0]["kind"], "extension")

        other_channel = copy.deepcopy(core.employee(employee_id))
        other_channel["draft_json"]["runtime"]["channel"] = "claude-code"
        with self.assertRaisesRegex(ContractError, "当前模型渠道"):
            core._release_snapshot(other_channel, verify=True)

    def test_package_import_is_content_addressed_and_really_runs_healthcheck(self):
        package = self.core.package(self.package["package_id"])
        self.assertEqual(package["digest"], self.package["digest"])
        self.assertTrue(os.path.isfile(os.path.join(package["blob_ref"], "SKILL.md")))
        self.assertFalse(any(name == "__pycache__" for _root, dirs, _files in
                             os.walk(package["blob_ref"]) for name in dirs))
        self.assertEqual(os.stat(os.path.join(package["blob_ref"], "SKILL.md")).st_mode & 0o222, 0)
        self.assertEqual([item["status"] for item in self.package["checks"]],
                         ["verified", "verified"])
        again = self.core.import_package(
            "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
        self.assertEqual(again["revision_id"], self.package["revision_id"])
        detail = self.core.package_catalog()[0]
        self.assertEqual(detail["verification"]["status"], "verified")
        self.assertEqual(detail["manifest_json"]["display_name"], "交接简报验证")
        self.assertEqual([item["kind"] for item in detail["manifest_json"]["capabilities"]],
                         ["skill", "tool"])
        self.assertEqual(
            [item["name"] for item in detail["manifest_json"]["capabilities"]],
            ["交接简报检查方法", "验证交接简报"])
        self.assertTrue(all(item["description"]
                            for item in detail["manifest_json"]["capabilities"]))
        self.assertEqual({item["path"] for item in detail["manifest_json"]["files"]},
                         {"SKILL.md", "runteams.json", "scripts/validate_brief.py"})
        self.assertIn("Python", detail["verification"]["runner"])
        self.assertTrue(detail["verification"]["checked_at"])

    def test_revalidation_records_current_environment_failure_without_changing_revision(self):
        before = self.core.package_detail(self.package["package_id"])
        with mock.patch.object(
                self.core.packages, "verify_manifest",
                side_effect=ContractError("managed runtime is unavailable")):
            failed = self.core.package_detail(self.package["package_id"], verify=True)
        self.assertEqual(failed["active_revision_id"], before["active_revision_id"])
        self.assertEqual(failed["digest"], before["digest"])
        self.assertEqual(failed["verification"]["status"], "failed")
        self.assertEqual(failed["verification"]["error"],
                         "managed runtime is unavailable")
        self.assertIn("Python", failed["verification"]["runner"])
        self.assertEqual(self.core.package_catalog()[0]["verification"]["status"], "failed")

        recovered = self.core.package_detail(self.package["package_id"], verify=True)
        self.assertEqual(recovered["active_revision_id"], before["active_revision_id"])
        self.assertEqual(recovered["verification"]["status"], "verified")
        self.assertEqual(recovered["verification"]["error"], "")

    def test_imports_pinned_public_agent_skill_without_runteams_extension(self):
        source = os.path.join(
            ROOT, "tests", "fixtures", "public-agent-skills", "brand-guidelines")
        imported = self.core.import_package("public-brand-guidelines", source)
        self.assertEqual(
            imported["digest"],
            "0338e6d90b753754016f122e57244a19195763b6fcc2453188eef31da1f5578e")
        manifest = imported["manifest"]
        self.assertEqual(manifest["format"], "agent-skill")
        self.assertEqual(manifest["extensions"]["agent_skills"]["name"],
                         "brand-guidelines")
        self.assertEqual(manifest["extensions"]["agent_skills"]["license"],
                         "Complete terms in LICENSE.txt")
        self.assertEqual(
            [(item["id"], item["kind"]) for item in manifest["capabilities"]],
            [("brand-guidelines", "skill")])
        self.assertEqual({item["path"] for item in manifest["files"]},
                         {"SKILL.md", "LICENSE.txt"})
        self.assertEqual(imported["checks"], [{
            "capability_id": "brand-guidelines", "status": "verified",
            "kind": "skill", "detail": "SKILL.md 结构有效",
        }])

    def test_declared_credentials_gate_release_and_are_the_only_secrets_injected(self):
        imported = self._import_credential_tool()
        available = set()
        self.core.credential_names_provider = lambda: available
        employee_id = self.core.create_employee(
            "Credential user", employee_draft("Use service", imported["package_id"],
                                               "probe-service"))
        with self.assertRaisesRegex(ContractError, "SERVICE_TOKEN"):
            self.core.publish_employee(employee_id)

        available.add("SERVICE_TOKEN")
        release = publish_verified_employee(self.core, employee_id)
        capability = next(item for item in
                          release["snapshot"]["capabilities"][0]["capabilities"]
                          if item["id"] == "probe-service")
        self.assertEqual(capability["credentials"], ["SERVICE_TOKEN"])

        package = self.core.package(imported["package_id"])
        old_hidden = os.environ.get("UNDECLARED_TEST_SECRET")
        os.environ["UNDECLARED_TEST_SECRET"] = "must-not-leak"
        try:
            result = self.core.packages.run_tool(
                package["blob_ref"], capability, [], self.tmp.name,
                credentials={"SERVICE_TOKEN": "real-secret"})
        finally:
            if old_hidden is None:
                os.environ.pop("UNDECLARED_TEST_SECRET", None)
            else:
                os.environ["UNDECLARED_TEST_SECRET"] = old_hidden
        evidence = json.loads(result["evidence"]["output"])
        self.assertEqual(evidence, {"declared": True, "undeclared": False,
                                    "echo": "[REDACTED]",
                                    "keys": {"[REDACTED]": True}})
        self.assertNotIn("real-secret", json.dumps(result))

        pipeline_id = self.core.create_pipeline("Credential flow", {
            "positions": [{"key": "work", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(pipeline_id, "Use service", {"objective": "Work"})
        available.clear()
        with self.assertRaisesRegex(ContractError, "SERVICE_TOKEN"):
            self.core.start_workflow(task_id)

    def test_agent_runtime_model_credentials_cannot_be_declared_by_packages(self):
        imported = self._import_credential_tool()
        package = self.core.package(imported["package_id"])
        with tempfile.TemporaryDirectory(prefix="reserved-credential-") as parent:
            source = Path(parent) / "credential-probe"
            shutil.copytree(package["blob_ref"], source)
            extension_path = source / "runteams.json"
            extension = json.loads(extension_path.read_text(encoding="utf-8"))
            extension["capabilities"][0]["credentials"] = ["OPENAI_API_KEY"]
            extension_path.chmod(0o644)
            extension_path.write_text(json.dumps(extension), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "Agent Runtime"):
                self.core.import_package("reserved-credential", source)

    def test_published_employee_can_receive_production_work_without_a_pipeline(self):
        employee_id = self.core.create_employee(
            "Opportunity analyst", employee_draft(
                "Screen one opportunity", self.package["package_id"], "validate-brief"))
        release = publish_verified_employee(self.core, employee_id)
        payload = {
            "objective": "Record the screened opportunity",
            "context": {"opportunity_key": "jira-audit-evidence"},
            "acceptance": ["Evidence is traceable"],
        }
        task_id = self.core.create_employee_task(
            employee_id, "Jira audit evidence", payload)
        workflow_id = self.core.start_workflow(task_id, source={
            "automation_id": 7, "automation_run_id": 11,
        })

        workflow = self.core.workflow(workflow_id)
        snapshot = workflow["snapshot_json"]
        self.assertIsNone(snapshot["pipeline_id"])
        self.assertEqual(snapshot["employee_id"], employee_id)
        self.assertEqual(snapshot["definition"]["positions"][0]["employee_release_id"],
                         release["release_id"])
        self.assertEqual(workflow["cursor_key"], "employee")
        self.assertEqual(
            self.core.find_employee_task_by_context(
                employee_id, "opportunity_key", "jira-audit-evidence")["id"],
            task_id,
        )
        self.assertEqual(
            [item["id"] for item in self.core.employee_workflow_catalog(employee_id)],
            [workflow_id],
        )
        event = self.core.repository.events("automation:7")[-1]
        self.assertEqual(event["data_json"]["employee_id"], employee_id)
        self.assertNotIn("pipeline_id", event["data_json"])

    def test_tampered_package_object_is_rejected_before_publication(self):
        package = self.core.package(self.package["package_id"])
        skill_path = os.path.join(package["blob_ref"], "SKILL.md")
        os.chmod(skill_path, 0o644)
        with open(skill_path, "a", encoding="utf-8") as handle:
            handle.write("\ntampered\n")
        employee_id = self.core.create_employee(
            "Tamper check", employee_draft("Work", self.package["package_id"],
                                           "validate-brief"))
        with self.assertRaisesRegex(ContractError, "manifest"):
            self.core.publish_employee(employee_id)

    def test_agent_skill_frontmatter_supports_folded_description_and_metadata(self):
        with tempfile.TemporaryDirectory(prefix="folded-skill-parent-") as parent:
            source = os.path.join(parent, "folded-skill")
            os.mkdir(source)
            with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("""---
name: folded-skill
description: >
  Analyze structured briefs.
  Use when validating handoffs.
license: Apache-2.0
metadata:
  author: example-org
  version: "1.0"
---
# Folded skill
""")
            imported = self.core.import_package("folded", source)
        metadata = imported["manifest"]["extensions"]["agent_skills"]
        self.assertEqual(metadata["description"],
                         "Analyze structured briefs. Use when validating handoffs.")
        self.assertEqual(metadata["metadata"]["version"], "1.0")

    def test_agent_skill_name_must_match_directory(self):
        with tempfile.TemporaryDirectory(prefix="mismatched-skill-") as source:
            with open(os.path.join(source, "SKILL.md"), "w", encoding="utf-8") as handle:
                handle.write("---\nname: another-name\ndescription: mismatch\n---\n")
            with self.assertRaisesRegex(ContractError, "目录名"):
                self.core.import_package("mismatch", source)

    def test_package_key_cannot_escape_materialization_namespace(self):
        with self.assertRaisesRegex(ContractError, "能力包 key"):
            self.core.import_package("../outside", os.path.join(ROOT, "examples", "brief-validator"))

    def test_kernel_has_only_the_ten_deliberate_business_tables(self):
        with sqlite3.connect(os.path.join(self.tmp.name, "runteams.db")) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        self.assertEqual(tables, {"packages", "package_revisions", "employees",
                                 "employee_releases", "pipelines", "tasks", "workflow_runs",
                                 "employee_runs", "artifacts", "events"})

    def test_existing_core_database_is_widened_for_trials_without_new_tables(self):
        with tempfile.TemporaryDirectory(prefix="runteams-core-migration-") as root:
            database = os.path.join(root, "runteams.db")
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE tasks(
                      id INTEGER PRIMARY KEY,
                      pipeline_id INTEGER NOT NULL REFERENCES pipelines(id),
                      title TEXT NOT NULL, payload_json TEXT NOT NULL,
                      state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE employee_runs(
                      id INTEGER PRIMARY KEY,
                      workflow_run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
                      position_key TEXT NOT NULL,
                      employee_release_id INTEGER NOT NULL REFERENCES employee_releases(id),
                      attempt INTEGER NOT NULL, state TEXT NOT NULL,
                      input_json TEXT NOT NULL, output_json TEXT NOT NULL,
                      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                      UNIQUE(workflow_run_id,position_key,attempt));
                """)
            migrated = RunTeamsCore(root)
            with migrated.repository.connect() as connection:
                task_columns = {row[1]: row for row in connection.execute(
                    "PRAGMA table_info(tasks)")}
                run_columns = {row[1]: row for row in connection.execute(
                    "PRAGMA table_info(employee_runs)")}
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")}
            self.assertIn("employee_id", task_columns)
            self.assertEqual(task_columns["pipeline_id"][3], 0)
            self.assertEqual(run_columns["employee_release_id"][3], 0)
            self.assertEqual(len(tables), 10)

    def test_pipeline_trash_restore_and_permanent_delete_are_core_lifecycle(self):
        employee_id = self.core.create_employee(
            "Trash owner", employee_draft("Own pipeline", self.package["package_id"],
                                           "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline(
            "Recoverable pipeline",
            {"positions": [{"key": "owner", "employee_id": employee_id}], "edges": []})
        self.core.create_task(pipeline_id, "Saved task", {"objective": "Keep until purged"})

        trashed = self.core.trash_pipeline(pipeline_id)
        self.assertIsNotNone(trashed["trashed_at"])
        self.assertIsNone(self.core.pipeline(pipeline_id))
        self.assertEqual(self.core.pipeline_catalog(), [])
        self.assertEqual(self.core.pipeline_trash_catalog()[0]["count"], 1)
        with self.assertRaisesRegex(ContractError, "流水线不存在"):
            self.core.create_task(pipeline_id, "Hidden task", {"objective": "Do not start"})

        restored = self.core.restore_pipeline(pipeline_id)
        self.assertIsNone(restored["trashed_at"])
        self.assertEqual(self.core.pipeline_catalog()[0]["id"], pipeline_id)

        self.core.trash_pipeline(pipeline_id)
        self.assertTrue(self.core.delete_trashed_pipeline(pipeline_id))
        self.assertIsNone(self.core.pipeline(pipeline_id, include_trashed=True))
        with sqlite3.connect(os.path.join(self.tmp.name, "runteams.db")) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE pipeline_id=?", (pipeline_id,)
            ).fetchone()[0], 0)

    def test_pipeline_position_trash_restores_position_and_its_tasks(self):
        first_employee = self.core.create_employee(
            "First worker", employee_draft("Start the work", self.package["package_id"],
                                            "validate-brief"))
        second_employee = self.core.create_employee(
            "Second worker", employee_draft("Finish the work", self.package["package_id"],
                                             "validate-brief"))
        publish_verified_employee(self.core, first_employee)
        publish_verified_employee(self.core, second_employee)
        pipeline_id = self.core.create_pipeline("Position trash", {
            "positions": [
                {"key": "first", "name": "First", "employee_id": first_employee,
                 "color": "purple"},
                {"key": "second", "name": "Second", "employee_id": second_employee},
            ],
            "edges": [{"from": "first", "to": "second"}],
        })
        task_id = self.core.create_task(
            pipeline_id, "Recover with position", {"objective": "Keep this task"})
        workflow_id = self.core.start_workflow(task_id)

        trashed = self.core.trash_pipeline_position(pipeline_id, "first")
        self.assertEqual(trashed["kind"], "position")
        self.assertEqual(trashed["title"], "First")
        self.assertEqual(trashed["count"], 1)
        self.assertEqual(
            [item["key"] for item in self.core.pipeline(pipeline_id)["definition_json"]["positions"]],
            ["second"])
        self.assertIsNotNone(self.core.task(task_id)["trashed_at"])
        self.assertEqual(self.core.task_trash_catalog(), [])

        restored = self.core.restore_pipeline_position(trashed["id"])
        self.assertEqual(
            [item["key"] for item in restored["definition_json"]["positions"]],
            ["first", "second"])
        self.assertEqual(restored["definition_json"]["positions"][0]["color"], "purple")
        self.assertIsNone(self.core.task(task_id)["trashed_at"])
        self.assertEqual(self.core.pipeline_position_trash_catalog(), [])

        trashed_again = self.core.trash_pipeline_position(pipeline_id, "first")
        self.assertTrue(self.core.delete_trashed_pipeline_position(trashed_again["id"]))
        self.assertIsNone(self.core.workflow(workflow_id))
        with self.assertRaisesRegex(ContractError, "至少需要保留一个岗位"):
            self.core.trash_pipeline_position(pipeline_id, "second")

    def test_completed_business_exception_routes_back_for_rework(self):
        engineer_id = self.core.create_employee(
            "Engineer", employee_draft("Implement the work", self.package["package_id"],
                                        "validate-brief"))
        reviewer_id = self.core.create_employee(
            "Reviewer", employee_draft("Review the work", self.package["package_id"],
                                        "validate-brief"))
        publish_verified_employee(self.core, engineer_id)
        publish_verified_employee(self.core, reviewer_id)
        pipeline_id = self.core.create_pipeline("Rework loop", {
            "positions": [
                {"key": "engineering", "employee_id": engineer_id},
                {"key": "review", "employee_id": reviewer_id},
            ],
            "edges": [
                {"from": "engineering", "to": "review"},
                {"from": "review", "to": "engineering", "when": "exception"},
            ],
        })
        task_id = self.core.create_task(
            pipeline_id, "Implement and review", {"objective": "Ship reviewed work"})
        workflow_id = self.core.start_workflow(task_id)
        reviewer_visits = 0

        def runtime(employee, _work_order, _emit):
            nonlocal reviewer_visits
            route = "completed"
            if employee["name"] == "Reviewer":
                reviewer_visits += 1
                route = "exception" if reviewer_visits == 1 else "completed"
            return {"status": "completed", "summary": "finished",
                    "output": {"route": route}, "artifacts": [], "issues": []}

        self.core.run_workflow(workflow_id, runtime, max_attempts=1)
        workflow = self.core.workflow(workflow_id)
        self.assertEqual(workflow["state"], "completed")
        self.assertEqual([item["position_key"] for item in workflow["employee_runs"]],
                         ["engineering", "review", "engineering", "review"])
        self.assertEqual(reviewer_visits, 2)

    def _pipeline_run_with_document(self, name="Documented pipeline"):
        employee_id = self.core.create_employee(
            "Document author", employee_draft("Write the report",
                                              self.package["package_id"], "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline(
            name, {"positions": [{"key": "author", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(pipeline_id, "Write it",
                                        {"objective": "Produce one document"})
        workflow_run_id = self.core.start_workflow(task_id)
        self.core.run_workflow(workflow_run_id, lambda employee, work_order, emit: {
            "status": "completed", "summary": "done", "output": {"ok": True},
            "artifacts": [{"name": "市场调研.md", "ref": "artifact://market",
                           "path": "market.md", "size": 12}],
            "issues": []})
        return employee_id, pipeline_id

    def test_non_markdown_deliverables_keep_native_format(self):
        """交付文件保留原始格式，文档系统只在边界声明内容模型。"""
        draft = employee_draft("Publish data", self.package["package_id"],
                               "brief-validator")
        draft["program"]["deliverables"] = [
            {"path": "table.csv", "name": "场景优先级"},
            {"path": "payload.json", "name": "交接简报"},
        ]
        employee_id = self.core.create_employee("Data author", draft)
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline("Keep native format", {
            "positions": [{"key": "write", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(pipeline_id, "Produce", {"objective": "Produce"})
        workflow_id = self.core.start_workflow(task_id)
        test_case = self

        class Runtime:
            def run(_self, employee, _work_order, _emit, *, employee_run_id, database):
                workspace = Path(test_case.tmp.name) / "convert-{}".format(employee_run_id)
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "table.csv").write_text(
                    "指标,数值\n分区月活,240000\n", encoding="utf-8")
                (workspace / "payload.json").write_text(
                    '{"objective": "验证交接"}', encoding="utf-8")
                (workspace / "brief.json").write_text(
                    json.dumps({"objective": "验证交接", "context": {}}), encoding="utf-8")
                protocol = EmployeeProtocol(database, employee_run_id, workspace)
                protocol.call("get_task", {})
                for step in employee["program"]["steps"]:
                    protocol.call("advance_step", {"step_id": step["id"], "summary": "完成"})
                protocol.call("run_capability", {
                    "capability_ref": "brief-validator/validate-brief",
                    "arguments": ["brief.json"]})
                protocol.call("complete", {"summary": "done", "output": {"ok": True}})
                run, _frozen = protocol.context()
                return json.loads(run["output_json"])

        self.core.run_workflow(workflow_id, Runtime(), max_attempts=1)
        self.assertEqual(self.core.workflow(workflow_id)["state"], "completed")

        documents = self.core.document_catalog()
        self.assertEqual(sorted(item["name"] for item in documents),
                         ["交接简报", "场景优先级"])
        by_name = {item["name"]: item for item in documents}
        self.assertEqual(by_name["场景优先级"]["path"], "table.csv")
        self.assertEqual(by_name["场景优先级"]["content_model"], "table")
        self.assertTrue(by_name["场景优先级"]["editable"])
        self.assertEqual(by_name["交接简报"]["path"], "payload.json")
        self.assertEqual(by_name["交接简报"]["content_model"], "json")
        with self.assertRaisesRegex(ContractError, "只读预览"):
            self.core.save_document_edit(by_name["交接简报"]["id"], "其它内容")
        revised = self.core.save_document_edit(
            by_name["场景优先级"]["id"],
            '指标,"数值,含逗号"\n分区月活,"240000"\n')
        self.assertTrue(revised["created_revision"])
        current = {item["name"]: item for item in self.core.document_catalog()}
        self.assertEqual(current["场景优先级"]["path"], "table.csv")
        self.assertEqual(current["场景优先级"]["content_model"], "table")
        bodies = {}
        for document in self.core.document_catalog():
            with open(self.core.artifact(document["id"])["ref"], encoding="utf-8") as handle:
                bodies[document["name"]] = handle.read()
        self.assertEqual(bodies["场景优先级"], '指标,"数值,含逗号"\n分区月活,"240000"\n')
        self.assertEqual(bodies["交接简报"], '{"objective": "验证交接"}')

    def test_declared_deliverables_are_registered_without_the_employee_publishing(self):
        """岗位声明会产出哪些文档，收尾时自动登记；必需的没产出就不许完成。"""
        draft = employee_draft("Write the report", self.package["package_id"],
                               "brief-validator")
        draft["capabilities"] = []
        draft["program"]["deliverables"] = [
            {"path": "reports/market.md", "name": "市场调研报告"},
            {"path": "notes.md", "name": "过程笔记", "required": False},
        ]
        employee_id = self.core.create_employee("Author", draft)
        publish_verified_employee(self.core, employee_id)
        release = self.core.employee(employee_id)["active_release"]
        self.assertEqual(
            [item["path"] for item in release["snapshot_json"]["program"]["deliverables"]],
            ["reports/market.md", "notes.md"])

        pipeline_id = self.core.create_pipeline("Declared delivery", {
            "positions": [{"key": "write", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(pipeline_id, "Write it", {"objective": "Produce"})
        workflow_id = self.core.start_workflow(task_id)
        orders = []
        test_case = self

        class DeclaredRuntime:
            def __init__(self, write_required, publish_explicitly=False):
                self.write_required = write_required
                self.publish_explicitly = publish_explicitly

            def run(_self, employee, work_order, _emit, *, employee_run_id, database):
                orders.append(work_order)
                workspace = Path(test_case.tmp.name) / "declared-{}".format(employee_run_id)
                workspace.mkdir(parents=True, exist_ok=True)
                protocol = EmployeeProtocol(database, employee_run_id, workspace)
                protocol.call("get_task", {})
                for step in employee["program"]["steps"]:
                    protocol.call("advance_step",
                                  {"step_id": step["id"], "summary": "完成"})
                if _self.write_required:
                    (workspace / "reports").mkdir(exist_ok=True)
                    (workspace / "reports" / "market.md").write_text(
                        "# 市场调研\n\n结论：GO。\n", encoding="utf-8")
                    if _self.publish_explicitly:
                        protocol.call("publish_artifact", {
                            "path": "reports/market.md", "title": "市场调研报告"})
                protocol.call("complete", {"summary": "done", "output": {"ok": True}})
                run, _frozen = protocol.context()
                return json.loads(run["output_json"])

        # 必需文档没写出来：不许完成，库里也不该出现半成品
        self.core.run_workflow(workflow_id, DeclaredRuntime(False), max_attempts=1)
        self.assertEqual(self.core.workflow(workflow_id)["state"], "failed")
        self.assertEqual(self.core.document_catalog(), [])
        # 工作单必须先告诉员工要产出什么
        self.assertEqual(
            [item["path"] for item in orders[0]["expected_output"]["documents"]],
            ["reports/market.md", "notes.md"])

        self.core.retry_workflow(workflow_id)
        self.core.run_workflow(workflow_id, DeclaredRuntime(True), max_attempts=1)
        self.assertEqual(self.core.workflow(workflow_id)["state"], "completed")
        documents = self.core.document_catalog()
        # 员工一次 publish_artifact 都没调，声明的文档照样入库；可选的没写就不登记
        self.assertEqual([item["name"] for item in documents], ["市场调研报告"])
        self.assertEqual(documents[0]["path"], "reports/market.md")

        # 兼容员工主动登记：收尾自动登记同一路径、同一内容时必须保持幂等。
        second_task = self.core.create_task(
            pipeline_id, "Write it explicitly", {"objective": "Produce again"})
        second_workflow = self.core.start_workflow(second_task)
        self.core.run_workflow(
            second_workflow, DeclaredRuntime(True, publish_explicitly=True),
            max_attempts=1)
        second_run = self.core.workflow(second_workflow)["employee_runs"][0]
        self.assertEqual(len(second_run["artifacts"]), 1)

    def test_human_revision_is_a_new_version_the_downstream_employee_receives(self):
        """老板改过的那一版要交给下游；员工最初写的那一版仍然留着可查。"""
        researcher = self.core.create_employee(
            "Researcher", employee_draft("Research", self.package["package_id"],
                                         "validate-brief"))
        publish_verified_employee(self.core, researcher)
        writer = self.core.create_employee(
            "Writer", employee_draft("Write", self.package["package_id"],
                                     "validate-brief"))
        publish_verified_employee(self.core, writer)
        pipeline_id = self.core.create_pipeline("Revise then write", {
            "positions": [{"key": "research", "employee_id": researcher},
                          {"key": "write", "employee_id": writer}],
            "edges": [{"from": "research", "to": "write"}]})
        task_id = self.core.create_task(pipeline_id, "Judge", {"objective": "Decide"})
        workflow_id = self.core.start_workflow(task_id)

        original = os.path.join(self.tmp.name, "artifacts", "market.md")
        os.makedirs(os.path.dirname(original), exist_ok=True)
        with open(original, "w", encoding="utf-8") as handle:
            handle.write("# 调研\n\n结论：GO。\n")

        def first_pass(employee, work_order, emit):
            if employee["name"] == "Researcher":
                return {"status": "completed", "summary": "done", "output": {"ok": True},
                        "artifacts": [{"name": "市场调研.md", "ref": original,
                                       "path": "market.md", "size": 24}],
                        "issues": []}
            return {"status": "blocked", "summary": "", "output": {},
                    "artifacts": [], "issues": ["等老板"]}

        self.core.run_workflow(workflow_id, first_pass, max_attempts=1)
        document = self.core.document_catalog()[0]
        self.assertEqual(document["revision"], 1)
        self.assertFalse(document["revised_by_human"])

        revised_id = self.core.create_document_revision(
            document["id"], "# 调研\n\n结论：NO-GO。\n", note="结论反了")
        current = self.core.document_catalog()[0]
        self.assertEqual(current["id"], revised_id)
        self.assertEqual(current["revision"], 2)
        self.assertEqual(current["revision_count"], 2)
        self.assertTrue(current["revised_by_human"])
        # 只显示当前版本，旧版本不占列表位置
        self.assertEqual(len(self.core.document_catalog()), 1)

        revisions = self.core.document_revisions(revised_id)
        self.assertEqual([item["author"] for item in revisions], ["employee", "human"])
        with open(self.core.artifact(document["id"])["ref"], encoding="utf-8") as handle:
            self.assertIn("GO。", handle.read())

        self.core.retry_workflow(workflow_id)
        received = []

        def second_pass(employee, work_order, emit):
            received.append(work_order)
            return {"status": "completed", "summary": "ok", "output": {"done": True},
                    "artifacts": [], "issues": []}

        self.core.run_workflow(workflow_id, second_pass, max_attempts=1)
        inputs = received[0]["inputs"]
        self.assertEqual(len(inputs), 1)
        self.assertEqual(inputs[0]["revision"], 2)
        self.assertTrue(inputs[0]["revised_by_human"])
        with open(inputs[0]["ref"], encoding="utf-8") as handle:
            self.assertIn("NO-GO。", handle.read())

    def _document_with_real_file(self, text="# 调研\n\n第一版内容。\n"):
        """跑一次流水线产出一份真的落了盘的文档，供需要读写文件的用例使用。"""
        employee_id = self.core.create_employee(
            "Document author", employee_draft("Write the report",
                                              self.package["package_id"], "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline(
            "Real document", {"positions": [{"key": "author", "employee_id": employee_id}],
                              "edges": []})
        task_id = self.core.create_task(pipeline_id, "Write it", {"objective": "One document"})
        workflow_run_id = self.core.start_workflow(task_id)
        source = os.path.join(self.tmp.name, "workspace-market.md")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.core.run_workflow(workflow_run_id, lambda employee, work_order, emit: {
            "status": "completed", "summary": "done", "output": {"ok": True},
            "artifacts": [{"name": "市场调研.md", "ref": source, "path": "market.md",
                           "size": len(text.encode("utf-8"))}],
            "issues": []})
        return self.core.document_catalog()[0]

    def test_reverting_to_an_old_revision_adds_a_version_and_keeps_the_rest(self):
        """恢复旧版本＝把它的内容重新放到链尾；中间那些版本一条都不能少。"""
        first = self._document_with_real_file()
        second_id = self.core.create_document_revision(
            first["id"], "# 调研\n\n第二版内容。\n", note="改了结论")

        reverted_id = self.core.revert_document(first["id"])

        current = self.core.document_catalog()[0]
        self.assertEqual(current["id"], reverted_id)
        self.assertEqual(current["revision"], 3)
        self.assertEqual(current["revision_count"], 3)
        # 恢复的是内容，不是"删掉后来那一版"
        revisions = self.core.document_revisions(reverted_id)
        self.assertEqual([item["revision"] for item in revisions], [1, 2, 3])
        with open(self.core.artifact(second_id)["ref"], encoding="utf-8") as handle:
            self.assertIn("第二版内容。", handle.read())
        with open(self.core.artifact(reverted_id)["ref"], encoding="utf-8") as handle:
            reverted_text = handle.read()
        with open(self.core.artifact(first["id"])["ref"], encoding="utf-8") as handle:
            self.assertEqual(reverted_text, handle.read())

    def test_deleting_one_revision_keeps_the_file_another_revision_still_uses(self):
        """产物按内容寻址：内容相同的两版共用一个文件，删一版不能把另一版的正文抹掉。"""
        first = self._document_with_real_file()
        text_a = "# 调研\n\n结论：GO。\n"
        a_id = self.core.create_document_revision(first["id"], text_a)
        self.core.create_document_revision(first["id"], "# 调研\n\n结论：NO-GO。\n")
        # 又改回 A：内容一样，落盘路径就和 A 那一版完全相同
        back_id = self.core.create_document_revision(first["id"], text_a)
        shared_ref = self.core.artifact(back_id)["ref"]
        self.assertEqual(shared_ref, self.core.artifact(a_id)["ref"])

        self.core.trash_document(back_id)
        self.core.delete_trashed_document(back_id)

        self.assertTrue(os.path.isfile(shared_ref))
        with open(self.core.artifact(a_id)["ref"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), text_a)

    def test_permanent_delete_never_silently_destroys_documents(self):
        """产物是历史事实：删除必须先说清份数，自动清空回收站永不销毁文档。"""
        _employee_id, pipeline_id = self._pipeline_run_with_document()
        self.assertEqual(len(self.core.document_catalog()), 1)

        self.core.trash_pipeline(pipeline_id)
        entry = self.core.pipeline_trash_catalog()[0]
        self.assertEqual(entry["document_count"], 1)

        with self.assertRaises(DocumentLossError) as blocked:
            self.core.delete_trashed_pipeline(pipeline_id)
        self.assertEqual(blocked.exception.documents, 1)
        with self.assertRaises(DocumentLossError):
            self.core.delete_trashed_pipeline(pipeline_id, acknowledged_documents=0)
        with self.assertRaises(DocumentLossError):
            self.core.delete_trashed_pipeline(pipeline_id, acknowledged_documents=7)
        self.assertEqual(len(self.core.document_catalog()), 1)

        # 到期的自动清空跳过含文档的条目，把决定留给人，而不是静默销毁。
        with sqlite3.connect(os.path.join(self.tmp.name, "runteams.db")) as connection:
            connection.execute("UPDATE pipelines SET trashed_at=? WHERE id=?",
                               ("2020-01-01T00:00:00+00:00", pipeline_id))
        self.assertEqual(self.core.purge_expired_pipelines(), 0)
        self.assertIsNotNone(self.core.pipeline(pipeline_id, include_trashed=True))
        self.assertEqual(len(self.core.document_catalog()), 1)

        self.assertTrue(
            self.core.delete_trashed_pipeline(pipeline_id, acknowledged_documents=1))
        self.assertIsNone(self.core.pipeline(pipeline_id, include_trashed=True))
        self.assertEqual(self.core.document_catalog(), [])

    def test_employee_permanent_delete_reports_document_loss(self):
        """岗位换人后旧运行仍冻结着这名员工，删除他也会销毁那批文档。"""
        author_id, pipeline_id = self._pipeline_run_with_document("Employee owned")
        replacement_id = self.core.create_employee(
            "Replacement", employee_draft("Take over", self.package["package_id"],
                                          "validate-brief"))
        publish_verified_employee(self.core, replacement_id)
        self.core.update_pipeline(
            pipeline_id, "Employee owned",
            {"positions": [{"key": "author", "employee_id": replacement_id}], "edges": []})

        self.core.trash_employee(author_id)
        self.assertEqual(
            self.core.employee_trash_catalog()[0]["document_count"], 1)
        with self.assertRaises(DocumentLossError) as blocked:
            self.core.delete_trashed_employee(author_id)
        self.assertEqual(blocked.exception.documents, 1)
        self.assertEqual(self.core.purge_expired_employees(), [])
        self.assertEqual(len(self.core.document_catalog()), 1)

        self.assertTrue(
            self.core.delete_trashed_employee(author_id, acknowledged_documents=1))
        self.assertEqual(self.core.document_catalog(), [])

    def test_employee_duplicate_discard_and_trash_are_core_lifecycle(self):
        employee_id = self.core.create_employee(
            "Original", employee_draft("Published role", self.package["package_id"],
                                        "validate-brief"))
        published = publish_verified_employee(self.core, employee_id)

        duplicate = self.core.duplicate_employee(employee_id)
        self.assertEqual(duplicate["name"], "Original 副本")
        self.assertEqual(duplicate["draft_json"], self.core.employee(employee_id)["draft_json"])
        self.assertIsNone(duplicate["active_release"])
        self.assertTrue(duplicate["has_unpublished_changes"])

        changed = employee_draft(
            "Unpublished role", self.package["package_id"], "validate-brief")
        self.core.update_employee(employee_id, "Renamed draft", changed)
        discarded = self.core.discard_employee_draft(employee_id)
        self.assertEqual(discarded["name"], "Original")
        self.assertEqual(discarded["draft_json"]["role"], "Published role")
        self.assertEqual(discarded["active_release"]["id"], published["release_id"])
        self.assertFalse(discarded["has_unpublished_changes"])

        pipeline_id = self.core.create_pipeline(
            "Employee lifecycle", {
                "positions": [{"key": "owner", "employee_id": employee_id}], "edges": []})
        with self.assertRaisesRegex(ContractError, "仍用于 1 条流水线"):
            self.core.trash_employee(employee_id)

        self.core.trash_pipeline(pipeline_id)
        self.core.trash_employee(employee_id)
        with self.assertRaisesRegex(ContractError, "仍被 1 条流水线引用"):
            self.core.delete_trashed_employee(employee_id)
        self.core.restore_employee(employee_id)
        self.core.restore_pipeline(pipeline_id)

        task_id = self.core.create_task(
            pipeline_id, "Historical work", {"objective": "Complete work"})
        workflow_id = self.core.start_workflow(task_id)
        self.core.run_workflow(workflow_id, lambda *_args: {
            "status": "completed", "summary": "done", "output": {},
            "artifacts": [], "issues": [],
        })
        self.core.update_pipeline(pipeline_id, "Employee lifecycle", {
            "positions": [{"key": "owner", "employee_id": duplicate["id"]}], "edges": []})

        trashed = self.core.trash_employee(employee_id)
        self.assertIsNotNone(trashed["trashed_at"])
        self.assertIsNone(self.core.employee(employee_id))
        self.assertEqual(self.core.employee_trash_catalog()[0]["count"], 1)
        restored = self.core.restore_employee(employee_id)
        self.assertIsNone(restored["trashed_at"])

        self.core.trash_employee(employee_id)
        self.assertTrue(self.core.delete_trashed_employee(employee_id))
        self.assertIsNone(self.core.employee(employee_id, include_trashed=True))
        self.assertIsNone(self.core.workflow(workflow_id))
        self.assertIsNotNone(self.core.pipeline(pipeline_id))

    def test_changed_package_creates_revision_without_mutating_employee_release(self):
        employee_id = self.core.create_employee(
            "Researcher", employee_draft("Research", self.package["package_id"],
                                         "validate-brief"))
        release = publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline(
            "Pinned release", {"positions": [{"key": "research", "employee_id": employee_id}],
                               "edges": []})
        task_id = self.core.create_task(pipeline_id, "Pinned task", {"objective": "Research"})
        workflow_id = self.core.start_workflow(task_id)
        workflow_snapshot = self.core.workflow(workflow_id)["snapshot_json"]
        with tempfile.TemporaryDirectory(prefix="runteams-package-edit-") as parent:
            edited = os.path.join(parent, "brief-validator")
            shutil.copytree(os.path.join(ROOT, "examples", "brief-validator"), edited)
            skill = os.path.join(edited, "SKILL.md")
            with open(skill, "a", encoding="utf-8") as handle:
                handle.write("\nA newly published instruction.\n")
            changed = self.core.import_package("brief-validator", edited)
        self.assertEqual(changed["version"], 2)
        self.assertNotEqual(changed["digest"], self.package["digest"])
        employee = self.core.employee(employee_id)
        frozen = employee["active_release"]["snapshot_json"]
        self.assertEqual(frozen["capabilities"][0]["digest"], self.package["digest"])
        self.assertTrue(employee["has_unpublished_changes"])
        self.assertEqual(self.core.workflow(workflow_id)["snapshot_json"], workflow_snapshot)

    def test_package_disable_previews_impact_and_preserves_frozen_workflows(self):
        employee_id = self.core.create_employee(
            "Package user", employee_draft("Use package", self.package["package_id"],
                                            "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline(
            "Package pipeline", {"positions": [{"key": "use", "employee_id": employee_id}],
                                 "edges": []})
        task_id = self.core.create_task(
            pipeline_id, "Frozen package task", {"objective": "Use package"})
        workflow_id = self.core.start_workflow(task_id)
        frozen_workflow = self.core.workflow(workflow_id)["snapshot_json"]

        impact = self.core.package_impact(self.package["package_id"])
        self.assertFalse(impact["can_disable"])
        self.assertEqual(impact["employees"], [{
            "id": employee_id, "name": "Package user", "draft": True,
            "published": True, "release_version": 1,
        }])
        self.assertEqual(impact["pipelines"], [{"id": pipeline_id,
                                                "name": "Package pipeline"}])
        self.assertEqual(impact["workflows"], [{"id": workflow_id,
                                                "title": "Frozen package task",
                                                "state": "ready"}])
        with self.assertRaisesRegex(ContractError, "受影响员工草稿"):
            self.core.disable_package(self.package["package_id"])

        without_package = employee_draft(
            "Use package", self.package["package_id"], "validate-brief")
        without_package["capabilities"] = []
        self.core.update_employee(employee_id, "Package user", without_package)
        publish_verified_employee(self.core, employee_id)
        ready = self.core.package_impact(self.package["package_id"])
        self.assertTrue(ready["can_disable"])
        self.assertEqual(ready["employees"], [])
        self.assertEqual(ready["pipelines"], [])
        self.assertEqual([item["id"] for item in ready["workflows"]], [workflow_id])

        disabled = self.core.disable_package(self.package["package_id"])
        self.assertFalse(disabled["enabled"])
        package = self.core.package_detail(self.package["package_id"])
        self.assertFalse(package["enabled"])
        self.assertIsNone(package["active_revision_id"])
        self.assertEqual(package["revision_id"], self.package["revision_id"])
        self.assertEqual(package["digest"], self.package["digest"])
        self.assertTrue(os.path.isdir(package["blob_ref"]))
        self.assertEqual(self.core.workflow(workflow_id)["snapshot_json"], frozen_workflow)
        with self.assertRaisesRegex(ContractError, "已停用"):
            self.core.package_detail(self.package["package_id"], verify=True)

        enabled = self.core.enable_package(self.package["package_id"])
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["active_revision_id"], self.package["revision_id"])
        self.assertEqual(enabled["digest"], self.package["digest"])
        self.assertEqual(enabled["verification"]["status"], "verified")

    def test_employee_release_freezes_exact_package_revision(self):
        employee_id = self.core.create_employee(
            "Researcher", employee_draft("Research the task", self.package["package_id"],
                                         "validate-brief"))
        release = publish_verified_employee(self.core, employee_id)
        frozen = release["snapshot"]["capabilities"][0]
        self.assertEqual(frozen["digest"], self.package["digest"])
        self.assertEqual(frozen["package_key"], "brief-validator")
        self.assertEqual(frozen["revision_id"], self.package["revision_id"])
        self.assertNotIn("package_id", frozen)
        self.assertNotIn("blob_ref", frozen)
        self.assertEqual(release["checks"][0]["status"], "verified")

    def test_employee_edit_keeps_active_release_until_explicit_republish(self):
        employee_id = self.core.create_employee(
            "Editor", employee_draft("First role", self.package["package_id"],
                                      "brief-validator"))
        self.assertTrue(self.core.employee(employee_id)["has_unpublished_changes"])
        first = publish_verified_employee(self.core, employee_id)
        self.assertFalse(self.core.employee(employee_id)["has_unpublished_changes"])
        changed = employee_draft("Changed role", self.package["package_id"],
                                 "brief-validator")
        self.core.update_employee(employee_id, "Editor", changed)
        pending = self.core.employee(employee_id)
        self.assertTrue(pending["has_unpublished_changes"])
        self.assertEqual(pending["active_release"]["id"], first["release_id"])
        self.assertEqual(pending["draft_json"]["tests"], [])
        second = publish_verified_employee(self.core, employee_id)
        self.assertEqual(second["version"], 2)
        self.assertFalse(self.core.employee(employee_id)["has_unpublished_changes"])

    def test_runtime_change_keeps_cases_but_requires_rerun(self):
        employee_id = self.core.create_employee(
            "Runtime editor", employee_draft("Stable role", self.package["package_id"],
                                              "brief-validator"))
        publish_verified_employee(self.core, employee_id)
        employee = self.core.employee(employee_id)
        draft = employee["draft_json"]
        case_ids = [item["id"] for item in draft["tests"]]
        draft["runtime"]["effort"] = "low"
        self.core.update_employee(employee_id, employee["name"], draft)

        changed = self.core.employee(employee_id)
        self.assertEqual([item["id"] for item in changed["draft_json"]["tests"]], case_ids)
        coverage = self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))
        self.assertEqual(coverage["verified"], 0)
        self.assertFalse(coverage["passed"])

    def test_release_digest_is_portable_across_two_data_directories(self):
        first_employee = self.core.create_employee(
            "Portable", employee_draft("Portable role", self.package["package_id"],
                                       "validate-brief"))
        first_release = publish_verified_employee(self.core, first_employee)
        with tempfile.TemporaryDirectory(prefix="runteams-core-second-") as second_root:
            second = RunTeamsCore(second_root)
            second_package = second.import_package(
                "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
            second_employee = second.create_employee(
                "Portable", employee_draft("Portable role", second_package["package_id"],
                                           "validate-brief"))
            second_release = publish_verified_employee(second, second_employee)
        self.assertEqual(first_release["digest"], second_release["digest"])

    def test_two_employees_exchange_structured_work_order(self):
        first = self.core.create_employee(
            "Researcher", employee_draft("Find three facts", self.package["package_id"],
                                         "brief-validator"))
        second = self.core.create_employee(
            "Writer", employee_draft("Write the final brief", self.package["package_id"],
                                     "brief-validator"))
        first_release = publish_verified_employee(self.core, first)
        second_release = publish_verified_employee(self.core, second)
        pipeline_id = self.core.create_pipeline("Research to writing", {
            "positions": [{"key": "research", "name": "Research", "employee_id": first},
                          {"key": "writing", "name": "Writing", "employee_id": second}],
            "edges": [{"from": "research", "to": "writing"}],
        })
        task_id = self.core.create_task(pipeline_id, "Explain the product", {
            "objective": "Produce a concise product brief", "context": {"audience": "founder"},
            "acceptance": ["Contains evidence"]})
        workflow_run_id = self.core.start_workflow(task_id)
        received = []

        def runtime(employee, work_order, emit):
            received.append((employee, work_order))
            emit("agent.progress", {"message": "working"})
            return {"status": "completed", "summary": "{} completed".format(employee["name"]),
                    "output": {"from": employee["name"], "objective": work_order["objective"]},
                    "artifacts": [{"name": "brief.json", "ref": "artifact://brief"}],
                    "issues": []}

        result = self.core.run_workflow(workflow_run_id, runtime)
        workflow = self.core.workflow(workflow_run_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(workflow["state"], "completed")
        self.assertEqual(len(workflow["employee_runs"]), 2)
        self.assertEqual(workflow["employee_runs"][0]["employee_release_id"],
                         first_release["release_id"])
        self.assertEqual(workflow["employee_runs"][1]["employee_release_id"],
                         second_release["release_id"])
        self.assertEqual(received[1][1]["context"]["upstream_position"], "research")
        self.assertEqual(received[1][1]["context"]["upstream_output"]["from"], "Researcher")
        self.assertEqual(received[1][1]["objective"], "Write the final brief")
        self.assertEqual(received[1][1]["schema"], "runteams.work-order/v1")

    def test_task_can_start_from_a_position_or_be_added_as_completed(self):
        first = self.core.create_employee(
            "Researcher", employee_draft("Research", self.package["package_id"],
                                         "brief-validator"))
        second = self.core.create_employee(
            "Writer", employee_draft("Write", self.package["package_id"],
                                     "brief-validator"))
        publish_verified_employee(self.core, first)
        second_release = publish_verified_employee(self.core, second)
        pipeline_id = self.core.create_pipeline("Research to writing", {
            "positions": [{"key": "research", "employee_id": first},
                          {"key": "writing", "employee_id": second}],
            "edges": [{"from": "research", "to": "writing"}],
        })

        with self.assertRaisesRegex(ContractError, "起始列不存在"):
            self.core.create_task(
                pipeline_id, "Invalid start", {"objective": "Work"},
                start_column_key="missing")
        task_id = self.core.create_task(
            pipeline_id, "Start with writing", {"objective": "Write directly"},
            start_column_key="writing")
        workflow_id = self.core.start_workflow(task_id)
        received = []

        def runtime(employee, work_order, emit):
            received.append((employee, work_order))
            return {"status": "completed", "summary": "done",
                    "output": {"ok": True}, "artifacts": [], "issues": []}

        self.core.run_workflow(workflow_id, runtime)
        workflow = self.core.workflow(workflow_id)
        self.assertEqual(workflow["snapshot_json"]["task"]["start_column_key"],
                         "writing")
        self.assertEqual([run["position_key"] for run in workflow["employee_runs"]],
                         ["writing"])
        self.assertEqual(workflow["employee_runs"][0]["employee_release_id"],
                         second_release["release_id"])
        self.assertEqual(received[0][1]["objective"], "Write directly")
        self.assertNotIn("upstream_position", received[0][1]["context"])

        completed_task_id = self.core.create_task(
            pipeline_id, "Already finished", {"objective": "Keep this result"},
            start_column_key="__completed")
        completed_workflow_id = self.core.start_workflow(completed_task_id)
        completed_workflow = self.core.workflow(completed_workflow_id)
        self.assertEqual(completed_workflow["state"], "completed")
        self.assertEqual(completed_workflow["snapshot_json"]["task"]["start_column_key"],
                         "__completed")
        self.assertEqual(completed_workflow["employee_runs"], [])
        self.assertEqual(self.core.task(completed_task_id)["state"], "completed")

    def test_unpublished_employee_trial_is_a_real_workflow_with_frozen_draft(self):
        draft = employee_draft("Review a brief", self.package["package_id"],
                               "brief-validator")
        draft["interface"] = {
            "output": {"type": "object", "properties": {
                "route": {"type": "string", "enum": ["completed", "exception"]},
            }},
        }
        draft["tests"] = [{
            "id": "happy-path", "name": "完整工作单",
            "work_order": {"objective": "Review this brief", "context": {"brief": "ready"},
                           "inputs": [], "expected_output": {"kind": "review"},
                           "acceptance": ["指出是否可交接"]},
            "expected_status": "completed",
            "expected_route": "completed",
        }]
        employee_id = self.core.create_employee("Draft reviewer", draft)
        trial = self.core.start_employee_trial(employee_id, "happy-path")
        workflow_id = trial["id"]
        seen = {}

        class TrialRuntime:
            def run(_self, employee, work_order, emit, *, employee_run_id, database):
                protocol = EmployeeProtocol(
                    database, employee_run_id, Path(self.tmp.name) / "trial-workspace")
                run, frozen = protocol.context()
                seen.update({"employee": frozen, "work_order": work_order,
                             "release_id": run["employee_release_id"]})
                return {"status": "completed", "summary": "reviewed",
                        "output": {"handoff": True, "route": "completed"},
                        "artifacts": [], "issues": []}

        self.core.run_workflow(workflow_id, TrialRuntime())
        finished = self.core.employee_trials(employee_id)[0]
        self.assertIsNone(seen["release_id"])
        self.assertEqual(seen["employee"]["role"], "Review a brief")
        self.assertEqual(seen["work_order"]["context"], {"brief": "ready"})
        self.assertEqual(finished["trial_result"]["verdict"], "matched")
        self.assertEqual(finished["trial_result"]["actual_route"], "completed")
        self.assertFalse(finished["trial_result"]["stale"])
        with self.core.repository.connect() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM employee_releases").fetchone()[0], 0)
            task = connection.execute("SELECT pipeline_id,employee_id FROM tasks").fetchone()
        self.assertIsNone(task["pipeline_id"])
        self.assertEqual(task["employee_id"], employee_id)

        changed = dict(draft)
        changed["role"] = "Review a changed brief"
        self.core.update_employee(employee_id, "Draft reviewer", changed)
        self.assertTrue(self.core.employee_trials(employee_id)[0]["trial_result"]["stale"])

    def test_employee_trial_checks_business_route_separately_from_run_status(self):
        draft = employee_draft("Route the finished review", self.package["package_id"],
                               "brief-validator")
        draft["interface"] = {
            "output": {"type": "object", "properties": {
                "route": {"type": "string", "enum": ["completed", "exception"]},
            }},
        }
        draft["tests"] = [{
            "id": "return-for-rework", "name": "报告完成但要返工",
            "work_order": {"objective": "Review and route the work"},
            "expected_status": "completed", "expected_route": "exception",
            "covers": ["result.completed"],
        }]
        employee_id = self.core.create_employee("Route reviewer", draft)
        trial = self.core.start_employee_trial(employee_id, "return-for-rework")
        self.core.run_workflow(trial["id"], lambda *_args: {
            "status": "completed", "summary": "review finished",
            "output": {"route": "completed"}, "artifacts": [], "issues": [],
        }, max_attempts=1)

        result = self.core.employee_trials(employee_id)[0]["trial_result"]
        self.assertEqual(result["actual_status"], "completed")
        self.assertEqual(result["actual_route"], "completed")
        self.assertEqual(result["expected_route"], "exception")
        self.assertEqual(result["verdict"], "mismatched")

    def test_noncompleted_employee_trial_cannot_declare_a_business_route(self):
        draft = employee_draft("Stop on an invalid handoff", self.package["package_id"],
                               "brief-validator")
        draft["tests"] = [{
            "id": "blocked-route", "name": "阻塞不会执行业务路由",
            "work_order": {"objective": "Reject the handoff"},
            "expected_status": "blocked", "expected_route": "exception",
            "covers": ["result.blocked"],
        }]
        with self.assertRaisesRegex(
                ContractError, "只有预期完成时才能声明业务去向"):
            self.core.create_employee("Invalid route employee", draft)

    def test_employee_trial_route_requires_a_declared_output_field(self):
        draft = employee_draft("Complete without routing", self.package["package_id"],
                               "brief-validator")
        draft["tests"] = [{
            "id": "undeclared-route", "name": "输出契约没有业务去向",
            "work_order": {"objective": "Complete the work"},
            "expected_status": "completed", "expected_route": "completed",
            "covers": ["result.completed"],
        }]
        with self.assertRaisesRegex(
                ContractError, "员工输出接口没有 route 字段"):
            self.core.create_employee("Undeclared route employee", draft)

    def test_one_lucky_rerun_cannot_erase_an_unstable_case(self):
        draft = employee_draft("Produce a stable result", self.package["package_id"],
                               "brief-validator")
        draft["tests"] = [{
            "id": "stability", "name": "Stable behavior",
            "work_order": {"objective": "Produce the result"},
            "expected_status": "completed", "covers": ["result.completed"],
        }]
        employee_id = self.core.create_employee("Stability employee", draft)
        first_samples = self.core.start_employee_trial_samples(
            employee_id, "stability", fresh=True)
        self.assertEqual(len(first_samples), 3)
        statuses = iter(("completed", "completed", "blocked"))
        for trial in first_samples:
            status = next(statuses)
            self.core.run_workflow(trial["id"], lambda *_args, value=status: {
                "status": value, "summary": "done" if value == "completed" else "",
                "output": {},
                "artifacts": [], "issues": [],
            }, max_attempts=1)

        first_coverage = self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))
        self.assertEqual(first_coverage["runs"]["stability"], {
            "passed": 2, "failed": 1, "running": 0,
        })
        self.assertTrue(any(item["id"] == "result.completed"
                            for item in first_coverage["unverified"]))

        lucky_samples = self.core.start_employee_trial_samples(
            employee_id, "stability", fresh=True)
        for trial in lucky_samples:
            self.core.run_workflow(trial["id"], lambda *_args: {
                "status": "completed", "summary": "done", "output": {},
                "artifacts": [], "issues": [],
            }, max_attempts=1)
        final_coverage = self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))
        self.assertEqual(final_coverage["runs"]["stability"]["passed"], 5)
        self.assertEqual(final_coverage["runs"]["stability"]["failed"], 1)
        self.assertTrue(any(item["id"] == "result.completed"
                            for item in final_coverage["unverified"]))

    def test_employee_protocol_can_report_a_technical_failure(self):
        draft = employee_draft("Report a technical failure", self.package["package_id"],
                               "brief-validator")
        draft["tests"] = [{
            "id": "technical-failure", "name": "Technical failure",
            "work_order": {"objective": "Handle a technical failure"},
            "expected_status": "failed", "covers": ["result.failed"],
        }]
        employee_id = self.core.create_employee("Failure reporter", draft)
        trial = self.core.start_employee_trial(employee_id, "technical-failure")
        root = Path(self.tmp.name)

        class FailureRuntime:
            def run(_self, _employee, _work_order, _emit, *, employee_run_id, database):
                workspace = root / "failure-protocol-workspace"
                workspace.mkdir()
                protocol = EmployeeProtocol(database, employee_run_id, workspace)
                protocol.call("get_task", {})
                reported = protocol.call("report_failed", {
                    "reason": "capability unavailable", "recovery": "restore capability",
                })
                self.assertFalse(reported["isError"])
                run, _frozen = protocol.context()
                return json.loads(run["output_json"])

        result = self.core.run_workflow(trial["id"], FailureRuntime(), max_attempts=3)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.core.workflow(trial["id"])["employee_runs"]), 1)

    def test_legacy_text_only_capability_failure_stays_visible_but_cannot_pass(self):
        draft = employee_draft("Handle capability failure", self.package["package_id"],
                               "brief-validator")
        draft["tests"] = [{
            "id": "legacy-failure", "name": "Legacy text-only failure",
            "work_order": {"objective": "Pretend the capability is unavailable"},
            "expected_status": "failed",
            "covers": ["result.failed", "capability.1:brief-validator.failure"],
        }]
        employee_id = self.core.create_employee("Legacy failure employee", draft)
        for trial in self.core.start_employee_trial_samples(
                employee_id, "legacy-failure", fresh=True):
            self.core.run_workflow(trial["id"], lambda *_args: {
                "status": "failed", "summary": "", "output": {},
                "artifacts": [], "issues": ["simulated"],
            }, max_attempts=1)

        coverage = self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))
        self.assertEqual(coverage["runs"]["legacy-failure"], {
            "passed": 0, "failed": 3, "running": 0,
        })
        self.assertTrue(any(item["id"] == "skill.1.failure"
                            for item in coverage["unverified"]))

    def test_employee_coverage_is_derived_from_interface_program_capabilities_and_flow(self):
        draft = employee_draft("Review a brief", self.package["package_id"],
                               "brief-validator")
        draft["interface"] = {
            "input": {"type": "object", "required": ["objective", "context"],
                      "properties": {"objective": {"type": "string", "minLength": 1},
                                     "context": {"type": "object", "required": ["brief"],
                                                 "properties": {
                                                     "brief": {"type": "string", "minLength": 3},
                                                 }}}},
            "output": {"type": "object", "required": ["verdict"],
                       "properties": {"verdict": {"type": "string",
                                                   "enum": ["pass", "fail"]}}},
        }
        normalized = normalize_employee_draft(draft)
        target_ids = [item["id"] for item in employee_coverage_targets(normalized)]
        self.assertIn("input.context.brief.required", target_ids)
        self.assertIn("output.verdict.enum", target_ids)
        self.assertIn("program.work", target_ids)
        self.assertIn("skill.1.failure", target_ids)
        self.assertIn("handoff.upstream.invalid", target_ids)

        common_order = {"objective": "Review", "context": {"brief": "ready"},
                        "inputs": [], "expected_output": {}, "acceptance": []}
        positive_targets = [target for target in target_ids if not (
            target in ("result.blocked", "result.needs_human", "result.failed",
                       "handoff.upstream.valid", "handoff.upstream.invalid") or
            target.endswith(".failure"))]
        draft["tests"] = [
            {"id": "completed", "name": "正常完成", "work_order": common_order,
             "expected_status": "completed", "covers": positive_targets},
            {"id": "blocked", "name": "业务阻塞", "work_order": common_order,
             "expected_status": "blocked", "covers": ["result.blocked"]},
            {"id": "needs-human", "name": "需要人工", "work_order": common_order,
             "expected_status": "needs_human", "covers": ["result.needs_human"]},
            {"id": "failed", "name": "能力失败",
             "work_order": {**common_order, "context": {
                 "brief": "ready", "test_signal": {
                     "capability_ref": "brief-validator/brief-validator",
                     "state": "unavailable"}}},
             "expected_status": "failed", "covers": ["result.failed"] + [
                 target for target in target_ids if target.endswith(".failure")]},
            {"id": "valid-upstream", "name": "正常上游",
             "work_order": {**common_order, "context": {
                 "brief": "ready", "upstream_position": "writer",
                 "upstream_output": {"brief": "ready"}}},
             "expected_status": "completed", "covers": ["handoff.upstream.valid"]},
            {"id": "invalid-upstream", "name": "无效上游",
             "work_order": {**common_order, "context": {
                 "brief": "ready", "upstream_position": "writer"}},
             "expected_status": "needs_human", "covers": ["handoff.upstream.invalid"]},
        ]
        employee_id = self.core.create_employee("Coverage employee", draft)
        coverage = self.core.employee_coverage(employee_id)
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["covered"], coverage["total"])
        self.assertFalse(coverage["passed"])

    def test_employee_case_cannot_claim_incompatible_coverage(self):
        draft = employee_draft("Review a brief", self.package["package_id"],
                               "brief-validator")
        draft["tests"] = [{
            "id": "fake-matrix", "name": "伪覆盖",
            "work_order": {"objective": "Review", "context": {}, "inputs": [],
                           "expected_output": {}, "acceptance": []},
            "expected_status": "completed",
            "covers": ["result.completed", "result.failed"],
        }]
        with self.assertRaisesRegex(ContractError, "结果状态与覆盖目标"):
            self.core.create_employee("Fake coverage", draft)

    def test_publish_requires_current_complete_employee_self_check(self):
        employee_id = self.core.create_employee(
            "Publish gate", employee_draft(
                "Validate before release", self.package["package_id"],
                "brief-validator"))
        with self.assertRaisesRegex(ContractError, "发布前必须完成员工验证"):
            self.core.publish_employee(employee_id)

        verify_employee(self.core, employee_id)
        employee = self.core.employee(employee_id)
        changed = employee["draft_json"]
        changed["tests"][0]["name"] = "Changed validation case"
        self.core.update_employee(employee_id, employee["name"], changed)
        stale = self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))
        self.assertEqual(stale["verified"], 0)
        self.assertFalse(stale["passed"])
        with self.assertRaisesRegex(ContractError, "发布前必须通过员工自查"):
            self.core.publish_employee(employee_id)

        verify_employee(self.core, employee_id)
        release = self.core.publish_employee(employee_id)
        self.assertEqual(release["version"], 1)

    def test_ai_repair_preserves_tests_and_contracts_then_revalidates_every_case(self):
        employee_id = self.core.create_employee(
            "Repairable employee", employee_draft(
                "Produce reliable work", self.package["package_id"],
                "brief-validator"))
        verify_employee(self.core, employee_id)
        original = self.core.employee(employee_id)
        original_draft = json.loads(json.dumps(original["draft_json"]))

        # A fresh unstable sample makes the current draft ineligible for release.
        for trial in self.core.start_employee_trial_samples(
                employee_id, "verified-completed", fresh=True):
            self.core.run_workflow(trial["id"], lambda *_args: {
                "status": "blocked", "summary": "", "output": {},
                "artifacts": [], "issues": ["missed the required result"],
            }, max_attempts=1)
        self.assertFalse(self.core.employee_coverage(employee_id)["passed"])

        queued = self.core.start_employee_repair(employee_id)
        self.assertEqual(queued["state"], "queued")
        with self.assertRaisesRegex(ContractError, "AI 正在修复员工"):
            self.core.start_employee_trial_samples(
                employee_id, "verified-completed", fresh=True)
        with self.assertRaisesRegex(ContractError, "AI 正在修复员工"):
            self.core.start_all_employee_trials(employee_id)
        self.assertEqual(
            self.core.start_employee_repair(employee_id)["id"], queued["id"])
        claimed = self.core.claim_employee_repair()
        self.assertEqual(claimed["state"], "repairing")
        seen = {}

        def repair_runtime(employee, failures, protected):
            seen["employee"] = employee
            seen["failures"] = failures
            seen["protected"] = protected
            return {
                "name": "AI must not rename this employee",
                "instructions": "Produce reliable work and explicitly verify the result.",
                "program": {
                    "objective": "Produce and verify reliable work",
                    "steps": [{"id": "work", "instructions":
                               "Complete the work, verify it, then deliver it."}],
                    "delivery": {"acceptance_criteria":
                                 "The result is verified before delivery"},
                },
                # These malicious changes must be discarded by the service.
                "tests": [], "interface": {"input": {"type": "string"}},
                "capabilities": [],
                "runtime": {"channel": "claude-code", "effort": "low"},
            }

        validating = self.core.execute_employee_repair(claimed, repair_runtime)
        self.assertEqual(validating["state"], "validating")
        self.assertEqual(validating["phase"], "targeted")
        self.assertTrue(validating["workflow_ids"])
        with self.assertRaisesRegex(ContractError, "AI 正在修复员工"):
            self.core.start_employee_trial(
                employee_id, "verified-completed")
        self.assertEqual(seen["failures"][0]["test"]["id"], "verified-completed")
        self.assertTrue(seen["failures"][0]["failed_samples"])
        self.assertTrue(seen["protected"])
        self.assertNotIn("verified-completed", {
            item["test"]["id"] for item in seen["protected"]})

        # Candidate instructions are staged in the repair event.  The authored
        # employee remains byte-for-byte unchanged until every check passes.
        staged_employee = self.core.employee(employee_id)
        self.assertEqual(staged_employee["draft_json"], original_draft)
        self.assertIn("explicitly verify", validating["candidate_draft"]["role"])
        for field in ("tests", "interface", "capabilities", "runtime"):
            self.assertEqual(validating["candidate_draft"][field], original_draft[field])

        def run_candidate_workflows(workflow_ids):
            for workflow_id in workflow_ids:
                workflow = self.core.workflow(workflow_id)
                expected_status = workflow["snapshot_json"]["trial"]["expected_status"]

                def validation_runtime(snapshot, _order, emit,
                                       result_status=expected_status):
                    if result_status == "completed":
                        for step in (snapshot.get("program") or {}).get("steps") or []:
                            emit("step.completed", {"step_id": step["id"]})
                        for frozen in snapshot.get("capabilities") or []:
                            capability = frozen.get("capability") or {}
                            if capability.get("kind") == "tool":
                                emit("capability.executed", {
                                    "capability_ref": "{}/{}".format(
                                        frozen.get("package_key"), capability.get("id"))})
                    return {"status": result_status,
                            "summary": "verified" if result_status == "completed" else "",
                            "output": {}, "artifacts": [], "issues": []}

                self.core.run_workflow(
                    workflow_id, validation_runtime, max_attempts=1)

        # Phase one only rechecks the cases that originally failed.
        run_candidate_workflows(validating["workflow_ids"])
        regression = self.core.employee_repair_status(employee_id)
        self.assertEqual(regression["state"], "validating")
        self.assertEqual(regression["phase"], "regression")
        self.assertTrue(regression["workflow_ids"])
        self.assertEqual(self.core.employee(employee_id)["draft_json"], original_draft)

        # Phase two checks all previously passing behavior before promotion.
        run_candidate_workflows(regression["workflow_ids"])
        completed = self.core.employee_repair_status(employee_id)
        self.assertEqual(completed["state"], "completed")
        repaired = self.core.employee(employee_id)
        self.assertEqual(repaired["name"], "Repairable employee")
        self.assertIn("explicitly verify", repaired["draft_json"]["role"])
        for field in ("tests", "interface", "capabilities", "runtime"):
            self.assertEqual(repaired["draft_json"][field], original_draft[field])
        self.assertTrue(self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))["passed"])
        self.assertEqual(self.core.employee_repair_status(employee_id)["state"],
                         "completed")
        terminal = [event for event in self.core.repository.events(queued["stream"])
                    if event["type"] == "employee.repair_completed"]
        self.assertEqual(len(terminal), 1)

    def test_ai_repair_discards_a_candidate_that_breaks_a_passing_case(self):
        draft = employee_draft(
            "Handle both cases", self.package["package_id"], "brief-validator")
        draft["tests"] = [{
            "id": "broken-a", "name": "Originally broken A",
            "work_order": {"objective": "Run A"},
            "expected_status": "completed", "covers": [],
        }, {
            "id": "passing-b", "name": "Originally passing B",
            "work_order": {"objective": "Run B"},
            "expected_status": "completed", "covers": [],
        }]
        employee_id = self.core.create_employee("Monotonic repair", draft)
        for test_id, status in (("broken-a", "blocked"), ("passing-b", "completed")):
            for trial in self.core.start_employee_trial_samples(
                    employee_id, test_id, fresh=True):
                self.core.run_workflow(trial["id"], lambda *_args, value=status: {
                    "status": value, "summary": "done" if value == "completed" else "",
                    "output": {}, "artifacts": [], "issues": [],
                }, max_attempts=1)
        original = copy.deepcopy(self.core.employee(employee_id)["draft_json"])
        queued = self.core.start_employee_repair(employee_id)
        claimed = self.core.claim_employee_repair()
        seen = {}

        def repair_runtime(_employee, _failures, protected):
            seen["protected"] = protected
            return {
                "instructions": "Candidate behavior",
                "program": {"objective": "Candidate objective", "steps": [{
                    "id": "work", "instructions": "Candidate step",
                }]},
            }

        targeted = self.core.execute_employee_repair(claimed, repair_runtime)
        self.assertEqual({item["test"]["id"] for item in seen["protected"]},
                         {"passing-b"})
        for workflow_id in targeted["workflow_ids"]:
            self.core.run_workflow(workflow_id, lambda *_args: {
                "status": "completed", "summary": "fixed A", "output": {},
                "artifacts": [], "issues": [],
            }, max_attempts=1)
        regression = self.core.employee_repair_status(employee_id)
        self.assertEqual(regression["phase"], "regression")

        for workflow_id in regression["workflow_ids"]:
            test_id = self.core.workflow(workflow_id)["snapshot_json"]["trial"]["test_id"]
            status = "blocked" if test_id == "passing-b" else "completed"
            self.core.run_workflow(workflow_id, lambda *_args, value=status: {
                "status": value, "summary": "done" if value == "completed" else "",
                "output": {}, "artifacts": [], "issues": [],
            }, max_attempts=1)
        failed = self.core.employee_repair_status(employee_id)

        self.assertEqual(failed["state"], "failed")
        self.assertIn("已丢弃", failed["message"])
        self.assertIn("passing-b", failed["message"])
        self.assertEqual(self.core.employee(employee_id)["draft_json"], original)
        self.assertEqual(len([event for event in self.core.repository.events(queued["stream"])
                              if event["type"] == "employee.repair_completed"]), 0)

    def test_completed_output_must_match_the_frozen_employee_interface(self):
        draft = employee_draft("Produce a verdict", self.package["package_id"],
                               "brief-validator")
        draft["interface"] = {
            "input": {"type": "object"},
            "output": {"type": "object", "required": ["verdict"],
                       "properties": {"verdict": {"type": "string"}}},
        }
        employee_id = self.core.create_employee("Typed employee", draft)
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline("Typed flow", {
            "positions": [{"key": "work", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(pipeline_id, "Typed task", {"objective": "Work"})
        workflow_id = self.core.start_workflow(task_id)
        result = self.core.run_workflow(workflow_id, lambda *_args: {
            "status": "completed", "summary": "done", "output": {"wrong": True},
            "artifacts": [], "issues": [],
        }, max_attempts=1)
        self.assertEqual(result["status"], "failed")
        self.assertIn("$.output.verdict", result["issues"][0])
        self.assertEqual(self.core.workflow(workflow_id)["state"], "failed")

    def test_employee_trial_can_handoff_to_a_published_downstream_employee(self):
        downstream_id = self.core.create_employee(
            "Receiver", employee_draft("Accept structured work", self.package["package_id"],
                                       "brief-validator"))
        downstream_release = publish_verified_employee(self.core, downstream_id)
        draft = employee_draft("Prepare work", self.package["package_id"], "brief-validator")
        draft["tests"] = [{
            "id": "handoff", "name": "交给真实下游",
            "work_order": {"objective": "Prepare", "context": {}, "inputs": [],
                           "expected_output": {}, "acceptance": ["可交接"]},
            "expected_status": "completed", "downstream_employee_id": downstream_id,
        }]
        subject_id = self.core.create_employee("Subject", draft)
        trial = self.core.start_employee_trial(subject_id, "handoff")
        received = []

        def runtime(employee, work_order, _emit):
            received.append((employee["name"], work_order))
            return {"status": "completed", "summary": employee["name"] + " done",
                    "output": {"by": employee["name"]}, "artifacts": [], "issues": []}

        self.core.run_workflow(trial["id"], runtime)
        finished = self.core.employee_trials(subject_id)[0]
        runs = finished["employee_runs"]
        self.assertIsNone(runs[0]["employee_release_id"])
        self.assertEqual(runs[1]["employee_release_id"], downstream_release["release_id"])
        self.assertEqual(received[1][1]["context"]["upstream_position"], "subject")
        self.assertEqual(received[1][1]["context"]["upstream_output"], {"by": "Subject"})
        self.assertEqual(finished["trial_result"]["downstream_status"], "completed")

    def test_automation_provenance_uses_events_and_tracks_open_work(self):
        employee_id = self.core.create_employee(
            "Scheduled worker", employee_draft("Handle scheduled work",
                                                self.package["package_id"],
                                                "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline("Scheduled pipeline", {
            "positions": [{"key": "work", "name": "Work", "employee_id": employee_id}],
            "edges": [],
        })
        task_id = self.core.create_task(
            pipeline_id, "Scheduled task", {"objective": "Complete scheduled work"})

        workflow_run_id = self.core.start_workflow(task_id, source={
            "automation_id": 17, "automation_run_id": 23,
        })

        self.assertTrue(self.core.automation_has_open_work(17))
        self.assertEqual(self.core.automation_workflows(17), [{
            "id": workflow_run_id,
            "task_id": task_id,
            "state": "ready",
            "created_at": self.core.workflow(workflow_run_id)["created_at"],
            "updated_at": self.core.workflow(workflow_run_id)["updated_at"],
        }])
        source_event = self.core.repository.events("automation:17")[0]
        self.assertEqual(source_event["type"], "automation.workflow_started")
        self.assertEqual(source_event["data_json"], {
            "workflow_run_id": workflow_run_id,
            "task_id": task_id,
            "pipeline_id": pipeline_id,
            "automation_run_id": 23,
        })

        self.core.cancel_workflow(workflow_run_id)
        self.assertFalse(self.core.automation_has_open_work(17))

    def test_employee_protocol_requires_real_final_verifier(self):
        employee_id = self.core.create_employee(
            "Verifier", employee_draft("Produce a valid brief", self.package["package_id"],
                                       "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline("Verified delivery", {
            "positions": [{"key": "verify", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(pipeline_id, "Make brief", {"objective": "Make a brief"})
        workflow_run_id = self.core.start_workflow(task_id)
        root = Path(self.tmp.name)

        class ProtocolRuntime:
            def run(_self, employee, work_order, emit, *, employee_run_id, database):
                workspace = root / "protocol-workspace"
                workspace.mkdir()
                protocol = EmployeeProtocol(database, employee_run_id, workspace)
                before_task = protocol.call("complete", {"summary": "bad", "output": {}})
                self.assertTrue(before_task["isError"])
                task = protocol.call("get_task", {})["structuredContent"]
                self.assertEqual(task["required_verifiers"],
                                 ["brief-validator/validate-brief"])
                protocol.call("advance_step", {"step_id": "work", "summary": "brief written"})
                before_verifier = protocol.call("complete", {"summary": "bad", "output": {}})
                self.assertTrue(before_verifier["isError"])
                brief_path = workspace / "brief.json"
                brief_path.write_text(json.dumps({"objective": "Make a brief", "context": {}}),
                                      encoding="utf-8")
                verified = protocol.call("run_capability", {
                    "capability_ref": "brief-validator/validate-brief",
                    "arguments": ["brief.json"]})
                self.assertEqual(verified["structuredContent"]["result"]["evaluation"]["status"],
                                 "passed")
                brief_path.write_text(json.dumps({"objective": "Changed after verification",
                                                  "context": {}}), encoding="utf-8")
                stale = protocol.call("complete", {"summary": "stale", "output": {}})
                self.assertTrue(stale["isError"])
                self.assertIn("失效", stale["structuredContent"]["message"])
                protocol.call("run_capability", {
                    "capability_ref": "brief-validator/validate-brief",
                    "arguments": ["brief.json"]})
                protocol.call("publish_artifact", {"path": "brief.json", "title": "Brief"})
                completed = protocol.call("complete", {
                    "summary": "validated brief", "output": {"valid": True}})
                self.assertFalse(completed["isError"])
                run, _ = protocol.context()
                return json.loads(run["output_json"])

        result = self.core.run_workflow(workflow_run_id, ProtocolRuntime())
        self.assertEqual(result["status"], "completed")
        visible_run = self.core.workflow(workflow_run_id)["employee_runs"][0]
        self.assertTrue(any(item["type"] == "capability.executed"
                            for item in visible_run["events"]))
        self.assertEqual(len(visible_run["artifacts"]), 1)
        with self.core.repository.connect() as connection:
            artifacts = connection.execute("SELECT * FROM artifacts").fetchall()
        self.assertEqual(len(artifacts), 1)

    def test_selected_skill_can_run_companion_tool_from_same_frozen_package(self):
        draft = employee_draft(
            "Follow the skill and validate the brief", self.package["package_id"],
            "brief-validator")
        draft["tests"] = [{
            "id": "package-unavailable", "name": "能力包不可用",
            "work_order": {
                "objective": "Validate the brief", "inputs": [],
                "expected_output": {}, "acceptance": [],
                "context": {"test_signal": {
                    "capability_ref": "brief-validator/brief-validator",
                    "state": "unavailable",
                }},
            },
            "expected_status": "failed",
            "covers": ["result.failed", "capability.1:brief-validator.failure"],
        }]
        employee_id = self.core.create_employee("Skill user", draft)
        publish_verified_employee(self.core, employee_id)

        pipeline_id = self.core.create_pipeline("Skill tools", {
            "positions": [{"key": "work", "employee_id": employee_id}], "edges": []})
        task_id = self.core.create_task(
            pipeline_id, "Use companion tool", {"objective": "Validate"})
        workflow_run_id = self.core.start_workflow(task_id)
        root = Path(self.tmp.name)

        class CompanionRuntime:
            def run(_self, employee, work_order, emit, *, employee_run_id, database):
                workspace = root / "skill-companion-workspace"
                workspace.mkdir()
                protocol = EmployeeProtocol(database, employee_run_id, workspace)
                task = protocol.call("get_task", {})["structuredContent"]
                refs = {item["ref"]: item for item in task["capabilities"]}
                self.assertEqual(refs["brief-validator/brief-validator"]["kind"], "skill")
                self.assertEqual(refs["brief-validator/validate-brief"]["kind"], "tool")
                (workspace / "valid-brief.json").write_text(
                    json.dumps({"objective": "Validate", "context": {}}),
                    encoding="utf-8")
                checked = protocol.call("run_capability", {
                    "capability_ref": "brief-validator/validate-brief",
                    "arguments": ["valid-brief.json"],
                })
                self.assertFalse(checked["isError"])
                protocol.call("advance_step", {"step_id": "work", "summary": "checked"})
                protocol.call("complete", {"summary": "done", "output": {}})
                run, _employee = protocol.context()
                return json.loads(run["output_json"])

        self.assertEqual(
            self.core.run_workflow(workflow_run_id, CompanionRuntime())["status"],
            "completed")

        current = self.core.employee(employee_id)
        current_draft = current["draft_json"]
        # Deliberately feed the v1 per-capability shape. Normalization must collapse
        # both references and their coverage ids into one package-level employee skill.
        current_draft["capabilities"] = [
            {"package_id": self.package["package_id"],
             "capability_id": "brief-validator"},
            {"package_id": self.package["package_id"],
             "capability_id": "validate-brief"},
        ]
        current_draft["tests"] = [{
            **draft["tests"][0],
            "covers": ["result.failed",
                       "capability.1:brief-validator.failure",
                       "capability.1:validate-brief.failure"],
        }]
        self.core.update_employee(
            employee_id, current["name"], current_draft, preserve_tests=True)
        migrated = self.core.employee(employee_id)["draft_json"]
        self.assertEqual(
            migrated["capabilities"], [{"package_id": self.package["package_id"]}])
        self.assertEqual(
            migrated["tests"][0]["covers"],
            ["result.failed", "skill.{}.failure".format(self.package["package_id"])])

        class UnavailableRuntime:
            def run(_self, employee, work_order, emit, *, employee_run_id, database):
                workspace = root / "skill-unavailable-{}".format(employee_run_id)
                workspace.mkdir()
                protocol = EmployeeProtocol(database, employee_run_id, workspace)
                task = protocol.call("get_task", {})["structuredContent"]
                self.assertFalse(next(item for item in task["capabilities"]
                                      if item["ref"] ==
                                      "brief-validator/validate-brief")["available"])
                blocked = protocol.call("run_capability", {
                    "capability_ref": "brief-validator/validate-brief",
                    "arguments": ["valid-brief.json"],
                })
                self.assertTrue(blocked["isError"])
                self.assertIn("本次验证场景中不可用",
                              blocked["structuredContent"]["message"])
                protocol.call("report_failed", {
                    "reason": "能力包不可用", "recovery": "恢复能力包"})
                run, _employee = protocol.context()
                return json.loads(run["output_json"])

        trials = self.core.start_employee_trial_samples(
            employee_id, "package-unavailable", fresh=True)
        self.assertEqual(len(trials), 3)
        for trial in trials:
            result = self.core.run_workflow(trial["id"], UnavailableRuntime())
            self.assertEqual(result["status"], "failed")
        coverage = self.core.employee_coverage(
            employee_id, trials=self.core.employee_trials(employee_id))
        self.assertEqual(coverage["runs"]["package-unavailable"], {
            "passed": 3, "failed": 0, "running": 0})

    def test_pipeline_preserves_conditional_branching_for_runtime(self):
        employee_id = self.core.create_employee(
            "One", employee_draft("Work", self.package["package_id"], "validate-brief"))
        pipeline_id = self.core.create_pipeline("Branch", {
            "positions": [{"key": key, "employee_id": employee_id}
                          for key in ("a", "b", "c")],
            "edges": [{"from": "a", "to": "b", "when": "failed"},
                      {"from": "a", "to": "c"},
                      {"from": "b", "to": "c"}],
        })
        self.assertEqual(self.core.pipeline(pipeline_id)["definition_json"]["edges"], [
            {"from": "a", "to": "b", "when": "failed"},
            {"from": "a", "to": "c"},
            {"from": "b", "to": "c"},
        ])

    def test_pipeline_preserves_board_states_without_turning_them_into_employee_positions(self):
        employee_id = self.core.create_employee(
            "One", employee_draft("Work", self.package["package_id"], "validate-brief"))
        pipeline_id = self.core.create_pipeline("States", {
            "positions": [{"key": "work", "employee_id": employee_id}],
            "edges": [],
            "states": [
                {"key": "state-pool-1", "name": "待定", "kind": "pool"},
                {"key": "state-done-2", "name": "完成", "kind": "done"},
                {"key": "state-dropped-3", "name": "放弃", "kind": "dropped"},
            ],
        })
        definition = self.core.pipeline(pipeline_id)["definition_json"]
        self.assertEqual([item["key"] for item in definition["positions"]], ["work"])
        self.assertEqual([item["kind"] for item in definition["states"]],
                         ["pool", "done", "dropped"])
        with self.assertRaises(ContractError):
            self.core.update_pipeline(pipeline_id, "States", {
                "positions": [{"key": "work", "employee_id": employee_id}],
                "edges": [],
                "states": [{"key": "state-review", "name": "审核", "kind": "review"}],
            })

    def test_pipeline_preserves_valid_board_column_colors(self):
        employee_id = self.core.create_employee(
            "One", employee_draft("Work", self.package["package_id"], "validate-brief"))
        pipeline_id = self.core.create_pipeline("Colors", {
            "positions": [{"key": "work", "employee_id": employee_id, "color": "purple"}],
            "edges": [],
            "states": [{"key": "state-done", "name": "完成", "kind": "done",
                        "color": "blue"}],
        })
        definition = self.core.pipeline(pipeline_id)["definition_json"]
        self.assertEqual(definition["positions"][0]["color"], "purple")
        self.assertEqual(definition["states"][0]["color"], "blue")
        with self.assertRaisesRegex(ContractError, "岗位颜色无效"):
            self.core.update_pipeline(pipeline_id, "Colors", {
                "positions": [{"key": "work", "employee_id": employee_id,
                               "color": "ultraviolet"}],
                "edges": [],
            })

    def test_pipeline_preserves_team_parameters_and_freezes_them_with_the_workflow(self):
        employee_id = self.core.create_employee(
            "One", employee_draft("Work", self.package["package_id"], "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        parameters = [
            {"key": "customer_name", "label": "客户名称", "type": "text",
             "source": "user", "display": "input", "visible_to": ["work"]},
            {"key": "review_result", "label": "评审结论", "type": "textarea",
             "source": "employee", "display": "handoff", "writers": ["work"],
             "producers": ["work"]},
        ]
        pipeline_id = self.core.create_pipeline("Parameters", {
            "positions": [{"key": "work", "employee_id": employee_id}],
            "edges": [], "parameters": parameters,
        })
        definition = self.core.pipeline(pipeline_id)["definition_json"]
        self.assertEqual(definition["parameters"], parameters)
        task_id = self.core.create_task(
            pipeline_id, "Parameterized task", {"objective": "Complete the task"})
        workflow_id = self.core.start_workflow(task_id)
        snapshot = self.core.workflow(workflow_id)["snapshot_json"]
        self.assertEqual(snapshot["definition"]["parameters"], parameters)
        task = copy.deepcopy(snapshot["task"])
        task["payload"]["parameters"] = {"customer_name": "Acme"}
        self.core.update_workflow_task(
            workflow_id, "Parameterized task",
            parameters={"customer_name": "Acme"})
        position = snapshot["definition"]["positions"][0]
        work_order = self.core._work_order(
            workflow_id, task, position, ["work"], 0, None, None,
            snapshot["definition"])
        self.assertEqual(
            work_order["context"]["team_parameters"][0]["value"], "Acme")
        self.assertEqual(
            work_order["expected_output"]["team_parameters"][0]["key"],
            "review_result")
        employee_run_id = self.core._start_employee_run(
            workflow_id, position, work_order)
        self.core._finish_employee_run(employee_run_id, {
            "schema": "runteams.work-result/v1",
            "status": "completed",
            "summary": "Reviewed",
            "output": {"team_parameters": {"review_result": "Approved"}},
            "artifacts": [],
            "issues": [],
        })
        workflow = self.core.workflow(workflow_id)
        self.assertEqual(workflow["team_parameters"], {
            "customer_name": "Acme", "review_result": "Approved"})
        next_order = self.core._work_order(
            workflow_id, task, position, ["work"], 0, None, None,
            snapshot["definition"])
        visible = {item["key"]: item.get("value") for item in
                   next_order["context"]["team_parameters"]}
        self.assertEqual(visible, {
            "customer_name": "Acme", "review_result": "Approved"})
        with self.assertRaisesRegex(ContractError, "无效岗位"):
            self.core.update_pipeline(pipeline_id, "Parameters", {
                "positions": [{"key": "work", "employee_id": employee_id}],
                "edges": [], "parameters": [dict(parameters[0], visible_to=["missing"])],
            })

    def test_pipeline_standards_are_frozen_and_scoped_to_employees(self):
        first_id = self.core.create_employee(
            "First", employee_draft(
                "Do first work", self.package["package_id"], "validate-brief"))
        second_id = self.core.create_employee(
            "Second", employee_draft(
                "Do second work", self.package["package_id"], "validate-brief"))
        publish_verified_employee(self.core, first_id)
        publish_verified_employee(self.core, second_id)
        standards = [
            {"key": "cite-sources", "name": "标明事实来源",
             "description": "输出包含外部事实时使用",
             "instructions": "每条关键事实都要标明来源。"},
            {"key": "second-only", "name": "复核交接内容",
             "instructions": "开始前先复核上游交接。",
             "employee_ids": [second_id]},
        ]
        pipeline_id = self.core.create_pipeline("Standards", {
            "positions": [
                {"key": "first", "employee_id": first_id},
                {"key": "second", "employee_id": second_id},
            ],
            "edges": [{"from": "first", "to": "second"}],
            "standards": standards,
        })
        task_id = self.core.create_task(
            pipeline_id, "Standards task", {"objective": "Complete it"})
        workflow_id = self.core.start_workflow(task_id)
        snapshot = self.core.workflow(workflow_id)["snapshot_json"]
        self.assertEqual(snapshot["definition"]["standards"], standards)
        task = copy.deepcopy(snapshot["task"])
        first_order = self.core._work_order(
            workflow_id, task, snapshot["definition"]["positions"][0],
            ["first", "second"], 0, None, None, snapshot["definition"])
        self.assertEqual(
            [item["key"] for item in first_order["context"]["team_standards"]],
            ["cite-sources"])
        upstream = {
            "schema": "runteams.work-result/v1", "status": "completed",
            "summary": "First completed", "output": {}, "artifacts": [],
            "issues": [],
        }
        second_order = self.core._work_order(
            workflow_id, task, snapshot["definition"]["positions"][1],
            ["first", "second"], 1, upstream, None, snapshot["definition"])
        self.assertEqual(
            [item["key"] for item in second_order["context"]["team_standards"]],
            ["cite-sources", "second-only"])
        self.core.update_pipeline(pipeline_id, "Standards", {
            "positions": snapshot["definition"]["positions"],
            "edges": snapshot["definition"]["edges"],
            "standards": [dict(standards[0], instructions="已修改")],
        })
        self.assertEqual(
            self.core.workflow(workflow_id)["snapshot_json"]["definition"]["standards"],
            standards)

    def test_task_inputs_are_frozen_while_new_attachments_target_the_next_run(self):
        employee_id = self.core.create_employee(
            "Input reader", employee_draft(
                "Read supplied materials", self.package["package_id"], "validate-brief"))
        publish_verified_employee(self.core, employee_id)
        pipeline_id = self.core.create_pipeline("Inputs", {
            "positions": [{"key": "read", "employee_id": employee_id}], "edges": [],
        })
        task_id = self.core.create_task(
            pipeline_id, "Read brief", {"objective": "Read the supplied brief"})
        first = {"id": "a" * 24, "name": "brief.md", "kind": "file", "size": 12,
                 "ref": "task-input://{}/{}".format(task_id, "a" * 24)}
        self.core.set_task_inputs(task_id, [first])
        workflow_id = self.core.start_workflow(task_id)
        workflow = self.core.workflow(workflow_id)
        self.assertEqual(workflow["snapshot_json"]["task"]["payload"]["inputs"], [first])

        second = {"id": "b" * 24, "name": "research", "kind": "folder",
                  "file_count": 2,
                  "ref": "task-input://{}/{}".format(task_id, "b" * 24)}
        updated = self.core.append_workflow_task_inputs(workflow_id, [second])
        self.assertEqual(updated["task"]["payload_json"]["inputs"], [first, second])
        self.assertEqual(updated["snapshot_json"]["task"]["payload"]["inputs"], [first])
        with self.assertRaisesRegex(ContractError, "请先停止任务"):
            self.core.remove_workflow_task_input(workflow_id, first["id"])
        self.core.cancel_workflow(workflow_id)
        with self.assertRaisesRegex(ContractError, "引用无效"):
            self.core.append_workflow_task_inputs(workflow_id, [{
                **second, "id": "c" * 24, "ref": "task-input://999/{}".format("c" * 24),
            }])

        self.core.remove_workflow_task_input(workflow_id, first["id"])
        retried = self.core.retry_workflow(workflow_id)
        self.assertEqual(
            retried["snapshot_json"]["task"]["payload"]["inputs"], [second])

    def test_task_inputs_remain_available_to_every_downstream_position(self):
        first_id = self.core.create_employee(
            "Input analyst", employee_draft(
                "Read the original material", self.package["package_id"], "validate-brief"))
        second_id = self.core.create_employee(
            "Input implementer", employee_draft(
                "Use the original material", self.package["package_id"], "validate-brief"))
        publish_verified_employee(self.core, first_id)
        publish_verified_employee(self.core, second_id)
        pipeline_id = self.core.create_pipeline("Shared original inputs", {
            "positions": [{"key": "analysis", "employee_id": first_id},
                          {"key": "implementation", "employee_id": second_id}],
            "edges": [{"from": "analysis", "to": "implementation"}],
        })
        task_id = self.core.create_task(
            pipeline_id, "Use one project snapshot", {"objective": "Keep the source visible"})
        original = {
            "id": "c" * 24, "name": "project", "kind": "folder", "file_count": 3,
            "ref": "task-input://{}/{}".format(task_id, "c" * 24),
        }
        self.core.set_task_inputs(task_id, [original])
        workflow_id = self.core.start_workflow(task_id)
        workflow = self.core.workflow(workflow_id)
        snapshot = workflow["snapshot_json"]
        work_order = self.core._work_order(
            workflow_id, copy.deepcopy(snapshot["task"]),
            snapshot["definition"]["positions"][1],
            ["analysis", "implementation"], 1, {
                "schema": "runteams.work-result/v1", "status": "completed",
                "summary": "analysis complete", "output": {}, "artifacts": [],
                "issues": [],
            }, None, snapshot["definition"])
        self.assertEqual(work_order["inputs"], [original])


if __name__ == "__main__":
    unittest.main()
