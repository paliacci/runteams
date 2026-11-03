"""Exact employee dependencies; author declarations never grant access.

Compilation is pure. Only the device host resolves declared pins through the
original source store or complete signed downloads. No employee is copied,
installed, upgraded or dispatched by this module.
"""
from runteams_core.pipelines import pipeline_dependency_contracts
import copy
from pathlib import Path

from runteams_core.authoring.creator_contracts import CreatorContractError, digest, relative

















def member_reference(pipeline, member):
    from runteams_core.employees import source_employee_runtime as employee
    from runteams_core.assets import rented_references
    from runteams_core.pipelines.pipeline_context import current
    if 'dependency' not in member:
        return (current().rented_member_reference(pipeline,member) if rented_references.is_rented(pipeline)
                else employee.reference(pipeline['source_id'], member['source']))
    pin = pipeline_dependency_contracts.checked(member['dependency'])
    if pin['kind'] == 'source': return employee.reference(pin['source_id'], pin['employee_source'])
    return current().acquired_member_reference(pin)


def describe(pipeline, member, revision):
    from runteams_core.employees import source_employee_runtime as employee
    from runteams_core.assets import rented_references
    from runteams_core.pipelines.pipeline_context import current
    if 'dependency' not in member:
        ref = (current().rented_member_reference(pipeline,member) if rented_references.is_rented(pipeline)
               else employee.reference(pipeline['source_id'], member['source']))
        if rented_references.is_rented(pipeline):
            package = current().rented_member_package(ref,revision)
            result = {'reference': ref, 'revision': revision, 'asset': current().rented_package_asset(package)}
        else:
            result = employee.describe(ref, revision=revision)
    else:
        if rented_references.is_rented(pipeline):
            raise PermissionError('租用流水线不能改绑本机员工。')
        pin = pipeline_dependency_contracts.checked(member['dependency'])
        if pin['kind'] == 'source':
            result = employee.describe(employee.reference(pin['source_id'], pin['employee_source']), revision=pin['revision'])
        else:
            result = current().acquired_member_description(pin)
        actual = [unit['key'] for unit in employee.units(result['asset'])]
        if sorted(actual) != sorted(pin['skills']):
            raise CreatorContractError('employee_dependency_contract_changed', '所选员工版本的技能与岗位声明不一致，请重新选择。')
    return result


def prepare(pipeline, member, operation, revision):
    from runteams_core.employees import source_employee_runtime as employee
    from runteams_core.assets import rented_references
    from runteams_core.pipelines.pipeline_context import current
    description = describe(pipeline, member, revision)
    if 'dependency' in member and member['dependency']['kind'] == 'download':
        return current().acquired_member_package(member['dependency'])
    if rented_references.is_rented(pipeline):
        return current().rented_member_package(description['reference'],description['revision'])
    return employee.prepare(description['reference'], operation, revision=description['revision'])
