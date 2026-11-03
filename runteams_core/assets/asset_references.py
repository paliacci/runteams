"""Persistable native business identity; never an authorization or success receipt.

Old bare integer / short-route references cannot be interpreted as native data.
Adapters must carry the verified deployment, workspace and data epoch together.
Commands still need the database's live permission and atomic epoch checks.
"""
from dataclasses import dataclass
import uuid

from runteams_core.foundation.identity.device_namespace import issuer

RESOURCES=frozenset({'employees','employee_releases','pipelines','pipeline_releases',
                     'employee_skills','employee_skill_revisions','tasks','workflow_runs','employee_runs','automations'})
SCHEMA='runteams.business-reference/v1'


class StaleBusinessReference(PermissionError):
    def __init__(self):
        super().__init__('这条记录的业务数据身份已变化，请重新打开。')


def identifier(value):
    if type(value) is not int or not 1<=value<=9007199254740991:
        raise ValueError('无效的业务记录编号。')
    return value


def uuid_text(value):
    try:return str(uuid.UUID(str(value)))
    except (ValueError,TypeError,AttributeError):raise ValueError('无效的业务数据身份。') from None


@dataclass(frozen=True)
class BusinessReference:
    deployment_id: str
    workspace_id: str
    data_epoch: str
    resource: str
    id: int

    def __post_init__(self):
        object.__setattr__(self,'deployment_id',issuer(self.deployment_id))
        object.__setattr__(self,'workspace_id',uuid_text(self.workspace_id))
        object.__setattr__(self,'data_epoch',uuid_text(self.data_epoch))
        if self.resource not in RESOURCES:raise ValueError('无效的业务记录类型。')
        identifier(self.id)

    def to_json(self):
        return {'schema':SCHEMA,'deployment_id':self.deployment_id,'workspace_id':self.workspace_id,
                'data_epoch':self.data_epoch,'resource':self.resource,'id':self.id}

    @classmethod
    def from_json(cls,value):
        fields={'schema','deployment_id','workspace_id','data_epoch','resource','id'}
        if not isinstance(value,dict) or set(value)!=fields or value.get('schema')!=SCHEMA:
            raise StaleBusinessReference()
        try:return cls(**{key:value[key] for key in fields-{'schema'}})
        except (ValueError,TypeError):raise StaleBusinessReference() from None

    @classmethod
    def from_profile(cls,deployment_id,profile,resource,resource_id):
        if not isinstance(profile,dict) or profile.get('schema')!='runteams.native-workspace/v1':
            raise StaleBusinessReference()
        try:return cls(deployment_id,profile['workspace_id'],profile['data_epoch'],resource,resource_id)
        except (KeyError,ValueError,TypeError):raise StaleBusinessReference() from None

    def require_current(self,deployment_id,profile,*,resource):
        current=self.from_profile(deployment_id,profile,resource,self.id)
        if current!=self:raise StaleBusinessReference()
        return self.id
