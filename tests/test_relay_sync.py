import os
import tempfile
import unittest
from unittest import mock

import relay_sync
import local_database
import product_store as store


class AccountRelayLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-relay-sync-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "test.db")
        store.init_product_db()

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_retirement_is_durable_when_relay_is_offline(self):
        old = store.get_or_create_mobile_host_sync("account-a")
        self.assertTrue(relay_sync.retire_account_host())
        self.assertIsNone(store.get_mobile_host_sync())
        pending = store.pending_mobile_host_retirements()
        self.assertEqual(pending[0]["host_id"], old["host_id"])
        self.assertEqual(pending[0]["last_error"], "")

    def test_pending_retirement_deletes_old_host_and_clears_queue(self):
        old = store.get_or_create_mobile_host_sync("account-a")
        store.retire_mobile_host_sync()
        calls = []

        def request(method, path, body=None, token="", timeout=8):
            calls.append((method, path, token))
            return {"deleted": True}

        with mock.patch.object(relay_sync, "_request", side_effect=request):
            revoked, errors = relay_sync.sync_pending_host_retirements()
        self.assertEqual((revoked, errors), (1, []))
        self.assertEqual(calls, [(
            "DELETE", "/v1/relay/hosts/{}".format(old["host_id"]), old["writer_token"]
        )])
        self.assertEqual(store.pending_mobile_host_retirements(), [])

    def test_failed_remote_delete_stays_queued_for_retry(self):
        old = store.get_or_create_mobile_host_sync("account-a")
        store.retire_mobile_host_sync()
        with mock.patch.object(
            relay_sync, "_request", side_effect=relay_sync.RelaySyncError("offline")
        ):
            revoked, errors = relay_sync.sync_pending_host_retirements()
        self.assertEqual(revoked, 0)
        self.assertEqual(errors[0]["host_id"], old["host_id"])
        pending = store.pending_mobile_host_retirements()
        self.assertEqual(pending[0]["last_error"], "offline")

    def test_new_account_never_reuses_previous_host(self):
        first = store.get_or_create_mobile_host_sync("account-a")
        second = store.get_or_create_mobile_host_sync("account-b")
        self.assertNotEqual(first["host_id"], second["host_id"])
        self.assertEqual(second["account_id"], "account-b")

    def test_mobile_device_list_exposes_metadata_without_public_keys(self):
        host = store.get_or_create_mobile_host_sync("account-a")
        remote = [{
            "device_id": "device-a", "display_name": "工作 iPhone",
            "created_at": "2026-08-01T00:00:00Z",
            "last_seen_at": "2026-08-02T00:00:00Z", "has_key": True,
            "key_agreement_public_key": "must-not-reach-web",
            "signing_public_key": "must-not-reach-web",
        }]
        with mock.patch.object(relay_sync, "account_access_token", return_value="account-token"), \
             mock.patch.object(relay_sync.account_auth, "session", return_value={"user_id": "account-a"}), \
             mock.patch.object(relay_sync, "_request", return_value=remote) as request:
            devices = relay_sync.mobile_devices()
        self.assertEqual(devices, [{
            "device_id": "device-a", "display_name": "工作 iPhone",
            "created_at": "2026-08-01T00:00:00Z",
            "last_seen_at": "2026-08-02T00:00:00Z", "ready": True,
        }])
        request.assert_called_once_with(
            "GET", "/v1/relay/hosts/{}/mobile-devices".format(host["host_id"]),
            token=host["writer_token"],
        )

    def test_revoke_mobile_device_uses_account_boundary(self):
        with mock.patch.object(relay_sync, "account_access_token", return_value="account-token"), \
             mock.patch.object(relay_sync, "_request", return_value={"revoked": True}) as request:
            result = relay_sync.revoke_mobile_device("device/a")
        self.assertTrue(result["revoked"])
        request.assert_called_once_with(
            "DELETE", "/v1/mobile/account-devices/device%2Fa", token="account-token"
        )


if __name__ == "__main__":
    unittest.main()
