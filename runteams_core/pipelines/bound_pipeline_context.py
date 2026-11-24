"""Original pipeline ports, bound to the current host provider rather than an account."""
from runteams_core.storage.storage_context import current_provider

class BoundPipelineContext:
    def __init__(self, provider):
        self.provider = provider
        self._check()


    def _check(self):
        if current_provider() is not self.provider:
            raise PermissionError('流水线工作提供者已变化，请重新打开。')


    def allowed_modes(self, reference):
        self._check()
        from runteams_core.pipelines.pipeline_references import REFERENCE
        if reference.get('schema') != REFERENCE:
            raise PermissionError('当前宿主不提供此流水线。')
        return ['creator']

    def additional_pipelines(self):
        self._check()
        return []

    def member_assets(self, pipeline, member, pin):
        self._check()
        from runteams_core.pipelines.pipeline_references import REFERENCE
        from runteams_core.pipelines.pipeline_employee_dependencies import SourceMember
        if pipeline.get('schema') != REFERENCE:
            raise PermissionError('当前宿主不提供此流水线。')
        if pin is None:
            return SourceMember(pipeline['source_id'], member['source'])
        if pin['kind'] == 'source':
            return SourceMember(pin['source_id'], pin['employee_source'], pin['revision'])
        raise PermissionError('本机资料库只使用自己的源码员工。')

    def binding(self, chat_id):
        self._check()
        from runteams_core.pipelines.pipeline_chat_binding import reference
        return reference(chat_id)


    def definition(self, reference):
        self._check()
        from runteams_core.pipelines.source_pipeline_workspace import _definition
        revision, asset, _ = _definition(reference)
        return revision, asset


    def member_configuration(self, reference, package):
        self._check()
        from runteams_core.pipelines.source_pipeline_settings import for_package
        return for_package(reference, package)


    def configuration_store(self,reference,employee_source):
        self._check()
        from runteams_core.pipelines.source_pipeline_settings import configuration
        return configuration(reference,employee_source)


    def own_configuration_store(self,reference):
        self._check()
        from runteams_core.pipelines.source_pipeline_settings import own_configuration_store
        return own_configuration_store(reference)


    def own_configuration(self, reference, asset, revision):
        self._check()
        from runteams_core.pipelines.source_pipeline_settings import OwnConfiguration
        return OwnConfiguration(reference, asset, revision)


    def describe_member(self, reference, member, revision):
        self._check()
        from runteams_core.pipelines.pipeline_employee_dependencies import describe
        return describe(reference, member, revision)


    def prepare_member(self, reference, member, operation_id, revision, *, runtime_selection=None):
        self._check()
        from runteams_core.pipelines.pipeline_employee_dependencies import prepare
        return prepare(reference, member, operation_id, revision, runtime_selection=runtime_selection)


    def attested_proof(self, core, connection, frozen, session):
        self._check()
        from runteams_core.pipelines.source_pipeline_recovery import attested_proof
        return attested_proof(core, connection, frozen, session)


    def reconcile_result(self, core, identifier, *, expected_visit=None):
        self._check()
        from runteams_core.pipelines.source_pipeline_recovery import reconcile
        return reconcile(core, identifier, expected_visit=expected_visit)

