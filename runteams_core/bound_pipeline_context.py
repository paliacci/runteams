"""Original pipeline ports, bound to the current host provider rather than an account."""
from .storage_context import current_provider

class BoundPipelineContext:
    def __init__(self, provider):
        self.provider = provider
        self._check()


    def _check(self):
        if current_provider() is not self.provider:
            raise PermissionError('流水线工作提供者已变化，请重新打开。')


    def binding(self, chat_id):
        self._check()
        from runteams_core.pipeline_chat_binding import reference
        return reference(chat_id)


    def definition(self, reference):
        self._check()
        from runteams_core.source_pipeline_workspace import _definition
        return _definition(reference)


    def member_configuration(self, reference, package):
        self._check()
        from runteams_core.source_pipeline_settings import for_package
        return for_package(reference, package)


    def configuration_store(self,reference,employee_source):
        self._check()
        from runteams_core.source_pipeline_settings import configuration
        return configuration(reference,employee_source)


    def own_configuration_store(self,reference):
        self._check()
        from runteams_core.source_pipeline_settings import own_configuration_store
        return own_configuration_store(reference)


    def own_configuration(self, reference, asset, revision):
        self._check()
        from runteams_core.source_pipeline_settings import OwnConfiguration
        return OwnConfiguration(reference, asset, revision)


    def describe_member(self, reference, member, revision):
        self._check()
        from runteams_core.pipeline_employee_dependencies import describe
        return describe(reference, member, revision)


    def prepare_member(self, reference, member, operation_id, revision):
        self._check()
        from runteams_core.pipeline_employee_dependencies import prepare
        return prepare(reference, member, operation_id, revision)


    def attested_proof(self, core, connection, frozen, session):
        self._check()
        from runteams_core.source_pipeline_recovery import attested_proof
        return attested_proof(core, connection, frozen, session)


    def reconcile_result(self, core, identifier):
        self._check()
        from runteams_core.source_pipeline_recovery import reconcile
        return reconcile(core, identifier)

