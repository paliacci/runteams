# -*- coding: utf-8 -*-
"""End-to-end encryption for account-associated mobile host snapshots."""
import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
ENVELOPE_VERSION = 1
ALGORITHM = "AES-256-GCM"


class MobileCryptoError(Exception):
    pass


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(value):
    raw = (value or "").encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def host_snapshot_associated_data(host_id, schema_version, snapshot_version):
    return "runteams-host-envelope-v1|{}|{}|{}".format(
        host_id, schema_version, snapshot_version
    ).encode("utf-8")


def encrypt_host_snapshot(host, snapshot, nonce=None, generated_at=None):
    nonce = nonce if nonce is not None else os.urandom(12)
    if len(nonce) != 12:
        raise ValueError("AES-GCM nonce must contain 12 bytes")
    plaintext = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    aad = host_snapshot_associated_data(
        host["host_id"], snapshot["schema_version"], snapshot["snapshot_version"]
    )
    sealed = AESGCM(_unb64url(host["snapshot_key"])).encrypt(nonce, plaintext, aad)
    return {
        "envelope_version": ENVELOPE_VERSION,
        "algorithm": ALGORITHM,
        "host_id": host["host_id"],
        "schema_version": snapshot["schema_version"],
        "snapshot_version": snapshot["snapshot_version"],
        "nonce": _b64url(nonce),
        "ciphertext": _b64url(sealed),
        "generated_at": generated_at or snapshot["synced_at"],
    }


def live_activity_item_associated_data(host_id, item_ref, snapshot_version):
    return "runteams-live-item-v1|{}|{}|{}".format(
        host_id, item_ref, int(snapshot_version)
    ).encode("utf-8")


def encrypt_live_activity_item(host, item_ref, snapshot_version, item, nonce=None):
    """Encrypt one compact Live Activity row without exposing its labels to Relay/APNs."""
    nonce = nonce if nonce is not None else os.urandom(12)
    if len(nonce) != 12:
        raise ValueError("AES-GCM nonce must contain 12 bytes")
    plaintext = json.dumps(
        item, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    sealed = AESGCM(_unb64url(host["snapshot_key"])).encrypt(
        nonce,
        plaintext,
        live_activity_item_associated_data(host["host_id"], item_ref, snapshot_version),
    )
    return {
        "ref": item_ref,
        "snapshot_version": int(snapshot_version),
        "nonce": _b64url(nonce),
        "ciphertext": _b64url(sealed),
    }

def decrypt_live_activity_item(host, item):
    try:
        plaintext = AESGCM(_unb64url(host["snapshot_key"])).decrypt(
            _unb64url(item["nonce"]),
            _unb64url(item["ciphertext"]),
            live_activity_item_associated_data(
                host["host_id"], item["ref"], item["snapshot_version"]
            ),
        )
        return json.loads(plaintext.decode("utf-8"))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MobileCryptoError("实时活动摘要认证失败") from exc


def host_key_wrap_associated_data(host_id, device_id):
    return "runteams-host-key-wrap-v1|{}|{}".format(host_id, device_id).encode("utf-8")


def wrap_host_snapshot_key(host, device_id, device_public_key, nonce=None, ephemeral_key=None):
    """Seal a host snapshot key to one iOS P-256 key-agreement public key."""
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), _unb64url(device_public_key)
        )
    except (ValueError, TypeError) as exc:
        raise MobileCryptoError("设备公钥无效") from exc
    ephemeral_key = ephemeral_key or ec.generate_private_key(ec.SECP256R1())
    shared_secret = ephemeral_key.exchange(ec.ECDH(), public_key)
    wrapping_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=host["host_id"].encode("utf-8"),
        info=b"runteams-host-key-wrap-v1",
    ).derive(shared_secret)
    nonce = nonce if nonce is not None else os.urandom(12)
    if len(nonce) != 12:
        raise ValueError("AES-GCM nonce must contain 12 bytes")
    sealed = AESGCM(wrapping_key).encrypt(
        nonce,
        _unb64url(host["snapshot_key"]),
        host_key_wrap_associated_data(host["host_id"], device_id),
    )
    ephemeral_public = ephemeral_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {
        "envelope_version": 1,
        "algorithm": "P256-HKDF-SHA256-AES-256-GCM",
        "host_id": host["host_id"],
        "device_id": device_id,
        "ephemeral_public_key": _b64url(ephemeral_public),
        "nonce": _b64url(nonce),
        "ciphertext": _b64url(sealed),
    }
