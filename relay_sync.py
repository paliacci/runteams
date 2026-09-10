# -*- coding: utf-8 -*-
"""Best-effort outbound synchronization to the opaque mobile relay."""
import hashlib
import http.client
import json
import os
import threading
import time
from urllib.parse import quote, urlparse

import account_auth
import mobile_commands
import mobile_crypto
import mobile_projection
import product_store as store

DEFAULT_RELAY_URL = "https://api.richrabbits.com"
COMMAND_LONG_POLL_SECONDS = 20
COMMAND_RECOVERY_POLL_SECONDS = 2
ENTITLEMENT_CACHE_SECONDS = 60

_entitlement_cache_lock = threading.Lock()
_entitlement_cache = {"token": "", "fetched_at": 0.0, "value": None}


class RelaySyncError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def relay_url():
    return (os.environ.get("RUNTEAMS_RELAY_URL") or DEFAULT_RELAY_URL).strip().rstrip("/")


def account_access_token():
    """Supabase user access token used by the production account boundary."""
    configured = os.environ.get("RUNTEAMS_ACCOUNT_ACCESS_TOKEN") or ""
    if configured:
        return configured
    try:
        return account_auth.access_token() or ""
    except account_auth.AuthError:
        # Account/cloud availability must never interrupt local pipeline work.
        return ""


def account_entitlements(access_token=None, force=False):
    """Return the last good provider-independent entitlement contract.

    Cloud failure must not block local execution. A successful value remains a
    stale-safe display cache; callers receive ``None`` only before the first
    successful fetch for the current account token.
    """
    token = access_token if access_token is not None else account_access_token()
    if not token:
        return None
    now = time.monotonic()
    with _entitlement_cache_lock:
        same_token = _entitlement_cache["token"] == token
        if (not force and same_token and _entitlement_cache["value"] is not None
                and now - _entitlement_cache["fetched_at"] < ENTITLEMENT_CACHE_SECONDS):
            return dict(_entitlement_cache["value"])
    try:
        result = _request("GET", "/v1/account/entitlements", token=token)
        if not isinstance(result, dict) or not isinstance(result.get("features"), dict):
            raise RelaySyncError("权益服务返回了无效响应")
    except RelaySyncError:
        with _entitlement_cache_lock:
            if _entitlement_cache["token"] == token and _entitlement_cache["value"] is not None:
                return dict(_entitlement_cache["value"])
        return None
    with _entitlement_cache_lock:
        _entitlement_cache.update({"token": token, "fetched_at": now, "value": dict(result)})
    return dict(result)


def enrich_account(account, access_token=None):
    result = dict(account or {})
    if not result.get("signed_in") or result.get("debug_local"):
        return result
    entitlements = account_entitlements(access_token=access_token)
    if entitlements:
        result["entitlements"] = entitlements
        result["plan"] = entitlements.get("display_name") or result.get("plan") or "Free"
    return result


def billing_request(method, path):
    """Proxy an authenticated billing request without exposing the account token to Web UI."""
    token = account_access_token()
    if not token:
        raise RelaySyncError("请先登录 RunTeams 账号", 401)
    if path not in {
        "/v1/billing/status",
        "/v1/billing/checkout-session",
        "/v1/billing/portal-session",
    }:
        raise RelaySyncError("不支持的账单操作", 400)
    return _request(method, path, {} if method == "POST" else None, token=token, timeout=15)


def feedback_request(feedback):
    """Send product feedback without exposing the account token to the browser."""
    payload = {
        key: str((feedback or {}).get(key) or "")
        for key in ("message", "page", "app_version", "platform")
    }
    return _request(
        "POST", "/v1/feedback", payload, token=account_access_token(), timeout=15
    )


def _validate_url(value):
    parsed = urlparse(value)
    local = (parsed.hostname or "").lower() in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RelaySyncError("中转服务地址无效")
    if parsed.scheme != "https" and not local:
        raise RelaySyncError("公网中转服务必须使用 HTTPS")
    return parsed


