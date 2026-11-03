"""Canonical platform-origin MCP state and approval operations."""

def dispatch(host,chat,method,body=None,*,observing=False):
    if method=='GET':return host.observe(chat) if observing else host.state(chat)
    if method!='POST' or not isinstance(body,dict):raise ValueError('请求无效。')
    fields, action = set(body), body.get('action')
    if action in ('connection-state','connection-authorize','connection-revoke','connection-receipt'):
        from runteams_core.work.work_connections import dispatch as connections
        return connections(host,chat,body)
    if action=='enable' and fields=={'action','binding_sha256','confirm'}:
        result = host.enable(chat,body['binding_sha256'],body['confirm'])
    elif action=='disable' and fields=={'action','binding_sha256'}:
        result = host.disable(chat,body['binding_sha256'])
    elif action=='close' and fields=={'action','binding_sha256'}:
        if host.state(chat)['binding_sha256']!=body['binding_sha256']: raise PermissionError('工作已变化。')
        host.close_work(chat);result = host.state(chat)
    elif action=='resume' and fields=={'action','binding_sha256'}:
        host.resume(chat,body['binding_sha256']);result = host.state(chat)
    elif action=='answer' and fields=={'action','binding_sha256','id','decision'}:
        result = host.answer(chat,body['binding_sha256'],body['id'],body['decision'])
    else: raise ValueError('请求无效。')
    return result
