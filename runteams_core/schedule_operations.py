"""Original list/command/receipt/abandon operations for both schedule transports."""
import re,json
from .contracts import ContractError

def dispatch(backend,method,path,query,data=None,on_mutation=None):
    if path == backend.api_path and method == 'GET':
        if set(query)!={'reference'} or len(query['reference'])!=1 or len(query['reference'][0])>4096:
            raise ContractError('请提供完整员工引用。')
        ref=json.loads(query['reference'][0]);value=backend.list_reference(ref)
    elif path == backend.api_path and method == 'POST':
        value = backend.command(data)
    elif method == 'GET' and re.fullmatch(re.escape(backend.api_path)+'/operations/[a-f0-9-]{36}', path):
        value = backend.receipt(path.rsplit('/', 1)[1])
    elif method == 'POST' and re.fullmatch(re.escape(backend.api_path)+'/operations/[a-f0-9-]{36}/abandon', path):
        if data != {}:
            raise ContractError('取消操作内容无效。')
        value = backend.abandon(path.split('/')[-2])
    else:
        raise KeyError('自动化接口不存在。')
    if method=='POST' and path==backend.api_path and on_mutation is not None:on_mutation()
    return value
