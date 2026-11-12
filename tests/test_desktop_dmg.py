"""Real Finder-backend acceptance, independent of hdiutil's legacy verifier."""
import hashlib
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from runteams_core.devtools.package_desktop_dmg import package


@unittest.skipUnless(sys.platform == 'darwin', 'macOS disk-image tools required')
class DesktopDMGTests(unittest.TestCase):
    def test_finder_backend_mounts_image_and_preserves_signed_app(self):
        probe = subprocess.run(['diskutil', 'image', 'attach', '--help'], capture_output=True)
        if probe.returncode:
            self.skipTest('DiskImages2 command-line acceptance requires macOS 26 or later')
        with tempfile.TemporaryDirectory(prefix='runteams-dmg-test-') as temporary:
            root = Path(temporary)
            app = root / 'RunTeams.app'
            executable = app / 'Contents/MacOS/RunTeams'
            executable.parent.mkdir(parents=True)
            shutil.copyfile('/usr/bin/true', executable)
            executable.chmod(0o755)
            (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'ai.runteams.desktop.local',
                'CFBundleExecutable': 'RunTeams', 'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '0.0.1', 'CFBundleShortVersionString': '0.0.1',
                'RunTeamsLocalBuild': True,
            }))
            payload = app / 'Contents/Resources/payload.bin'
            payload.parent.mkdir()
            payload.write_bytes(b'dmg mount acceptance\n' * (8 * 1024 * 1024 // 21))
            expected = hashlib.sha256(payload.read_bytes()).hexdigest()
            subprocess.run(['codesign', '--force', '--sign', '-', str(app)],
                           check=True, capture_output=True)
            image = root / 'installer.dmg'
            package(app, image)
            mount = root / 'mount'
            mount.mkdir()
            attached = False
            try:
                result = subprocess.run(['diskutil', 'image', 'attach', '--readOnly',
                    '--nobrowse', '--mountPoint', str(mount), str(image)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                attached = True
                self.assertEqual(hashlib.sha256((mount / 'RunTeams.app/Contents/Resources/payload.bin').read_bytes()).hexdigest(), expected)
                self.assertEqual((mount / 'Applications').readlink(), Path('/Applications'))
                subprocess.run(['codesign', '--verify', '--deep', '--strict', str(mount / 'RunTeams.app')],
                               check=True, capture_output=True)
            finally:
                if attached or mount.is_mount():
                    subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)
