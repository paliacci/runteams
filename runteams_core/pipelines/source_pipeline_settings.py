"""Trusted source editing and configuration of one local pipeline.

Source edits never apply or start work. Employee defaults remain independent;
scoped values use the existing declaration, grants, CAS and receipt machinery.
"""
from runteams_core.pipelines import pipeline_references
from runteams_core.assets import rented_references
import copy
import json
import uuid
from contextlib import contextmanager

from runteams_core.storage import device_data
from runteams_core.pipelines import source_pipeline_work as work, source_pipeline_control as control
from runteams_core.foundation.contracts import ContractError
from runteams_core.authoring.creator_contracts import canonical, strict_json, digest
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.configuration.employee_configuration import ConfigurationStore, EMPTY, profile


def _source(ref):
    ref = pipeline_references.checked_reference(ref)
    revisions = work.source(ref)
    return ref, revisions


def _asset(files, ref):
    project = strict_json(files['project.json'])
    if ref['pipeline_source'] not in project['entrypoints'].get('pipelines', []):
        raise PermissionError('智能体团队不属于当前源码工程。')
    from runteams_core.authoring.creator_definitions import validate_author
    return validate_author('pipeline', strict_json(files[ref['pipeline_source']]))


class PipelineConfiguration(ConfigurationStore):
    def __init__(self, pipeline, reference, definition, revision, *, connection_asset=None):
        super().__init__(reference, definition, revision,connection_asset=connection_asset)
        self.namespace = 'pipeline-configuration:' + digest(pipeline) + ':'
        self.key = self.namespace + digest(self.reference)
        self.receipt_prefix = self.namespace + 'receipt:'

    def _load(self, connection):
        if connection.execute('SELECT 1 FROM device_settings WHERE key=?', (self.key,)).fetchone():
            return super()._load(connection)
        # Initial values use the same employee's existing configuration. The
        # first pipeline save creates a separate complete value set, not field
        # overrides. No read writes or duplicates business records.
        original = ConfigurationStore(self.reference, self.definition, self.definition_revision,connection_asset=self.connection_asset)
        value = copy.deepcopy(original._load(connection))
        value['revision'] = 0
        return value


class OwnConfiguration(ConfigurationStore):
    """The pipeline itself, never an employee's defaults or position settings."""
    def __init__(self, reference, asset, revision):
        super().__init__(pipeline_references.checked_reference(reference), asset.get('configuration', EMPTY), revision)
        self.key = 'pipeline-own-configuration:' + digest(self.reference)
        self.receipt_prefix = 'pipeline-own-configuration-receipt:' + digest(self.reference) + ':'


@contextmanager
def own_configuration_store(ref):
    ref, revisions = _source(ref)
    with revisions.locked():
        revision = revisions._head()
        yield OwnConfiguration(ref, _asset(revisions._files(revision), ref), revision)


def own_configuration(core, data):
    core._actor()
    action = data.get('action')
    extra = {'read': set(), 'receipt': {'operation_id'}, 'credential':{'field','definition_sha256','value'},
        'reveal-credential': {'field','definition_sha256'}, 'save': {
        'operation_id', 'expected_revision', 'definition_sha256', 'values', 'bindings'}}.get(action)
    if extra is None or set(data) != {'reference', 'action'} | extra:
        raise ContractError('智能体团队配置请求无效。')
    with own_configuration_store(data['reference']) as config:
        if action == 'reveal-credential': return config.reveal_credential(**{k:data[k] for k in extra})
        if action == 'credential': return config.credential(**{k:data[k] for k in extra})
        if action == 'read': return config.read()
        if action == 'receipt': return config.receipt(data['operation_id'])
        return config.save(**{key: data[key] for key in extra})