def _request(method, path, body=None, token="", timeout=8):
    base = relay_url()
    if not base:
        raise RelaySyncError("中转服务尚未配置")
    parsed = _validate_url(base)
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection = connection_type(parsed.hostname, port, timeout=timeout)
    prefix = (parsed.path or "").rstrip("/")
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(payload))
    try:
        connection.request(method, prefix + path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
    except OSError as exc:
        raise RelaySyncError("无法连接中转服务：{}".format(str(exc)[:180])) from exc
    finally:
        connection.close()
    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        result = {}
    if not 200 <= response.status < 300:
        raise RelaySyncError(result.get("error") or "中转请求失败（{}）".format(response.status), response.status)
    return result


def _send_account_live_activity_events(host, events, snapshot_version):
    sent = 0
    for event in events:
        target_ref = mobile_projection.notification_target_ref(
            host["host_id"], "live", event["object_id"]
        )
        sealed_items = []
        for item in event.get("items") or []:
            item_ref = mobile_projection.notification_target_ref(
                host["host_id"], "live-item", item["object_id"]
            )
            if item.get("kind") == "position":
                plaintext = {
                    "kind": "position",
                    "pipeline": item["pipeline_name"],
                    "position": item["position_name"],
                    "count": int(item["task_count"]),
                }
            else:
                plaintext = {"kind": "terminal"}
            sealed = mobile_crypto.encrypt_live_activity_item(
                host,
                item_ref,
                snapshot_version,
                plaintext,
            )
            sealed.update({
                "status": item["status"],
                "updated_at": int(item["updated_at"]),
            })
            sealed_items.append(sealed)
        identity = "{}|live|{}|{}|{}".format(
            host["host_id"], event["operation"], target_ref, snapshot_version
        )
        _request(
            "POST",
            "/v1/relay/hosts/{}/live-activity-events".format(host["host_id"]),
            {
                "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                "operation": event["operation"],
                "status": event["status"],
                "snapshot_version": int(snapshot_version),
                "target_ref": target_ref,
                "started_at": int(event["started_at"]),
                "active_count": int(event.get("active_count") or 0),
                "items": sealed_items,
            },
            host["writer_token"],
        )
        sent += 1
    return sent


def status():
    token = account_access_token()
    host = store.get_mobile_host_sync()
    pending = store.pending_mobile_host_retirements()
    if token:
        account_id = str((account_auth.session() or {}).get("user_id") or "")
        if host and host.get("account_id") != account_id:
            host = None
        return {
            "configured": bool(relay_url()),
            "relay_url": relay_url(),
            "auth_mode": "account",
            "active_devices": int((host or {}).get("relay_device_count") or 0),
            "synced_devices": (
                int((host or {}).get("relay_device_count") or 0)
                if host and host.get("relay_last_synced_at") and not host.get("relay_last_error") else 0
            ),
            "pending_revocations": len(pending),
            "last_synced_at": (host or {}).get("relay_last_synced_at") or "",
            "has_errors": bool((host or {}).get("relay_last_error") or pending),
        }
    return {
        "configured": False,
        "relay_url": relay_url(),
        "auth_mode": "",
        "active_devices": 0,
        "synced_devices": 0,
        "pending_revocations": len(pending),
        "last_synced_at": "",
        "has_errors": bool(pending),
    }


def mobile_devices():
    """Return only user-facing device metadata; key material never reaches the Web UI."""
    token = account_access_token()
    session = account_auth.session() or {}
    host = store.get_mobile_host_sync()
    if not token or not host or host.get("account_id") != str(session.get("user_id") or ""):
        return []
    rows = _request(
        "GET",
        "/v1/relay/hosts/{}/mobile-devices".format(host["host_id"]),
        token=host["writer_token"],
    )
    if not isinstance(rows, list):
        raise RelaySyncError("中转服务返回了无效的设备列表")
    return [
        {
            "device_id": str(row.get("device_id") or ""),
            "display_name": str(row.get("display_name") or "").strip()[:80],
            "created_at": row.get("created_at") or "",
            "last_seen_at": row.get("last_seen_at") or "",
            "ready": bool(row.get("has_key")),
        }
        for row in rows if row.get("device_id")
    ]


def revoke_mobile_device(device_id):
    token = account_access_token()
    if not token:
        raise RelaySyncError("请先登录", 401)
    device_id = str(device_id or "").strip()
    if not device_id:
        raise RelaySyncError("设备不存在", 400)
    result = _request(
        "DELETE",
        "/v1/mobile/account-devices/{}".format(quote(device_id, safe="")),
        token=token,
    )
    return result if isinstance(result, dict) else {"revoked": True}


def sync_pending_host_retirements():
    errors = []
    revoked = 0
    for pending in store.pending_mobile_host_retirements():
        try:
            _request(
                "DELETE", "/v1/relay/hosts/{}".format(pending["host_id"]),
                token=pending["writer_token"],
            )
            store.mark_mobile_host_retired(pending["host_id"])
            revoked += 1
        except RelaySyncError as exc:
            if exc.status == 404:
                store.mark_mobile_host_retired(pending["host_id"])
                revoked += 1
            else:
                store.mark_mobile_host_retirement_error(pending["host_id"], str(exc))
                errors.append({"host_id": pending["host_id"], "error": str(exc)})
    return revoked, errors


def retire_account_host():
    # Queue only. The worker deletes remote ciphertext after the logout response,
    # so a slow or offline relay never makes signing out feel stuck.
    return bool(store.retire_mobile_host_sync())


def sync_all(app_version="开发版"):
    if not relay_url():
        return {"configured": False, "synced": 0, "unchanged": 0, "pushed": 0,
                "failed": 0, "revoked": 0, "errors": []}
    revoked, retirement_errors = sync_pending_host_retirements()
    if not account_access_token():
        return {"configured": False, "synced": 0, "unchanged": 0, "pushed": 0,
                "failed": len(retirement_errors), "revoked": revoked, "errors": retirement_errors}
    result = _sync_account_host(app_version)
    result["revoked"] = revoked
    result["errors"] = retirement_errors + result.get("errors", [])
    result["failed"] = len(result["errors"])
    return result


def _sync_account_host(app_version):
    """Publish one encrypted host snapshot to every phone on the same account."""
    token = account_access_token()
    account = dict(account_auth.session() or {})
    account_id = str(account.get("user_id") or "")
    if not account_id:
        raise RelaySyncError("登录会话缺少账号标识", 401)
    host = store.get_or_create_mobile_host_sync(account_id)
    try:
        _request(
            "POST",
            "/v1/relay/hosts",
            {
                "host_id": host["host_id"],
                "writer_token_hash": hashlib.sha256(
                    host["writer_token"].encode("utf-8")
                ).hexdigest(),
            },
            token,
        )
        entitlements = account_entitlements(access_token=token)
        if entitlements:
            account["entitlements"] = entitlements
            account["plan"] = entitlements.get("display_name") or account.get("plan") or "Free"
        mobile_app_enabled = bool(
            ((account.get("entitlements") or {}).get("features") or {}).get(
                "mobile.app", True
            )
        )
        if not mobile_app_enabled:
            store.mark_mobile_host_registered(0)
            return {
                "configured": True, "synced": 0, "unchanged": 0, "pushed": 0,
                "failed": 0, "revoked": 0, "errors": [], "entitled": False,
            }
        devices = _request(
            "GET",
            "/v1/relay/hosts/{}/mobile-devices".format(host["host_id"]),
            token=host["writer_token"],
        )
        if not isinstance(devices, list):
            raise RelaySyncError("中转服务返回了无效的设备列表")
        for device in devices:
            if device.get("has_key"):
                continue
            wrapped = mobile_crypto.wrap_host_snapshot_key(
                host,
                device["device_id"],
                device["key_agreement_public_key"],
            )
            _request(
                "PUT",
                "/v1/relay/hosts/{}/mobile-devices/{}/key".format(
                    host["host_id"], device["device_id"]
                ),
                wrapped,
                host["writer_token"],
            )
        store.mark_mobile_host_registered(len(devices))
        if not devices:
            return {
                "configured": True, "synced": 0, "unchanged": 0, "pushed": 0,
                "failed": 0, "revoked": 0, "errors": [],
            }

        next_version = max(
            int(time.time() * 1000), int(host.get("relay_last_snapshot_version") or 0) + 1
        )
        live_activity_enabled = bool(
            ((account.get("entitlements") or {}).get("features") or {}).get(
                "mobile.live_activity", True
            )
        )
        snapshot = mobile_projection.build_dashboard_snapshot(
            app_version=app_version,
            snapshot_version=next_version,
            account=account,
        )
        snapshot_hash = mobile_projection.snapshot_content_hash(snapshot)
        push_state = mobile_projection.build_push_state(snapshot)
        previous_push_state = host.get("relay_push_state_json") or ""
        same_snapshot = (
            host.get("relay_last_snapshot_hash") == snapshot_hash
            and host.get("relay_last_synced_at")
            and not host.get("relay_last_error")
        )
        if same_snapshot:
            live_events = (
                mobile_projection.new_live_activity_events(
                    previous_push_state, push_state, snapshot
                ) if live_activity_enabled else []
            )
            pushed = _send_account_live_activity_events(
                host,
                live_events,
                int(host.get("relay_last_snapshot_version") or next_version),
            )
            encoded_state = mobile_projection.encode_push_state(push_state)
            if previous_push_state != encoded_state:
                store.mark_mobile_host_push_state(encoded_state)
            return {
                "configured": True, "synced": 0, "unchanged": 1, "pushed": pushed,
                "failed": 0, "revoked": 0, "errors": [],
            }
        envelope = mobile_crypto.encrypt_host_snapshot(host, snapshot)
        _request(
            "PUT",
            "/v1/relay/hosts/{}/snapshot".format(host["host_id"]),
            envelope,
            host["writer_token"],
        )
        events = mobile_projection.new_push_events(
            previous_push_state, push_state
        )
        live_events = (
            mobile_projection.new_live_activity_events(
                previous_push_state, push_state, snapshot
            ) if live_activity_enabled else []
        )
        pushed = 0
        for event in events:
            identity = "{}|{}|{}".format(
                host["host_id"], event["kind"], ",".join(event["object_ids"])
            )
            _request(
                "POST",
                "/v1/relay/hosts/{}/push-events".format(host["host_id"]),
                {
                    "event_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "kind": event["kind"],
                    "snapshot_version": int(envelope["snapshot_version"]),
                    "target_ref": mobile_projection.notification_target_ref(
                        host["host_id"], event["kind"], event["object_ids"][-1]
                    ),
                },
                host["writer_token"],
            )
            pushed += 1
        pushed += _send_account_live_activity_events(
            host, live_events, envelope["snapshot_version"]
        )
        store.mark_mobile_host_push_state(mobile_projection.encode_push_state(push_state))
        store.mark_mobile_host_synced(envelope["snapshot_version"], snapshot_hash, len(devices))
        return {
            "configured": True, "synced": 1, "unchanged": 0, "pushed": pushed,
            "failed": 0, "revoked": 0, "errors": [],
        }
    except (RelaySyncError, mobile_crypto.MobileCryptoError) as exc:
        store.mark_mobile_host_relay_error(str(exc))
        return {
            "configured": True, "synced": 0, "unchanged": 0, "pushed": 0,
            "failed": 1, "revoked": 0,
            "errors": [{"host_id": host["host_id"], "error": str(exc)}],
        }


def _upload_command_results(host):
    uploaded = 0
    for pending in store.pending_mobile_command_results():
        result = pending["result"]
        _request(
            "PUT",
            "/v1/relay/hosts/{}/commands/{}/result".format(
                host["host_id"], pending["command_id"]
            ),
            result,
            host["writer_token"],
        )
        store.mark_mobile_command_result_uploaded(pending["command_id"])
        uploaded += 1
    return uploaded


def _sync_account_commands(command_handler, wait_seconds=0):
    """Claim opaque commands, execute once locally, and durably upload E2EE receipts."""
    if command_handler is None or not account_access_token():
        return 0
    account_id = str((account_auth.session() or {}).get("user_id") or "")
    if not account_id:
        return 0
    host = store.get_or_create_mobile_host_sync(account_id)
    uploaded_before = _upload_command_results(host)
    if uploaded_before:
        return uploaded_before
    wait_seconds = max(0, min(25, int(wait_seconds or 0)))
    commands = _request(
        "GET", "/v1/relay/hosts/{}/commands?limit=20&wait_seconds={}".format(
            host["host_id"], wait_seconds
        ),
        token=host["writer_token"], timeout=max(8, wait_seconds + 5),
    )
    if not isinstance(commands, list):
        raise RelaySyncError("中转服务返回了无效的指令列表")
    processed = 0
    for command in commands:
        signing_key = command.pop("signing_public_key", "")
        try:
            result = mobile_commands.process(command, signing_key, host, command_handler)
        except mobile_commands.CommandRejected as exc:
            result = mobile_commands.reject(command, host, str(exc))
        store.queue_mobile_command_result(command["command_id"], result)
        processed += 1
    uploaded_after = _upload_command_results(host)
    return max(uploaded_before, processed, uploaded_after)


class RelaySyncWorker:
    def __init__(self, app_version="开发版", interval_seconds=30):
        self.app_version = app_version
        self.interval_seconds = max(5, int(interval_seconds))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._command_handler = None

    def set_command_handler(self, handler):
        self._command_handler = handler

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="runteams-relay-sync", daemon=True)
        self._thread.start()

    def wake(self):
        self._wake.set()

    def sync_now(self):
        with self._lock:
            return sync_all(self.app_version)

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        self._wake.set()
        next_full_sync = 0
        while not self._stop.is_set():
            try:
                explicitly_woken = self._wake.is_set()
                self._wake.clear()
                now = time.monotonic()
                if explicitly_woken or not next_full_sync or now >= next_full_sync:
                    self.sync_now()
                    next_full_sync = time.monotonic() + self.interval_seconds
                    continue
                if self._command_handler is None or not account_access_token():
                    self._wake.wait(min(
                        COMMAND_RECOVERY_POLL_SECONDS,
                        max(0, next_full_sync - time.monotonic()),
                    ))
                    continue
                wait_seconds = min(
                    COMMAND_LONG_POLL_SECONDS,
                    max(1, int(next_full_sync - time.monotonic())),
                )
                with self._lock:
                    completed = _sync_account_commands(
                        self._command_handler, wait_seconds=wait_seconds
                    )
                if completed:
                    self.sync_now()
                    next_full_sync = time.monotonic() + self.interval_seconds
            except Exception:
                # Remote availability must never affect local pipeline execution.
                self._wake.wait(COMMAND_RECOVERY_POLL_SECONDS)
