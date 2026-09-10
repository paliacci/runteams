# -*- coding: utf-8 -*-
import hashlib
import io
import json
import os
import plistlib
import tempfile
import unittest
from unittest import mock
import zipfile

import app_update


class DownloadResponse:
    def __init__(self, payload):
        self.payload = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size=-1):
        return self.payload.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class AppUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="runteams-update-test-")

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, version, artifact=b"new app", digest=None):
        return {
            "schema_version": 1,
            "version": version,
            "platforms": {
                app_update.target_key(): {
                    "kind": "macos-app-zip" if os.name != "nt" else "windows-nsis",
                    "url": "https://downloads.example.test/RunTeams-update.zip",
                    "sha256": digest or hashlib.sha256(artifact).hexdigest(),
                },
            },
        }

    def test_version_comparison_uses_semver_order(self):
        self.assertTrue(app_update.is_newer("0.10.0", "0.9.9"))
        self.assertFalse(app_update.is_newer("0.9.9", "0.10.0"))
        self.assertTrue(app_update.is_newer("1.0.0", "1.0.0-beta.1"))
        with self.assertRaises(app_update.UpdateError):
            app_update.is_newer("tomorrow", "1.0.0")

    def test_new_release_downloads_and_persists_pending_update(self):
        artifact = b"signed desktop update"
        manifest = json.dumps(self._manifest("0.2.0", artifact)).encode()
        manager = app_update.UpdateManager(
            "0.1.0", self.tmp.name,
            manifest_url="https://updates.example.test/stable.json", enabled=True)
        with mock.patch.object(app_update.urllib.request, "urlopen", side_effect=[
                DownloadResponse(manifest), DownloadResponse(artifact)]):
            status = manager.check_now()
        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["available_version"], "0.2.0")
        pending = app_update._read_json(app_update.pending_path(self.tmp.name))
        self.assertEqual(pending["version"], "0.2.0")
        with open(pending["artifact_path"], "rb") as handle:
            self.assertEqual(handle.read(), artifact)

    def test_current_release_does_not_require_platform_artifacts(self):
        manifest = json.dumps({
            "schema_version": 1, "version": "0.1.0", "platforms": {},
        }).encode()
        manager = app_update.UpdateManager(
            "0.1.0", self.tmp.name,
            manifest_url="https://updates.example.test/stable.json", enabled=True)
        with mock.patch.object(app_update.urllib.request, "urlopen",
                               return_value=DownloadResponse(manifest)) as request:
            status = manager.check_now()
        self.assertEqual(status["state"], "current")
        self.assertEqual(request.call_count, 1)
        self.assertFalse(os.path.exists(app_update.pending_path(self.tmp.name)))

    def test_bad_artifact_hash_is_not_promoted(self):
        artifact = b"tampered"
        manifest = json.dumps(self._manifest("0.2.0", artifact, digest="0" * 64)).encode()
        manager = app_update.UpdateManager(
            "0.1.0", self.tmp.name,
            manifest_url="https://updates.example.test/stable.json", enabled=True)
        with mock.patch.object(app_update.urllib.request, "urlopen", side_effect=[
                DownloadResponse(manifest), DownloadResponse(artifact)]):
            with self.assertRaises(app_update.UpdateError):
                manager.check_now()
        self.assertFalse(os.path.exists(app_update.pending_path(self.tmp.name)))

    def test_macos_update_replaces_bundle_only_after_validation(self):
        app_bundle = os.path.join(self.tmp.name, "RunTeams.app")
        os.makedirs(os.path.join(app_bundle, "Contents", "MacOS"))
        with open(os.path.join(app_bundle, "old-version"), "w", encoding="utf-8") as handle:
            handle.write("old")

        archive_buffer = io.BytesIO()
        info = plistlib.dumps({
            "CFBundleIdentifier": "ai.runteams.desktop",
            "CFBundleShortVersionString": "0.2.0",
        })
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("RunTeams.app/Contents/Info.plist", info)
            archive.writestr("RunTeams.app/Contents/MacOS/RunTeams", "#!/bin/sh\n")
            archive.writestr("RunTeams.app/new-version", "new")
        payload = archive_buffer.getvalue()
        directory = os.path.join(app_update.update_dir(self.tmp.name), "0.2.0")
        os.makedirs(directory)
        artifact = os.path.join(directory, "RunTeams-0.2.0.zip")
        with open(artifact, "wb") as handle:
            handle.write(payload)
        app_update._atomic_json(app_update.pending_path(self.tmp.name), {
            "schema_version": 1,
            "version": "0.2.0",
            "target": "darwin-aarch64",
            "kind": "macos-app-zip",
            "artifact_path": artifact,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        verified = mock.Mock(returncode=0, stderr="")
        with mock.patch.object(app_update.sys, "platform", "darwin"), \
                mock.patch.object(app_update.platform, "machine", return_value="arm64"), \
                mock.patch.object(app_update.subprocess, "run", return_value=verified):
            self.assertTrue(app_update.apply_pending_update(app_bundle, self.tmp.name))
        self.assertTrue(os.path.isfile(os.path.join(app_bundle, "new-version")))
        self.assertFalse(os.path.exists(os.path.join(app_bundle, "old-version")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.tmp.name, ".RunTeams.previous.app", "old-version")))
        self.assertFalse(os.path.exists(app_update.pending_path(self.tmp.name)))


if __name__ == "__main__":
    unittest.main()