@contextmanager
def configuration(ref, employee_source):
    ref, revisions = _source(ref)
    from runteams_core.pipelines.pipeline_employee_dependencies import describe as describe_member
    from runteams_core.pipelines.pipeline_dependency_contracts import selector
    with revisions.locked():
        revision = revisions._head(); asset = _asset(revisions._files(revision), ref)
        member = next((m for m in asset['employees'] if selector(m) == employee_source and any(
            p.get('employee_ref') == m['ref'] for p in asset['pipeline']['positions'])), None)
        if member is None: raise PermissionError('这名员工不属于智能体团队岗位。')
    if 'dependency' not in member:
        from runteams_core.pipelines.pipeline_employee_dependencies import member_reference
        from runteams_core.configuration.employee_configuration import for_source
        with for_source(member_reference(ref, member)) as original:
            # for_source already owns this exact project's edit lock.
            now = _asset(revisions._files(revisions._head()), ref)
            if not any(m == member and any(p.get('employee_ref') == m['ref'] for p in now['pipeline']['positions']) for m in now['employees']):
                raise PermissionError('智能体团队岗位已改变，请重新打开配置。')
            config = PipelineConfiguration(ref, original.reference, original.definition, original.definition_revision)
            config.employee = original.employee
            yield config
        return
    description = describe_member(ref, member, revision)
    employee = description['asset']['employee']
    # All employee definitions are immutable at this point. Recheck the owning
    # graph under its source lock; no independent employee settings are written.
    with revisions.locked():
        now = _asset(revisions._files(revisions._head()), ref)
        if not any(m == member and any(p.get('employee_ref') == m['ref'] for p in now['pipeline']['positions']) for m in now['employees']):
            raise PermissionError('智能体团队岗位已改变，请重新打开配置。')
        connection_asset=({**{k:member['dependency'][k] for k in ('installation_id','release_id','rental_source_id') if k in member['dependency']},'employee_source':member['dependency']['employee_source']} if member.get('dependency',{}).get('kind')=='download' else None)
        config = PipelineConfiguration(ref, description['reference'], employee.get('configuration', EMPTY), description['revision'],connection_asset=connection_asset)
        config.employee = {key: employee[key] for key in ('name', 'avatar')}
        yield config


def for_package(ref, package):
    from runteams_core.employees.source_employee_runtime import package_asset
    from runteams_core.configuration.connections.configuration_connections import package_asset_binding
    employee = package_asset(package)['employee']
    return PipelineConfiguration(pipeline_references.checked_reference(ref), package['reference'],
                                 employee.get('configuration', EMPTY), package['revision'],connection_asset=package_asset_binding(package))


def employee_configuration(core, data):
    core._actor()
    allowed = {'reference', 'employee_source', 'action'}
    action = data.get('action')
    extra = {'read': set(), 'receipt': {'operation_id'}, 'credential':{'field','definition_sha256','value'},
        'reveal-credential': {'field','definition_sha256'}, 'save': {
        'operation_id', 'expected_revision', 'definition_sha256', 'values', 'bindings'}}.get(action)
    if extra is None or set(data) != allowed | extra:
        raise ContractError('智能体团队员工配置请求无效。')
    if action == 'receipt':
        # A lost save remains recoverable after this employee leaves the graph,
        # just like the independent employee's original source receipt path.
        ref,revisions = _source(data['reference'])
        with revisions.locked(): _asset(revisions._files(revisions._head()),ref)
        from runteams_core.pipelines.pipeline_employee_dependencies import member_reference
        from runteams_core.pipelines.pipeline_dependency_contracts import selector
        with revisions.locked():
            versions = [revisions._head()] + ([m['revision'] for m in revisions._history()] + [ref['source_id']] if not rented_references.is_rented(ref) else [])
            member = next((m for revision in versions for m in _asset(revisions._files(revision), ref)['employees']
                           if selector(m) == data['employee_source']), None)
        if member is None: raise PermissionError('配置回执的员工引用不存在。')
        return PipelineConfiguration(ref, member_reference(ref, member), EMPTY, None).receipt(data['operation_id'])
    with configuration(data['reference'], data['employee_source']) as config:
        if action == 'reveal-credential': return config.reveal_credential(**{k:data[k] for k in extra})
        if action == 'credential': return config.credential(**{k:data[k] for k in extra})
        if action == 'read': return config.read()
        return config.save(**{k: v for k, v in data.items() if k in extra})


def read(core, ref, *, include_configuration=False):
    core._actor(); ref, revisions = _source(ref)
    with revisions.locked():
        revision = revisions._head(); files = revisions._files(revision); asset = _asset(files, ref)
    embedded = {} if include_configuration else None
    employees = _settings_employees(ref, revision, files, asset, configuration_employees=embedded)
    result = {'reference': ref, 'source_revision': revision, 'asset': asset,
            'version': strict_json(files['project.json']).get('version'),
            'employees': employees, 'storage_scope': 'device'}
    if include_configuration:
        states = {}
        # Embedded members share one validated source revision. Reuse its declarations
        # while the head is locked. Dynamic values still use the normal scoped store.
        with revisions.locked():
            if revisions._head() == revision:
                for path, (reference, employee) in embedded.items():
                    try:
                        store = PipelineConfiguration(ref, reference, employee['configuration'], revision)
                        store.employee = profile(employee)
                        states[path] = store.read()
                    except (ValueError, OSError, PermissionError):
                        continue
                if any(group['fields'] for group in asset.get('configuration', EMPTY)['groups']):
                    try:
                        states[''] = OwnConfiguration(ref, asset, revision).read()
                    except (ValueError, OSError, PermissionError):
                        pass
        for row in employees:
            if row['field_count'] and row['source'] not in embedded:
                try:
                    with configuration(ref, row['source']) as store:
                        states[row['source']] = store.read()
                except (ValueError, OSError, PermissionError):
                    continue
        # Missing groups use the individual read, including its recovery controls.
        result['configuration_states'] = states
    return result


