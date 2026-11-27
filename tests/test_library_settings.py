"""Real local settings transactions, receipts and the canonical UI boundary."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from runteams_core.assets.library_assets import AssetConflict
from runteams_core.application.local_application import LocalApplication
from runteams_core.application.local_host_lock import RuntimeBusy
from runteams_core.storage import local_database
from runteams_core.application.http.local_web import ASSETS, read_asset

ROOT=Path(__file__).resolve().parents[1]


class LibrarySettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=LocalApplication(Path(self.temp.name));self.addCleanup(self.app.close)
    def operation(self,revision=0,**values):
        return {'expected_revision':revision,'patch':values,'operation_id':str(uuid.uuid4())}

    def test_manual_backup_waits_for_catalog_read(self):
        self.check_backup_during_discovery('GET', '/api/model-catalog')

    def test_preview_releases_the_archive_and_restore_requires_the_previewed_bytes(self):
        from runteams_core.application.http.local_http import LocalServer
        with patch.object(local_database, 'DB_PATH', str(self.app.data_directory/'runteams.db')):
            backup = self.app.dispatch('POST', '/api/backups', {'operation_id': str(uuid.uuid4())})
            archive = self.app.backups.download(backup['backup_id']).read_bytes()
            store = self.app.backups.root
            initial = set(store.rglob('*'))
            generation = self.app.backups.generation
            server = LocalServer(self.app, 0)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()

            def upload(action, body, **headers):
                conn = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                try:
                    conn.request('POST', '/api/backups/'+action, body, {
                        'Authorization': 'Bearer '+server.session_token, 'Content-Type': 'application/zip',
                        'X-RunTeams-Operation': str(uuid.uuid4()), **headers})
                    response = conn.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    conn.close()

            try:
                status, preview = upload('preview', archive)
                self.assertEqual(status, 200)
                self.assertEqual(preview['sha256'], hashlib.sha256(archive).hexdigest())
                digest = {'X-RunTeams-Backup-SHA256': preview['sha256']}
                status, _ = upload('restore', archive+b'changed', **digest)
                self.assertEqual(status, 400)
                self.assertEqual(self.app.backups.generation, generation)
                self.assertEqual(set(store.rglob('*')), initial)
                status, receipt = upload('restore', archive, **digest)
                self.assertEqual(status, 200)
                self.assertEqual(receipt['state'], 'completed')
                self.assertNotEqual(self.app.backups.generation, generation)
                self.assertFalse(list((store/'imports').iterdir()))
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_manual_backup_waits_for_a_channel_probe(self):
        self.check_backup_during_discovery('POST', '/api/channel/2/probe')

    def test_manual_backup_waits_for_settings_discovery_reads(self):
        for path in ('/api/channels', '/api/channel-usage', '/api/environment'):
            with self.subTest(path=path):
                self.check_backup_during_discovery('GET', path)

    def check_backup_during_discovery(self, method, path):
        reading, release = threading.Event(), threading.Event()
        def catalog(*args):
            reading.set()
            self.assertTrue(release.wait(5))
            return {}
        wait_for = self.app._gate.wait_for
        def drain(predicate, timeout):
            release.set()
            return wait_for(predicate, timeout)
        request = {'operation_id': str(uuid.uuid4())}
        with patch.object(local_database, 'DB_PATH', str(self.app.data_directory / 'runteams.db')), \
                patch.object(self.app, '_dispatch', side_effect=catalog), \
                patch.object(self.app._gate, 'wait_for', side_effect=drain) as waited, \
                ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.app.dispatch, method, path, {})
            try:
                self.assertTrue(reading.wait(5))
                reply = self.app.dispatch('POST', '/api/backups', request)
                self.assertEqual(reply['state'], 'completed')
                waited.assert_called_once()
            finally:
                release.set()
            future.result(timeout=5)
            with self.app.request(), self.assertRaises(RuntimeBusy):
                self.app.dispatch('POST', '/api/backups', {'operation_id': str(uuid.uuid4())})
    def test_restart_and_original_operation_replay_preserve_one_revision(self):
        body=self.operation(send_mode='meta-enter');first=self.app.dispatch('POST','/api/settings',body)
        self.app.close()
        restarted=LocalApplication(Path(self.temp.name));self.addCleanup(restarted.close)
        self.assertEqual(restarted.dispatch('POST','/api/settings',body),first)
        self.assertEqual(restarted.dispatch('GET','/api/settings',{})['revision'],1)
        self.assertEqual(restarted.settings.read()['settings'],{'send_mode':'meta-enter'})
    def test_conflicting_replay_and_parallel_expected_revision_are_rejected(self):
        body=self.operation(allow_supplement=False);self.app.settings.save(body)
        with self.assertRaises(AssetConflict):self.app.settings.save({**body,'patch':{'allow_supplement':True}})
        def save(index):
            try:return self.app.settings.save(self.operation(1,sound=bool(index)))
            except AssetConflict:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,[0,1]))
        self.assertEqual(sum(value is not None for value in results),1)
        self.assertEqual(self.app.settings.read()['revision'],2)
    def test_unknown_fields_and_removed_identity_never_commit(self):
        with self.assertRaises(ValueError):self.app.settings.save(self.operation(arbitrary='not a setting'))
        self.assertEqual(self.app.settings.read()['revision'],0)
        (self.app.base/'.local-library.json').unlink()
        with self.assertRaises(PermissionError):self.app.settings.save(self.operation(sound=False))
    def test_foreign_settings_database_and_symlinks_are_rejected(self):
        self.app.settings.save(self.operation(sound=False))
        with tempfile.TemporaryDirectory() as second:
            other=LocalApplication(Path(second));self.addCleanup(other.close);other.binding.root.mkdir(parents=True,exist_ok=True)
            other.settings.path.write_bytes(self.app.settings.path.read_bytes())
            with self.assertRaises(PermissionError):other.settings.read()
        self.app.settings.path.rename(self.app.settings.path.with_suffix('.saved'))
        self.app.settings.path.symlink_to(self.app.settings.path.with_suffix('.saved'))
        with self.assertRaises(ValueError):self.app.settings.read()
    def test_canonical_entry_has_only_registered_shared_inputs(self):
        self.assertEqual(ASSETS['/'][0],'web/index.html')
        raw,_=read_asset('/','test-nonce')
        self.assertIn(b'/ui/host.js',raw)
        self.assertIn(b'/community/application.js',raw)
        self.assertNotIn(b'runteams-edition',raw)

    def test_unknown_api_names_never_advertise_an_unwired_feature(self):
        for path in ('/api/no-such-route','/api/core/no-such-route','/api/device/no-such-route'):
            with self.subTest(path=path),self.assertRaises(KeyError):
                self.app.dispatch('GET',path,{})
