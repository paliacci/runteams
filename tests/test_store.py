# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import local_database
import product_store


class ProductStoreBoundaryTests(unittest.TestCase):
    def test_fresh_product_database_contains_only_shell_automation_and_mobile_tables(self):
        tmp = tempfile.TemporaryDirectory(prefix="runteams-product-store-")
        old_db = local_database.DB_PATH
        try:
            local_database.DB_PATH = os.path.join(tmp.name, "runteams.db")
            product_store.init_product_db()
            product_store.init_product_db()
            with product_store.conn() as connection:
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertEqual(tables - {"sqlite_sequence"}, {
                "app_state",
                "credential_entries",
                "model_channels",
                "chats",
                "chat_messages",
                "mobile_host_sync",
                "mobile_host_retirements",
                "mobile_command_receipts",
                "mobile_command_result_outbox",
                "automations",
                "automation_runs",
                "automation_run_events",
            })
        finally:
            local_database.DB_PATH = old_db
            tmp.cleanup()





if __name__ == "__main__":
    unittest.main()
