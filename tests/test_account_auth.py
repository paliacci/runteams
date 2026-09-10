# -*- coding: utf-8 -*-
import json
import unittest
from unittest import mock

import account_auth


class MemoryTokenStore:
    def __init__(self):
        self.value = ""
        self.writes = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.writes.append(value)

    def delete(self):
        self.value = ""


class FakeAuthClient:
    def __init__(self):
        self.requested = []
        self.verified = []
        self.refreshed = []
        self.logged_out = []

    @staticmethod
    def session(suffix="1"):
        return {
            "access_token": "access-secret-" + suffix,
            "refresh_token": "refresh-secret-" + suffix,
            "expires_in": 3600,
            "user": {
                "id": "user-123",
                "email": "owner@example.com",
                "user_metadata": {},
            },
        }

    def request_otp(self, email):
        self.requested.append(email)
        return {}

    def verify_otp(self, email, token):
        self.verified.append((email, token))
        return self.session("1")

    def refresh(self, token):
        self.refreshed.append(token)
        return self.session("2")

    def logout(self, token):
        self.logged_out.append(token)
        return {}


class AccountAuthTests(unittest.TestCase):
    def setUp(self):
        self.clock_value = 1000
        self.client = FakeAuthClient()
        self.store = MemoryTokenStore()
        self.manager = account_auth.AuthManager(
            client=self.client,
            token_store=self.store,
            clock=lambda: self.clock_value,
        )

    def test_request_otp_normalizes_email_without_storing_credentials(self):
        result = self.manager.request_otp(" Owner@Example.COM ")
        self.assertEqual(result, {"ok": True, "email": "owner@example.com"})
        self.assertEqual(self.client.requested, ["owner@example.com"])
        self.assertEqual(self.store.value, "")

    def test_verify_keeps_tokens_out_of_public_session(self):
        result = self.manager.verify_otp("owner@example.com", "123456")
        self.assertTrue(result["signed_in"])
        self.assertEqual(result["name"], "owner")
        self.assertEqual(self.store.value, "refresh-secret-1")
        serialized = json.dumps(result)
        self.assertNotIn("access-secret", serialized)
        self.assertNotIn("refresh-secret", serialized)
        self.assertNotIn("token", serialized)

    def test_access_token_refresh_rotates_keychain_credential(self):
        self.manager.verify_otp("owner@example.com", "123456")
        self.clock_value += 3601
        self.assertEqual(self.manager.access_token(), "access-secret-2")
        self.assertEqual(self.client.refreshed, ["refresh-secret-1"])
        self.assertEqual(self.store.value, "refresh-secret-2")

    def test_restart_recovers_session_from_refresh_token(self):
        self.store.value = "refresh-from-keychain"
        result = self.manager.session()
        self.assertTrue(result["signed_in"])
        self.assertEqual(self.client.refreshed, ["refresh-from-keychain"])

    def test_logout_clears_memory_and_keychain(self):
        self.manager.verify_otp("owner@example.com", "123456")
        result = self.manager.logout()
        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.client.logged_out, ["access-secret-1"])
        self.assertEqual(self.store.value, "")
        self.assertEqual(self.manager.session()["signed_in"], False)

    def test_invalid_email_and_otp_are_rejected_locally(self):
        with self.assertRaises(account_auth.AuthError):
            self.manager.request_otp("not-an-email")
        with self.assertRaises(account_auth.AuthError):
            self.manager.verify_otp("owner@example.com", "12345a")
        self.assertEqual(self.client.requested, [])
        self.assertEqual(self.client.verified, [])

    def test_packaged_network_encoding_failure_becomes_safe_auth_error(self):
        client = account_auth.SupabaseAuthClient(url="https://example.invalid", anon_key="public")
        with mock.patch("urllib.request.urlopen", side_effect=LookupError("unknown encoding: idna")):
            with self.assertRaisesRegex(account_auth.AuthError, "暂时无法连接登录服务"):
                client.request_otp("owner@example.com")

    @mock.patch("account_auth.sys.platform", "darwin")
    @mock.patch("account_auth.subprocess.run")
    def test_macos_keychain_uses_security_without_secret_in_argv(self, run):
        run.side_effect = [
            mock.Mock(returncode=0, stdout="saved-refresh-token\n", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
        ]
        store = account_auth.KeyringTokenStore()

        self.assertEqual(store.get(), "saved-refresh-token")
        store.set("new-refresh-token")
        store.delete()

        get_args = run.call_args_list[0].args[0]
        set_args = run.call_args_list[1].args[0]
        self.assertEqual(get_args[0], "/usr/bin/security")
        self.assertEqual(set_args[0], "/usr/bin/expect")
        self.assertIn("/usr/bin/security add-generic-password", set_args[2])
        self.assertNotIn("saved-refresh-token", get_args)
        self.assertNotIn("new-refresh-token", set_args)
        self.assertEqual(run.call_args_list[1].kwargs["input"],
                         "new-refresh-token\n")

    @mock.patch("account_auth.sys.platform", "darwin")
    @mock.patch("account_auth.subprocess.run")
    def test_macos_keychain_missing_item_is_signed_out_not_error(self, run):
        run.return_value = mock.Mock(returncode=44, stdout="", stderr="not found")
        self.assertEqual(account_auth.KeyringTokenStore().get(), "")

    def test_explicit_local_debug_identity_never_mints_cloud_token(self):
        manager = account_auth.AuthManager(
            client=self.client,
            token_store=self.store,
            clock=lambda: self.clock_value,
            debug_email="debug@runteams.local",
            debug_code="654321",
        )
        requested = manager.request_otp("debug@runteams.local")
        self.assertTrue(requested["debug_local"])
        self.assertEqual(self.client.requested, [])
        with self.assertRaisesRegex(account_auth.AuthError, "调试验证码无效"):
            manager.verify_otp("debug@runteams.local", "000000")
        session = manager.verify_otp("debug@runteams.local", "654321")
        self.assertTrue(session["debug_local"])
        self.assertEqual(session["plan"], "Debug")
        self.assertEqual(manager.access_token(), "")
        self.assertEqual(self.store.value, "")
        self.assertEqual(self.client.verified, [])
        manager.logout()
        self.assertFalse(manager.session()["signed_in"])


if __name__ == "__main__":
    unittest.main()
