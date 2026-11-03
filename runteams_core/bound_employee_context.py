"""Official employee context delegates to the original authority-owning code."""
from runteams_core.storage_context import current_provider


class BoundEmployeeContext:
    def __init__(self, provider):
        self.provider = provider
        self._check()

    def _check(self):
        if current_provider() is not self.provider:
            raise PermissionError('员工工作提供者已变化，请重新打开。')

    def prepare_work(self,core,chat_id,frozen):
        # Source-owned local connections keep their original native authority.
        self._check()

    def resolve(self, context):
        self._check()
        from runteams_core.employee_binding import for_context
        return for_context(context)

    def document_owner(self, session):
        self._check()
        from runteams_core.employee_binding import document_owner
        return document_owner(session)

    def configuration(self, chat_id):
        self._check()
        from runteams_core.employee_configuration import for_chat
        return for_chat(chat_id)

    def validate_configuration_snapshot(self, definition, reference, revision, snapshot):
        self._check()
        from runteams_core.employee_configuration import _validate_snapshot
        return _validate_snapshot(definition, reference, revision, snapshot)

    def validate_source_package(self, package):
        self._check()
        from runteams_core.source_employee_runtime import employee
        return employee(package)

    def workspace(self, chat_id):
        self._check()
        from runteams_core.employee_workspaces import workspace
        return workspace(chat_id)

    def verify_authoring(self, session):
        self._check()
        from runteams_core.employee_binding import authoring_reference
        return authoring_reference(session)

    def package_source(self, reference):
        self._check()
        from runteams_core.source_employee_runtime import source
        return source(reference)

    def package_asset(self, package):
        self._check()
        from runteams_core.source_employee_runtime import package_asset
        return package_asset(package)

    def validate_package(self, package):
        self._check()
        from runteams_core.source_employee_runtime import validate
        return validate(package)

    def prepare_source_build(self, store, source_id, revision, operation_id):
        self._check()
        from runteams_core.source_employee_runtime import prepare_build
        return prepare_build(store, source_id, revision, operation_id)

    def validate_package_configuration(self, package, snapshot):
        self._check()
        from runteams_core.employee_configuration import validate_snapshot
        return validate_snapshot(package, snapshot)

    def work_detail(self, core, identifier):
        self._check()
        from runteams_core.employee_chat_work import detail
        return detail(core, identifier)

