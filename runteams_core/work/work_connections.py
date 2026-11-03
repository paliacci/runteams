"""Explicit host-local service grants for original source employee/pipeline work.

Service consent follows the frozen source/owner/program/service. Every issued
credential remains bound to the current full work. Only platform ingress may
authorize. Source/config declarations, program
consent and service consent remain separate. No cloud namespace or fake account.
The canonical work_connection_calls coordinator supplies actual SDK dispatch and
durable phases only after original admitted MCP tool authority.
"""
from contextlib import contextmanager
from pathlib import Path
import hmac,time,uuid,re
from runteams_core.configuration.credentials import app_secrets
from runteams_core.storage import local_database
from runteams_core.storage import device_data
from runteams_core.configuration.credentials.connection_credentials import ConnectionCredentialRecords
from runteams_core.authoring.creator_contracts import CreatorContractError, digest
from runteams_core.authoring.creator_connection import ConnectionUnknown
from runteams_core.foundation.identity.local_connection_identity import for_work, for_authority


class WorkConnections(ConnectionCredentialRecords):
    def __init__(self,host):
        self.host=host;self.scope=host.scope;self.root=host.root;self.lock=host.lock
        self.vault=app_secrets.vault_path()
        self.directory=Path(local_database.DB_PATH).parent/'host-credentials/work-connections'/digest(self.scope)

    def check(self):
        self.host.check();device_data.check(self.scope)
        if not self.scope.get('library_id') or device_data.root()!=self.root:raise PermissionError('请在原本机资料库核对连接。')

    def _owner(self,chat,package):
        self.check();owner,packages,_,bound=self.host._identity(chat)
        if package not in packages:raise PermissionError('程序不属于当前工作版本。')
        from runteams_core.employees.mcp.employee_mcp import PipelineWorkBinding
        if type(bound) is PipelineWorkBinding:
            ref,revision,definition=owner['reference'],owner['revision'],owner['asset'].get('configuration',{})
        else:
            source=owner.get('local_package')
            if not source:raise PermissionError('本机连接只接当前源码工作。')
            from runteams_core.employees.source_employee_runtime import package_asset
            ref,revision=source['reference'],source['revision'];definition=package_asset(source)['employee'].get('configuration',{})
        if ref.get('schema') not in ('runteams.local-employee-reference/1','runteams.local-pipeline-reference/1'):
            raise PermissionError('本机连接不接取得或租用资产的授权。')
        from runteams_core.configuration.connections.configuration_connections import descriptors as source_descriptors
        descriptors=source_descriptors(ref,revision,definition)
        return ref,revision,bound,descriptors

    def _binding(self,chat,package,key):
        ref,revision,bound,descriptors=self._owner(chat,package)
        if key not in descriptors:raise PermissionError('此服务未由原工作配置声明。')
        descriptor=descriptors[key]
        return for_work(ref,revision,bound,package,descriptor),descriptor,bound

    def _root_identity(self):
        info=self.root.stat();return [info.st_dev,info.st_ino]

    def _current(self,binding):
        row=self._record(for_authority(binding))
        if row is None or row.get('root_identity')!=self._root_identity():raise CreatorContractError('credential_scope')
        return row,self._credential(binding,row)

    def state(self,chat,package):
        with self.lock:
            _,_,bound,descriptors=self._owner(chat,package);rows=[]
            for key,descriptor in descriptors.items():
                binding,_,_=self._binding(chat,package,key);row=None
                try:row,credential=self._current(binding)
                except CreatorContractError:pass
                rows.append({'key':key,'origin':descriptor['origin'],'scopes':descriptor['oauth']['scopes'],
                    'binding_sha256':digest(binding),'authorized':row is not None,'expires_at':row['expires_at'] if row else None})
            with app_secrets.vault_scope(self.vault):names=sorted(app_secrets.names())
            self.check()
            return {'schema':'runteams.work-connections/1','chat_id':chat,'package':package,
                'program_enabled':self.host.enabled(bound,package),'connections':rows,'credential_names':names}

    def authorize(self,chat,package,key,expected,*,credential_name=None,token=None,confirm=False):
        with self.lock:
            binding,descriptor,_=self._binding(chat,package,key)
            if confirm is not True or expected!=digest(binding):raise PermissionError('请核对原工作、服务地址和授权范围后确认。')
            if token is not None:
                if credential_name is not None:raise ValueError('请选择已有凭据或填写访问令牌。')
                credential_name='SDK_'+key+'_'+digest(for_authority(binding))[:24]
            elif isinstance(credential_name,str):
                with app_secrets.vault_scope(self.vault):token=app_secrets.resolve([credential_name]).get(credential_name,'')
            if not isinstance(token,str) or not 1<=len(token)<=8192 or not re.fullmatch(r'[A-Za-z0-9._~+/-]+=*',token):raise ValueError('请选择可用的访问令牌，或重新填写。')
            fingerprint=self._fingerprint(token);prior=self._record(for_authority(binding))
            if (prior and prior['state']=='authorized' and prior.get('root_identity')==self._root_identity()
                    and prior.get('expires_at',0)>time.time() and prior.get('credential_name')==credential_name
                    and hmac.compare_digest(prior.get('fingerprint',''),fingerprint)):
                try:self._credential(binding,prior)
                except CreatorContractError:pass
                else:return self.state(chat,package)
            row={'binding':for_authority(binding),'credential_name':credential_name,'origin':descriptor['origin'],
                'scopes':sorted(descriptor['oauth']['scopes']),'fingerprint':fingerprint,
                'expires_at':int(time.time())+3600,'operation_id':str(uuid.uuid4()),'state':'authorized','root_identity':self._root_identity()}
            with app_secrets.vault_scope(self.vault):app_secrets.set_secret(credential_name,token)
            self._save(row);self.host._notice_changed()
            return self.state(chat,package)

    def revoke(self,chat,package,key,expected):
        with self.lock:
            binding,_,_=self._binding(chat,package,key)
            if expected!=digest(binding):raise PermissionError('连接已变化，请重新核对原工作。')
            row=self._record(for_authority(binding))
            if row is not None and row['state']!='revoked':self._save({**row,'state':'revoked'})
            self.host._notice_changed();return self.state(chat,package)

    @contextmanager
    def lease(self,chat,package,key,expected):
        def current():
            with self.lock:
                binding,_,bound=self._binding(chat,package,key)
                _,packages,work,actual=self.host._identity(chat)
                if (expected!=digest(binding) or actual!=bound or package not in packages
                        or not self.host.enabled(bound,package) or self.host.suspended(work)):
                    raise PermissionError('原程序或连接授权已失效。')
                self.host.check_operation(chat)
                from runteams_core.configuration.employee_configuration import ConfigurationInvalid
                try:self.host.credential_configuration(chat,bound)
                except (ConfigurationInvalid,ValueError):raise PermissionError('请先保存并核对此项服务配置。') from None
                row,credential=self._current(binding);return row,credential
        with self.host.operation_scope():
            original,credential=current()
            yield credential
            try:row,actual=current()
            except (PermissionError,ValueError,OSError):raise ConnectionUnknown() from None
            if row!=original or not hmac.compare_digest(actual.token,credential.token):raise ConnectionUnknown()