def _settings_employees(ref, revision, files, asset, *, configuration_employees=None):
    from runteams_core.authoring.source.creator_source_import import validated_employee_assets
    from runteams_core.configuration.configuration_schema import fields
    from runteams_core.employees.employee_references import source_reference
    from runteams_core.pipelines.pipeline_dependency_contracts import selector
    from runteams_core.pipelines.pipeline_employee_dependencies import describe as describe_member, member_reference
    from runteams_core.pipelines.source_pipeline_workspace import skill_description

    positions = {}
    for position in asset['pipeline']['positions']:
        positions.setdefault(position.get('employee_ref'), []).append(position['name'])
    members = [member for member in asset['employees'] if member['ref'] in positions]
    embedded = {member['ref'] for member in members if 'dependency' not in member and not rented_references.is_rented(ref)}
    source_assets = {}
    source_error = None
    if embedded:
        # These members belong to the same authorized, immutable snapshot as the pipeline.
        try:
            source_assets = validated_employee_assets(files)
        except (ValueError, OSError, PermissionError) as error:
            source_error = str(error)

    employees = []
    for member in members:
        reference = None
        try:
            if member['ref'] in embedded:
                path = member['source']
                reference = source_reference(ref['source_id'], path)
                if source_error is not None:
                    raise ContractError(source_error)
                if path not in source_assets:
                    raise ContractError('员工源码入口已不存在，请在原工程中核对。')
                member_asset, member_revision = source_assets[path], revision
            else:
                description = describe_member(ref, member, revision)
                reference = description['reference']
                member_asset, member_revision = description['asset'], description['revision']
            employee = member_asset['employee']
            row = {'reference': reference, 'name': employee['name'], 'revision': member_revision,
                   'field_count': len(fields(employee.get('configuration', EMPTY))),
                   'skills': [skill for bundle in member_asset.get('skill_bundles', [])
                              if (skill := skill_description(bundle)) is not None]}
            if configuration_employees is not None and row['field_count'] and member['ref'] in embedded:
                configuration_employees[member['source']] = (reference, employee)
        except (ValueError, OSError, PermissionError) as error:
            row = {'reference': reference or member_reference(ref, member), 'name': positions[member['ref']][0],
                   'field_count': 0, 'error': str(error)}
        employees.append({'source': selector(member), 'member_ref': member['ref'], 'positions': positions[member['ref']], **row})
    return employees


def edit(core, data):
    from runteams_core.assets.rented_references import is_rented
    if is_rented(data.get('reference')):raise PermissionError('租用资产只可配置使用，不能修改或恢复源码。')
    core._actor()
    if set(data) not in ({'reference', 'base_revision', 'operation_id', 'asset'},
                         {'reference', 'base_revision', 'operation_id', 'avatar'},
                         {'reference', 'base_revision', 'operation_id', 'restore_revision'}):
        raise ContractError('智能体团队保存参数无效。')
    try:
        if str(uuid.UUID(data['operation_id'])) != data['operation_id']: raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('请沿原保存操作核对。') from None
    ref, revisions = _source(data['reference'])
    files = revisions.files_at(data['base_revision']); previous = _asset(files, ref)
    operation = 'pipeline-edit-' + digest(ref)[:32] + '-' + data['operation_id']
    asset = data.get('asset')
    if 'avatar' in data:
        from runteams_core.employees.employee_avatars import prepare_picture
        reference, picture = prepare_picture(data['avatar'])
        files[reference] = picture
        asset = {**previous, 'avatar': reference}
        files[ref['pipeline_source']] = canonical(asset)
        result = revisions.commit(files, data['base_revision'], operation)
        from runteams_core.pipelines.pipeline_avatars import image_src, source_fields
        return {'reference': ref, 'revision': result['revision'], 'avatar': reference,
                'avatar_src': image_src(source_fields(asset, files)), 'storage_scope': 'device'}
    if 'restore_revision' in data:
        restored_files = revisions.files_at(data['restore_revision'])
        asset = _asset(restored_files, ref)
        from runteams_core.employees.employee_avatars import bundled
        reference = asset.get('avatar')
        if bundled(reference):
            files[reference] = restored_files[reference]
    if not isinstance(asset, dict) or asset.get('key') != previous.get('key'):
        raise ContractError('智能体团队身份不能在编辑中改变。')
    graph = asset.get('pipeline')
    if not isinstance(graph, dict) or graph.get('routing_policy') != previous['pipeline'].get('routing_policy'):
        raise ContractError('智能体团队流转规则版本不能在常规编辑中改变。')
    from runteams_core.authoring.source.creator_source_import import validate_source
    from runteams_core.authoring.creator_conversation_assets import compile_catalog
    original = compile_catalog(files, validate_source(files))
    files[ref['pipeline_source']] = canonical(asset)
    checked = compile_catalog(files, validate_source(files))
    if original['employees'] != checked['employees']:
        raise ContractError('智能体团队编辑不能改写员工资产。')
    from runteams_core.pipelines.pipeline_employee_dependencies import describe as describe_member
    for member in asset['employees']:
        if 'dependency' in member:
            describe_member(ref, member, data['base_revision'])
    result = revisions.commit(files, data['base_revision'], operation)
    return {'reference': ref, 'revision': result['revision'], 'pipeline': checked['pipelines'][ref['pipeline_source']]['pipeline'],
            'storage_scope': 'device'}


