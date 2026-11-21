"""Configuration paths are local values selected independently from asset imports."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runteams_core.configuration.configuration_schema import validate_declaration
from runteams_core.configuration.employee_configuration import ConfigurationInvalid, validate_values
from runteams_core.conversations import chat_attachments


class ConfigurationLocationTests(unittest.TestCase):
    def test_path_declaration_and_values(self):
        for kind in ('file_path', 'directory_path'):
            field = {'key': 'target', 'label': 'Target', 'type': kind}
            definition = {'schema': 'runteams.employee-configuration/1', 'groups': [
                {'key': 'paths', 'label': 'Locations', 'fields': [field]}]}
            validate_declaration(definition)
            for path in ('', '/tmp/my folder'):
                self.assertEqual(validate_values(definition, {'target': path}), {'target': path})
            for invalid in (42, '../folder', '/tmp/\x00'):
                with self.assertRaises(ConfigurationInvalid):
                    validate_values(definition, {'target': invalid})
            field['required'] = True
            with self.assertRaises(ConfigurationInvalid):
                validate_values(definition, {'target': ''})
            field['default'] = '/tmp'
            with self.assertRaises(ValueError):
                validate_declaration(definition)

    @patch.object(chat_attachments.sys, 'platform', 'darwin')
    @patch.object(chat_attachments.subprocess, 'run')
    def test_picker_returns_only_the_selected_kind_or_cancellation(self, run):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / ' 空 格 '
            file.touch()
            for kind, path in [('file', str(file)), ('folder', directory)]:
                run.return_value = subprocess.CompletedProcess([], 0, path+'\n', '')
                self.assertEqual(chat_attachments.pick_configuration_location({'kind': kind, 'language':'en'}), {'path': path})
                self.assertIn('choose ' + kind, run.call_args.args[0][2])
            with self.assertRaises(ValueError):
                chat_attachments.choose_location('file', 'Choose file')
        run.return_value = subprocess.CompletedProcess([], 1, '', 'User canceled. (-128)')
        self.assertIsNone(chat_attachments.choose_location('folder', 'Choose folder'))
        with self.assertRaises(ValueError):
            chat_attachments.choose_location('other', '')
