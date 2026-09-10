# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import local_database
import product_store as store
from scripts import mobile_e2e_fixture


class MobileE2EFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-mobile-e2e-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "runteams.db")
        store.init_product_db()
        self.name = mobile_e2e_fixture.PIPELINE_PREFIX + "unit-test"

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_deterministic_mobile_lifecycle_and_cleanup(self):
        created = mobile_e2e_fixture.create(self.name)
        self.assertEqual(created["card_status"], "queued")
        self.assertEqual(created["record_count"], 0)

        queued = mobile_e2e_fixture.queue(self.name)
        self.assertEqual(queued["workflow_status"], "ready")

        running = mobile_e2e_fixture.running(self.name)
        self.assertEqual(running["card_status"], "running")
        self.assertEqual(running["record_count"], 1)

        handed_off = mobile_e2e_fixture.handoff(self.name)
        self.assertEqual(handed_off["column"], mobile_e2e_fixture.SECOND_POSITION)
        self.assertEqual(handed_off["record_count"], 1)

        reviewing = mobile_e2e_fixture.reviewing(self.name)
        self.assertEqual(reviewing["card_status"], "running")
        self.assertEqual(reviewing["record_count"], 2)

        completed = mobile_e2e_fixture.complete(self.name)
        self.assertEqual(completed["card_status"], "succeeded")
        self.assertEqual(completed["workflow_status"], "completed")
        self.assertEqual(completed["record_count"], 2)
        self.assertEqual(completed["artifact_count"], 1)

        self.assertTrue(mobile_e2e_fixture.cleanup(self.name)["removed"])
        with self.assertRaises(RuntimeError):
            mobile_e2e_fixture.describe(self.name)


if __name__ == "__main__":
    unittest.main()
