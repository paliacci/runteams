"""Source SDK connections use the original work ledger and native HTTPS phases.

Only an actually admitted, active original MCP tool call may send. Events are
business receipts in the original library DB, never authority or a new store.
"""
from contextlib import contextmanager
import copy,json,re,threading
from collections import OrderedDict
from runteams_core.storage import device_data
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, digest
from runteams_core.authoring.creator_connection import PinnedHTTPS, prepared_request, ConnectionUnknown
from runteams_core.authoring.creator_sdk import sdk_frame
from runteams_core.configuration.connections.connection_exchange import exchange
from runteams_core.configuration.credentials.credential_redaction import redact_value
from runteams_core.foundation.identity.local_connection_identity import valid_binding, for_authority
from runteams_core.work.work_connections import for_host
from runteams_core.foundation.identity.work_identity import principal
from runteams_core.storage.storage_contracts import BusinessCloudUnknown

PREFIX='sdk-connection:'
REQUEST='sdk.connection.requested'
SETTLED='sdk.connection.settled'
SCHEMA='runteams.connection-call/1'
# Immutable JSON validation proofs only: no rows, replies, credentials, active
# state or permission decisions. Ownership/state are always read again.
_validated=OrderedDict();_validation_lock=threading.RLock()

def checked_content(value,check):
    key=digest(value)
    with _validation_lock:
        if key in _validated:_validated.move_to_end(key);return
    check()
    with _validation_lock:
        _validated[key]=True
        while len(_validated)>512:_validated.popitem(last=False)


def reply(frame,state,response=None):
    value={'abi':'runteams.sdk/1','id':frame['id'],'ok':state=='confirmed'}
    value.update(result=response) if value['ok'] else value.update(error={'code':'connection_failed' if state=='failed' else 'connection_unknown','retry':'read' if state=='failed' else 'reconcile'})
    return sdk_frame(value,reply=True)


def records(rows,scope):
    values={}
    for stream,kind,raw in rows:
        value=json.loads(raw)
        if kind not in (REQUEST,SETTLED) or not isinstance(value,dict) or value.get('schema')!=SCHEMA:raise ValueError('连接回执无效。')
        key=value.get('operation_key')
        if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('连接调用编号无效。')
        if kind==REQUEST:
            if set(value)!={'schema','operation_key','parent_call','binding','descriptor','params','semantic_sha256'} or key in values:raise ValueError('连接受理记录无效。')
            binding=value['binding']
            if (not valid_binding(binding) or binding['library_id']!=scope.get('library_id')
                    or stream!=PREFIX+digest(for_authority(binding)) or digest(value['descriptor'])!=binding['descriptor_sha256']
                    or not isinstance(value['parent_call'],str) or not re.fullmatch('[a-f0-9]{64}',value['parent_call'])):raise ValueError('连接回执归属无效。')
            checked_content(value,lambda:prepared_request(value['descriptor'],value['params']))
            if value['params'].get('operation_key',key)!=key:raise ValueError('连接编号与原请求不符。')
            if value['semantic_sha256']!=digest({k:v for k,v in value['params'].items() if k!='operation_key'}):raise ValueError('连接请求内容无效。')
            values[key]={'request':value,'state':'pending','response':None}
        else:
            if set(value)!={'schema','operation_key','request_sha256','state','response'} or key not in values:raise ValueError('连接结算记录无效。')
            row=values[key]
            if row['state']!='pending' or value['request_sha256']!=digest(row['request']) or value['state'] not in ('confirmed','failed','unknown'):raise ValueError('连接结算归属无效。')
            if value['state']=='confirmed':
                response=value['response']
                if not isinstance(response,dict) or set(response)!={'status','body'} or type(response['status']) is not int or not 200<=response['status']<300:raise ValueError('连接响应记录无效。')
                from runteams_core.authoring.compilation.creator_validation import validate_data
                checked_content({'response':response,'descriptor':row['request']['descriptor'],'params':row['request']['params']},
                    lambda:validate_data(row['request']['descriptor']['endpoints'][row['request']['params']['endpoint']]['output'],response['body']))
            elif value['response'] is not None:raise ValueError('连接失败记录不能包含确认结果。')
            row.update(state=value['state'],response=value['response'])
    return values