def edit_receipt(core, data):
    core._actor()
    if set(data) != {'reference', 'operation_id'}: raise ContractError('原保存请求无效。')
    ref, revisions = _source(data['reference'])
    if not isinstance(data['operation_id'], str) or len(data['operation_id']) != 36:
        raise ContractError('原保存编号无效。')
    # Receipt contains only the source revision; source ownership is verified.
    return revisions.receipt('pipeline-edit-' + digest(ref)[:32] + '-' + data['operation_id'])


def history(core, ref):
    if rented_references.is_rented(ref):
        core._actor()
        from runteams_core.pipelines.pipeline_context import current
        return current().rented_history(ref)
    core._actor(); ref, revisions = _source(ref)
    with revisions.locked():
        records = revisions._history(); original = revisions.store.describe(ref['source_id'])
        rows = [*records, {'revision': ref['source_id'], 'created_at': original['created_at']}]
        result, previous = [], None
        for row in reversed(rows):
            files = revisions._files(row['revision'])
            if ref['pipeline_source'] not in files: continue
            asset = strict_json(files[ref['pipeline_source']]); fingerprint = digest(asset)
            if fingerprint == previous: continue
            result.append({'revision': row['revision'], 'created_at': row['created_at'],
                'revision_number': len(result) + 1, 'notes_kind': 'pipeline_definition',
                'version': '修订 ' + str(len(result) + 1), 'notes': '智能体团队定义和团队规范；员工资产保持独立。'})
            previous = fingerprint
    return {'items': list(reversed(result)), 'storage_scope': 'device'}


def _overview_record(core, connection, row, task_id, frozen, reports):
    from runteams_core.pipelines import pipeline_task_report
    identifier = row['id']
    record = {'key': f'workflow-{identifier}', 'workflow_id': identifier, 'state': row['state']}
    if row['state'] == 'recorded':
        return None
    if row['state'] == 'completed':
        record['delivery_document'] = pipeline_task_report.final_delivery_reference(core, {'task_id': task_id, 'task': row})
    summary = reports[0]['summary'] if reports else ''
    if not summary:
        attempt = connection.execute('SELECT output_json FROM employee_runs WHERE workflow_run_id=? ORDER BY id DESC LIMIT 1',
                                     (identifier,)).fetchone()
        output = json.loads(attempt[0]) if attempt else {}
        summary = output.get('summary') or next(iter(output.get('issues') or []), '')
    return {**record, 'summary': summary}


def records(core, ref, *, overview=False):
    from runteams_core.pipelines.source_pipeline_workspace import workspace
    with core.repository.read_snapshot() as connection:
        ref = pipeline_references.checked_reference(ref); rows = workspace(core, ref)['workflows']
        from runteams_core.employees.employee_chat_work import delivery
        from runteams_core.work.work_reports import catalog as report_catalog
        report_groups = {}
        for report in report_catalog(core): report_groups.setdefault(report['binding'].get('workflow_id'), []).append(report)
        deliveries = []
        for row in reversed(rows):
            ledger, frozen = work._authorized_work(connection, ref, row['id'])
            reports = report_groups.get(row['id'], [])
            if overview:
                preview = _overview_record(core, connection, row, ledger['task_id'], frozen, reports)
                if preview is not None:
                    deliveries.append(preview)
                    continue
            projected = delivery(core, {**row, 'workflow_id': row['id']},
                                 reports)
            projected['origin'] = {'kind':'workflow','workflow_id':row['id']}
            deliveries.append(projected)
        return {'schema': 'runteams.result-view/v1', 'scope': {'source_pipeline_reference': ref},
                'results': deliveries, 'storage_scope': 'device'}
