"""Shared native/browser work router with exact provider and receipt ownership."""
import secrets
import threading
from . import workspace_context
from .creator_contracts import CreatorContractError,digest
from .native_view_transport import _Server
from .native_work_owner import NativeWorkOwner
from .resource_ids import resource_id


class CreatorOwnerRouter:
    """Stable native control, with separate local and cloud authorities."""
    _handler=NativeWorkOwner._handler

    def __init__(self,cloud_owner,*,device_owner=None):
        self.cloud_owner=cloud_owner
        self.device_owner=device_owner
        self.lock=threading.RLock();self.closed=False;self.clients={};self.requests={};self.works={}
        self.nonce=secrets.token_urlsafe(32);self.server=_Server(self._handler())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='creator-owner-router');self.thread.start()

    native_control=NativeWorkOwner.native_control

    def _check(self):
        if self.closed:raise PermissionError('Creator owner closed')

    def _provider(self,chat,workspace):
        with workspace_context.use(workspace):
            if self.device_owner is not None:
                device=self.device_owner(chat,workspace)
                if device is not None:return device
        cloud=self.cloud_owner()
        if cloud is None:raise PermissionError('云端作品暂时不可用。')
        return cloud

    def discover(self,chat_id,workspace=''):
        with self.lock:self._check()
        return self._provider(chat_id,workspace).discover(chat_id,workspace)

    def client(self,key,*,close=False):
        key=resource_id(key)
        with self.lock:
            self._check()
            if key not in self.clients and len(self.clients)>=64:raise CreatorContractError('work_owner_capacity')
            if not close and self.clients.get(key) is False:raise PermissionError('Creator native document closed')
            self.clients[key]=not close
            providers={p for (c,_,_),(_,p) in self.requests.items() if c==key}
        if not close:return {'active':True}
        works=[]
        for provider in providers:
            if not provider.closed:works.extend(provider.client(key,close=True)['works'])
            else:
                # Retirement may have lost a cloud close acknowledgement. An
                # empty list must not turn that into confirmed cloud cleanup.
                with provider.lock:
                    works.extend(dict(entry.get('close_result') or {'id':entry['id'],
                        'native_closed':True,'cloud_session_closed':False})
                        for entry in provider.entries.values() if entry.get('client')==key)
        return {'active':False,'works':works}

    def open(self,payload,*,client=None):
        # Preserve the original provider for every request key, including an
        # unknown result. Retiring/replacing a cloud owner cannot redispatch it.
        if not isinstance(payload,dict) or set(payload)!={'workspace_id','chat_id','installation_id','view','input','operation_key'}:
            raise CreatorContractError('invalid_work_open')
        if client is not None:client=resource_id(client)
        workspace=payload['workspace_id'];key=payload['operation_key']
        if not isinstance(workspace,str) or not isinstance(key,str) or not 1<=len(key)<=128:raise CreatorContractError('invalid_work_open')
        if workspace:resource_id(workspace)
        identity=(client,workspace,key);hashed=digest(payload)
        with self.lock:
            self._check()
            if client is not None and self.clients.get(client) is not True:raise PermissionError('Creator native document closed')
            previous=self.requests.get(identity)
            if previous:
                if previous[0]!=hashed:raise CreatorContractError('work_key_conflict')
                provider=previous[1]
            else:
                if len(self.requests)>=64:raise CreatorContractError('work_owner_capacity')
                provider=self._provider(payload['chat_id'],workspace)
                self.requests[identity]=(hashed,provider)
            if client is not None:provider.client(client)
        value=provider.open(payload,client=client)
        with self.lock:
            if self.closed or client is not None and self.clients.get(client) is not True:
                if not provider.closed:provider.release(value['id'])
                raise PermissionError('Creator native document closed')
            self.works[value['id']]=provider
        return value

    def release(self,work_id):
        work_id=resource_id(work_id)
        with self.lock:self._check();provider=self.works.get(work_id)
        if provider is None:raise PermissionError('Creator work missing')
        return provider.release(work_id)

    def reset(self):
        with self.lock:self._check();providers=set(self.works.values())
        works=[]
        for provider in providers:
            if not provider.closed:works.extend(provider.reset()['works'])
        return {'works':works}

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);self.nonce=''
