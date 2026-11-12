"""Create and verify a smaller, lossless macOS DMG from a signed desktop app."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile

# hdiutil counts sectors (512 bytes), not bytes. Finder's DiskImages2 backend
# rejects oversized compressed runs even when hdiutil can verify/mount them.
# Use the standard 1 MiB run size for images opened through Finder.
LZMA_CHUNK_SECTORS = 2048


def verify_image(image, app_name):
    subprocess.run(['hdiutil', 'verify', str(image)], check=True)
    # macOS 26 exposes the same backend used by Finder. Older build hosts only
    # have the legacy verifier; they still use the compatible 1 MiB encoding.
    probe = subprocess.run(['diskutil', 'image', 'attach', '--help'], capture_output=True)
    if probe.returncode:
        return False
    with tempfile.TemporaryDirectory(prefix='runteams-dmg-mount-') as temporary:
        mount = Path(temporary) / 'mount'
        mount.mkdir()
        attached = False
        try:
            subprocess.run(['diskutil', 'image', 'attach', '--readOnly', '--nobrowse',
                            '--mountPoint', str(mount), str(image)], check=True, capture_output=True)
            attached = True
            subprocess.run(['codesign', '--verify', '--deep', '--strict', str(mount / app_name)],
                           check=True, capture_output=True)
        finally:
            if attached or mount.is_mount():
                subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)
    return True



def package(app, output, image_format='ULMO', *, signer=None):
    if signer is not None and signer.local:
        raise ValueError('A distribution DMG requires Developer ID signing')
    app, output = Path(app).resolve(), Path(output).resolve()
    if app.suffix != '.app' or not (app / 'Contents/Info.plist').is_file():
        raise ValueError('Expected a built RunTeams application')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    executable = {'ai.runteams.desktop': 'RunTeams', 'ai.runteams.desktop.local': 'RunTeams',
                  'ai.runteams.community': 'RunTeamsLocal'}.get(info.get('CFBundleIdentifier'))
    if not executable or info.get('CFBundleExecutable') != executable or not (app / 'Contents/MacOS' / executable).is_file():
        raise ValueError('Expected a known RunTeams application identity')
    if info.get('CFBundleIdentifier') == 'ai.runteams.desktop.local' and info.get('RunTeamsLocalBuild') is not True:
        raise ValueError('The local official identity must be an explicit local build')
    if signer is not None and info.get('RunTeamsLocalBuild') is True:
        raise ValueError('Local acceptance applications cannot become signed distribution images')
    if output.suffix != '.dmg' or output.exists():
        raise ValueError('Choose a new .dmg output path')
    if app in output.parents:
        raise ValueError('DMG output must be outside the app')
    if image_format not in ('ULMO', 'UDZO'):
        raise ValueError('Unsupported DMG format')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.runteams-dmg-', dir=output.parent) as temporary:
        root = Path(temporary)
        contents = root / 'contents'
        contents.mkdir()
        # Preserve the sealed app bytes, permissions and links while staging.
        subprocess.run(['ditto', str(app), str(contents / app.name)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(contents / app.name)], check=True)
        (contents / 'Applications').symlink_to('/Applications')
        image = root / 'package.dmg'
        # Converting a completed filesystem produces a smaller LZMA image than
        # compressing directly while hdiutil creates the filesystem.
        intermediate = root / 'filesystem.dmg' if image_format == 'ULMO' else image
        subprocess.run(['hdiutil', 'create', '-srcfolder', str(contents), '-volname', 'RunTeams Local' if executable == 'RunTeamsLocal' else 'RunTeams',
                        '-fs', 'APFS', '-format', 'UDZO', '-nospotlight', str(intermediate)], check=True)
        if image_format == 'ULMO':
            subprocess.run(['hdiutil', 'convert', str(intermediate), '-format', 'ULMO',
                            '-imagekey', f'udif-chunk-size={LZMA_CHUNK_SECTORS}',
                            '-o', str(image)], check=True)
        if signer is not None:
            signer.sign(image)
        finder_verified = verify_image(image, app.name)
        image.rename(output)
    with (app / 'Contents/Info.plist').open('rb') as stream:
        version = plistlib.load(stream)['CFBundleShortVersionString']
    return {'app': str(app), 'version': version, 'dmg': str(output),
            'bytes': output.stat().st_size, 'format': image_format,
            'lzma_chunk_bytes': LZMA_CHUNK_SECTORS * 512 if image_format == 'ULMO' else None,
            'asset_files_preserved_independently': True, 'verified': True,
            'finder_backend_verified': finder_verified}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--format', choices=('ULMO', 'UDZO'), default='ULMO')
    args = parser.parse_args()
    print(json.dumps(package(args.app, args.output, args.format), indent=2))
