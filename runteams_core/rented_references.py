"""Rented asset reference syntax and scope, independent of acquisition or execution."""
import re
from . import device_data
from .contracts import ContractError
from .creator_contracts import relative

PIPELINE = 'runteams.rented-pipeline-reference/1'


EMPLOYEE = 'runteams.rented-employee-reference/1'


FIELDS = {'schema','source_id','pipeline_source','account_id','deployment_id','storage_namespace'}


def is_rented(ref):
    return isinstance(ref,dict) and ref.get('schema') in (PIPELINE,EMPLOYEE)


def checked(ref, scope=None, *, employee=False):
    scope = device_data.identity() if scope is None else scope
    fields = FIELDS - {'pipeline_source'} | {'employee_source'} if employee else FIELDS
    if (not isinstance(ref,dict) or set(ref)!=fields or ref.get('schema')!=(EMPLOYEE if employee else PIPELINE)
            or not isinstance(ref['source_id'],str) or not re.fullmatch('[a-f0-9]{64}',ref['source_id'])):
        raise ContractError('租用资产引用无效。')
    relative(ref['employee_source' if employee else 'pipeline_source'])
    if any(ref[k]!=scope[k] for k in ('account_id','deployment_id','storage_namespace')):
        raise PermissionError('租用资产属于其他账户或部署。')
    return ref
