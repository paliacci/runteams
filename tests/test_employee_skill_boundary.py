import os
import tempfile
import unittest

import agent_tool_registry
import chat
from runteams_core import RunTeamsCore
from runteams_core.contracts import normalize_capability_references


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EmployeeSkillBoundaryTests(unittest.TestCase):
    def test_legacy_capability_references_collapse_to_one_employee_skill(self):
        self.assertEqual(normalize_capability_references([
            {"package_id": 7, "capability_id": "instructions"},
            {"package_id": 7, "capability_id": "validator"},
        ]), [{"package_id": 7}])

    def test_release_freezes_one_complete_skill(self):
        with tempfile.TemporaryDirectory(prefix="runteams-skill-boundary-") as root:
            core = RunTeamsCore(root)
            package = core.import_package(
                "brief-validator", os.path.join(ROOT, "examples", "brief-validator"))
            employee_id = core.create_employee("交接检查员", {
                "role": "检查交接简报",
                "program": {
                    "objective": "让下游收到可执行的交接简报",
                    "steps": [{"id": "check", "instruction": "检查交接简报"}],
                    "acceptance": ["交接简报可执行"],
                    "deliverables": [{
                        "path": "reports/brief.md",
                        "name": "交接检查报告",
                        "required": True,
                    }],
                },
                "capabilities": [{"package_id": package["package_id"]}],
                "runtime": {"channel": "codex", "model": "test", "effort": "low"},
            })
            snapshot, _checks = core._release_snapshot(core.employee(employee_id), False)
            self.assertEqual(snapshot["schema"], "runteams.employee-release/v2")
            self.assertEqual(snapshot["program"]["deliverables"], [{
                "path": "reports/brief.md",
                "name": "交接检查报告",
                "required": True,
            }])
            self.assertEqual(len(snapshot["capabilities"]), 1)
            frozen = snapshot["capabilities"][0]
            self.assertEqual({item["id"] for item in frozen["capabilities"]}, {
                "brief-validator", "validate-brief"})

    def test_agent_chat_cannot_select_or_run_employee_skills(self):
        self.assertEqual(chat._normalize_capabilities([
            {"kind": "package", "id": "7", "label": "员工技能"},
        ]), [])
        self.assertNotIn("runteams_run_extension", {
            tool.name for tool in agent_tool_registry.tools()})

    def test_web_unifies_catalog_without_unifying_runtime_boundaries(self):
        with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('["plugin","skill","mcp","package"]', source)
        self.assertNotIn("function employeeSkillsPage", source)
        self.assertNotIn("function capabilityFromPackage", source)
        catalog = source.split("function environmentExtensionEntries", 1)[1].split(
            "function environmentExtensionRows", 1)[0]
        self.assertIn("S.corePackages", catalog)
        self.assertIn("installed:true", catalog)
        self.assertIn('class="environment-employee-mark"', source)
        self.assertIn('${ICON("users")}</span>', source)
        detail_header = source.split("function environmentExtensionHeaderModel", 1)[1].split(
            "function environmentDetailSummary", 1)[0]
        self.assertIn('sourceMark:`<span class="environment-employee-mark"', detail_header)
        plugin_rows = source.split("function environmentPluginRows", 1)[1].split(
            "function corePackageLabel", 1)[0]
        self.assertNotIn("environment-use-tag", plugin_rows)
        self.assertNotIn("对话 · 员工", plugin_rows)


if __name__ == "__main__":
    unittest.main()
