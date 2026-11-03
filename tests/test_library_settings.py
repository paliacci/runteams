"""Real local settings transactions, receipts and the canonical UI boundary."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
import uuid

from runteams_core.assets.library_assets import AssetConflict
from runteams_core.application.local_application import LocalApplication
from runteams_core.application.http.local_web import ASSETS, read_asset

ROOT=Path(__file__).resolve().parents[1]


class LibrarySettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=LocalApplication(Path(self.temp.name));self.addCleanup(self.app.close)
    def operation(self,revision=0,**values):
        return {'expected_revision':revision,'patch':values,'operation_id':str(uuid.uuid4())}
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
