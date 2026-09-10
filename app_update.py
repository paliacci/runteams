# -*- coding: utf-8 -*-
"""Silent desktop update download and next-launch installation.

The release service is intentionally just one HTTPS-hosted JSON document.  The
running app downloads a newer, platform-specific artifact into its writable
data directory.  The desktop launcher applies it only before starting the local
server, so closing and reopening the window cannot interrupt a running task.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile


DEFAULT_MANIFEST_URL = "https://runteams.ai/updates/stable.json"
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _version_key(value):
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise UpdateError("更新清单包含无效版本号")
    major, minor, patch = (int(match.group(i)) for i in range(1, 4))
    # A stable release sorts after its own prerelease.  Build metadata does not
    # affect ordering; treating the suffix as a prerelease is conservative.
    suffix = match.group(4)
    return major, minor, patch, 1 if not suffix else 0, suffix or ""


def is_newer(candidate, current):
    return _version_key(candidate) > _version_key(current)


def target_key():
    machine = platform.machine().lower()
    architectures = {
        "arm64": "aarch64", "aarch64": "aarch64",
        "x86_64": "x86_64", "amd64": "x86_64",
    }
    architecture = architectures.get(machine, machine or "unknown")
    if sys.platform == "darwin":
        system = "darwin"
    elif os.name == "nt":
        system = "windows"
    else:
        system = "linux"
    return "{}-{}".format(system, architecture)


def update_dir(data_dir):
    return os.path.join(os.path.realpath(data_dir), "updates")


def pending_path(data_dir):
    return os.path.join(update_dir(data_dir), "pending.json")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _https_url(value, label):
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    allow_insecure = os.environ.get("RUNTEAMS_ALLOW_INSECURE_UPDATE_URL") == "1"
    if parsed.scheme != "https" and not (allow_insecure and parsed.scheme == "http"):
        raise UpdateError("{}必须使用 HTTPS".format(label))
    if not parsed.netloc:
        raise UpdateError("{}无效".format(label))
    return url


def _response_length(response):
    try:
        return int(response.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return 0


class UpdateManager:
    def __init__(self, current_version, data_dir, manifest_url=None, enabled=None):
        self.current_version = str(current_version)
        self.data_dir = os.path.realpath(data_dir)
        self.manifest_url = manifest_url or os.environ.get(
            "RUNTEAMS_UPDATE_MANIFEST_URL", DEFAULT_MANIFEST_URL)
        if enabled is None:
            enabled = bool(getattr(sys, "frozen", False))
        self.enabled = bool(enabled) and os.environ.get("RUNTEAMS_DISABLE_AUTO_UPDATE") != "1"
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {
            "state": "idle" if self.enabled else "disabled",
            "current_version": self.current_version,
            "target": target_key(),
        }

    def status(self):
        with self._lock:
            result = dict(self._status)
        pending = _read_json(pending_path(self.data_dir))
        if pending and os.path.isfile(str(pending.get("artifact_path") or "")):
            result.update(state="ready", available_version=pending.get("version"),
                          downloaded_at=pending.get("downloaded_at"))
        return result

    def _set_status(self, **changes):
        with self._lock:
            self._status.update(changes)

    def start(self):
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run, name="runteams-update", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def _run(self):
        try:
            self.check_now()
        except Exception as exc:
            self._set_status(state="error", error=str(exc)[:300], checked_at=_now())

    def _fetch_manifest(self):
        url = _https_url(self.manifest_url, "更新地址")
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "RunTeams/{}".format(
                self.current_version)})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise UpdateError("更新清单过大")
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise UpdateError("更新清单不是有效 JSON") from exc
        if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) != 1:
            raise UpdateError("更新清单版本不受支持")
        return manifest

    def check_now(self):
        if not self.enabled or self._stop.is_set():
            return self.status()
        self._set_status(state="checking", error="")
        manifest = self._fetch_manifest()
        version = str(manifest.get("version") or "")
        if not is_newer(version, self.current_version):
            self._set_status(state="current", checked_at=_now(), available_version=version)
            return self.status()
        platform_entry = (manifest.get("platforms") or {}).get(target_key())
        if not isinstance(platform_entry, dict):
            self._set_status(state="unavailable", checked_at=_now(), available_version=version)
            return self.status()
        return self._download(version, platform_entry)

    def _download(self, version, entry):
        url = _https_url(entry.get("url"), "更新资源地址")
        expected = str(entry.get("sha256") or "").lower()
        if not _SHA256_RE.fullmatch(expected):
            raise UpdateError("更新资源缺少有效 SHA-256")
        kind = str(entry.get("kind") or "")
        allowed_kinds = {"macos-app-zip", "windows-nsis", "windows-msi"}
        if kind not in allowed_kinds:
            raise UpdateError("更新资源格式不受支持")
        filename = os.path.basename(urllib.parse.urlparse(url).path) or "runteams-update"
        if filename in (".", "..") or not re.fullmatch(r"[0-9A-Za-z._+-]+", filename):
            raise UpdateError("更新资源文件名无效")
        directory = os.path.join(update_dir(self.data_dir), version)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        artifact = os.path.join(directory, filename)
        temporary = artifact + ".part"
        self._set_status(state="downloading", available_version=version)
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(url, headers={"User-Agent": "RunTeams/{}".format(
            self.current_version)})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                declared = _response_length(response)
                if declared > MAX_ARTIFACT_BYTES:
                    raise UpdateError("更新资源超过大小限制")
                with open(temporary, "wb") as handle:
                    while not self._stop.is_set():
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_ARTIFACT_BYTES:
                            raise UpdateError("更新资源超过大小限制")
                        digest.update(chunk)
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            if self._stop.is_set():
                raise UpdateError("更新下载已停止")
            if digest.hexdigest() != expected:
                raise UpdateError("更新资源校验失败")
            os.replace(temporary, artifact)
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        pending = {
            "schema_version": 1,
            "version": version,
            "target": target_key(),
            "kind": kind,
            "artifact_path": artifact,
            "sha256": expected,
            "downloaded_at": _now(),
        }
        _atomic_json(pending_path(self.data_dir), pending)
        self._set_status(state="ready", checked_at=_now(), available_version=version,
                         downloaded_bytes=size)
        return self.status()


def _safe_zip_members(archive):
    members = archive.infolist()
    if not members:
        raise UpdateError("更新压缩包为空")
    for member in members:
        normalized = member.filename.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part not in ("", ".")]
        mode = member.external_attr >> 16
        if (not parts or normalized.startswith("/") or ".." in parts
                or stat.S_ISLNK(mode)):
            raise UpdateError("更新压缩包包含不安全路径")
    return members


def _verify_hash(path, expected):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise UpdateError("待安装更新校验失败")


def apply_pending_update(app_bundle, data_dir):
    """Apply one downloaded update before the desktop server starts.

    Returns True only when the current macOS app bundle was replaced.  Windows
    uses its signed installer from the future Windows launcher and shares the
    same pending manifest/download format.
    """
    pending_file = pending_path(data_dir)
    pending = _read_json(pending_file)
    if not pending or pending.get("target") != target_key():
        return False
    artifact = os.path.realpath(str(pending.get("artifact_path") or ""))
    expected_root = os.path.realpath(update_dir(data_dir)) + os.sep
    if not artifact.startswith(expected_root) or not os.path.isfile(artifact):
        raise UpdateError("待安装更新资源不存在")
    expected_hash = str(pending.get("sha256") or "").lower()
    if not _SHA256_RE.fullmatch(expected_hash):
        raise UpdateError("待安装更新校验信息无效")
    _verify_hash(artifact, expected_hash)
    if sys.platform != "darwin" or pending.get("kind") != "macos-app-zip":
        return False

    app_bundle = os.path.realpath(app_bundle)
    if not app_bundle.endswith(".app") or not os.path.isdir(app_bundle):
        raise UpdateError("当前应用位置无效")
    parent = os.path.dirname(app_bundle)
    stage = tempfile.mkdtemp(prefix=".runteams-update-", dir=parent)
    backup = os.path.join(parent, ".RunTeams.previous.app")
    moved_old = False
    try:
        with zipfile.ZipFile(artifact) as archive:
            archive.extractall(stage, _safe_zip_members(archive))
        candidates = []
        for current, dirs, _files in os.walk(stage):
            for name in dirs:
                if name.endswith(".app"):
                    candidates.append(os.path.join(current, name))
            dirs[:] = [name for name in dirs if not name.endswith(".app")]
        if len(candidates) != 1:
            raise UpdateError("更新压缩包必须只包含一个应用")
        incoming = candidates[0]
        info_path = os.path.join(incoming, "Contents", "Info.plist")
        try:
            with open(info_path, "rb") as handle:
                info = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException) as exc:
            raise UpdateError("更新应用缺少有效版本信息") from exc
        if str(info.get("CFBundleIdentifier") or "") != "ai.runteams.desktop":
            raise UpdateError("更新应用身份不匹配")
        if str(info.get("CFBundleShortVersionString") or "") != str(pending.get("version") or ""):
            raise UpdateError("更新应用版本不匹配")
        verified = subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", incoming],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
        if verified.returncode:
            raise UpdateError("更新应用签名验证失败")
        assessed = subprocess.run(
            ["/usr/sbin/spctl", "--assess", "--type", "execute", "--verbose", incoming],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
        if assessed.returncode:
            raise UpdateError("更新应用未通过 macOS 安全验证")
        if os.path.exists(backup):
            shutil.rmtree(backup)
        os.replace(app_bundle, backup)
        moved_old = True
        os.replace(incoming, app_bundle)
        os.unlink(pending_file)
        _atomic_json(os.path.join(update_dir(data_dir), "applied.json"), {
            "version": pending.get("version"), "applied_at": _now(), "backup_path": backup,
        })
        return True
    except Exception:
        if moved_old and not os.path.exists(app_bundle) and os.path.exists(backup):
            os.replace(backup, app_bundle)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
