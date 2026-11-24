import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from runteams_core.devtools import provision_mcp_node as node


class NodeProvisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cache = Path(temporary.name).resolve()

    def check(self, archive, target, machine, executable):
        lock = self.cache / 'node-runtime.json'
        lock.write_text(json.dumps({'version': '24.22.1', 'targets': {target: {
            'file': archive.name, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()
        }}}))
        with patch.object(node, 'LOCK', lock), patch.object(node.sys, 'platform', target.split('-')[0]), \
                patch.object(node.platform, 'machine', return_value=machine):
            binary = node.provision(self.cache)
            self.assertEqual(binary.name, executable)
            self.assertEqual(binary.read_bytes(), b'node fixture')
            self.assertEqual((binary.parent.parent / 'LICENSE').read_bytes(), b'license fixture')
            self.assertFalse((binary.parent.parent / 'unrequested').exists())
            self.assertEqual(node.provision(self.cache), binary)
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'cache_changed'):
                node.provision(self.cache)
            archive.write_bytes(b'invalid')
            with self.assertRaisesRegex(ValueError, 'download_integrity'):
                node.provision(self.cache)

    def test_windows_amd64_zip(self):
        prefix = 'node-v24.22.1-win-x64'
        path = self.cache / (prefix + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(prefix + '/node.exe', b'node fixture')
            archive.writestr(prefix + '/LICENSE', b'license fixture')
            archive.writestr(prefix + '/unrequested', b'extra')
        self.check(path, 'win32-x64', 'AMD64', 'node.exe')

    def test_mac_arm64_tar(self):
        prefix = 'node-v24.22.1-darwin-arm64'
        path = self.cache / (prefix + '.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in [('bin/node', b'node fixture'), ('LICENSE', b'license fixture')]:
                info = tarfile.TarInfo(prefix + '/' + name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        self.check(path, 'darwin-arm64', 'arm64', 'node')