def for_host(host,chat):
    owner,_,_,_=host._identity(chat)
    ref=owner.get('reference') or (owner.get('local_package') or {}).get('reference',{})
    if ref.get('schema') in ('runteams.local-employee-reference/1','runteams.local-pipeline-reference/1'):return WorkConnections(host)
    if ref.get('schema') not in ('runteams.acquired-employee-reference/1','runteams.rented-employee-reference/1','runteams.rented-pipeline-reference/1') and (not owner.get('native_asset') or not owner.get('sdk_asset')):return None
    from runteams_core.employees.employee_context import current
    return current().connection_provider(host,chat)


def dispatch(host,chat,body):
    fields=set(body);action=body.get('action');base={'action','package'}
    with host.operation_scope():
        provider=for_host(host,chat)
        if provider is None:raise PermissionError('此工作没有声明的服务连接。')
        if action=='connection-state' and fields==base:return provider.state(chat,body['package'])
        if action=='connection-receipt' and fields==base|{'connection','operation_key'}:
            from runteams_core.work.work_connection_calls import receipt
            return receipt(host,chat,body['package'],body['connection'],body['operation_key'])
        extra={'connection','binding_sha256'}
        if action=='connection-revoke' and fields==base|extra:return provider.revoke(chat,body['package'],body['connection'],body['binding_sha256'])
        if action=='connection-authorize' and fields in (base|extra|{'credential_name','confirm'},base|extra|{'token','confirm'}):
            return provider.authorize(chat,body['package'],body['connection'],body['binding_sha256'],**{k:body[k] for k in ('credential_name','token','confirm') if k in body})
        raise ValueError('连接授权请求无效。')