def verify(connection,scope,directory=None):
    streams=[row[0] for row in connection.execute('SELECT DISTINCT stream FROM events WHERE stream LIKE ?',(PREFIX+'%',))]
    if streams and directory is not None and not scope.get('library_id'):
        from pathlib import Path
        from runteams_core.foundation.identity.library_identity import MARKER
        from runteams_core.storage.local_library import _read as read_library_identity
        scope={**scope,'library_id':read_library_identity(Path(directory)/MARKER)}
    for stream in streams:
        rows=records(connection.execute('SELECT stream,type,data_json FROM events WHERE stream=? ORDER BY id',(stream,)),scope)
        if directory is None:continue
        from pathlib import Path
        from runteams_core.storage.backups.backup_files import safe_name
        from runteams_core.storage.device_files import _read
        for row in rows.values():
            request=row['request'];binding=request['binding'];work=safe_name(binding['work_id'])
            base=Path(directory)/('employee-workspaces' if binding['owner_kind']=='employee' else 'pipeline-workspaces')/work
            if binding['owner_kind']=='pipeline':base=base/binding['release_digest']
            parent=_read(base/'.runteams/mcp-calls'/(request['parent_call']+'.json'))
            if (parent.get('id')!=request['parent_call'] or parent.get('binding',{}).get('work_id')!=binding['work_id']
                    or parent.get('binding',{}).get('release_digest')!=binding['release_digest']
                    or parent.get('request',{}).get('package')!=binding['program_sha256']
                    or parent.get('state') not in ('pending','unknown','completed')):raise ValueError('连接回执缺少原工具受理记录。')
            frozen=_read(base/'.runteams/mcp-work.json')
            source=(frozen.get('employee',{}).get('local_package') or {}) if binding['owner_kind']=='employee' else frozen
            reference=source.get('reference')
            if digest(reference)!=binding['owner_sha256'] or source.get('revision')!=binding['source_revision']:raise ValueError('连接回执与原冻结源码不符。')


