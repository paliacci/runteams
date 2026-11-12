import base64
from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from PIL import Image

from runteams_core.application.local_application import LocalApplication
from runteams_core.assets.rented_references import PIPELINE
from runteams_core.authoring.source.creator_local_source import current_store
from runteams_core.employees.employee_avatars import preset_items
from runteams_core.storage import device_data
from test_employee_pipeline_groups import member, save_project


class PipelineAvatarTests(unittest.TestCase):
    def test_creator_saves_revisioned_icon_and_renter_cannot_edit(self):
        with TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), directory],
                check=True, timeout=30, env={**os.environ, 'PYTHONPATH': os.pathsep.join(
                    [str(Path(__file__).resolve().parents[1]), os.environ.get('PYTHONPATH', '')]),
                    'RUNTEAMS_DATA': directory, 'RUNTEAMS_AUTOMATION_DISPATCH': '0'})


def check_avatar(directory):
    check = unittest.TestCase()
    app = LocalApplication(Path(directory))
    try:
        with app.runtime.scope():
            store = current_store(device_data.identity()['cache_scope'])
            save_project(store, 'avatar-example', [('worker', 'Worker', '👤')], [
                ('example', 'Example pipeline', [member('worker')]),
            ])

        def request(action, body):
            return app.dispatch('POST', '/api/device/work/source-pipelines/' + action, body)

        row = request('catalog', {})['items'][0]
        check.assertNotIn('avatar_src', row)
        reference = row['reference']
        old = request('workspace', {'reference': reference})
        check.assertNotIn('avatar_src', old)
        first = {'reference': reference, 'base_revision': old['source_revision'],
                 'operation_id': str(uuid4()), 'avatar': preset_items()[0]['avatar']}
        saved = request('edit', first)
        check.assertEqual(request('edit', first), saved)
        check.assertTrue(saved['avatar_src'].startswith('data:image/svg+xml;base64,'))

        upload = BytesIO()
        Image.new('RGB', (96, 48), '#268a80').save(upload, 'PNG')
        updated = request('edit', {**first, 'base_revision': saved['revision'],
            'operation_id': str(uuid4()), 'avatar': {
                'content_base64': base64.b64encode(upload.getvalue()).decode()}})
        workspace = request('workspace', {'reference': reference})
        check.assertTrue(workspace['avatar_src'].startswith('data:image/webp;base64,'))
        row = request('catalog', {})['items'][0]
        check.assertEqual(row['avatar_src'], workspace['avatar_src'])
        check.assertEqual(row['revision'], updated['revision'])
        check.assertEqual(workspace['source_revision'], updated['revision'])
        check.assertEqual(workspace['pipeline'], old['pipeline'])
        check.assertEqual(workspace['workflows'], old['workflows'])
        with check.assertRaises(PermissionError):
            request('edit', {**first, 'reference': {**reference, 'schema': PIPELINE}})
        with check.assertRaises(PermissionError):
            request('edit', {**first, 'reference': {**reference, 'library_id': str(uuid4())}})
    finally:
        app.close()


if __name__ == '__main__':
    check_avatar(sys.argv[1])
