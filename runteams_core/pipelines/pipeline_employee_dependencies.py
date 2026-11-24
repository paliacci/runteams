"""Resolve exact pipeline employee dependencies through the active host."""
from runteams_core.authoring.creator_contracts import CreatorContractError
from runteams_core.pipelines import pipeline_dependency_contracts
from runteams_core.pipelines.pipeline_context import current


class SourceMember:
    def __init__(self, source_id, path, pinned_revision=None):
        self.source_id = source_id
        self.path = path
        self.pinned_revision = pinned_revision

    def reference(self):
        from runteams_core.employees import source_employee_runtime as employee
        return employee.reference(self.source_id, self.path)

    def describe(self, revision):
        from runteams_core.employees import source_employee_runtime as employee
        return employee.describe(self.reference(), revision=self.pinned_revision or revision)

    def prepare(self, description, operation, runtime_selection):
        from runteams_core.employees import source_employee_runtime as employee
        return employee.prepare(description['reference'], operation, revision=description['revision'],
                                runtime_selection=runtime_selection)


def _resolve(pipeline, member):
    pin = pipeline_dependency_contracts.checked(member['dependency']) if 'dependency' in member else None
    return current().member_assets(pipeline, member, pin), pin


def member_reference(pipeline, member):
    assets, _ = _resolve(pipeline, member)
    return assets.reference()


def _description(assets, pin, revision):
    result = assets.describe(revision)
    if pin is not None:
        from runteams_core.employees import source_employee_runtime as employee
        actual = [unit['key'] for unit in employee.units(result['asset'])]
        if sorted(actual) != sorted(pin['skills']):
            raise CreatorContractError('employee_dependency_contract_changed', '所选员工版本的技能与岗位声明不一致，请重新选择。')
    return result


def describe(pipeline, member, revision):
    assets, pin = _resolve(pipeline, member)
    return _description(assets, pin, revision)


def prepare(pipeline, member, operation, revision, *, runtime_selection=None):
    assets, pin = _resolve(pipeline, member)
    description = _description(assets, pin, revision)
    return assets.prepare(description, operation, runtime_selection)