class ConnectionCalls:
    def __init__(self,host,chat,package,binding):
        self.host=host;self.chat=chat;self.package=package;self.bound=binding;self.provider=for_host(host,chat)
        from runteams_core.work.device_work_services import current
        self.core=current();self.scope=device_data.identity()

    def active(self):
        with self.host.lock:
            self.host.check_operation(self.chat)
            _,packages,work,binding=self.host._identity(self.chat)
            parent,read_only=self.host.connection_calls.get((self.chat,self.package,binding),(None,False))
            if read_only:raise PermissionError('只读工具不能调用外部服务。')
            if (binding!=self.bound or self.package not in packages or not self.host.enabled(binding,self.package)
                    or self.host.suspended(work) or not isinstance(parent,str)):raise PermissionError('连接必须来自当前已受理的工具调用。')
            from runteams_core.storage.device_files import _read
            row=_read(work/'.runteams/mcp-calls'/(parent+'.json'))
            if row.get('state')!='pending' or row.get('binding')!=binding.__dict__ or row.get('request',{}).get('package')!=self.package:raise PermissionError('原工具调用已结束。')
            return parent

    @contextmanager
    def transaction(self):
        self.core._actor();device_data.check(self.scope)
        with self.core.repository.definition_lock(),self.core.repository.connect() as connection:
            connection.execute('BEGIN IMMEDIATE');yield connection
            device_data.check(self.scope)

    def load(self,connection,stream):
        return records(connection.execute('SELECT stream,type,data_json FROM events WHERE stream=? ORDER BY id',(stream,)),self.scope)

    def append(self,connection,stream,kind,value,parent):
        return self.core.repository.event(stream,kind,value,connection=connection,actor_id=principal(self.scope),correlation_id=parent,source='native_sdk')

    def exchange(self,frame):
        frame=json.loads(canonical(frame));sdk_frame(frame)
        if frame['method']!='connection.http':raise CreatorContractError('unsupported_capability')
        parent=self.active();key=frame['params'].get('operation_key') or parent+':'+str(frame['id'])
        binding,descriptor,_=self.provider._binding(self.chat,self.package,frame['params']['connection'])
        prepared_request(descriptor,frame['params']);stream=PREFIX+digest(for_authority(binding))
        semantic=digest({k:v for k,v in frame['params'].items() if k!='operation_key'})
        with self.transaction() as connection:
            known=self.load(connection,stream)
            if key in known:
                row=known[key]
                if row['request']['params']!=frame['params']:raise CreatorContractError('operation_key_conflict')
                return reply(frame,row['state'],row['response'])
            if any(row['state'] in ('pending','unknown') and row['request']['semantic_sha256']==semantic for row in known.values()):return reply(frame,'unknown')
        # Check the actual vault before persisting any guest bytes. A native
        # credential must never be echoed into a request or portable receipt.
        with self.provider.lease(self.chat,self.package,frame['params']['connection'],digest(binding)) as credential:
            if redact_value(frame['params'],{'bearer':credential.token})!=frame['params']:raise CreatorContractError('credential_scope')
        request={'schema':SCHEMA,'operation_key':key,'parent_call':parent,'binding':binding,'descriptor':descriptor,
                 'params':frame['params'],'semantic_sha256':semantic}
        with self.transaction() as connection:
            known=self.load(connection,stream)
            if key in known:
                row=known[key]
                if row['request']['params']!=frame['params']:raise CreatorContractError('operation_key_conflict')
                return reply(frame,row['state'],row['response'])
            if any(row['state'] in ('pending','unknown') and row['request']['semantic_sha256']==semantic for row in known.values()):return reply(frame,'unknown')
            if sum(row['request']['parent_call']==parent for row in known.values())>=128:raise CreatorContractError('sdk_frame_limit')
            self.active();self.append(connection,stream,REQUEST,request,parent)
        claim={'send':True,'binding':binding,'descriptor':descriptor,'params':frame['params']}
        @contextmanager
        def credential_scope(expected):
            entered=False
            try:
                self.active()
                with self.provider.lease(self.chat,self.package,frame['params']['connection'],digest(expected)) as credential:
                    entered=True;yield credential
            except PermissionError:
                if entered:raise ConnectionUnknown() from None
                raise CreatorContractError('credential_scope') from None
        def settle(payload):
            with self.transaction() as connection:
                known=self.load(connection,stream);actual=known[key]
                if actual['request']!=request:raise CreatorContractError('operation_key_conflict')
                value={'schema':SCHEMA,'operation_key':key,'request_sha256':digest(request),'state':payload['state'],'response':payload.get('response')}
                self.append(connection,stream,SETTLED,value,parent)
            return reply(frame,payload['state'],payload.get('response'))
        transport=getattr(self.host,'connection_transport',None) or PinnedHTTPS(binding_validator=valid_binding)
        return exchange(frame,claim,binding,credential_scope,transport,settle)


