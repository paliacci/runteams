"""Actual host identity for local work; library actors are never cloud accounts."""
def principal(scope):
    return scope['library_id'] if scope.get('storage_kind')=='local' else scope['account_id']


def source_scope(scope):
    if scope.get('storage_kind')=='local' or scope.get('source_library_id'):
        return {'storage_kind':'local','library_id':scope['library_id']}
    return {key:scope[key] for key in ('account_id','deployment_id','storage_namespace')}


def checked_source_scope(reference, scope):
    if reference.get('storage_kind')=='local':
        if reference.get('library_id')!=scope.get('library_id'):
            raise PermissionError('员工不属于当前资料库。')
        return {'storage_kind','library_id'}
    if scope.get('storage_kind')=='local':
        raise PermissionError('本机资料库不提供官方资产授权。')
    fields={'account_id','deployment_id','storage_namespace'}
    if any(reference.get(k)!=scope.get(k) for k in fields):
        raise PermissionError('员工不属于当前账户或部署。')
    return fields


def collection_namespace(scope):
    if scope.get('source_library_id'):
        from .local_library import scope_for
        return scope_for(scope['library_id'])['storage_namespace']
    return scope['storage_namespace']


def work_scope(scope):
    if scope.get('storage_kind')=='local' or scope.get('source_library_id'):
        return {'storage_kind':'local','library_id':scope['library_id']}
    from .device_files import _scope
    return _scope(scope)


def source_owner(reference):
    """Compare frozen asset owners without current authority or a fake account."""
    if not isinstance(reference,dict):raise PermissionError('资产归属无效。')
    fields=('storage_kind','library_id') if reference.get('storage_kind')=='local' else ('account_id','deployment_id','storage_namespace')
    if any(key not in reference or not isinstance(reference[key],str) for key in fields):
        raise PermissionError('资产归属不完整。')
    if not reference.get('library_id' if fields[0]=='storage_kind' else 'account_id'):
        raise PermissionError('资产归属不完整。')
    return {key:reference[key] for key in fields}


def schedule_binding(scope):
    """Actual schedule-store owner; original library namespace survives adoption."""
    if scope.get('storage_kind')=='local' or scope.get('source_library_id'):
        return {'storage_kind':'local','library_id':scope['library_id'],'storage_namespace':collection_namespace(scope)}
    return {key:scope.get(key,'') for key in ('account_id','storage_service_url','storage_namespace','deployment_id')}
