"""Pipeline source capabilities owned by one real local library."""
from .bound_pipeline_context import BoundPipelineContext

class LocalPipelineContext(BoundPipelineContext):
    def rented_catalog(self):
        self._check();return []

    def acquired_employee_catalog(self):
        self._check();return [],[]

    def create_downloaded(self,*args):
        self._check();raise PermissionError('本机资料库只使用自己的源码员工。')

    def rented_revisions(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')

    def rented_context(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')

    def acquired_member_reference(self,*args):
        self._check();raise PermissionError('本机资料库不提供取得资产授权。')

    def acquired_member_description(self,*args):
        self._check();raise PermissionError('本机资料库不提供取得资产授权。')

    def acquired_member_package(self,*args):
        self._check();raise PermissionError('本机资料库不提供取得资产授权。')

    def rented_member_reference(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')

    def rented_member_package(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')

    def rented_package_asset(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')

    def rented_history(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')

    def rented_applied_catalog(self,*args):
        self._check();raise PermissionError('本机资料库不提供租用资产授权。')