@contextmanager
def environment(host,chat,package,binding):
    owner,_,_,_=host._identity(chat)
    employee_sdk = host.sdk_configuration(chat,binding,owner) is not None
    provider = for_host(host,chat) if host.scope.get('library_id') else None
    http = bool(provider and provider._owner(chat,package)[3])
    capabilities = ['connection.http'] if http else []
    if employee_sdk:
        capabilities.extend(('data.query','data.mutate','application.status','application.call'))
    if not capabilities:
        yield {}
        return
    from runteams_core.foundation.transport.loopback_rpc import serve_rpc

    def handle(message):
        if not isinstance(message,dict) or set(message)!={'jsonrpc','id','method','params'} or message['jsonrpc']!='2.0':
            raise ValueError('SDK 请求无效。')
        method, params = message['method'],message['params']
        frame={'abi':'runteams.sdk/1','id':message['id'],'method':method,'params':params}
        sdk_frame(frame)
        base={'abi':'runteams.sdk/1','id':message['id']}
        def error(code,retry='never'):
            return {**base,'ok':False,'error':{'code':code,'retry':retry}}
        def verify_owner():
            host.check_operation(chat)
            employee,packages,work,current = host._identity(chat)
            if current!=binding or package not in packages or not host.enabled(binding,package) or host.suspended(work):
                raise PermissionError('原程序已关闭。')
            return employee,work
        def guard():
            verify_owner()
            if host.connection_calls.get(call_key) != invocation or invocation is None:
                raise PermissionError('原工具调用已结束。')
            if cancel is not None and cancel.is_set():
                raise PermissionError('原工具调用已停止。')

        call_key=(chat,package,binding)
        invocation=host.connection_calls.get(call_key)
        cancel=host.turns.get(chat)
        try:
            employee,work=verify_owner()
            if method=='system.negotiate':
                result=({**base,'ok':True,'result':{'sdk':'1.0.0','capabilities':capabilities}}
                        if set(params['required'])<=set(capabilities) else error('unsupported_capability'))
            elif method not in capabilities:
                result=error('unsupported_capability')
            else:
                guard()
                parent,read_only=invocation
                from runteams_core.storage.device_files import _read
                journal=_read(work/'.runteams/mcp-calls'/(parent+'.json'))
                if journal.get('state')!='pending' or journal.get('binding')!=binding.__dict__ or journal.get('request',{}).get('package')!=package:
                    raise PermissionError('原工具调用已结束。')
                if read_only and method not in ('data.query','application.status'):
                    raise PermissionError('只读工具不能写入或调用外部服务。')
                if method=='connection.http':
                    result=ConnectionCalls(host,chat,package,binding).exchange(frame)
                else:
                    from runteams_core.work import employee_sdk_operations as operations
                    from runteams_core.employees.mcp.employee_applications import AccountRequired
                    config=host.sdk_configuration(chat,binding,employee)
                    if config is None:raise PermissionError('员工 SDK 当前不可用。')
                    try:
                        value=(operations.collections(config,method,params,binding.release_digest,guard)
                               if method.startswith('data.') else operations.applications(config,method,params,guard,cancel))
                        result={**base,'ok':True,'result':value}
                    except AccountRequired:
                        result=error('application_needs_connection','reauthorize')
        except BusinessCloudUnknown:
            result=error('sdk_outcome_unknown','reconcile')
        except PermissionError:
            result=error('sdk_permission_denied')
        except ValueError as exc:
            result=error('sdk_outcome_unknown','reconcile') if getattr(exc,'code',None)=='outcome_unknown' else error('sdk_invalid_operation')
        return {'jsonrpc':'2.0','id':message['id'],'result':result}
    def dispatch(message):
        with host.operation_scope():return handle(message)
    with serve_rpc(dispatch) as (endpoint,capability):yield {'RUNTEAMS_CONNECTION_HOST':endpoint,'RUNTEAMS_CONNECTION_CAPABILITY':capability}


def receipt(host,chat,package,connection,key):
    # Historical facts only. No active tool, program/service consent, bearer,
    # transport or new event is created by reading the original receipt.
    from runteams_core.work.device_work_services import current
    provider=for_host(host,chat);binding,_,_=provider._binding(chat,package,connection)
    core=current();core._actor();scope=device_data.identity();stream=PREFIX+digest(for_authority(binding))
    with core.repository.connect() as c:known=records(c.execute('SELECT stream,type,data_json FROM events WHERE stream=? ORDER BY id',(stream,)),scope)
    row=known.get(key)
    if row is None:return {'operation_key':key,'state':'not_found'}
    return {'operation_key':key,'state':'unknown' if row['state']=='pending' else row['state'],**({'response':copy.deepcopy(row['response'])} if row['state']=='confirmed' else {})}
