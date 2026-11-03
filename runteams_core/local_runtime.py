"""Account-free composition of shared CLI channels, device chat records and runner.

Personal chats and verified SDK employee conversations share this native host.
Pipeline admission retains its independent owner.
"""
from contextlib import contextmanager, nullcontext
from pathlib import Path
import sqlite3
import os
import json
import re
import threading
import uuid


def handles(path):
    return path in {'/api/channels', '/api/model-catalog', '/api/channel-usage',
                    '/api/environment', '/api/environment/capabilities', '/api/app-info', '/api/attachments/pick', '/api/work-folders', '/api/chats', '/api/conversations', '/api/device/page-ids'} or bool(
        re.fullmatch(r'/api/work-folders/(?:pick|clear|bind|open)', path) or
        re.fullmatch(r'/api/chat/[1-9][0-9]*/attachment/[a-f0-9]{24}', path) or
        re.fullmatch(r'/api/channel/[1-9][0-9]*/(?:probe|connect|remove)', path) or
        re.fullmatch(r'/api/chat/[1-9][0-9]*(?:/(?:config|rename|delete|cancel|interaction|stream))?', path))


class LocalInputError(ValueError):
    pass


from .local_host_lock import RuntimeBusy


class LocalRuntime:
    def __init__(self, application):
        import local_database
        # Process composition, never request-time environment switching.
        if Path(local_database.DB_PATH).resolve().parent != application.data_directory:
            raise ValueError('本机运行目录未绑定，请通过免费版正式入口启动。')
        self.app = application
        self.lock = threading.RLock()
        self.active = {}
        self.source_builds = {}
        self.employee_jobs = {}
        self._pending_work_wakes=set()
        self._work_core = None
        self._employee_mcp = None
        self._pipeline_mcp = None
        self._schedules=None
        self._work_router=None
        self._browser_work=None
        self.closing = False
        self.picker_cancel = threading.Event()
        self.picker_lock = threading.Lock()
        self.lease=application.own()
        import product_store
        self.store = product_store
        self.store.init_host_db()
        with self.scope():
            from . import device_data
            # An exclusive owner may finalize accepted but unfinished turns.
            with device_data.connect() as c:
                rows = c.execute("SELECT m.chat_id,m.metadata FROM chat_messages m JOIN chats c ON c.id=m.chat_id WHERE m.role='user' AND c.scope_type='global' AND json_type(c.context_json,'$.pipeline_work') IS NULL").fetchall()
                for row in rows:
                    op = json.loads(row['metadata'] or '{}').get('local_turn_id')
                    if op and not self.completed(row['chat_id'], op):
                        self.finish(row['chat_id'], op, '上次对话因应用退出而中断，可以继续发送。', stopped=True)

    def schedule_host(self):
        with self.lock:
            if self._schedules is None:
                from .local_schedules import LocalSchedules
                self._schedules=LocalSchedules(self)
            return self._schedules

    def activate_employee_host(self):
        with self.app.request(),self.scope():
            from .device_work import database_path
            if database_path().is_file():
                core=self.work_core()
                with core.repository.connect() as connection:
                    rows=connection.execute("SELECT wr.id FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id WHERE wr.state='ready' AND "+core._workflow_claim_filter()).fetchall()
                self.schedule_employee_work([{'workflow_id':row[0]} for row in rows])
            self.schedule_host().activate_existing()

    def work_core(self,**options):
        with self.lock,self.scope():
            if self._work_core is None:
                from .local_work_core import LocalWorkCore
                self._work_core=LocalWorkCore(channel_resolver=self.store.get_channel)
                self._work_core.chat_executor=self.execute_employee_chat
                self._work_core.pipeline_program_control=self.pipeline_program_control
                self._work_core.recover_interrupted_workflows()
            return self._work_core

    def employee_chat(self,value):
        context=value.get('context') or {}
        if not context.get('local_employee_package'):return False
        if context.get('pipeline_work'):
            from .source_pipeline_work import verify_context
            verify_context(context['pipeline_work'],context['local_employee_package'])
        from .source_employee_runtime import for_chat
        employee=for_chat(value['id'])
        if not employee:raise PermissionError('员工工作引用无效。')
        return True

    def pipeline_chat(self,value):
        if not (value or {}).get('context',{}).get('source_pipeline_workspace'):return False
        from .pipeline_chat_binding import reference
        reference(value['id'])
        return True

    @contextmanager
    def employee_operation_scope(self):
        with self.app.request(),self.scope():yield

    def work_router(self):
        with self.lock,self.scope():
            if self._work_router is None:
                from .creator_work_router import CreatorOwnerRouter
                def employee_owner(chat,workspace):
                    with self.employee_operation_scope():
                        if workspace:return None
                        session=self.chat(chat,include_live=False)
                        if self.pipeline_chat(session):return self.pipeline_mcp_work().native_owner()
                        return self.employee_mcp_work().native_owner() if self.employee_chat(session) else None
                self._work_router=CreatorOwnerRouter(lambda:None,device_owner=employee_owner)
            return self._work_router

    def browser_work(self,body,origin):
        with self.lock:
            if self._browser_work is None:
                from .browser_work_host import BrowserWorkHost
                self._browser_work=BrowserWorkHost(self.work_router(),lambda:('local-library',self.app.binding.library_id,self.app.backups.generation))
        return self._browser_work.call(body,origin)

    def retire_employee_services(self):
        if self._schedules:self._schedules.stop()
        with self.scope():
            if self._browser_work:self._browser_work.close();self._browser_work=None
            if self._pipeline_mcp:self._pipeline_mcp.close();self._pipeline_mcp=None
            if self._employee_mcp:self._employee_mcp.close();self._employee_mcp=None
            self._work_core=None

    def employee_mcp_work(self):
        with self.lock,self.scope():
            if self._employee_mcp is None:
                from .device_employee_mcp import EmployeeMCPWork
                from .employee_mcp import platform_runtime,MCPError
                try:runtime=platform_runtime()
                except MCPError:runtime=None
                self._employee_mcp=EmployeeMCPWork(runtime,operation_scope=self.employee_operation_scope)
            self._employee_mcp.check()
            return self._employee_mcp

    def pipeline_mcp_work(self):
        with self.lock,self.scope():
            if self._pipeline_mcp is None:
                from .device_pipeline_mcp import PipelineMCPWork
                self._pipeline_mcp=PipelineMCPWork(self.employee_mcp_work().runtime,self.work_core,self.activate_employee_host,operation_scope=self.employee_operation_scope)
            self._pipeline_mcp.check()
            return self._pipeline_mcp

    def pipeline_program_control(self,action,chats):
        from .device_pipeline_mcp import control_programs
        return control_programs(self,action,chats)

    def execute_employee_chat(self,chat_id,prompt,cancel,operation):
        operation=str(uuid.uuid5(uuid.NAMESPACE_URL,operation))
        with self.scope():
            session=self.store.get_chat(chat_id,include_messages=False)
            identifier=(session.get('context') or {}).get('employee_work',{}).get('workflow_id')
            if session.get('context',{}).get('pipeline_work'):
                from .employee_chat_work import snapshot
                frozen=snapshot(self.work_core(),identifier)
                if not frozen or frozen.get('work_chat_id')!=chat_id:raise PermissionError('原岗位工作未能确认。')
                repair=frozen.get('pipeline_result_correction') or {}
                if repair.get('admitted'):
                    operation=str(uuid.uuid5(uuid.UUID(operation),'correction:'+str(repair['submission_id'])+':'+str(repair['message_id'])))
        _,op=self.start(chat_id,{'message':prompt,'operation_id':operation},work_id=identifier)
        while True:
            with self.lock:turn=self.active.get(chat_id)
            if turn is None:break
            if cancel.is_set():turn['cancel'].set();turn['cancel'].questions.close()
            turn['done'].wait(.1)
        with self.scope():result=self.completed(chat_id,op)
        if not result:return 'interrupted','工作回复尚未确认，请查看原对话。'
        return ('cancelled' if result.get('incomplete') else 'failed' if result.get('failed') else 'completed'),result['reply']

    def schedule_employee_work(self,cards):
        for card in cards:
            identifier=card['workflow_id']
            with self.lock:
                if self.closing:continue
                if identifier in self.employee_jobs:
                    self._pending_work_wakes.add(identifier);continue
                # Keep maintenance/restore out until the admitted worker settles.
                lease=self.app.request();lease.__enter__()
                def run(identifier=identifier,lease=lease):
                    try:
                        with self.scope():
                            core=self.work_core()
                            with core.repository.audit_context(actor_id=self.app.binding.library_id,source='executor'):
                                while not self.closing:
                                    claimed=core.claim_workflow(identifier)
                                    if claimed is None:break
                                    try:core.execute_claimed_workflow(claimed,core.runtime())
                                    except Exception as error:
                                        from .employee_chat_work import finish,snapshot
                                        frozen=snapshot(core,claimed)
                                        finish(core,claimed,'interrupted' if frozen.get('send_admitted') else 'blocked',str(error),visit=frozen.get('pipeline_visit'))
                                        break
                    finally:
                        with self.lock:
                            self.employee_jobs.pop(identifier,None)
                            repeat=identifier in self._pending_work_wakes
                            self._pending_work_wakes.discard(identifier)
                        lease.__exit__(None,None,None)
                        if repeat:self.schedule_employee_work([{'workflow_id':identifier}])
                thread=threading.Thread(target=run,name='local-employee-work',daemon=False)
                self.employee_jobs[identifier]=thread;thread.start()

    @contextmanager
    def scope(self):
        from .storage_context import using
        self.app.check()
        with using(self.app.provider):
            yield
            self.app.check()

    def close(self):
        with self.lock:
            if self.lease is None:
                return
            self.closing = True
            self.picker_cancel.set()
            active = list(self.active.values())
            jobs=list(self.employee_jobs.values())
            if self._work_core:
                for event in self._work_core._cancel_events.values():event.set()
            builds = list(self.source_builds.values())
            with self.scope():
                for job in builds:job['builds'].cancel(job['operation'])
            for turn in active:
                turn['cancel'].set()
        if self._schedules:self._schedules.stop()
        for turn in active:
            turn['thread'].join(timeout=15)
        if any(t['thread'].is_alive() for t in active):
            raise RuntimeError('对话仍在停止，运行锁保持。')
        for thread in jobs:thread.join(timeout=15)
        if any(thread.is_alive() for thread in jobs):raise RuntimeError('员工工作仍在停止，运行锁保持。')
        with self.scope():
            self.retire_employee_services()
            if self._work_router:self._work_router.close();self._work_router=None
        for job in builds:job['thread'].join(timeout=15)
        if any(job['thread'].is_alive() for job in builds):
            raise RuntimeError('源码构建仍在停止，运行锁保持。')
        if not self.picker_lock.acquire(timeout=15):
            raise RuntimeError('资料选择仍在结束，运行锁保持。')
        try:
            import chat_attachments
            chat_attachments.discard_native_selections(self.app.binding.scope)
        finally:
            self.picker_lock.release()
        self.lease.rollback()
        self.lease.close()
        self.lease = None

    def completed(self, chat_id, operation):
        from . import device_data
        with device_data.connect(readonly=True) as c:
            for row in c.execute("SELECT id,text,applied,metadata FROM chat_messages WHERE chat_id=? AND role='bot' ORDER BY id DESC", (chat_id,)):
                meta = json.loads(row['metadata'] or '{}')
                if meta.get('local_turn_id') == operation:
                    from .local_documents import LocalDocuments
                    return {'type': 'result', 'message_id': row['id'], 'reply': row['text'],
                            'failed': bool(meta.get('failed')), 'incomplete': bool(meta.get('stopped')),
                            'applied':json.loads(row['applied'] or '[]'),'run_cards':meta.get('run_cards',[]),
                            **({'session':self.public_chat(self.chat(chat_id,include_live=False))} if self.source_chat(self.store.get_chat(chat_id,include_messages=False)) else {}),
                            **({'device_page_ids':self.work_core().page_ids()} if json.loads(row['applied'] or '[]') else {})}
        return None

    def finish(self, chat_id, operation, text, *, stopped=False, failed=False, events=None, document_result=None):
        if not self.completed(chat_id, operation):
            if document_result is None:
                from .local_document_tools import receipt
                document_result=receipt(chat_id,operation)
            self.store.add_chat_message(chat_id, 'bot', text, applied=(document_result or {}).get('applied',[]), metadata={
                'local_turn_id': operation, 'stopped': stopped, 'failed': failed,'run_cards':(document_result or {}).get('run_cards',[]),
                'trace': {'complete': not stopped, 'cancelled': stopped, 'failed': failed,
                          'events': __import__('agent_stream').present_trace_events(events or [])}})
        return self.completed(chat_id, operation)

    def chat(self, chat_id, data=None, *, include_live=True):
        from . import device_data
        from .employee_session_view import work_session_record
        if not device_data.contains(chat_id):
            raise KeyError('本机对话不存在。')
        data = data or {}
        value = self.store.get_chat(chat_id, message_limit=int(data['messages_limit']) if 'messages_limit' in data else None,
                                    message_cursor=data.get('cursor'))
        if not value or (value['subject_type'] != 'workspace' and not work_session_record(value)) or value['scope_type'] != 'global' :
            raise KeyError('普通本机对话不存在。')
        self.pipeline_chat(value)
        if value.get('kind') != 'general' and not self.source_chat(value):
            raise KeyError('本机对话不存在。')
        if any(m.get('applied') for m in value.get('messages',[])):
            from .local_documents import LocalDocuments
            value['device_page_ids']=self.work_core().page_ids()
        if include_live:
            value['active_turn'] = self.interaction(chat_id)
        return value

    def interaction(self, chat_id):
        turn = self.active.get(chat_id)
        if not turn:
            answers = [m['metadata']['question_receipt'] for m in self.store.get_chat(chat_id)['messages']
                       if m.get('metadata', {}).get('question_receipt')]
            return {'active': False, 'requests': [], 'answers': answers, 'can_steer': False}
        broker = turn['cancel'].questions
        return {'active': True, 'requests': broker.pending(broker.owner),
                'answers': broker.receipts(broker.owner), 'can_steer': False,
                'events': [e['event'] for e in turn['events'] if e['type'] == 'agent_event']}

    def public_chat(self, value):
        import chat_attachments
        from .employee_session_view import public_session,work_session_record
        if work_session_record(value) or self.source_chat(value):
            value=public_session(value)
        if value.get('kind') == 'employee_design':
            from .creator_local_authoring import source
            from .creator_contracts import strict_json
            try:
                files = source(value).files()
                project = strict_json(files['project.json'])
                paths = project['entrypoints']['employees']
                path = value['context'].get('creator_employee_source') or (paths[0] if len(paths)==1 else None)
                employee = strict_json(files[path])
                if not isinstance(employee.get('name'),str) or not isinstance(employee.get('avatar'),str):
                    raise ValueError('员工源码身份无效。')
                from .employee_avatars import identity
                value = {**value,'identity':identity(employee, files=files)}
            except (KeyError,ValueError,OSError) as error:
                value = {**value,'employee_error':str(error)}
        return {**value, 'messages': [{**message, 'attachments': chat_attachments.public(message.get('attachments'))}
                                     for message in value['messages']]}

    def accepted(self, chat_id, message_id):
        import chat_attachments
        with self.scope():
            value = self.store.get_chat_message(chat_id, message_id)
            return {'type': 'accepted', 'message_id': message_id,
                    'operation_id': value['metadata']['local_turn_id'],
                    'attachments': chat_attachments.public(value.get('attachments')), 'capabilities': value.get('capabilities') or []}

    def answer(self, chat_id, data):
        from .local_conversation_inputs import request_digest
        request_id, answers = data.get('request_id'), data.get('answers')
        digest = request_digest({'message': json.dumps(answers, ensure_ascii=False, sort_keys=True)})
        turn = self.active.get(chat_id)
        if not turn:
            for message in self.store.get_chat(chat_id)['messages']:
                meta = message.get('metadata') or {}
                if meta.get('question_request_id') == request_id and meta.get('question_digest') == digest:
                    return meta['question_receipt']
            raise ValueError('这个问题已结束，请重新打开对话查看已保存的回答。')
        broker = turn['cancel'].questions
        def accept(prompt, public):
            text = '\n'.join(q['question'] + '：' + '、'.join(public[q['id']]['answers']) for q in prompt['questions'])
            # Shared broker redacts secret answers before this persistence hook.
            details = {'question_request_id': prompt['id'], 'question_summary': '已回答助手提问',
                       **({} if any(q['isSecret'] for q in prompt['questions']) else {'question_digest': digest})}
            from . import device_data
            with device_data.connect() as c:
                message = self.store.add_chat_question_answer(chat_id, text, details)
                receipt = {'accepted': True, 'id': prompt['id'], 'message': message}
                saved = {**details, 'question_receipt': receipt}
                c.execute('UPDATE chat_messages SET metadata=? WHERE chat_id=? AND id=?',
                          (json.dumps(saved, ensure_ascii=False), chat_id, message['id']))
            return {'message': message}
        return broker.answer(request_id, answers, broker.owner, accept=accept)

    def source_chat(self, value):
        from .creator_local_authoring import valid_context, source
        context = value.get('context') or {}
        if value.get('kind') != 'employee_design' or not valid_context(context):
            return False
        if context.get('creator_local_scope') != self.app.binding.scope['cache_scope']:
            raise PermissionError('源码资料库已变化。')
        source(value).current()
        return True

    def config(self, data, *, session=None):
        import model_channels
        authoring = bool(session and self.source_chat(session))
        pipeline = bool(session and self.pipeline_chat(session))
        if pipeline:
            if data.get('context') not in (None,session['context']):raise ValueError('流水线绑定不能由运行设置修改。')
            data={**data,'context':{}}
        employee = bool(session and self.employee_chat(session))
        if employee:
            from .source_employee_runtime import work_config_context
            worker_context=work_config_context(session,data.get('context'))
            data={**data,'subject_type':'workspace','context':{}}
        if authoring:
            if data.get('context') not in (None, session['context']):
                raise ValueError('源码绑定不能由运行设置修改。')
            data = {**data, 'kind':'general', 'context':{}}
        if data.get('kind', 'general') != 'general' or data.get('subject_type', 'workspace') != 'workspace' or data.get('scope_type', 'global') != 'global' or any(data.get(key) for key in ('scope_pipeline_id', 'scope_run_id', 'employee_id', 'employee_release_id')):
            raise ValueError('请从原员工或流水线入口打开工作会话。')
        context = data.get('context') or {}
        if not isinstance(context, dict) or context.get('domain', 'general') != 'general' or {'pipeline_id','employee_id','local_employee_package','source_pipeline_workspace','pipeline_work','employee_work','pipeline_generation','creator_work','creator_local_source_id','creator_local_scope','creator_authoring','creator_employee_source'} & context.keys():
            raise ValueError('此入口只接受普通本机对话。')
        channel = self.store.get_channel(data['channel_id']) if data.get('channel_id') else self.store.get_default_channel()
        if not channel or not channel.get('enabled'):
            raise ValueError('请先连接模型渠道。')
        model, effort = model_channels.normalize_selection(channel, data.get('model', ''), data.get('reasoning_effort', ''))
        return channel, model, effort, session['context'] if authoring or pipeline else (worker_context if employee else context)

    def dispatch(self, method, path, data):
        import model_channels
        metadata = path == '/api/attachments/pick' or method == 'GET' or path.endswith(('/interaction', '/cancel')) or path in {'/api/channels','/api/model-catalog','/api/channel-usage','/api/environment'} or path.startswith('/api/channel/')
        with (nullcontext() if metadata or path.startswith('/api/work-folders') else self.lock), self.scope():
            if path.startswith('/api/work-folders'):
                from .local_conversation_folders import dispatch
                return dispatch(self, method, path, data)
            if method == 'GET' and path == '/api/app-info':
                import chat_attachments
                return {'native_attachment_picker': bool(os.environ.get('RUNTEAMS_ATTACHMENT_PICKER')) and chat_attachments.native_picker_available()}
            if method == 'POST' and path == '/api/attachments/pick':
                import chat_attachments
                if data:
                    raise ValueError('附件选择请求无效。')
                if not os.environ.get('RUNTEAMS_ATTACHMENT_PICKER'):
                    raise ValueError('请使用浏览器文件选择器；文件夹资料请在本机桌面版选择。')
                if self.closing or not self.picker_lock.acquire(blocking=False):
                    raise RuntimeBusy('已有资料选择窗口，或应用正在退出。')
                try:
                    return {'items': chat_attachments.pick_native(cancel_event=self.picker_cancel)}
                finally:
                    self.picker_lock.release()
            attachment = re.fullmatch(r'/api/chat/([1-9][0-9]*)/attachment/([a-f0-9]{24})', path)
            if method == 'GET' and attachment:
                if data:
                    raise ValueError('附件读取不接受其他参数。')
                from .local_conversation_inputs import file_for
                return file_for(self, int(attachment[1]), attachment[2])
            if method == 'GET' and path == '/api/channels':
                return {'providers': model_channels.public_providers(), 'channels': [model_channels.public_channel(c) for c in self.store.list_channels()]}
            if method == 'GET' and path == '/api/model-catalog':
                import model_catalog_display
                channels = self.store.list_channels()
                if 'channel_ids' in data:
                    if not re.fullmatch(r'[1-9][0-9]*(?:,[1-9][0-9]*)*', data['channel_ids']):
                        raise ValueError('模型渠道选择无效。')
                    ids = {int(x) for x in data['channel_ids'].split(',')}
                    if not ids <= {c['id'] for c in channels}:
                        raise ValueError('模型渠道不存在。')
                    channels = [c for c in channels if c['id'] in ids]
                return model_catalog_display.catalog(channels, ('library', self.app.binding.library_id), refresh=data.get('refresh') == '1', wait=data.get('wait') == '1')
            if method == 'GET' and path == '/api/channel-usage':
                return model_channels.channels_usage(self.store.list_channels())
            if method == 'GET' and path == '/api/environment/capabilities':
                if data.keys() - {'channel_id','after','q','limit','chat_id'} or not re.fullmatch(r'[1-9][0-9]*', str(data.get('channel_id', ''))):
                    raise ValueError('技能查询无效。')
                channel = self.store.get_channel(int(data['channel_id']))
                if not channel:
                    raise KeyError('模型渠道不存在。')
                chat_id = data.get('chat_id')
                source_session = None
                if chat_id not in (None, '', 'new'):
                    if not str(chat_id).isdigit():raise ValueError('对话编号无效。')
                    chat_id = int(chat_id)
                    source_session = self.chat(chat_id, include_live=False)
                if source_session and self.source_chat(source_session):
                    from .creator_local_authoring import source, _work_root
                    workspace = _work_root(source(source_session),chat_id)/'source'
                    if workspace.is_symlink():raise ValueError('源码工作目录无效。')
                    folder={'available':True,'path':str(workspace),'id':source_session['context']['creator_local_source_id']}
                elif source_session and self.employee_chat(source_session):
                    from .employee_workspaces import workspace
                    folder={'available':True,'path':str(workspace(chat_id)),'id':str(chat_id)}
                else:
                    from .conversation_folders import read as read_folder
                    folder = read_folder(chat_id)
                if not folder['available']:raise ValueError('工作文件夹不可用，请重新选择。')
                import runtime_capabilities
                return runtime_capabilities.capability_page(channel, after=data.get('after',''), query=data.get('q',''),
                    limit=data.get('limit',40), workspace_root=folder['path'], installed_only=True, include_skills=True,
                    scope=json.dumps([self.app.binding.library_id, chat_id, folder['id']]))
            if method == 'GET' and path == '/api/environment':
                import runtime_capabilities
                channels = self.store.list_channels()
                status_only = 'channel_ids' not in data
                if not status_only:
                    ids = {int(x) for x in data['channel_ids'].split(',') if x}
                    if not ids <= {c['id'] for c in channels}:
                        raise ValueError('模型渠道不存在。')
                    channels = [c for c in channels if c['id'] in ids and c.get('enabled')]
                return runtime_capabilities.environment_summary(channels, refresh=data.get('refresh') == '1', status_only=status_only)
            match = re.fullmatch(r'/api/channel/([1-9][0-9]*)/(probe|connect|remove)', path)
            if method == 'POST' and match:
                cid, action = int(match[1]), match[2]
                channel = self.store.get_channel(cid)
                if not channel:
                    raise KeyError('渠道不存在。')
                if action != 'probe':
                    self.store.set_channel_enabled(cid, action == 'connect')
                channel = self.store.get_channel(cid)
                public = model_channels.public_channel(channel, with_status=action != 'remove')
                return {'channel': public, 'requires_login': bool(public.get('probe', {}).get('installed') and not public.get('probe', {}).get('authenticated'))}
            if method == 'GET' and path == '/api/device/page-ids':
                from . import device_data
                from .local_documents import LocalDocuments
                directory=device_data.page_ids()
                directory['items'].extend(self.work_core().page_ids())
                return directory
            if method == 'GET' and path == '/api/chats':
                from . import device_data
                from .employee_session_view import public_session,work_session_record
                rows = self.store.list_chats(device_only=True)
                rows = [{**row,'context':json.loads(row.get('context_json') or '{}')} for row in rows]
                rows = [row for row in rows if (row['subject_type'] == 'workspace' or work_session_record(row)) and row['scope_type'] == 'global' and not row['context'].get('source_pipeline_workspace')]
                rows = [row for row in rows if row.get('kind') == 'general' or self.source_chat(row)]
                return {'chats': [public_session(dict(row, public_id=device_data.public_id(row['id']))) for row in rows]}
            if method == 'POST' and path == '/api/conversations':
                channel, model, effort, context = self.config(data)
                cid = self.store.create_chat(channel['id'], model, effort, context=context)
                return {'session': self.public_chat(self.chat(cid))}
            match = re.fullmatch(r'/api/chat/([1-9][0-9]*)(?:/(config|rename|delete|cancel|interaction))?', path)
            if not match:
                raise KeyError('本机接口不存在。')
            cid, action = int(match[1]), match[2]
            chat = self.chat(cid, data if method == 'GET' and action is None else {}, include_live=method == 'GET')
            if method == 'GET' and action is None:
                return self.public_chat(chat)
            if method == 'GET' and action == 'interaction':
                return self.interaction(cid)
            if method == 'POST' and action == 'interaction':
                return self.answer(cid, data)
            if method == 'POST' and action == 'cancel':
                if cid in self.active:
                    self.active[cid]['cancel'].set()
                    self.active[cid]['cancel'].questions.close()
                return {'ok': True}
            if cid in self.active:
                raise RuntimeBusy('请先停止当前回复。')
            if method == 'POST' and action == 'config':
                channel, model, effort, context = self.config(data, session=chat)
                self.store.update_chat_config(cid, channel['id'], model, effort, context=context)
                return {'ok': True}
            if method == 'POST' and action == 'rename':
                title = data.get('title')
                if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
                    raise ValueError('对话名称无效。')
                self.store.rename_chat(cid, title)
                return {'ok': True}
            if method == 'POST' and action == 'delete':
                import chat_attachments
                self.store.delete_chat(cid)
                chat_attachments.remove_chat(cid)
                return {'ok': True}
            raise KeyError('本机接口不存在。')

    def start(self, chat_id, data, *, work_id=None):
        """Accept once durably, then run independently of the observing socket."""
        import model_channels
        supported = {'operation_id','message','attachments','attachment_tokens','reuse_attachment_ids',
                     'local_asset_ids','local_asset_bindings','capabilities','view_context','rewind_message_id'}
        if not isinstance(data, dict) or data.keys() - supported:
            raise ValueError('对话请求字段无效。')
        with self.lock, self.scope():
            if self.closing:
                raise RuntimeBusy('应用正在退出，请重新打开。')
            chat = self.chat(chat_id, include_live=False)
            if chat.get('context',{}).get('pipeline_work'):
                if work_id is None or work_id!=chat['context'].get('employee_work',{}).get('workflow_id'):
                    raise PermissionError('岗位执行只沿原流水线工作账本受理。')
                from .source_pipeline_control import check_chat_operation
                check_chat_operation(chat_id)
            operation = data.get('operation_id')
            if not isinstance(operation, str) or str(uuid.UUID(operation)) != operation:
                raise ValueError('对话操作标识无效。')
            message = data.get('message')
            if not isinstance(message, str) or not (message.strip() or data.get('attachments') or data.get('attachment_tokens') or data.get('reuse_attachment_ids') or data.get('local_asset_ids')) or len(message) > 100000:
                raise ValueError('请输入对话内容。')
            if any(data.get(key) for key in ('local_asset_ids','local_asset_bindings')) and not (self.employee_chat(chat) or self.source_chat(chat)):
                raise ValueError('请在绑定员工的会话中交办工作资料。')
            from .conversation_capabilities import _normalize_capabilities
            raw_capabilities = data.get('capabilities')
            if raw_capabilities is not None and (not isinstance(raw_capabilities, list) or any(not isinstance(item,dict) for item in raw_capabilities) or len(raw_capabilities)>12):
                raise ValueError('技能选择无效。')
            capabilities = _normalize_capabilities(raw_capabilities)
            if len(capabilities) != len(raw_capabilities or []):raise ValueError('技能选择无效。')
            from .local_conversation_inputs import request_digest, prepare
            digest = request_digest(data)
            if any(operation in m.get('metadata',{}).get('superseded_local_turns',{}) for m in chat['messages']):
                raise RuntimeBusy('这条消息已被回退替换，请重新打开当前对话。')
            prior = next((m for m in chat['messages'] if m.get('metadata', {}).get('local_turn_id') == operation and m['role'] == 'user'), None)
            if prior:
                if prior.get('metadata', {}).get('local_turn_request_sha256') != digest:
                    raise ValueError('原操作内容不能改变。')
                if chat_id not in self.active and not self.completed(chat_id, operation):
                    self.finish(chat_id, operation, '消息已保存，上次处理已中断。', stopped=True)
                return prior['id'], operation
            if chat_id in self.active:
                raise RuntimeBusy('当前对话正在回复。')
            rewind_id = data.get('rewind_message_id')
            rewind_source = None
            if rewind_id not in (None, ''):
                if isinstance(rewind_id,bool) or not str(rewind_id).isdigit():raise ValueError('要编辑的消息无效。')
                rewind_id = int(rewind_id)
                rewind_source = next((m for m in chat['messages'] if m['id']==rewind_id and m['role']=='user'),None)
                if not rewind_source:raise RuntimeBusy('要编辑的消息已经不存在，请重新打开当前对话。')
            channel, model, effort, _ = self.config(chat, session=chat)
            from .conversation_folders import runtime as folder_runtime
            # Source authoring owns its exact checkout; ordinary chats retain
            # their existing explicit folder authorization.
            authoring = self.source_chat(chat)
            employee=self.employee_chat(chat)
            configuration=None
            if employee:
                from .employee_configuration import admission
                configuration=admission(chat)
            from .employee_workspaces import workspace as employee_workspace
            workspace = None if authoring else Path(folder_runtime(chat_id, employee_workspace(chat_id) if employee else self.store.assistant_workspace()))
            mid, attachments = prepare(self, chat, data, operation, digest, capabilities=capabilities, rewind_source=rewind_source, employee_configuration=configuration)
            if rewind_source:
                chat = {**chat, 'messages': [m for m in chat['messages'] if m['id'] < rewind_id]}
            if chat.get('title_source') == 'pending':
                title = message
                for item in capabilities:
                    if item.get('mention_token'):title = title.replace(item['mention_token'], item['label'])
                self.store.rename_chat(chat_id, title.strip()[:60] or '附件对话')
            turn = {'cancel': threading.Event(), 'events': [], 'done': threading.Event(), 'operation': operation}
            if configuration is not None:
                turn['cancel'].employee_data_lease=(configuration['reference'],{'chat_id':chat_id,'message_id':mid})
            from agent_interaction import TurnQuestions
            turn['cancel'].questions = TurnQuestions(turn['cancel'], (self.app.binding.library_id, chat_id, operation))
            self.active[chat_id] = turn
            def run():
                from errors import Cancelled
                class Activity:
                    def __call__(self, *args): pass
                    def request_user_input(self, questions):
                        return turn['cancel'].questions.ask(questions, self.on_event)
                    def request_user_input_deferred(self, questions):
                        return turn['cancel'].questions.ask_deferred(questions, self.on_event)
                    def request_user_input_async(self, questions, submit=None):
                        return turn['cancel'].questions.ask_async(questions, self.on_event, submit)
                    def request_user_input_response(self, request_id):
                        return turn['cancel'].questions.response(request_id)
                    def request_user_input_expired(self, request_id):
                        return turn['cancel'].questions.expire(request_id)
                    def on_event(self, event):
                        with self_outer.lock:
                            # Reconnect uses saved final text; cap live observations.
                            if len(turn['events']) < 10000:
                                turn['events'].append({'type': 'agent_event', 'event': event})
                self_outer = self
                try:
                    with self.scope():
                        from .conversation_folders import runtime as folder_runtime
                        if not authoring and Path(folder_runtime(chat_id, employee_workspace(chat_id) if employee else self.store.assistant_workspace())) != workspace:
                            raise PermissionError('工作文件夹已变化，请重新打开对话。')
                        from .local_conversation_tools import run
                        activity = Activity()
                        from .creator_local_authoring import workspace as source_workspace
                        with (source_workspace(chat) if authoring else nullcontext(workspace)) as working:
                            text, incomplete = run(channel, chat, message, attachments, working, activity,
                                                   turn['cancel'], self.store, self.app.binding.library_id, capabilities, employee_host=self.employee_mcp_work() if employee else None, configuration=configuration)
                        if turn['cancel'].is_set():raise Cancelled('运行已停止')
                        from .local_conversation_tools import apply_completed
                        activity.document_result=apply_completed(chat_id,getattr(activity,'native_tool_results',[]),turn['cancel'])
                        turn['cancel'].questions.close()
                        final = self.finish(chat_id, operation, text, failed=incomplete, document_result=getattr(activity,'document_result',{}),
                            events=[e['event'] for e in turn['events'] if e['type'] == 'agent_event'])
                        self.schedule_employee_work(activity.document_result.get('run_cards',[]))
                except Cancelled:
                    turn['cancel'].questions.close()
                    with self.scope():
                        final = self.finish(chat_id, operation, '回复已停止。', stopped=True, events=[e['event'] for e in turn['events'] if e['type'] == 'agent_event'])
                except Exception as error:
                    turn['cancel'].questions.close()
                    with self.scope():
                        # Persist a recoverable failure; never rerun a user turn automatically.
                        final = self.finish(chat_id, operation, str(error)[:4000] or '模型未能完成回复，请检查渠道后重试。', failed=True, events=[e['event'] for e in turn['events'] if e['type'] == 'agent_event'])
                finally:
                    turn['cancel'].questions.close()
                    with self.scope():
                        from .managed_employee_data import release_turn
                        release_turn(turn['cancel'])
                    with self.lock:
                        turn['events'].append(final if 'final' in locals() else {'type': 'error', 'message': '回复保存失败，请重新打开对话确认。'})
                        turn['done'].set()
                        self.active.pop(chat_id, None)
            turn['thread'] = threading.Thread(target=run, name='local-conversation', daemon=False)
            turn['thread'].start()
            return mid, operation

    def observe(self, chat_id, operation):
        # No socket failure or window reload cancels an accepted turn.
        index = 0
        while True:
            with self.lock, self.scope():
                turn = self.active.get(chat_id)
                if turn and turn['operation'] == operation:
                    events = turn['events'][index:]
                    index += len(events)
                else:
                    result = self.completed(chat_id, operation)
                    events = [result] if result else [{'type': 'error', 'message': '回复状态未能确认，请重新打开对话。'}]
            for event in events:
                yield event
                if event['type'] in ('result', 'error'):
                    return
            if turn:
                turn['done'].wait(.1)
