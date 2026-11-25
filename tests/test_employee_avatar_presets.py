"""Preset identity, exact picture migration and portable employee revisions."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from runteams_core.employees import employee_avatars as avatars
from runteams_core.foundation.resources import root
from runteams_core.authoring.creator_contracts import canonical, strict_json, tree
from runteams_core.authoring.source.creator_source_archive import pack, inspect
from runteams_core.authoring.source.creator_source_import import inspect_source
from runteams_core.authoring.source.creator_local_source import LocalSources, snapshot
from runteams_core.foundation.regular_files import storage_path
from runteams_core.authoring.source.creator_source_revisions import Revisions


class EmployeeAvatarPresetTests(unittest.TestCase):
    def test_sixty_unique_static_portable_presets_and_default(self):
        from runteams_core.foundation.contracts import DEFAULT_EMPLOYEE_AVATAR
        catalog = avatars.preset_catalog()
        self.assertEqual(len(catalog['presets']), 60)
        items = avatars.preset_items()
        self.assertEqual([item['id'] for item in items], catalog['featured'])
        self.assertEqual(len(items), 14)
        self.assertEqual(len({item['asset_avatar'] for item in items}), 14)
        self.assertEqual(DEFAULT_EMPLOYEE_AVATAR, items[0]['avatar'])
        pictures = set()
        for item in catalog['presets']:
            path, body = avatars.prepare_picture(avatars.preset_reference(item['id']))
            self.assertEqual(avatars.validate_image(path, body), 'image/svg+xml')
            self.assertEqual(body, (root() / 'web/worker-avatars/colleague' / (item['id'] + '.svg')).read_bytes())
            self.assertEqual(path, 'assets/avatars/' + hashlib.sha256(body).hexdigest() + '.svg')
            pictures.add(path)
        self.assertEqual(len(pictures), 60)

    def test_unfeatured_saved_picture_is_preserved_and_resolves_in_browser(self):
        reference = avatars.preset_reference('colleague-002')
        self.assertNotIn(reference, [item['avatar'] for item in avatars.preset_items()])
        path, body = avatars.prepare_picture(reference)
        identity = avatars.identity({'name': 'Saved employee', 'avatar': path}, files={path: body})
        self.assertEqual(base64.b64decode(identity['avatar_src'].split(',')[1]), body)
        self.assertEqual(avatars.canonical_preset(reference), reference)

    def test_old_references_and_exact_embedded_robots_share_stable_people(self):
        for item in avatars.preset_catalog()['legacy']:
            old = 'preset:bottts:' + item['id']
            new = avatars.preset_reference(item['target'])
            self.assertEqual(avatars.canonical_preset(old), new)
            self.assertEqual(avatars.prepare_picture(old), avatars.prepare_picture(new))
            body = (root() / 'web/worker-avatars/bottts' / (item['id'] + '.svg')).read_bytes()
            employee = {'name': 'Unchanged', 'avatar': 'art/custom.svg'}
            files = {'art/custom.svg': body}; before = copy.deepcopy(files)
            identity = avatars.identity(employee, files=files)
            self.assertEqual(identity['avatar'], employee['avatar'])
            self.assertEqual(base64.b64decode(identity['avatar_src'].split(',')[1]), avatars.prepare_picture(new)[1])
            self.assertEqual(files, before)
            self.assertEqual(avatars.canonical_preset('assets/avatars/' + item['sha256'] + '.svg'), new)

    def test_custom_picture_stays_exact_and_invalid_old_attachment_is_rejected(self):
        body = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
        identity = avatars.identity({'name': 'Custom', 'avatar': 'art/custom.svg'}, files={'art/custom.svg': body})
        self.assertEqual(base64.b64decode(identity['avatar_src'].split(',')[1]), body)
        legacy = avatars.preset_catalog()['legacy'][0]
        with self.assertRaises(ValueError):
            avatars.identity({'name': 'Bad', 'avatar': 'art/old.svg'}, avatar_file={
                'sha256': legacy['sha256'], 'content_base64': base64.b64encode(body).decode()})
        for ref in ('preset:colleague:colleague-061', 'preset:bottts:unknown', 'preset:colleague:../colleague-001'):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                avatars.prepare_picture(ref)

    def test_selected_preset_round_trips_in_atomic_source_revision(self):
        files = {'project.json': canonical({'schema':'runteams.creator-project/2','key':'avatar-test','version':'1.0.0','name':'Avatar test','sdk':'mcp-apps/1-dev',
            'entrypoints':{'employees':['employees/main.json']},'dependency_lock':'dependencies.lock.json','source_access':{'default':'author','public_files':[]}}),
            'dependencies.lock.json':canonical({'schema':'runteams.dependencies/2','root':'avatar-test','runtime':{'protocol':'mcp','managed_node':'24'},'dependencies':[]}),
            'employees/main.json':canonical({'schema':'runteams.employee-source/3','key':'main','name':'Employee','avatar':'preset:bottts:nova','soul_file':'employees/soul.md','skill_dirs':[],
                'runtime_requirement':{'provider':'codex','model':'','effort':''}}), 'employees/soul.md':b'', 'notes.txt':b'Keep me'}
        with tempfile.TemporaryDirectory() as directory:
            store = LocalSources(Path(directory).resolve() / 'creator-sources'); sid = tree(files)['sha256']
            store.save(pack(files), sid, inspect_source)
            request = {'base_revision':sid,'operation_key':'avatar-test-001','employee_source':'employees/main.json','name':'Employee','avatar':avatars.preset_reference('colleague-060')}
            result = avatars.edit(store, sid, request)
            self.assertEqual(result, avatars.edit(store, sid, request))
            revisions = Revisions(store, sid); restored = inspect(revisions.export(result['revision']))
            with tempfile.TemporaryDirectory(dir=storage_path(tempfile.gettempdir())) as backup:
                destination = Path(tempfile.gettempdir()) / Path(backup).name / ('备份-' + 'a' * 80) / ('修订-' + 'b' * 80)
                snapshot(Path(directory), destination, None, lambda: None)
                copied = Revisions(LocalSources(destination / 'creator-sources'), sid)
                self.assertEqual(inspect(copied.export(result['revision'])), restored)
            employee = strict_json(restored['employees/main.json'])
            self.assertEqual(restored[employee['avatar']], avatars.prepare_picture(request['avatar'])[1])
            self.assertEqual(restored['notes.txt'], files['notes.txt'])
            self.assertEqual(store.archive(sid), pack(files))
            self.assertEqual(avatars.identity(employee, files=restored), result['identity'])

    def test_generated_browser_catalog_and_asset_register_match_owned_sources(self):
        from runteams_core.devtools.build_employee_avatar_catalog import expected
        from runteams_core.devtools.build_community_web_manifest import expected as assets
        self.assertEqual((root() / 'web/ui/employee-avatars.js').read_text(), expected())
        actual = json.loads((root() / 'runteams_core/application/http/community_web_assets.json').read_text())
        self.assertEqual(actual, assets())
        for item in avatars.preset_catalog()['legacy']:
            self.assertEqual(actual['/worker-avatars/bottts/' + item['id'] + '.svg'][0], 'web/worker-avatars/colleague/' + item['target'] + '.svg')
        self.assertIn("'web/worker-avatars'", (root() / 'runteams_core/devtools/export_creator_devkit.py').read_text())

    def test_shipped_browser_renderer_preserves_uploads_and_maps_old_pictures(self):
        script = '''const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const api=require('./web/ui/employee-avatars.js'),catalog=JSON.parse(fs.readFileSync('web/worker-avatars/presets.json'));
for(const item of catalog.presets){const avatar='preset:colleague:'+item.id;assert.equal(api.src(avatar),'/worker-avatars/colleague/'+item.id+'.svg');assert(api.matches({avatar},avatar));}
for(const old of catalog.legacy){const avatar='preset:colleague:'+old.target,expected=api.src(avatar),ref='preset:bottts:'+old.id;
const body=fs.readFileSync('web/worker-avatars/bottts/'+old.id+'.svg');assert.equal(crypto.createHash('sha256').update(body).digest('hex'),old.sha256);
assert.equal(api.src(ref),expected);assert.equal(api.src('assets/avatars/'+old.sha256+'.svg'),expected);
const worker={avatar_src:'data:image/svg+xml;base64,'+body.toString('base64')};assert.equal(api.src('art/custom.svg',worker),expected);assert(api.matches({avatar},'art/custom.svg',worker));}
const upload='upload:'+'a'.repeat(64)+'.webp',custom={avatar_src:'data:image/png;base64,AAAA'};
assert.equal(api.src(upload),'/api/worker-avatar/upload/'+upload.slice(7));assert.equal(api.src('art/custom.png',custom),custom.avatar_src);
assert.equal(api.src('assets/avatars/'+catalog.legacy[0].sha256+'.svg',custom),custom.avatar_src);
assert.equal(api.src('unknown',{avatar_src:'__proto__'}),api.src(api.defaultAvatar));
assert.equal(api.src('preset:colleague:../unknown'),api.src(api.defaultAvatar));console.log('ok');'''
        subprocess.run(['node', '-e', script], cwd=root(), check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
