"""Finder folders are inserted as original directory paths."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch
import uuid

from runteams_core.application.local_application import LocalApplication
from runteams_core.conversations import chat_attachments
from runteams_core.storage import local_database


class LocalClipboardAttachmentsTests(unittest.TestCase):
    def test_paste_routes_reference_folders_without_opening_them(self):
        with ExitStack() as stack:
            root = Path(stack.enter_context(TemporaryDirectory()))
            library = root / 'library'
            stack.enter_context(patch.object(local_database, 'DB_PATH', str(library / 'runteams.db')))
            app = LocalApplication(library)
            stack.callback(app.close)
            folder = root / '项目 folder.txt'
            folder.mkdir()
            for i in range(101):
                (folder / f'{i}.txt').write_text('original', encoding='utf-8')
            file = root / '补充.txt'
            file.write_text('separate file', encoding='utf-8')

            with patch.object(chat_attachments, 'native_picker_path', return_value=''):
                self.assertEqual(app.dispatch('POST', '/api/attachments/paste', {}),
                                 {'items': [], 'folder_paths': []})
            with patch.object(chat_attachments, 'native_picker_path', return_value='/picker'), \
                 patch.object(chat_attachments, 'native_reference_paths', return_value=[str(file)]) as read, \
                 patch.object(chat_attachments, '_folder_files', side_effect=AssertionError('enumerated')):
                with self.assertRaisesRegex(ValueError, '附件粘贴请求无效'):
                    app.dispatch('POST', '/api/attachments/paste', {'paths': [str(folder)]})
                read.assert_not_called()
                self.assertEqual(app.dispatch('POST', '/api/attachments/paste', {}),
                                 {'items': [], 'folder_paths': []})
                read.return_value = [str(folder)]
                with patch.object(chat_attachments, '_selection_root', side_effect=AssertionError('staged')):
                    self.assertEqual(app.dispatch('POST', '/api/attachments/paste', {}),
                                     {'items': [], 'folder_paths': [str(folder)]})
                for action, body in [('paste', {}), ('prepare', {'paste': True, 'paths': [str(folder)]})]:
                    result = app.dispatch('POST', '/api/local-references/' + action, body)
                    self.assertEqual(result, {'references': [], 'pending': [], 'folder_paths': [str(folder)]})
                    read.assert_called_with('paste')
                with self.assertRaisesRegex(ValueError, '剪贴板内容已变化'):
                    app.dispatch('POST', '/api/local-references/prepare', {'paste': True, 'paths': [str(file)]})

                read.return_value = [str(folder), str(file)]
                result = app.dispatch('POST', '/api/attachments/paste', {})
                self.assertEqual(result['folder_paths'], [str(folder)])
                self.assertEqual([(item['kind'], item['name']) for item in result['items']], [('file', file.name)])
                result = app.dispatch('POST', '/api/local-references/paste', {})
                self.assertEqual(result['folder_paths'], [str(folder)])
                self.assertEqual([item['path'] for item in result['pending']], [str(file.resolve())])

                read.return_value = [str(folder)]
                result = app.dispatch('POST', '/api/local-references/drop', {})
                read.assert_called_with('drop')
                self.assertEqual(result['pending'][0]['path'], str(folder.resolve()))

    def test_original_path_text_arrives_in_native_cli_processes(self):
        from runteams_core.agents.adapters.adapter_claude import ClaudeCodeAdapter
        from runteams_core.agents.environment.cli_compatibility import required_options
        from runteams_core.agents.models import model_channels
        with ExitStack() as stack:
            root = Path(stack.enter_context(TemporaryDirectory())).resolve()
            library = root / 'library'
            stack.enter_context(patch.object(local_database, 'DB_PATH', str(library / 'runteams.db')))
            app = LocalApplication(library)
            stack.callback(app.close)
            folder = root / '本机项目 with spaces'
            folder.mkdir()
            second_folder = root / 'empty'
            second_folder.mkdir()
            received = root / 'received.txt'
            shebang = '#!python -X utf8\n' if sys.platform == 'win32' else f'#!{sys.executable}\n'
            claude = root / 'claude'
            claude.write_text(
                shebang +
                'from pathlib import Path\n'
                'import sys\n'
                'if "--help" in sys.argv:\n'
                f'    print({" ".join(required_options("claude-code"))!r})\n'
                '    sys.exit()\n'
                f'Path({str(received)!r}).write_text(sys.argv[sys.argv.index("-p") + 1], encoding="utf-8")\n'
                'print(\'{"type":"result","subtype":"success","result":"received"}\')\n',
                encoding='utf-8',
            )
            claude.chmod(0o700)
            codex = root / 'codex'
            codex.write_text(
                shebang +
                'from pathlib import Path\n'
                'import json, sys\n'
                'def send(message):\n'
                '    print(json.dumps(message), flush=True)\n'
                'turn = {"id": "turn-test", "status": "completed", "items": [\n'
                '    {"type": "agentMessage", "phase": "final_answer", "text": "received"}]}\n'
                'for line in sys.stdin:\n'
                '    request = json.loads(line)\n'
                '    if "id" not in request:\n'
                '        continue\n'
                '    method = request["method"]\n'
                '    result = {}\n'
                '    if method == "thread/start":\n'
                '        result = {"thread": {"id": "thread-test"}}\n'
                '    elif method == "turn/start":\n'
                f'        Path({str(received)!r}).write_text(json.dumps(request["params"]["input"]), encoding="utf-8")\n'
                '        result = {"turn": turn}\n'
                '    send({"id": request["id"], "result": result})\n'
                '    if method == "turn/start":\n'
                '        send({"method": "turn/completed", "params": {"turn": turn}})\n',
                encoding='utf-8',
            )
            codex.chmod(0o700)
            if sys.platform == 'win32':
                # Windows CreateProcess needs executable console launchers for
                # the two fixture scripts. Use the same launcher provided by pip.
                from pip._vendor.distlib.scripts import ScriptMaker
                target = root / 'bin'
                target.mkdir()
                maker = ScriptMaker(str(root), str(target))
                claude, = map(Path, maker.make('claude'))
                codex, = map(Path, maker.make('codex'))
            stack.enter_context(patch.object(model_channels, 'adapter_for', return_value=ClaudeCodeAdapter(executable=str(claude))))
            stack.enter_context(patch.object(model_channels, 'resolve_channel_executable', return_value=str(codex)))
            with patch.object(chat_attachments, 'native_picker_available', return_value=True), \
                 patch.object(chat_attachments, 'native_reference_paths', return_value=[str(folder), str(second_folder)]):
                pasted = app.dispatch('POST', '/api/attachments/paste', {})
            prefix = f'📁 普通文字 {folder}\n请检查\n'
            message = prefix + '\n'.join(pasted['folder_paths'])
            self.assertEqual(message, f'{prefix}{folder}\n{second_folder}')
            folder_refs = [
                {'start': len(prefix), 'end': len(prefix) + len(str(folder))},
                {'start': len(message) - len(str(second_folder)), 'end': len(message)},
            ]
            for provider in ('claude', 'codex'):
                with self.subTest(provider=provider), patch.object(
                        app.runtime, 'config', return_value=({'id': 1, 'provider': provider}, 'test', '', {})):
                    chat = app.dispatch('POST', '/api/conversations', {})['session']['id']
                    request = {'message': message, 'operation_id': str(uuid.uuid4()), 'folder_refs': folder_refs}
                    mid, operation = app.runtime.start(chat, request)
                    events = list(app.runtime.observe(chat, operation))
                    self.assertTrue(received.exists(), events)
                    payload = received.read_text(encoding='utf-8')
                    received.unlink()
                    if provider == 'codex':
                        self.assertEqual(json.loads(payload), [{'type': 'text', 'text': message}])
                    else:
                        self.assertTrue(payload.endswith('# 当前消息\n' + message))
                    saved = app.dispatch('GET', f'/api/chat/{chat}', {})['messages'][0]
                    self.assertEqual(saved['id'], mid)
                    self.assertEqual(saved['text'], message)
                    self.assertEqual(saved['attachments'], [])
                    self.assertEqual(saved['metadata']['folder_refs'], folder_refs)
                    self.assertEqual(app.runtime.start(chat, request), (mid, operation))
                    with self.assertRaisesRegex(ValueError, '原操作内容不能改变'):
                        app.runtime.start(chat, {**request, 'folder_refs': folder_refs[1:]})
