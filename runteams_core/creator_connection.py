"""Native HTTPS transport for declared connections; not an authorization grant.

Only trusted host code may supply bound credentials or the explicit test peer.
The configured host supplies an explicit identity validator and committed effect claims;
calling this transport by itself is never an authorization or durable receipt.
"""
from dataclasses import dataclass
import http.client
import ipaddress
import math
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import quote, urlencode, urlsplit

from .creator_contracts import CreatorContractError, canonical, contract, digest, strict_json
from .creator_sdk import bounded_json, sdk_frame
from .creator_validation import validate_data, validate_schemas


class ConnectionNotSent(Exception):
    """Trusted transport proves application HTTP bytes have not been sent."""
    code = 'connection_not_sent'


class ConnectionUnknown(Exception):
    """HTTP may have reached the supplier; this never authorizes a retry."""
    code = 'connection_unknown'


@dataclass(frozen=True, repr=False)
class NativeCredential:
    token: str
    origin: str
    scopes: frozenset
    expires_at: float
    binding_sha256: str




def prepared_request(descriptor, params):
    contract('connection.schema.json', descriptor)
    sdk_frame({'abi':'runteams.sdk/1','id':1,'method':'connection.http','params':params})
    if params['connection'] != descriptor['key'] or params['endpoint'] not in descriptor['endpoints']:
        raise CreatorContractError('connection_scope')
    endpoint = descriptor['endpoints'][params['endpoint']]
    path = endpoint['path']
    if (any(part in ('.','..') for part in path.split('/')) or '//' in path
            or endpoint['effect']=='read' and endpoint['method']!='GET'):
        raise CreatorContractError('invalid_endpoint')
    if endpoint['effect']=='write' and not params.get('operation_key'):
        raise CreatorContractError('operation_key_required')
    names = re.findall(r'\{([A-Za-z][A-Za-z0-9_]*)\}',path)
    supplied = params.get('path_params',{})
    if set(names)!=set(supplied) or '{' in re.sub(r'\{[A-Za-z][A-Za-z0-9_]*\}','',path) or '}' in re.sub(r'\{[A-Za-z][A-Za-z0-9_]*\}','',path):
        raise CreatorContractError('invalid_path_params')
    for name,value in supplied.items():
        if value in ('.','..') or any(ch in value for ch in '/\\%?#\r\n'):
            raise CreatorContractError('invalid_path_params')
        path=path.replace('{'+name+'}',quote(value,safe=''))
    query=params.get('query',{})
    if set(query)-set(endpoint['query']):
        raise CreatorContractError('undeclared_query')
    validate_schemas([endpoint['output']])
    validate_data(endpoint['input'],params.get('body'))
    for name,value in query.items(): validate_data(endpoint['query'][name],value)
    if query:
        path+='?'+urlencode({key:str(value).lower() if isinstance(value,bool) else value for key,value in sorted(query.items())})
    body=canonical(params['body']) if params.get('body') is not None else None
    return {'path':path,'method':endpoint['method'],'body':body,'output':endpoint['output']}


_DNS_SLOTS=threading.BoundedSemaphore(2)


def addresses(host, resolver, deadline):
    # The OS resolver can outlive a deadline. At most two daemon lookups may
    # remain blocked; they cannot consume all platform workers or delay exit.
    if not _DNS_SLOTS.acquire(blocking=False): raise ConnectionNotSent()
    result=queue.Queue(maxsize=1)
    def lookup():
        try: result.put((True,resolver(host)))
        except Exception: result.put((False,None))
        finally: _DNS_SLOTS.release()
    threading.Thread(target=lookup,daemon=True,name='creator-dns').start()
    try: ok,values=result.get(timeout=max(.001,min(3,deadline-time.monotonic())))
    except queue.Empty: raise ConnectionNotSent() from None
    if not ok or not isinstance(values,(list,tuple)) or not 1<=len(values)<=16:
        raise ConnectionNotSent()
    checked=[]
    for value in values:
        try: ip=ipaddress.ip_address(value)
        except (ValueError,TypeError): raise ConnectionNotSent() from None
        if not ip.is_global or ip.is_multicast: raise ConnectionNotSent()
        if str(ip) not in checked: checked.append(str(ip))
    return checked


def system_resolver(host):
    return list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))


