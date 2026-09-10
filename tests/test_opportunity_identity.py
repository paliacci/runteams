import json
import sqlite3
import tempfile
import unittest

from runteams_core import RunTeamsCore


class OpportunityIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-opportunity-")
        self.core = RunTeamsCore(self.tmp.name)
        self.employee_id = self.core.create_employee("分析员", {
            "role": "分析机会",
            "program": {"objective": "分析", "steps": [{"id": "s", "instruction": "分析"}],
                        "acceptance": ["完成"]},
            "capabilities": [],
            "runtime": {"channel": "codex", "model": "test", "effort": "high"},
        })
        self.pipeline_id = self.core.create_pipeline("研发", {
            "positions": [{"key": "p", "employee_id": self.employee_id}], "edges": [],
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_is_atomic_and_scoped_by_owner(self):
        payload = {"objective": "分析", "context": {"opportunity_key": "same-key"}}
        first = self.core.create_employee_task(self.employee_id, "第一次", payload)
        second = self.core.create_employee_task(self.employee_id, "重复", payload)
        self.assertEqual(first, second)
        # The same opportunity intentionally has one analysis record and one
        # downstream development record, each with its own owner scope.
        downstream = self.core.create_task(self.pipeline_id, "研发", payload)
        self.assertNotEqual(first, downstream)
        catalog = self.core.opportunity_catalog()
        self.assertEqual([item["opportunity_key"] for item in catalog], ["same-key"])
        self.assertEqual(len(catalog[0]["related_workflows"]), 2)

    def test_registry_is_unpaginated_and_missing_query_is_full_history(self):
        for i in range(520):
            self.core.create_employee_task(self.employee_id, "机会 {}".format(i), {
                "objective": "分析", "context": {"opportunity_key": "key-{}".format(i)},
            })
        registry = self.core.opportunity_identity_catalog("employee", self.employee_id)
        self.assertEqual(len(registry), 520)
        missing = self.core.opportunity_keys_missing_in_pipeline(
            self.employee_id, self.pipeline_id)
        self.assertEqual(len(missing), 520)
        self.assertEqual(missing[-1]["opportunity_key"], "key-519")

    def test_result_catalog_projects_structured_opportunity_without_new_table(self):
        task_id = self.core.create_employee_task(self.employee_id, "Jira 通知治理", {
            "objective": "分析 Jira 通知治理机会",
            "context": {
                "opportunity_key": "jira-notification-governance",
                "product": "jira",
                "marketplace_keyword": "notification",
                "target_user": "Jira 管理员",
                "jtbd": "识别通知盲区",
                "problem": "通知配置难以审计",
                "analysis_decision": "continue",
                "decision_reason": "需求和技术可行性通过",
                "evidence": [{"title": "官方文档", "url": "https://example.com"}],
            },
        })
        items = self.core.opportunity_catalog()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["task_id"], task_id)
        self.assertEqual(item["opportunity_key"], "jira-notification-governance")
        self.assertEqual(item["analysis_decision"], "continue")
        self.assertEqual(item["evidence_count"], 1)
        self.assertEqual(item["source_urls"], ["https://example.com"])
        self.assertEqual(item["documents"], [])
        self.assertIsNone(item.get("output"))
        detail = self.core.opportunity_detail("jira-notification-governance")
        self.assertEqual(detail["opportunity_key"], item["opportunity_key"])
        self.assertEqual(detail["output"], {})

    def test_result_catalog_applies_limit_after_full_query_filter(self):
        """A view limit must not stop the ledger scan before an older match."""
        for key, title in (("old-match", "目标机会"), ("new-no-match", "其他记录"),
                           ("newest-no-match", "最新记录")):
            self.core.create_employee_task(self.employee_id, title, {
                "objective": "分析", "context": {
                    "opportunity_key": key,
                    "problem": "目标问题" if key == "old-match" else "无关问题",
                },
            })
        items = self.core.opportunity_catalog(query="目标问题", limit=1)
        self.assertEqual([item["opportunity_key"] for item in items], ["old-match"])

    def test_result_catalog_scans_large_ledgers_in_sqlite_safe_chunks(self):
        """Full-history reads remain valid beyond SQLite's bind-variable limit."""
        now = "2026-09-01T00:00:00+00:00"
        with self.core.repository.connect() as connection:
            task_ids = []
            for index in range(1001):
                task_ids.append(connection.execute(
                    "INSERT INTO tasks(pipeline_id,employee_id,opportunity_key,title,"
                    "payload_json,state,created_at,updated_at) VALUES(NULL,?,?,?,?,?,?,?)",
                    (self.employee_id, "large-key-{}".format(index),
                     "机会 {}".format(index), json.dumps({
                         "objective": "分析", "context": {
                             "opportunity_key": "large-key-{}".format(index),
                         },
                     }, ensure_ascii=False), "ready", now, now),
                ).lastrowid)
            connection.executemany(
                "INSERT INTO workflow_runs(task_id,state,snapshot_json,created_at,updated_at) "
                "VALUES(?,?,?, ?, ?)",
                [(task_id, "ready", "{}", now, now) for task_id in task_ids],
            )
        items = self.core.opportunity_catalog(limit=0)
        self.assertEqual(len(items), 1001)

    def test_migration_keeps_ten_tables_and_adds_unique_indexes(self):
        db = sqlite3.connect(self.tmp.name + "/runteams.db")
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(len(tables), 10)
        indexes = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%opportunity%'")}
        self.assertEqual(indexes, {"idx_tasks_employee_opportunity",
                                  "idx_tasks_pipeline_opportunity"})


if __name__ == "__main__":
    unittest.main()
