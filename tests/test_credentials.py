# -*- coding: utf-8 -*-
import os
import json
import tempfile
import unittest
from pathlib import Path

import app
import app_secrets
import local_database
import product_store as store
from scripts.fixture_validation import publish_verified_employee


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-credentials-")
        self.old_db = local_database.DB_PATH
        self.old_data = os.environ.get("RUNTEAMS_DATA")
        self.old_core_data = os.environ.get("RUNTEAMS_CORE_DATA")
        self.old_controller = app._CORE_CONTROLLER
        os.environ["RUNTEAMS_DATA"] = self.tmp.name
        os.environ["RUNTEAMS_CORE_DATA"] = os.path.join(self.tmp.name, "core")
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        app._CORE_CONTROLLER = None
        store.init_product_db()

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        if self.old_data is None:
            os.environ.pop("RUNTEAMS_DATA", None)
        else:
            os.environ["RUNTEAMS_DATA"] = self.old_data
        if app._CORE_CONTROLLER is not None:
            app._CORE_CONTROLLER.stop()
        app._CORE_CONTROLLER = self.old_controller
        if self.old_core_data is None:
            os.environ.pop("RUNTEAMS_CORE_DATA", None)
        else:
            os.environ["RUNTEAMS_CORE_DATA"] = self.old_core_data
        self.tmp.cleanup()

    def _import_credential_package(self):
        source = Path(self.tmp.name) / "usage-probe"
        (source / "scripts").mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: usage-probe\ndescription: Verify credential usage projection.\n---\n",
            encoding="utf-8")
        (source / "runteams.json").write_text(json.dumps({
            "schema": "runteams.package-extension/v1", "capabilities": [{
                "id": "use-service", "entry": "scripts/use.py",
                "credentials": ["SERVICE_TOKEN"],
                "runtime": {"version": 2, "runner": "python", "effect": "operation",
                            "dependencies": [],
                            "healthcheck": {
                                "cases": [{"arguments": ["--self-check"],
                                           "expected": "passed"}]}},
            }],
        }), encoding="utf-8")
        (source / "scripts" / "use.py").write_text(
            "print('{\"schema\":\"runteams.tool-result/v1\","
            "\"execution\":{\"status\":\"completed\",\"exit_code\":0},"
            "\"evaluation\":{\"status\":\"passed\"}}')\n", encoding="utf-8")
        return app.core_controller().core.import_package("usage-probe", source)

    def test_entries_are_user_owned_ordered_metadata(self):
        entry = store.save_credential_entry("SERVICE_API_KEY")
        store.save_credential_entry("SECOND_KEY")
        self.assertEqual(entry, {"name": "SERVICE_API_KEY", "source_name": ""})
        self.assertEqual(
            [item["name"] for item in store.list_credential_entries()],
            ["SERVICE_API_KEY", "SECOND_KEY"],
        )

        store.reorder_credential_entries(["SECOND_KEY", "SERVICE_API_KEY"])
        self.assertEqual(
            [item["name"] for item in store.list_credential_entries()],
            ["SECOND_KEY", "SERVICE_API_KEY"],
        )
        with self.assertRaisesRegex(ValueError, "不完整"):
            store.reorder_credential_entries(["SERVICE_API_KEY"])
        with self.assertRaisesRegex(ValueError, "字母、数字和下划线"):
            store.save_credential_entry("not a key")

    def test_grouped_development_schema_migrates_to_flat_order(self):
        with store.conn() as connection:
            connection.execute("DROP TABLE credential_entries")
            connection.execute("CREATE TABLE credential_groups("
                               "id INTEGER PRIMARY KEY,name TEXT,pos INTEGER,"
                               "created_at TEXT,updated_at TEXT)")
            connection.execute("CREATE TABLE credential_entries("
                               "name TEXT PRIMARY KEY,group_id INTEGER,pos INTEGER,"
                               "created_at TEXT,updated_at TEXT)")
            connection.execute("INSERT INTO credential_groups VALUES(1,'发布',1,'t','t')")
            connection.execute("INSERT INTO credential_entries VALUES('FREE_KEY',NULL,2,'t','t')")
            connection.execute("INSERT INTO credential_entries VALUES('GROUP_KEY',1,1,'t','t')")

        store.init_product_db()

        self.assertEqual(
            [item["name"] for item in store.list_credential_entries()],
            ["FREE_KEY", "GROUP_KEY"],
        )
        with store.conn() as connection:
            self.assertEqual(
                [row[1] for row in connection.execute("PRAGMA table_info(credential_entries)")],
                ["name", "pos", "source_name", "created_at", "updated_at"],
            )
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='credential_groups'"
            ).fetchone())


    def test_batch_secret_save_is_atomic_and_masked(self):
        app_secrets.set_secrets({"FIRST_KEY": "first-secret", "SECOND_KEY": "second-secret"})
        masked = app_secrets.list_masked()
        self.assertEqual(set(masked), {"FIRST_KEY", "SECOND_KEY"})
        self.assertNotEqual(masked["FIRST_KEY"]["masked"], "first-secret")
        with self.assertRaisesRegex(ValueError, "不能为空"):
            app_secrets.set_secrets({"FIRST_KEY": "replacement", "SECOND_KEY": ""})
        self.assertEqual(set(app_secrets.list_masked()), {"FIRST_KEY", "SECOND_KEY"})
        self.assertEqual(app_secrets.names(), {"FIRST_KEY", "SECOND_KEY"})
        self.assertEqual(app_secrets.resolve(["SECOND_KEY"]),
                         {"SECOND_KEY": "second-secret"})

    def test_development_secret_file_keeps_global_values_and_drops_card_overrides(self):
        with open(os.path.join(self.tmp.name, "secrets.json"), "w", encoding="utf-8") as handle:
            json.dump({"global": {"KEEP_KEY": "keep-secret"},
                       "cards": {"7": {"DROP_KEY": "drop-secret"}}}, handle)

        masked = app_secrets.list_masked()

        self.assertEqual(set(masked), {"KEEP_KEY"})
        app_secrets.set_secret("NEW_KEY", "new-secret")
        with open(os.path.join(self.tmp.name, "secrets.json"), encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(set(stored), {"KEEP_KEY", "NEW_KEY"})



    def test_vault_payload_never_contains_plain_values_or_project_scope(self):
        store.save_credential_entry("MY_SERVICE_KEY")
        app_secrets.set_secret("MY_SERVICE_KEY", "top-secret-value")

        payload = app.secret_vault_payload()

        credential = payload["credentials"][0]
        self.assertEqual(credential["name"], "MY_SERVICE_KEY")
        self.assertTrue(credential["set"])
        self.assertNotEqual(credential["masked"], "top-secret-value")
        self.assertNotIn("projects", payload)
        self.assertNotIn("globals", payload)
        self.assertNotIn("groups", payload)

    def test_vault_usage_is_derived_from_employee_release_and_pipeline(self):
        imported = self._import_credential_package()
        app_secrets.set_secret("SERVICE_TOKEN", "top-secret-value")
        core = app.core_controller().core
        employee_id = core.create_employee("Service user", {
            "role": "Use the service", "program": {
                "objective": "Use the service", "steps": [{
                    "id": "work", "instruction": "Run the service tool"}], "acceptance": []},
            "capabilities": [{"package_id": imported["package_id"],
                              "capability_id": "use-service"}],
            "runtime": {"channel": "codex", "model": "", "effort": "low"},
        })
        publish_verified_employee(core, employee_id)
        core.create_pipeline("Service line", {"positions": [{
            "key": "service", "name": "Service", "employee_id": employee_id}], "edges": []})

        credential = next(item for item in app.secret_vault_payload()["credentials"]
                          if item["name"] == "SERVICE_TOKEN")

        self.assertEqual(credential["used_by_count"], 1)
        self.assertEqual(credential["used_by"][0]["employee_name"], "Service user")
        self.assertEqual(credential["used_by_positions"][0]["pipeline_name"], "Service line")
        self.assertNotIn("top-secret-value", json.dumps(credential))




if __name__ == "__main__":
    unittest.main()
