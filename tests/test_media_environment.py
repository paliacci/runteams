import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runteams_core.agents.environment import media_checks
from runteams_core.assets.skills.skill_metadata import declared_environment, bundle_environment
from runteams_core.foundation.contracts import ContractError


class MediaEnvironmentTests(unittest.TestCase):
    def test_declaration_travels_with_skill_bytes(self):
        markdown = b'---\nname: media\ndescription: Media\nmetadata:\n  runteams-environment: ffmpeg ffprobe\n---\n'
        bundle = {'files': [{'path': 'SKILL.md', 'content_base64': base64.b64encode(markdown).decode()}]}
        self.assertEqual(bundle_environment(bundle), ['ffmpeg', 'ffprobe'])
        self.assertEqual(declared_environment(b'---\nname: writer\ndescription: Write\n---\n'), [])
        with self.assertRaises(ContractError):
            declared_environment(markdown.replace(b'ffmpeg ffprobe', b'echo'))

    def test_missing_and_broken_checked_independently_and_removal_seen(self):
        installed = media_checks._executable('ffprobe')
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'ffprobe'
            bad.write_text('#!/bin/sh\nprintf "{}"\n')
            bad.chmod(0o755)
            with patch.object(media_checks, '_executable', side_effect=lambda n: str(bad) if n == 'ffprobe' and bad.exists() else None):
                tools = {'tools': ['ffmpeg', 'ffprobe']}
                self.assertEqual(media_checks.check(tools)['checks'], {'ffmpeg':'missing', 'ffprobe':'failed'})
                bad.unlink()
                self.assertEqual(media_checks.check(tools)['checks']['ffprobe'], 'missing')
                if installed:
                    bad.symlink_to(installed)
                    self.assertEqual(media_checks.check(tools)['checks'], {'ffmpeg':'missing', 'ffprobe':'ready'})
                    bad.unlink()
                    self.assertEqual(media_checks.check(tools)['checks']['ffprobe'], 'missing')

    def test_rejects_programs_or_arguments_from_assets(self):
        for values in ({'tools': ['/bin/ls']}, {'tools': []}, {'tools':['ffmpeg'], 'args':['-y']}, {'tools':['ffprobe','ffprobe']}):
            with self.subTest(values=values), self.assertRaises(ContractError):
                media_checks.check(values)

    def test_installed_tools_process_sample(self):
        for name in ('ffmpeg','ffprobe'):
            exe = media_checks._executable(name)
            if not exe:
                self.skipTest(name + ' is not installed')
            with self.subTest(name=name):
                self.assertEqual(media_checks._probe(name, exe), 'ready')
