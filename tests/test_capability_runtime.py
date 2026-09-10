# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from unittest import mock

import capability_runtime


class CapabilityRuntimeTests(unittest.TestCase):
    def portable_runtime(self, **overrides):
        spec = {
            "version": 3, "runner": "portable", "dependencies": [],
            "package": {"id": "ruby-runtime", "version": "3.4.1", "publisher": "Ruby",
                        "platforms": {capability_runtime.platform_key(): {
                            "url": "https://downloads.example.test/ruby.zip",
                            "sha256": "a" * 64, "archive": "zip",
                            "executable": "bin/ruby"}}},
            "limits": {"memory_mb": 512, "cpu_seconds": 120, "processes": 4,
                       "file_size_mb": 32, "open_files": 64},
        }
        spec.update(overrides)
        return spec

    def test_legacy_python_entry_gets_compatible_contract(self):
        runtime = capability_runtime.normalize({}, "tools/main.py")
        self.assertEqual(runtime["runner"], "python")
        self.assertEqual(runtime["dependencies"], [])

    def test_python_dependency_uses_distribution_and_import_names(self):
        runtime = capability_runtime.normalize({
            "runner": "python",
            "dependencies": [{"name": "PyJWT", "import": "jwt", "version": "==2.13.0"}],
        }, "main.py")
        self.assertEqual(runtime["dependencies"][0]["name"], "PyJWT")
        self.assertEqual(runtime["dependencies"][0]["import"], "jwt")

    def test_missing_dependency_is_owned_by_capability(self):
        entry = {"slug": "demo", "entry_path": "main.py", "runtime": {
            "runner": "python", "dependencies": [{
                "ecosystem": "python", "name": "missing-package", "import": "never_installed_xyz",
                "version": "==1.0.0"}]}}
        with mock.patch.object(capability_runtime.importlib.util, "find_spec", return_value=None):
            report = capability_runtime.preflight_entry(entry, {"main.py": "print('x')\n"})
        issue = next(item for item in report["checks"] if item["kind"] == "capability_dependency")
        self.assertFalse(report["ready"])
        self.assertEqual(issue["owner"], "capability")

    def test_node_runner_does_not_require_python_extension(self):
        runtime = capability_runtime.normalize({"runner": "node"}, "main.mjs")
        self.assertEqual(runtime["runner"], "node")

    def test_v2_dependency_rejects_floating_version(self):
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "精确版本"):
            capability_runtime.normalize({"version": 2, "runner": "python", "dependencies": [
                {"name": "PyJWT", "import": "jwt", "version": ">=2.8,<3"}]}, "main.py")

    def test_import_failure_stays_unknown_until_independently_reproduced(self):
        issue = capability_runtime.classify_failure(
            "ModuleNotFoundError: No module named 'jwt'", 1)
        self.assertEqual(issue["code"], "dependency_missing")
        self.assertEqual(issue["owner"], "unknown")

    def test_v3_portable_runtime_is_platform_pinned_and_resource_bounded(self):
        runtime = capability_runtime.normalize(self.portable_runtime(), "main.rb")
        self.assertEqual(runtime["runner"], "portable")
        self.assertEqual(runtime["package"]["version"], "3.4.1")
        self.assertEqual(runtime["limits"]["memory_mb"], 512)
        self.assertEqual(runtime["limits"]["processes"], 4)

    def test_portable_runtime_rejects_insecure_url_and_escaping_executable(self):
        spec = self.portable_runtime()
        source = spec["package"]["platforms"][capability_runtime.platform_key()]
        source["url"] = "http://downloads.example.test/ruby.zip"
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "HTTPS"):
            capability_runtime.normalize(spec, "main.rb")
        source["url"] = "https://downloads.example.test/ruby.zip"
        source["executable"] = "../bin/ruby"
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "安全相对路径"):
            capability_runtime.normalize(spec, "main.rb")
        source["executable"] = "/bin/ruby"
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "安全相对路径"):
            capability_runtime.normalize(spec, "main.rb")

    def test_portable_runtime_must_be_v3_and_self_contained(self):
        spec = self.portable_runtime(version=2)
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "version=3"):
            capability_runtime.normalize(spec, "main.rb")
        spec = self.portable_runtime()
        spec["dependencies"] = [{"ecosystem": "python", "name": "requests",
                                  "import": "requests", "version": "==2.32.5"}]
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "自包含"):
            capability_runtime.normalize(spec, "main.rb")

    def test_portable_command_uses_only_installed_executable(self):
        runtime = self.portable_runtime()
        with tempfile.NamedTemporaryFile() as executable:
            os.chmod(executable.name, 0o700)
            command = capability_runtime.command(
                {"entry_path": "main.rb", "runtime": runtime}, "/work/main.rb", ["one"],
                {"RUNTEAMS_PORTABLE_EXECUTABLE": executable.name})
        self.assertEqual(command, [executable.name, "/work/main.rb", "one"])

    def test_resource_limit_failure_is_structured(self):
        issue = capability_runtime.classify_failure(
            "RUNTEAMS_RESOURCE_LIMIT: too many processes", 70)
        self.assertEqual(issue["code"], "resource_limit")
        self.assertEqual(issue["owner"], "unknown")

    def test_simulator_accessibility_service_failure_belongs_to_system(self):
        issue = capability_runtime.classify_failure(
            "Failed to get matching snapshots: Error getting main window "
            "kAXErrorAPIDisabled\nUnable to determine access", 1)
        self.assertEqual(issue["code"], "simulator_service_unavailable")
        self.assertEqual(issue["owner"], "system")
        self.assertEqual(issue["remediation"], "")

    def test_test_assertion_belongs_to_task_not_capability(self):
        issue = capability_runtime.classify_failure("assertion failed", 1)
        self.assertEqual(issue["owner"], "task")
        self.assertEqual(issue["code"], "task_verification_failed")

    def test_common_project_test_framework_failures_never_trigger_capability_maintenance(self):
        samples = (
            "pytest: 2 failed, 18 passed\nAssertionError",
            "Jest test failed: Expected 2, Received 3",
            "Gradle BUILD FAILED: There were failing tests",
            "XCTAssertEqual failed in FeatureTests",
        )
        for output in samples:
            with self.subTest(output=output):
                issue = capability_runtime.classify_failure(output, 1)
                self.assertEqual(issue["owner"], "task")

    def test_unknown_nonzero_exit_is_not_assumed_to_be_broken_capability(self):
        issue = capability_runtime.classify_failure("unexpected domain-specific output", 23)
        self.assertEqual(issue["owner"], "unknown")
        self.assertEqual(issue["code"], "execution_failed")

    def test_runtime_effect_is_explicit_and_validated(self):
        runtime = capability_runtime.normalize(
            {"runner": "python", "effect": "verifier"}, "main.py")
        self.assertEqual(runtime["effect"], "verifier")
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "作用类型"):
            capability_runtime.normalize(
                {"runner": "python", "effect": "magic"}, "main.py")

    def test_legacy_effect_inference_is_conservative(self):
        self.assertEqual(capability_runtime.infer_effect("ios-simulator"), "verifier")
        self.assertEqual(capability_runtime.infer_effect("market-scorecard"), "diagnostic")
        self.assertEqual(capability_runtime.infer_effect("asc-submit"), "operation")

    def test_shared_data_contract_blocks_missing_asset_and_accepts_existing_file(self):
        entry = {"slug": "shared-db", "entry_path": "main.py", "runtime": {
            "version": 2, "runner": "python", "effect": "operation",
            "shared_data": [{"path": "shared/demo/data.db", "kind": "file",
                             "access": "read_write", "label": "共享数据库"}]}}
        with tempfile.TemporaryDirectory() as root:
            missing = capability_runtime.preflight_entry(
                entry, {"main.py": "print('ok')\n"}, shared_root=root)
            issue = next(item for item in missing["checks"]
                         if item["kind"] == "capability_environment")
            self.assertFalse(missing["ready"])
            self.assertEqual(issue["owner"], "system")
            os.makedirs(os.path.join(root, "shared", "demo"))
            with open(os.path.join(root, "shared", "demo", "data.db"), "wb") as handle:
                handle.write(b"sqlite")
            ready = capability_runtime.preflight_entry(
                entry, {"main.py": "print('ok')\n"}, shared_root=root)
            self.assertTrue(ready["ready"])

    def test_shared_data_contract_rejects_path_traversal(self):
        with self.assertRaisesRegex(capability_runtime.CapabilityRuntimeError, "安全相对路径"):
            capability_runtime.normalize({
                "version": 2, "runner": "python",
                "shared_data": [{"path": "../private.db"}]}, "main.py")


if __name__ == "__main__":
    unittest.main()
