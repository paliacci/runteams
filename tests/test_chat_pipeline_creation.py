import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from runteams_core.agents.tools import agent_tool_registry
from runteams_core.application.local_application import LocalApplication
from runteams_core.pipelines import source_pipeline_workspace
from runteams_core.storage import device_data, product_store


class ChatPipelineCreationTests(unittest.TestCase):
    def test_empty_team_is_visible_and_retry_keeps_the_same_discussion(self):
        with TemporaryDirectory() as directory:
            subprocess.run([sys.executable, '-B', '-c',
                'import runpy,sys;runpy.run_path(sys.argv[1])["check_creation"](sys.argv[2])',
                __file__, directory], check=True, timeout=40,
                env={**os.environ, 'RUNTEAMS_DATA': directory, 'RUNTEAMS_AUTOMATION_DISPATCH': '0'})


def check_creation(directory):
    self = unittest.TestCase()
    app = LocalApplication(Path(directory))
    try:
        with app.runtime.scope():
            chat_id = product_store.create_chat()
            library = device_data.identity()['library_id']
            context = {'chat_id': chat_id, 'actor_id': library, 'library_id': library}
            request = {'action': 'create_pipeline', 'name': '项目组'}
            def create(payload):
                return agent_tool_registry.dispatch('runteams_creator_source', payload, context).data
            receipt = create(request)
            self.assertEqual(create(request), receipt)
            with self.assertRaises(ValueError):
                create({**request, 'name': '其他团队'})
            reference = receipt['reference']
            core = app.runtime.work_core()
            self.assertEqual([item['reference'] for item in source_pipeline_workspace.catalog(core)['items']], [reference])
            workspace = source_pipeline_workspace.workspace(core, reference)
            self.assertEqual(workspace['name'], '项目组')
            self.assertEqual(workspace['pipeline']['positions'], [])
            session = product_store.get_chat(chat_id)
            self.assertEqual(session['context']['source_pipeline_workspace'], reference)
    finally:
        app.close()
