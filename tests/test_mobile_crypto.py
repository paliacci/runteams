import os
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import mobile_crypto
import local_database
import product_store as store


class MobileHostCryptoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-mobile-host-")
        self.old_db = local_database.DB_PATH
        local_database.DB_PATH = os.path.join(self.tmp.name, "test.db")
        store.init_product_db()

    def tearDown(self):
        local_database.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_host_snapshot_key_wrap_round_trip(self):
        host = store.get_or_create_mobile_host_sync("account-a")
        device_id = "d" * 32
        device_private = ec.generate_private_key(ec.SECP256R1())
        public_key = mobile_crypto._b64url(device_private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        ))
        wrapped = mobile_crypto.wrap_host_snapshot_key(host, device_id, public_key)
        ephemeral = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), mobile_crypto._unb64url(wrapped["ephemeral_public_key"])
        )
        shared = device_private.exchange(ec.ECDH(), ephemeral)
        wrapping_key = HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=host["host_id"].encode(), info=b"runteams-host-key-wrap-v1",
        ).derive(shared)
        plaintext = AESGCM(wrapping_key).decrypt(
            mobile_crypto._unb64url(wrapped["nonce"]),
            mobile_crypto._unb64url(wrapped["ciphertext"]),
            mobile_crypto.host_key_wrap_associated_data(host["host_id"], device_id),
        )
        self.assertEqual(plaintext, mobile_crypto._unb64url(host["snapshot_key"]))

    def test_account_switch_rotates_host_without_touching_local_data(self):
        chat_id = store.create_chat()
        first = store.get_or_create_mobile_host_sync("account-a")
        second = store.get_or_create_mobile_host_sync("account-b")
        self.assertNotEqual(first["host_id"], second["host_id"])
        self.assertNotEqual(first["snapshot_key"], second["snapshot_key"])
        self.assertEqual(second["account_id"], "account-b")
        self.assertIsNotNone(store.get_chat(chat_id))
        self.assertEqual(
            [item["host_id"] for item in store.pending_mobile_host_retirements()],
            [first["host_id"]],
        )


if __name__ == "__main__":
    unittest.main()
