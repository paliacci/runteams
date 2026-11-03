"""Shared private native page owner, epochs, close barriers and bounded transport."""
import hmac,secrets,threading,uuid
from http.server import BaseHTTPRequestHandler
from runteams_core.foundation.identity.resource_ids import resource_id
from runteams_core.authoring.creator_contracts import CreatorContractError, canonical, digest, strict_json
from runteams_core.foundation.transport.native_view_transport import _Server
ACTIVE_WORK_LIMIT=8

class NativeWorkOwner:
    def _initialize(self):
        self.lock=threading.RLock(); self.entries={}; self.closed=False
        self.clients={}
        self.idle=threading.Condition(self.lock);self.opening=0;self.close_lock=threading.Lock()
        self.generation=0; self.nonce=secrets.token_urlsafe(32)
        self.server=_Server(self._handler())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='creator-work-owner')
        self.thread.start()


    @property
    def native_control(self):
        # This descriptor is for native provisioning, never an HTTP app status.
        return {'control':f'http://127.0.0.1:{self.server.server_port}','nonce':self.nonce}


    def _check(self):
        if self.closed: raise PermissionError('Creator owner closed')


    def client(self,key,*,close=False):
        key=resource_id(key)
        with self.lock:
            self._check()
            previous=self.clients.get(key)
            if previous is None and len(self.clients)>=64: raise CreatorContractError('work_owner_capacity')
            if not close:
                if previous is False: raise PermissionError('Creator native document closed')
                self.clients[key]=True
                return {'active':True}
            # Closing an unregistered epoch leaves a tombstone. A delayed
            # register/open from that document cannot resurrect it.
            self.clients[key]=False
            ids=[e['id'] for e in self.entries.values() if e.get('client')==key and e['state']!='closed']
        return {'active':False,'works':[self.release(work) for work in ids]}


    def open(self,payload,*,client=None):
        if not isinstance(payload,dict) or set(payload)!={'workspace_id','chat_id','installation_id','view','input','operation_key'}:
            raise CreatorContractError('invalid_work_open')
        payload=strict_json(canonical(payload))
        workspace=payload['workspace_id']
        if not isinstance(workspace,str): raise CreatorContractError('invalid_work_open')
        if workspace: workspace=resource_id(workspace)
        payload['workspace_id']=workspace
        installation=resource_id(payload['installation_id']); chat=payload['chat_id']
        if type(chat) is not int or not 0<chat<=9007199254740991: raise CreatorContractError('invalid_work_open')
        key=payload['operation_key']
        if (not isinstance(key,str) or not 1<=len(key)<=128 or not isinstance(payload['view'],str) or
                not 1<=len(payload['view'])<=128 or not isinstance(payload['input'],dict) or len(canonical(payload))>20000):
            raise CreatorContractError('invalid_work_open')
        if client is not None: client=resource_id(client)
        identity=(client,workspace,key); hashed=digest(payload)
        with self.lock:
            self._check()
            if client is not None and self.clients.get(client) is not True: raise PermissionError('Creator native document closed')
            entry=self.entries.get(identity)
            if entry is not None:
                if entry['hash']!=hashed: raise CreatorContractError('work_key_conflict')
                if entry['state']!='ready': return {'state':entry['state'],'id':entry['id']}
                bridge=entry['bridge']
            else:
                if len(self.entries)>=64 or sum(e['state'] in ('opening','ready','unknown','closing') for e in self.entries.values())>=ACTIVE_WORK_LIMIT:
                    raise CreatorContractError('work_owner_capacity')
                entry={'id':str(uuid.uuid4()),'hash':hashed,'state':'opening','bridge':None,'generation':self.generation,
                    'workspace':workspace,'chat_id':chat,'client':client}
                self.entries[identity]=entry; self.opening+=1;bridge=None
        if bridge is None:
            try:
                bridge=self._create_bridge(entry,workspace,installation,chat,payload)
            finally:
                with self.idle: self.opening-=1;self.idle.notify_all()
        # Never use a cached configuration as authorization. An uncertain Chat
        # remains recoverable through its already-mounted original native view.
        self._call(workspace,bridge.authority)
        with self.lock:
            self._check()
            if entry['state']!='ready' or entry['generation']!=self.generation:
                raise PermissionError('Creator work closed')
            return {'state':'ready','id':entry['id'],'chat_id':chat,'configuration':bridge.native_configuration}


    def _create_bridge(self,entry,workspace,installation,chat,payload):
        created=[]
        def create():
            value=self._bridge(installation,chat,payload)
            created.append(value)
            return value
        try:
            bridge=self._call(workspace,create)
        except BaseException as error:
            for value in created: value.close()
            with self.lock:
                # Repeating an uncertain app key must never create a fresh
                # bridge/session. A missing cloud reference can only expire.
                definite=isinstance(error,(PermissionError,CreatorContractError)) or getattr(error,'status_code',None) in (400,403,404,409,422)
                if entry['state']=='opening': entry['state']='rejected' if definite else 'unknown'
                elif entry['state']=='closing': entry['state']='closed'
            raise
        with self.lock:
            accepted=(not self.closed and entry['state']=='opening' and entry['generation']==self.generation and
                (entry['client'] is None or self.clients.get(entry['client']) is True))
            if accepted: entry['bridge']=bridge; entry['state']='ready'
        if not accepted:
            result=bridge.close()
            with self.lock:
                entry['state']='closed';entry['close_result']={'id':entry['id'],**result}
            raise PermissionError('Creator owner changed')
        return bridge


    def release(self,work_id):
        resource_id(work_id)
        with self.lock:
            self._check()
            entry=next((e for e in self.entries.values() if e['id']==work_id),None)
            if entry is None: raise PermissionError('Creator work missing')
            if entry['state']=='closed' or entry['state']=='closing' and entry['bridge'] is None:
                return dict(entry['close_result'])
            previous=entry['state'];bridge=entry['bridge']
            entry['state']='closing' if bridge is not None or previous=='opening' else 'closed'
            result={'id':work_id,'native_closed':previous=='rejected',
                'cloud_session_closed':False}
            entry['close_result']=result
        if bridge is not None: result.update(bridge.close())
        with self.lock:
            entry['close_result']=dict(result)
            if bridge is not None: entry['state']='closed'
        return result


    def reset(self):
        with self.lock:
            self._check()
            self.generation+=1
            ids=[e['id'] for e in self.entries.values() if e['state']!='closed']
        return {'works':[self.release(key) for key in ids]}


    def close(self):
        with self.close_lock:
            with self.lock:
                if self.closed: return
                self.closed=True; self.generation+=1
                bridges=[e['bridge'] for e in self.entries.values() if e['bridge'] is not None]
                for entry in self.entries.values(): entry['state']='closed'
            for bridge in bridges: bridge.close()
            # A bounded HTTP opening may still be returning. Drain it while old
            # account/host credentials can close its late session. Do not let
            # logout retire the host before that cleanup has been attempted.
            with self.idle:
                while self.opening: self.idle.wait()
            self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.nonce=''


    def _handler(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_args): pass
            def setup(self): super().setup(); self.connection.settimeout(3)
            def send(self,status,value):
                raw=canonical(value)
                self.send_response(status); self.send_header('Content-Type','application/json')
                self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(raw)))
                self.send_header('Connection','close'); self.end_headers(); self.wfile.write(raw)
            def do_POST(self):
                try:
                    if (self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}' or self.headers.get('Origin') or
                            any(k.lower().startswith('sec-fetch-') for k in self.headers) or
                            not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+owner.nonce) or
                            self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type')!='application/json'):
                        raise PermissionError()
                    length=int(self.headers.get('Content-Length','-1'))
                    if not 0<=length<=20000: raise CreatorContractError('invalid_work_open')
                    raw=self.rfile.read(length)
                    if len(raw)!=length: raise CreatorContractError('invalid_work_open')
                    value=strict_json(raw)
                    if self.path=='/open': result=owner.open(value)
                    elif self.path=='/client-open' and isinstance(value,dict) and set(value)=={'client','payload'}:
                        result=owner.open(value['payload'],client=value['client'])
                    elif self.path in ('/client-register','/client-close') and isinstance(value,dict) and set(value)=={'client'}:
                        result=owner.client(value['client'],close=self.path=='/client-close')
                    elif self.path=='/discover' and isinstance(value,dict) and set(value)=={'workspace_id','chat_id'}:
                        result=owner.discover(value['chat_id'],value['workspace_id'])
                    elif self.path=='/release' and isinstance(value,dict) and set(value)=={'id'}: result=owner.release(value['id'])
                    elif self.path=='/reset' and value=={}: result=owner.reset()
                    else: raise PermissionError()
                    self.send(200,result)
                except PermissionError: self.send(403,{'error':'work_access_denied'})
                except (CreatorContractError,ValueError): self.send(400,{'error':'work_input_rejected'})
                except Exception: self.send(503,{'error':'work_outcome_unknown'})
        return Handler

