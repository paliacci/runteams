"""Frozen employee/pipeline link validation without asset or runtime access."""
from runteams_core.authoring.creator_contracts import CreatorContractError
from runteams_core.pipelines.pipeline_dependency_contracts import checked
from runteams_core.employees import employee_acquisition_refs


def verify_binding(pipeline, member, package, revision=None):
    """Pure frozen-link check, also safe during archive verification."""
    from runteams_core.employees import employee_references
    from runteams_core.assets import rented_references
    ref = package['reference']
    from runteams_core.foundation.identity.work_identity import source_owner
    if source_owner(pipeline) != source_owner(ref):
        raise PermissionError('员工与流水线不属于同一资料库、账户或部署。')
    if 'dependency' in member:
        pin = checked(member['dependency'])
        if pin['kind'] == 'source':
            expected = (employee_references.SOURCE_SCHEMA, pin['source_id'], pin['employee_source'], pin['revision'])
        else:
            expected = (employee_references.ACQUIRED_SCHEMA, employee_acquisition_refs.source_id(pin), pin['employee_source'], 'r-' + pin['sha256'])
            if package.get('acquisition') != employee_acquisition_refs.acquisition(pin):
                raise CreatorContractError('employee_dependency_package_mismatch')
        if (ref['schema'], ref['source_id'], ref['employee_source'], package['revision']) != expected:
            raise CreatorContractError('employee_dependency_package_mismatch')
    elif (ref['schema'] != (rented_references.EMPLOYEE if rented_references.is_rented(pipeline) else employee_references.SOURCE_SCHEMA)
          or ref['source_id'] != pipeline['source_id'] or ref['employee_source'] != member['source']
          or revision is not None and package['revision'] != revision):
        raise CreatorContractError('pipeline_employee_package_mismatch')
