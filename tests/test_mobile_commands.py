import base64
import datetime as dt
import json
import os
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import mobile_commands
import local_database
import product_store as store


def b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class MobileCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-mobile-commands-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "test.db")
        store.init_product_db()
        self.addCleanup(self._cleanup)
        self.host = {
            "host_id": "fedcba9876543210fedcba9876543210",
            "snapshot_key": b64url(bytes(range(32))),
        }
        self.device_id = "0123456789abcdef0123456789abcdef"
        self.signing_key = ec.derive_private_key(7, ec.SECP256R1())
        self.public_key = b64url(self.signing_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        ))

    def _cleanup(self):
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def envelope(self, sequence=1, command_id="a" * 64, payload=None):
        issued = dt.datetime(2026, 8, 3, 12, 0, tzinfo=dt.timezone.utc)
        expires = issued + dt.timedelta(minutes=2)
        value = {
            "command_version": 1,
            "algorithm": mobile_commands.COMMAND_ALGORITHM,
            "command_id": command_id,
            "host_id": self.host["host_id"],
            "device_id": self.device_id,
            "sequence": sequence,
            "issued_at": issued.isoformat().replace("+00:00", "Z"),
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
            "nonce": b64url(bytes(range(12))),
        }
        plaintext = json.dumps(payload or {
            "schema_version": 1,
            "action": "run.control",
            "target_id": "workflow:123",
            "action_id": "cancel",
        }, separators=(",", ":")).encode()
        value["ciphertext"] = b64url(AESGCM(bytes(range(32))).encrypt(
            bytes(range(12)), plaintext, mobile_commands.command_associated_data(value)
        ))
        value["signature"] = b64url(self.signing_key.sign(
            mobile_commands.command_signature_data(value), ec.ECDSA(hashes.SHA256())
        ))
        return value

    def test_signed_encrypted_command_executes_once_and_reuses_receipt(self):
        envelope = self.envelope()
        calls = []

        def execute(payload, device_id):
            calls.append((payload, device_id))
            return {"ok": True, "message": "已终止"}

        now = dt.datetime(2026, 8, 3, 12, 0, 30, tzinfo=dt.timezone.utc)
        first = mobile_commands.process(envelope, self.public_key, self.host, execute, now=now)
        second = mobile_commands.process(envelope, self.public_key, self.host, execute, now=now)

        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(second["status"], "succeeded")
        self.assertEqual(len(calls), 1)

    def test_tampering_fails_before_execution(self):
        envelope = self.envelope()
        envelope["ciphertext"] = ("A" if envelope["ciphertext"][0] != "A" else "B") + envelope["ciphertext"][1:]
        with self.assertRaisesRegex(mobile_commands.CommandRejected, "签名验证失败"):
            mobile_commands.process(
                envelope, self.public_key, self.host, lambda *_: self.fail("executed"),
                now=dt.datetime(2026, 8, 3, 12, 0, 30, tzinfo=dt.timezone.utc),
            )

    def test_lower_sequence_is_rejected_after_newer_command(self):
        now = dt.datetime(2026, 8, 3, 12, 0, 30, tzinfo=dt.timezone.utc)
        newer = self.envelope(sequence=2, command_id="b" * 64)
        older = self.envelope(sequence=1, command_id="c" * 64)
        mobile_commands.process(newer, self.public_key, self.host, lambda *_: {"ok": True}, now=now)

        result = mobile_commands.process(
            older, self.public_key, self.host, lambda *_: self.fail("replayed"), now=now
        )

        self.assertEqual(result["status"], "rejected")

    def test_expired_command_is_rejected(self):
        with self.assertRaisesRegex(mobile_commands.CommandRejected, "已经过期"):
            mobile_commands.decrypt_and_verify(
                self.envelope(), self.public_key, self.host,
                now=dt.datetime(2026, 8, 3, 12, 3, tzinfo=dt.timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
