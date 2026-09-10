# -*- coding: utf-8 -*-
"""End-to-end encrypted, signed mobile control commands.

The relay sees routing metadata and ciphertext only. The desktop verifies the
originating device signature, decrypts with its local host snapshot key, and
uses a durable local sequence ledger before invoking an allowlisted action.
"""
import base64
import datetime as dt
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import product_store as store


COMMAND_VERSION = 1
COMMAND_ALGORITHM = "AES-256-GCM+P256-SHA256"
RESULT_ALGORITHM = "AES-256-GCM"
MAX_CLOCK_SKEW_SECONDS = 120
MAX_LIFETIME_SECONDS = 300


class CommandError(Exception):
    pass


class CommandRejected(CommandError):
    pass


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(value):
    raw = (value or "").encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def _parse_time(value):
    try:
        parsed = dt.datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CommandRejected("指令时间无效") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommandRejected("指令时间缺少时区")
    return parsed.astimezone(dt.timezone.utc)


def command_associated_data(envelope):
    return "runteams-mobile-command-v1|{}|{}|{}|{}|{}|{}".format(
        envelope["command_id"], envelope["host_id"], envelope["device_id"],
        int(envelope["sequence"]), envelope["issued_at"], envelope["expires_at"],
    ).encode("utf-8")


def command_signature_data(envelope):
    return command_associated_data(envelope) + b"|" + envelope["nonce"].encode(
        "ascii"
    ) + b"|" + envelope["ciphertext"].encode("ascii")


def result_associated_data(command_id, host_id, device_id, status, completed_at):
    return "runteams-mobile-command-result-v1|{}|{}|{}|{}|{}".format(
        command_id, host_id, device_id, status, completed_at
    ).encode("utf-8")


def _validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) - {
        "schema_version", "action", "target_id", "action_id", "response"
    }:
        raise CommandRejected("指令内容无效")
    if payload.get("schema_version") != 1:
        raise CommandRejected("不支持的指令版本")
    action = payload.get("action")
    if action not in ("intervention.perform", "run.control"):
        raise CommandRejected("不支持的远程操作")
    target_id = payload.get("target_id")
    if not isinstance(target_id, str) or not 1 <= len(target_id) <= 128:
        raise CommandRejected("操作目标无效")
    action_id = payload.get("action_id")
    if not isinstance(action_id, str) or not 1 <= len(action_id) <= 120:
        raise CommandRejected("操作类型无效")
    response = payload.get("response")
    if response is not None and (not isinstance(response, str) or len(response) > 5000):
        raise CommandRejected("回复内容无效")
    if action == "run.control" and action_id != "cancel":
        raise CommandRejected("不支持的运行控制操作")
    return payload


def decrypt_and_verify(envelope, signing_public_key, host, now=None):
    if envelope.get("command_version") != COMMAND_VERSION:
        raise CommandRejected("不支持的指令版本")
    if envelope.get("algorithm") != COMMAND_ALGORITHM:
        raise CommandRejected("不支持的指令加密算法")
    if envelope.get("host_id") != host.get("host_id"):
        raise CommandRejected("指令目标电脑不匹配")
    issued = _parse_time(envelope.get("issued_at"))
    expires = _parse_time(envelope.get("expires_at"))
    current = now or dt.datetime.now(dt.timezone.utc)
    if issued > current + dt.timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise CommandRejected("指令签发时间异常")
    if expires <= current or expires <= issued:
        raise CommandRejected("指令已经过期")
    if (expires - issued).total_seconds() > MAX_LIFETIME_SECONDS:
        raise CommandRejected("指令有效期过长")
    try:
        public = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), _unb64url(signing_public_key)
        )
        public.verify(
            _unb64url(envelope["signature"]),
            command_signature_data(envelope),
            ec.ECDSA(hashes.SHA256()),
        )
    except (ValueError, TypeError, KeyError, InvalidSignature) as exc:
        raise CommandRejected("设备签名验证失败") from exc
    try:
        nonce = _unb64url(envelope["nonce"])
        if len(nonce) != 12:
            raise ValueError("nonce")
        plaintext = AESGCM(_unb64url(host["snapshot_key"])).decrypt(
            nonce, _unb64url(envelope["ciphertext"]), command_associated_data(envelope)
        )
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise CommandRejected("指令未通过完整性验证") from exc
    return _validate_payload(payload)


def encrypt_result(envelope, host, status, result, completed_at=None, nonce=None):
    completed_at = completed_at or dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    nonce = nonce if nonce is not None else os.urandom(12)
    plaintext = json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    sealed = AESGCM(_unb64url(host["snapshot_key"])).encrypt(
        nonce,
        plaintext,
        result_associated_data(
            envelope["command_id"], envelope["host_id"], envelope["device_id"],
            status, completed_at,
        ),
    )
    return {
        "command_id": envelope["command_id"],
        "host_id": envelope["host_id"],
        "device_id": envelope["device_id"],
        "status": status,
        "algorithm": RESULT_ALGORITHM,
        "completed_at": completed_at,
        "nonce": _b64url(nonce),
        "ciphertext": _b64url(sealed),
    }


def process(envelope, signing_public_key, host, executor, now=None):
    """Verify, replay-check, execute once, and return an encrypted receipt."""
    payload = decrypt_and_verify(envelope, signing_public_key, host, now=now)
    claimed = store.claim_mobile_command(
        envelope["command_id"], envelope["device_id"], int(envelope["sequence"]),
        envelope["issued_at"], envelope["expires_at"], payload["action"],
        payload["target_id"], payload["action_id"],
    )
    if claimed.get("existing"):
        if claimed.get("status") == "processing":
            raise CommandRejected("指令正在处理")
        result = claimed.get("result") or {"ok": False, "message": "指令状态无法恢复"}
        return encrypt_result(envelope, host, claimed["status"], result)
    if not claimed.get("claimed"):
        result = {"ok": False, "message": claimed.get("message") or "重复或过期的指令"}
        store.complete_mobile_command(envelope["command_id"], "rejected", result)
        return encrypt_result(envelope, host, "rejected", result)
    try:
        result = executor(payload, envelope["device_id"])
        if not isinstance(result, dict):
            result = {"ok": True, "message": "操作已完成"}
        result.setdefault("ok", True)
        result.setdefault("message", "操作已完成")
        status = "succeeded"
    except CommandRejected as exc:
        result = {"ok": False, "message": str(exc)[:240]}
        status = "rejected"
    except Exception:
        result = {"ok": False, "message": "电脑处理指令时发生内部错误"}
        status = "rejected"
    store.complete_mobile_command(envelope["command_id"], status, result)
    return encrypt_result(envelope, host, status, result)


def reject(envelope, host, message):
    result = {"ok": False, "message": (message or "指令已拒绝")[:240]}
    return encrypt_result(envelope, host, "rejected", result)