class PinnedHTTPS:
    def __init__(self, *, binding_validator, context=None, resolver=system_resolver, timeout=8, supervised_peer=None):
        if not callable(binding_validator):raise CreatorContractError('connection_binding_required')
        self.binding_validator=binding_validator
        self.context=context or ssl.create_default_context()
        if not self.context.check_hostname or self.context.verify_mode!=ssl.CERT_REQUIRED:
            raise CreatorContractError('tls_verification_required')
        if not math.isfinite(timeout) or not 0<timeout<=8: raise ValueError('invalid deadline')
        self.resolver,self.timeout,self.supervised_peer=resolver,timeout,supervised_peer

    def request(self, descriptor, params, credential, *, binding):
        return self.request_http(descriptor,params,credential,binding=binding)['body']

    def request_http(self, descriptor, params, credential, *, binding):
        descriptor,params,binding=(strict_json(canonical(value)) for value in (descriptor,params,binding))
        prepared=prepared_request(descriptor,params)
        origin=descriptor['origin'];target=urlsplit(origin)
        if (self.binding_validator(binding) is not True
                or not isinstance(credential,NativeCredential) or credential.origin!=origin
                or credential.binding_sha256!=digest(binding)
                or binding.get('connection')!=descriptor['key']
                or binding.get('descriptor_sha256')!=digest(descriptor)
                or not set(descriptor['oauth']['scopes']).issubset(credential.scopes)
                or not isinstance(credential.token,str) or not 1<=len(credential.token)<=8192
                or not re.fullmatch(r'[A-Za-z0-9._~+/-]+=*',credential.token)
                or not math.isfinite(credential.expires_at) or credential.expires_at<=time.time()):
            raise CreatorContractError('credential_scope')
        deadline=time.monotonic()+self.timeout
        if self.supervised_peer is not None:
            # Explicit engineering supervisor only. Never read this from a
            # descriptor, guest arguments, proxy env or installed source files.
            fixture_origin,port=self.supervised_peer
            if fixture_origin!=origin or type(port) is not int or not 1<=port<=65535:
                raise ConnectionNotSent()
            peers=['127.0.0.1']
        else:
            peers=addresses(target.hostname,self.resolver,deadline);port=443
        channel=None
        for peer in peers:
            raw=None
            try:
                remaining=deadline-time.monotonic()
                if remaining<=0: raise ConnectionNotSent()
                raw=socket.create_connection((peer,port),timeout=min(3,remaining))
                raw.settimeout(max(.001,min(3,deadline-time.monotonic())))
                channel=self.context.wrap_socket(raw,server_hostname=target.hostname)
                break
            except (OSError,ssl.SSLError):
                if raw is not None: raw.close()
        if channel is None: raise ConnectionNotSent()
        connection=http.client.HTTPConnection(target.hostname,443)
        connection.sock=channel
        response=None
        def interrupt():
            try: channel.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        timer=threading.Timer(max(.001,deadline-time.monotonic()),interrupt);timer.daemon=True;timer.start()
        try:
            # From this point onward all errors are unknown, even if sendall
            # raised before revealing how much of a request reached the peer.
            connection.request(prepared['method'],prepared['path'],body=prepared['body'],headers={
                'Authorization':'Bearer '+credential.token,'Accept':'application/json',
                'Content-Type':'application/json','Connection':'close'})
            response=connection.getresponse()
            if not 200<=response.status<300: raise ConnectionUnknown()
            if response.getheader('Content-Encoding','identity').lower()!='identity': raise ConnectionUnknown()
            raw=response.read(12289)
            if len(raw)>12288 or time.monotonic()>deadline: raise ConnectionUnknown()
            value=bounded_json(strict_json(raw),limit=12288)
            def reflected(item):
                if isinstance(item,str): return credential.token in item
                if isinstance(item,list): return any(reflected(v) for v in item)
                if isinstance(item,dict): return any(reflected(k) or reflected(v) for k,v in item.items())
                return False
            if credential.token.encode() in raw or reflected(value): raise ConnectionUnknown()
            validate_data(prepared['output'],value)
            if time.monotonic()>deadline: raise ConnectionUnknown()
            return {'status':response.status,'body':value}
        except (ConnectionUnknown,): raise
        except Exception: raise ConnectionUnknown() from None
        finally:
            timer.cancel()
            if response is not None: response.close()
            connection.close()
