"""The platform tool subprocess runs through its canonical module after packaging."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from runteams_core.foundation.transport.loopback_rpc import serve_rpc


class ToolTransportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'no-services.env').write_text('')
        self.enterContext(patch.dict(os.environ, {
            'RUNTEAMS_DATA': str(root / 'profile'), 'RUNTEAMS_AUTOMATION_DISPATCH': '0',
            'RUNTEAMS_SERVICE_CONFIG': str(root / 'no-services.env')}))

    def test_canonical_module_round_trip_uses_the_existing_bound_transport(self):
        from runteams_core.agents.tools.agent_tools_mcp import bridge_arguments
        packet = {'jsonrpc': '2.0', 'id': 731, 'method': 'initialize', 'params': {}}
        response = {'jsonrpc': '2.0', 'id': 731, 'result': {'fixture': 'bound-transport'}}
        with serve_rpc(lambda received: response if received == packet else None) as (endpoint, capability):
            result = subprocess.run([sys.executable, '-I', '-B', *bridge_arguments(endpoint)],
                input=json.dumps(packet)+'\n', capture_output=True, text=True, timeout=15,
                env={**os.environ, 'RUNTEAMS_PROTOCOL_CAPABILITY': capability})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), response)

    def test_frozen_product_uses_its_existing_bridge_mode(self):
        from runteams_core.agents.tools.agent_tools_mcp import bridge_arguments
        with patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(bridge_arguments('http://127.0.0.1:731/bridge'),
                             ['--runteams-core-mcp-bridge', 'http://127.0.0.1:731/bridge'])


if __name__ == '__main__':
    unittest.main()
