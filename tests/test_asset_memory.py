import os
import base64
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from runteams_core.conversations import asset_memory as memory
from runteams_core.pipelines import pipeline_references
from runteams_core.storage import local_database, product_store, storage_context
from runteams_core.storage.local_library import LocalLibrary


class AssetMemoryTests(TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(TemporaryDirectory()))
        stack.enter_context(patch.object(local_database, 'DB_PATH', str(root / 'db')))
        stack.enter_context(storage_context.using(LocalLibrary()))
        stack.enter_context(patch.dict(os.environ, RUNTEAMS_HINDSIGHT_KEY_FILE=''))
        self.team = pipeline_references.reference('1' * 64, 'pipelines/team.json')

    def chat(self, ref):
        return {'chat_id': product_store.create_chat(channel_id=1, context={'source_pipeline_workspace': ref})}

    def test_fresh_turn_isolation_edits_and_clear(self):
        first, fresh = self.chat(self.team), self.chat(self.team)
        other = self.chat(pipeline_references.reference('2' * 64, 'pipelines/team.json'))
        for ctx in (first, fresh, other):
            memory.turn(ctx)
        revision = memory.tool({'action': 'read'}, first).data['revision']
        change = {'action': 'save', 'revision': revision, 'text': '面向新手设计师'}
        written = memory.tool(change, first).data
        self.assertEqual(memory.tool(change, fresh).data, written)
        self.assertIn(written['text'], memory.turn(fresh))
        self.assertNotIn(written['text'], memory.turn(other))
        with self.assertRaises(ValueError):
            memory.tool({**change, 'text': '另一窗口的旧修改'}, fresh)
        with self.assertRaises(PermissionError):
            memory.tool({'action': 'read'}, {**other, 'asset_memory_binding': first['asset_memory_binding']})
        memory.tool({'action': 'save', 'revision': written['revision'], 'text': ''}, fresh)
        self.assertEqual(memory.tool({'action': 'read'}, first).data['text'], '')

    def test_stage_and_scheduled_member_share_readonly_bank(self):
        from runteams_core.employees import employee_binding
        from runteams_core.pipelines import scheduled_followup, source_pipeline_work
        from runteams_core.pipelines.bound_pipeline_context import BoundPipelineContext
        from runteams_core.pipelines import pipeline_employee_dependencies
        team = self.chat(self.team)
        memory.turn(team)
        bank = team['asset_memory_binding']['bank']
        memory.save(bank, '持续偏好', memory.read(bank)['revision'])
        employee = {'reference': {'source_id': '1'*64}, 'package': {}}
        with ExitStack() as stack:
            get = stack.enter_context(patch.object(product_store, 'get_chat'))
            stack.enter_context(patch.object(employee_binding, 'resolve', return_value=employee))
            stack.enter_context(patch.object(source_pipeline_work, 'verify_context', return_value={'reference': self.team}))
            stack.enter_context(patch.object(scheduled_followup, 'occurrence', return_value={'status': 'running'}))
            stack.enter_context(patch.object(scheduled_followup, 'followup_scope', return_value=(self.team, 'published', 'run')))
            stack.enter_context(patch.object(BoundPipelineContext, 'definition', return_value=('rev', {'employees': [{}]})))
            stack.enter_context(patch.object(pipeline_employee_dependencies, 'member_reference', return_value=employee['reference']))
            for context in ({'pipeline_work': {'role': 'editor'}}, {}):
                get.return_value = {'kind': 'general', 'subject_type': 'employee', 'context': context}
                turn = {'chat_id': team['chat_id']}
                self.assertIn('持续偏好', memory.turn(turn))
                self.assertEqual(turn['asset_memory_binding'], {'bank': bank, 'writable': False, 'reference': self.team})
                with self.assertRaises(PermissionError):
                    memory.tool({'action': 'save', 'text': '', 'revision': ''}, turn)

    def test_legacy_import_is_once_and_clear_is_durable(self):
        ctx = self.chat(self.team)
        bank = memory._binding(ctx['chat_id'])['bank']
        with patch.dict(os.environ, RUNTEAMS_HINDSIGHT_KEY_FILE='legacy'), patch.object(memory, '_legacy_text', return_value='旧版偏好') as fetch:
            old = memory.read(bank)
            self.assertEqual(old['text'], '旧版偏好')
            memory.save(bank, '', old['revision'])
            self.assertEqual(memory.read(bank)['text'], '')
            fetch.assert_called_once_with(bank)

    def test_plain_chat_has_no_asset_knowledge(self):
        general = {'chat_id': product_store.create_chat(channel_id=1)}
        self.assertEqual(memory.turn(general), '')
        self.assertNotIn('asset_memory_binding', general)

    def test_uploaded_source_survives_chat_deletion_and_replacement(self):
        from runteams_core.conversations import chat_attachments
        source, fresh = self.chat(self.team), self.chat(self.team)
        other = self.chat(pipeline_references.reference('2' * 64, 'pipelines/team.json'))
        def upload(ctx, text):
            data = base64.b64encode(text.encode()).decode()
            items = chat_attachments.save(ctx['chat_id'], [{'name':'品牌手册.md', 'data':data}])
            product_store.add_chat_message(ctx['chat_id'], 'user', '附件', attachments=items)
        upload(source, '独立资料原文')
        memory.turn(fresh)
        saved = memory.tool({'action':'sources'}, fresh).data['sources'][0]
        request = {'action':'excerpt','source':saved['id']}
        self.assertEqual(memory.tool(request, fresh).data['text'], '独立资料原文')
        memory.turn(other)
        with self.assertRaises(ValueError):
            memory.tool(request, other)
        chat_attachments.remove_chat(source['chat_id'])
        self.assertEqual(memory.tool(request, fresh).data['text'], '独立资料原文')
        upload(fresh, '修改后的资料')
        self.assertEqual(memory.tool(request, fresh).data['text'], '修改后的资料')

    def test_drawer_and_chat_share_sources_and_isolate_other_assets(self):
        from runteams_core.conversations import asset_sources
        from runteams_core.pipelines.bound_pipeline_context import BoundPipelineContext
        fresh = self.chat(self.team)
        with patch.object(BoundPipelineContext, 'definition', return_value=('rev', {})):
            owner = {'reference': self.team}
            upload = {**owner, 'name': 'brief.md', 'data': base64.b64encode(b'first').decode(), 'replace': False}
            self.assertEqual(asset_sources.drawer(owner)['total'], 0)
            self.assertTrue(asset_sources.drawer(upload)['saved'])
            self.assertTrue(asset_sources.drawer(upload)['duplicate'])
            self.assertTrue(asset_sources.drawer({**upload, 'replace': True, 'data': 'bmV3'})['saved'])
            self.assertEqual(asset_sources.drawer(owner)['total'], 1)
            memory.turn(fresh)
            source = memory.tool({'action': 'sources'}, fresh).data['sources'][0]
            excerpt = {'source': source['id'], 'page': 1, 'offset': 0}
            self.assertEqual(asset_sources.drawer({**owner, **excerpt})['text'], 'new')
            other = {'reference': pipeline_references.reference('2' * 64, 'pipelines/team.json')}
            self.assertEqual(asset_sources.drawer(other)['total'], 0)
            with self.assertRaises(ValueError):
                asset_sources.drawer({**other, **excerpt})

    def test_expanding_drawer_returns_whole_catalog_without_changing_agent_pagination(self):
        from runteams_core.conversations import asset_sources
        from runteams_core.pipelines.bound_pipeline_context import BoundPipelineContext
        from runteams_core.storage import device_data
        bank = memory.bank_for(self.team)
        with device_data.connect() as connection:
            for i in range(asset_sources.CATALOG_SIZE + 1):
                asset_sources._store(connection, bank, f'{i:02}.md', b'note', ['note'])
        owner = {'reference': self.team}
        with patch.object(BoundPipelineContext, 'definition', return_value=('revision', {})):
            expanded = asset_sources.drawer({**owner, 'expanded': True})
        self.assertEqual(len(expanded['sources']), expanded['total'])
        self.assertEqual(expanded['sources'][-1]['name'], f'{asset_sources.CATALOG_SIZE:02}.md')
        self.assertIsNone(expanded['next_offset'])
        self.assertEqual(asset_sources.catalog(bank)['next_offset'], asset_sources.CATALOG_SIZE)

    def test_same_name_binary_and_bundled_remain_private_and_portable(self):
        from runteams_core.assets import knowledge_archive, bundled_knowledge
        from runteams_core.authoring.creator_contracts import canonical, tree
        from runteams_core.authoring.source import knowledge_packages
        from runteams_core.authoring.source.creator_local_source import current_store
        from runteams_core.conversations import asset_sources
        from runteams_core.pipelines.bound_pipeline_context import BoundPipelineContext
        from runteams_core.storage import device_data
        with TemporaryDirectory() as root, patch.object(BoundPipelineContext, 'definition', return_value=('revision', {})):
            path = Path(root)
            docs = path/'docs'
            docs.mkdir()
            (docs/'logo.png').write_bytes(b'bundled-logo')
            team_docs = path/'team-docs'
            team_docs.mkdir()
            (team_docs/'guide.md').write_text('quote this line')
            owner = 'pipelines/team.json'
            member = 'employees/designer.json'
            outsider = 'employees/unrelated.json'
            private_folder = path/'unrelated'
            private_folder.mkdir()
            (private_folder/'other.md').write_text('not on the team')
            files, blobs = knowledge_archive.inventory({
                'project.json':canonical({'entrypoints':{'employees':[member, outsider],'pipelines':[owner]}}),
                owner:canonical({'employees':[{'ref':'designer','source':member}]}),
                member:canonical({'name':'视觉设计师'}),
            }, {owner:team_docs, member:docs, outsider:private_folder})
            archive = path/'source.zip'
            knowledge_archive.write_archive(archive, files, blobs.__getitem__)
            store = current_store(device_data.identity()['cache_scope'])
            report = {'scope':'local-preflight','source':tree(files),'employees':0,'pipelines':1,
                      'dependencies':[],'project':{'key':'team','version':'1','name':'Team'}}
            sid = knowledge_packages.receive(store, archive, lambda _:report)['id']
            ref = pipeline_references.reference(sid, owner)
            drawer = {'reference':ref}
            self.assertTrue(asset_sources.drawer({**drawer, 'replace':False,'name':'logo.png','data':'bXk='})['saved'])
            from runteams_core.employees import employee_references
            member_ref = employee_references.source_reference(sid, member)
            member_bank = memory.bank_for(member_ref)
            with device_data.connect() as connection:
                asset_sources._store(connection, member_bank, 'private.md', b'personal note', ['personal note'])
            items = asset_sources.drawer(drawer)
            self.assertEqual(items['total'],3)
            self.assertCountEqual([item['name'] for item in items['sources']], ['guide.md','logo.png','logo.png'])
            member_items = asset_sources.catalog(member_bank, bundled=bundled_knowledge.catalog(member_ref))
            self.assertCountEqual([item['name'] for item in member_items['sources']], ['private.md','logo.png'])
            self.assertEqual([i['origin'] for i in items['sources']].count('bundled'),2)
            self.assertEqual([(i['name'],i.get('employee_name')) for i in items['sources'] if i['origin']=='bundled'],
                             [('guide.md',None),('logo.png','视觉设计师')])

            ctx = self.chat(ref)
            ctx['runtime'] = {'cwd':str(path)}
            self.assertIn('guide.md', memory.turn(ctx))
            for item in items['sources']:
                if item['name']=='guide.md':
                    self.assertEqual(memory.tool({'action':'excerpt','source':item['id']},ctx).data['text'],'quote this line')
                else:
                    result = memory.tool({'action':'original','source':item['id']},ctx).data
                    self.assertEqual(Path(result['path']).read_bytes(),b'my' if item['origin']=='personal' else b'bundled-logo')
            with knowledge_packages.download(store,sid,sid) as (stream,_):
                archive.write_bytes(stream.read())
            staging=path/'exported'
            staging.mkdir()
            knowledge_archive.unpack(archive,staging)
            self.assertEqual(sorted(f.read_bytes() for f in staging.iterdir()),[b'bundled-logo',b'not on the team',b'quote this line'])
            other=self.chat(self.team)
            memory.turn(other)
            bundled_id=next(iter(bundled_knowledge.catalog(ref)))
            with self.assertRaises(ValueError):
                memory.tool({'action':'original','source':bundled_id},other)

    def test_large_import_is_atomic_scoped_and_keeps_every_byte(self):
        from runteams_core.conversations import asset_sources as sources
        bank = memory.bank_for(self.team)
        name = 'large.txt'
        block = b'a' * sources.UPLOAD_CHUNK
        chunks = [block] * 5 + [b'last line']
        size = sum(map(len, chunks))
        token = sources._upload(bank, {'upload':'begin','name':name,'size':size})['upload']
        offset = 0
        for chunk in chunks:
            request = {'upload':token,'offset':offset,'chunk':base64.b64encode(chunk).decode()}
            with self.assertRaises(ValueError):
                sources._upload('different-bank', request)
            result = sources._upload(bank, request)
            self.assertEqual(sources._upload(bank, request), result)
            offset += len(chunk)
        self.assertEqual(sources.catalog(bank)['total'], 0)
        self.assertTrue(sources._upload(bank, {'upload':token,'replace':False})['saved'])
        item, = sources.catalog(bank)['sources']
        self.assertEqual(sources.excerpt(bank, item['id'], item['pages'], 0)['text'], 'last line')
        with TemporaryDirectory() as directory:
            saved = sources.original(bank, item['id'], {}, directory)
            self.assertEqual(Path(saved['path']).read_bytes(), b''.join(chunks))
        token = sources._upload(bank, {'upload':'begin','name':name,'size':0})['upload']
        self.assertTrue(sources._upload(bank, {'upload':token,'replace':False})['duplicate'])
        sources._upload(bank, {'upload':token,'cancel':True})
        self.assertEqual(sources.catalog(bank)['sources'], [item])

    def test_upgrade_old_library_and_import_pdf_by_physical_page(self):
        import sqlite3
        from runteams_core.storage import device_data
        from runteams_core.conversations import chat_attachments
        db = device_data.root() / 'personal.sqlite3'
        with sqlite3.connect(db) as c:
            c.executescript(device_data.schema(5))
            c.execute('PRAGMA user_version=5')
            c.execute("INSERT INTO device_settings VALUES('existing','true')")
        source, fresh = self.chat(self.team), self.chat(self.team)
        fixture = Path(__file__).parent / 'fixtures/two-pages.pdf'
        uploads = [{'name':'两页.pdf','data':base64.b64encode(fixture.read_bytes()).decode()}]
        items = chat_attachments.save(source['chat_id'], uploads)
        product_store.add_chat_message(source['chat_id'], 'user', '参考资料', attachments=items)
        memory.turn(fresh)
        doc = memory.tool({'action':'sources'}, fresh).data['sources'][0]
        self.assertEqual(doc['pages'], 2)
        result = memory.tool({'action':'excerpt','source':doc['id'],'page':2}, fresh).data
        self.assertIn('Page 2 content', result['text'])
        with device_data.connect(readonly=True) as c:
            self.assertEqual(c.execute("SELECT value FROM device_settings WHERE key='existing'").fetchone()[0], 'true')

    def test_history_pages_quotes_and_isolation(self):
        from runteams_core.conversations import asset_history
        from runteams_core.storage import device_data
        from runteams_core.authoring.creator_contracts import digest
        earlier, fresh = self.chat(self.team), self.chat(self.team)
        other = self.chat(pipeline_references.reference('2' * 64, 'pipelines/team.json'))
        memory.turn(fresh)
        def send(chat, role, text):
            return product_store.add_chat_message(chat['chat_id'], role, text)
        def query(**kwargs):
            return memory.tool(kwargs, fresh).data
        words = '原话，保留标点！' * 900
        identifier = send(earlier, 'user', words)
        send(earlier, 'system', 'invisible')
        for i in range(asset_history.PAGE):
            send(earlier, 'bot', str(i))
        foreign = send(other, 'user', '他人原话')
        first = query(action='history')
        send(fresh, 'user', '在翻页之后发送')
        last = query(action='history', before=first['next_before'])
        self.assertIsNone(last['next_before'])
        self.assertEqual([m['message'] for m in last['messages']], [identifier])
        m = last['messages'][0]
        self.assertEqual((m['role'], m['chat'], m['conversation_url']),
                         ('user', earlier['chat_id'], '/pipelines/' + digest(self.team)[:32] + '/chats/' + device_data.public_id(earlier['chat_id'])))
        text = m['text']
        while m['next_offset'] is not None:
            m = query(action='history_message', message=identifier, offset=m['next_offset'])
            text += m['text']
        self.assertEqual(text, words)
        self.assertEqual(query(action='history', chat=other['chat_id'])['messages'], [])
        for args in ({'action':'history', 'before':foreign}, {'action':'history_message', 'message':foreign},
                     {'action':'history_message', 'message':True}):
            with self.assertRaises(ValueError):
                query(**args)
        product_store.delete_chat(earlier['chat_id'])
        with self.assertRaises(ValueError):
            query(action='history_message', message=identifier)

    def test_new_team_discussion_retries_and_preserves_board_chat(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from uuid import uuid4
        from runteams_core.pipelines import source_pipeline_workspace as workspace
        core = SimpleNamespace(_actor=lambda: True)
        source = SimpleNamespace(locked=nullcontext)
        runtime = {'channel_id': 1}
        with patch.object(workspace, '_definition', return_value=(None, {'pipeline': {'name': '编辑部'}}, None)), \
                patch.object(workspace.work, 'source', return_value=source):
            token = str(uuid4())
            def open_chat(**params):
                return workspace.conversation(core, self.team, runtime, **params)['session']
            fresh = open_chat(discussion_id=token)
            board = open_chat()
            self.assertNotEqual(board['id'], fresh['id'])
            self.assertEqual(board['id'], open_chat()['id'])
            self.assertEqual(fresh['id'], open_chat(discussion_id=token)['id'])
            self.assertNotEqual(fresh['id'], open_chat(discussion_id=str(uuid4()))['id'])
            self.assertEqual(fresh['context']['source_pipeline_workspace'], self.team)

    def test_employee_history_supports_legacy_identity_and_skips_work(self):
        from runteams_core.conversations import asset_history
        from runteams_core.storage import device_data
        employee, work = self.chat(self.team), self.chat(self.team)
        for ctx in (employee, work):
            product_store.add_chat_message(ctx['chat_id'], 'user', '访问自己的记录')
        with device_data.connect() as c:
            c.execute("UPDATE chats SET subject_type='employee',employee_id=9,context_json='{}' WHERE id=?",
                      (employee['chat_id'],))
            c.execute("""UPDATE chats SET subject_type='employee',employee_id=9,
                         context_json='{"employee_work":{"id":1}}' WHERE id=?""", (work['chat_id'],))
        owner = {'bank': 'legacy', 'writable': True, 'reference': {'resource':'employees', 'id':9}}
        with patch.object(memory, '_binding', return_value=owner):
            page = asset_history.query({'action':'history'}, owner, employee['chat_id'])
            self.assertEqual([r['chat'] for r in page['messages']], [employee['chat_id']])

    def test_workbook_preview_and_new_chat_use_original_sheet_and_row(self):
        from io import BytesIO
        from openpyxl import Workbook
        from runteams_core.conversations import asset_sources
        book = Workbook()
        book.active.title = '草案'
        book.active['C17'] = '旧标记'
        book.create_sheet('正式')['C29'] = '新标记'
        book.create_sheet('空表')
        stream = BytesIO()
        book.save(stream)
        source_chat = self.chat(self.team)
        bank = memory._binding(source_chat['chat_id'])['bank']
        asset_sources._save_upload(bank, '进度.xlsx', stream, stream.tell(), False)
        fresh = self.chat(self.team)
        memory.turn(fresh)
        source, = memory.tool({'action':'sources'}, fresh).data['sources']
        sheets = asset_sources.open_original(bank, source['id'], {})['sheets']
        self.assertEqual([s['name'] for s in sheets], ['草案', '正式', '空表'])
        self.assertEqual(sheets[1]['rows'], [(29, ['', '', '新标记'])])
        self.assertEqual(sheets[2]['rows'], [])
        citation = memory.tool({'action':'excerpt', 'source':source['id'], 'page':2}, fresh).data
        self.assertIn('工作表「正式」', citation['text'])
        self.assertIn('第29行\t\t\t新标记', citation['text'])
        self.assertNotIn('旧标记', citation['text'])
