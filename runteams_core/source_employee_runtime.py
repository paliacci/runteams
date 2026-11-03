"""Run saved SDK employees from verified, revision-bound local build artifacts.

Local packages are execution facts about a directory source, never employee IDs,
publication receipts, installation grants or a second authoring model.
"""
from runteams_core import employee_work_contracts
from . import employee_references, rented_references
import json
import time
import uuid
import threading
from collections import OrderedDict
import os
import subprocess
import tempfile
from pathlib import Path

from . import device_data
from .contracts import ContractError
from .creator_contracts import digest, strict_json
from .creator_local_source import current_store, _read
from .creator_source_revisions import Revisions
from .creator_local_build import LocalBuilds
from .creator_definitions import CATALOG_PATH
from .creator_conversation_assets import validate_asset as verified_employee_asset, extension as _extension

_revalidated_builds=OrderedDict()
_revalidation_lock=threading.Lock()


def _recheck_artifacts(files,tools,pin,runtime):
    """Use the existing isolated builder, including on a source host hot update."""
    from .creator_source_archive import pack
    from .creator_worker_process import command
    from .creator_contracts import canonical,tree
    with tempfile.TemporaryDirectory(prefix='runteams-frozen-build-check-') as directory:
        root=Path(directory);(root/'source.zip').write_bytes(pack(files))
        request={'schema':'runteams.local-build-request/1','job':str(root),'tools':str(tools),
            'toolchain_sha256':pin,'parent_pid':os.getpid(),'builder_profile':'mcp'}
        if runtime is not None:request['mcp_runtime']={'root':str(runtime.root),'manifest_sha256':runtime.manifest_sha256}
        result=subprocess.run(command('build'),input=canonical(request),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            env={'PATH':os.defpath,'LANG':'en_US.UTF-8'},timeout=190,start_new_session=True)
        response=strict_json(result.stdout[:128*1024])
        if result.returncode or response.get('state')!='succeeded':
            raise ContractError('原员工运行包未通过当前构建核验，请保留原工作。')
        stage=root/'.result-stage';metadata=strict_json((stage/'build.json').read_bytes())
        if metadata['manifest']['source_sha256']!=tree(files)['sha256']:
            raise ContractError('原员工冻结源码核验不一致。')
        values={}
        for path in stage.rglob('*'):
            if path.is_symlink():raise ContractError('冻结产物核验路径无效。')
            if path.is_file() and path!=stage/'build.json':values[path.relative_to(stage).as_posix()]=path.read_bytes()
        return values


def _validate_frozen_build(builds,state,files,artifacts):
    """A compiler update cannot replace or unnecessarily retire frozen work.

    Recheck the same immutable source with the current verified tools. Only
    byte-identical complete artifacts remain usable; unavailable/changed native
    resources never fall back to an old toolchain. No source or saved pin changes.
    """
    reason=builds.toolchain_stale_reason(state)
    if not reason:return
    if reason!='toolchain_changed':raise ContractError('原员工的运行资源已变化。')
    from .creator_build_tools import load,directory
    try:
        _,pin=load(profile='mcp');runtime=None
        if state.get('mcp_runtime_sha256'):
            from .employee_mcp import platform_runtime
            runtime=platform_runtime()
            if runtime.manifest_sha256!=state['mcp_runtime_sha256']:
                raise ContractError('原员工的运行资源已变化。')
        key=(state['result_sha256'],pin,state.get('mcp_runtime_sha256'))
        with _revalidation_lock:
            if key not in _revalidated_builds:
                current=_recheck_artifacts(files,directory(),pin,runtime)
                if (current!=artifacts or load(profile='mcp')[1]!=pin or
                        runtime is not None and platform_runtime().manifest_sha256!=state['mcp_runtime_sha256']):
                    raise ContractError('当前核验产物与原员工运行包不一致，请保留原工作核对。')
                _revalidated_builds[key]=True
                while len(_revalidated_builds)>64:_revalidated_builds.popitem(last=False)
            else:_revalidated_builds.move_to_end(key)
    except ContractError:raise
    except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired) as error:
        raise ContractError('原员工运行包未通过当前构建核验，请保留原工作。') from error


def reference(source_id, employee_source):
    scope = device_data.identity()
    from .work_identity import source_scope
    value = {'schema':employee_references.SOURCE_SCHEMA,'source_id':source_id,'employee_source':employee_source,**source_scope(scope)}
    source(value)
    return value


def source(ref):
    if rented_references.is_rented(ref):
        rented_references.checked(ref,employee=True); revisions=_external('rented','Revisions',ref)
        return revisions,revisions
    ref = employee_references.checked_reference(ref)
    scope = device_data.identity()
    if ref.get('schema')!=employee_references.SOURCE_SCHEMA:
        raise ContractError('员工源码引用无效。')
    store = current_store(scope['cache_scope'])
    revisions = Revisions(store, ref['source_id'])
    return store, revisions


def describe(ref, *, revision=None):
    _, revisions = source(ref)
    with revisions.locked():
        revision = revision or revisions._head()
    files = revisions.files_at(revision)
    project=strict_json(files['project.json'])
    if ref['employee_source'] not in project['entrypoints']['employees']:
        raise ContractError('员工源码入口已不存在，请在原工程中核对。')
    from .creator_source_import import validate_source
    from .creator_conversation_assets import compile_catalog
    compiled = validate_source(files)
    definitions = compile_catalog(files, compiled)
    if ref['employee_source'] not in definitions['employees']:
        raise ContractError('员工源码入口已不存在，请在原工程中核对。')
    asset = definitions['employees'][ref['employee_source']]
    return {'reference': ref, 'revision': revision, 'asset': asset, 'project_name': compiled['project']['name'],
            'skills': units(asset)}


def units(asset):
    return [{'key': b['package_key'], 'name': _extension(b)['work']['name'],
             'input_schema': _extension(b)['work']['input_schema']} for b in asset['skill_bundles'] if _extension(b).get('work')]


def prepare(ref, operation_id, *, cancel=None, revision=None):
    if rented_references.is_rented(ref):return _external('rented','package',ref,revision)
    saved_revision = revision is not None
    store, revisions = source(ref)
    revision = revision or revisions.current()['revision']
    revisions.files_at(revision)
    state, artifacts = prepare_build(store, ref['source_id'], revision, operation_id,
                                     cancel=cancel, saved_revision=saved_revision)
    catalog = strict_json(artifacts[CATALOG_PATH])
    if ref['employee_source'] not in catalog['employees']:
        raise ContractError('运行包缺少当前员工入口。')
    asset = verified_employee_asset(catalog['employees'][ref['employee_source']])
    runtime = resolve_runtime(asset['employee']['runtime_requirement'])
    package = {'schema': employee_work_contracts.SOURCE_PACKAGE, 'reference': ref, 'revision': revision,
               'build_operation_key': state['operation_key'], 'result_sha256': state['result_sha256'],
               'runtime': runtime}
    return validate(package)


def resolve_runtime(requirement):
    from runteams_core import product_store; from runteams_core import model_channels
    provider=requirement['provider']
    channels=[c for c in product_store.list_channels() if c.get('enabled') and c['provider']==provider]
    if not channels:raise ContractError('员工需要的模型渠道尚未连接。')
    settings=device_data.settings();choice=str(settings.get('default_model') or '').split('::',1)
    configured=next((c for c in channels if str(c['id'])==choice[0]),None)
    channel=configured or next((c for c in channels if c.get('is_default')),channels[0])
    try:catalog=model_channels.require_catalog(channel)
    except ValueError as error:raise ContractError(str(error)) from error
    models=catalog['models']
    requested=requirement.get('model') or ''
    preferred=choice[1] if configured and len(choice)==2 and any(item['value']==choice[1] for item in models) else ''
    model=requested or preferred or model_channels.latest_flagship_model(models)
    if not any(item['value']==model for item in models):raise ContractError('员工指定的模型已不可用，请在原员工设置中核对。')
    effort=requirement.get('effort') or settings.get('default_effort') or ''
    model,effort=model_channels.normalize_selection(channel,model,effort,catalog=catalog)
    if not model or not any(item['value']==model for item in models):raise ContractError('员工未能选定可用模型，请重新读取模型渠道。')
    return {**requirement,'channel_id':channel['id'],'provider':provider,'model':model,'effort':effort}


def validate(package):
    if isinstance(package, dict) and package.get('schema') == employee_work_contracts.ACQUIRED_PACKAGE:
        return _external('acquired','validate',package)
    if isinstance(package,dict) and package.get('schema')==employee_work_contracts.RENTED_PACKAGE:return _external('rented','validate',package)
    if not isinstance(package, dict) or set(package) != {'schema','reference','revision','build_operation_key','result_sha256','runtime'} or package.get('schema') != employee_work_contracts.SOURCE_PACKAGE:
        raise ContractError('原员工运行包引用无效。')
    expected_scope=device_data.identity()
    store, revisions = source(package['reference'])
    builds = LocalBuilds(store, package['reference']['source_id'])
    metadata, artifacts = builds.artifacts(package['build_operation_key'])
    state = strict_json(_read(builds.job(package['build_operation_key'])/'status.json',128*1024))
    if (state['state'] != 'succeeded' or state['revision'] != package['revision'] or
            state.get('result_sha256') != package['result_sha256'] or digest(metadata) != package['result_sha256']):
        raise ContractError('原员工运行包已变化。')
    # Saved history, not the mutable editing directory, is the source authority.
    from .creator_contracts import tree
    files=revisions.files_at(package['revision'])
    if tree(files)['sha256'] != metadata['manifest']['source_sha256']:
        raise ContractError('原员工源码与运行包不一致。')
    _validate_frozen_build(builds,state,files,artifacts)
    asset = verified_employee_asset(strict_json(artifacts[CATALOG_PATH])['employees'][package['reference']['employee_source']])
    from .definition_contracts import validate_definition
    runtime = validate_definition('runtime_snapshot', package['runtime'])
    for key, value in asset['employee']['runtime_requirement'].items():
        if value and runtime.get(key) != value:
            raise ContractError('员工运行设置不符合源码要求。')
    device_data.check(expected_scope)
    return package


def package_asset(package):
    if isinstance(package, dict) and package.get('schema') == employee_work_contracts.ACQUIRED_PACKAGE:
        return _external('acquired','package_asset',package)
    if isinstance(package,dict) and package.get('schema')==employee_work_contracts.RENTED_PACKAGE:return _external('rented','package_asset',package)
    store, _ = source(package['reference'])
    _, artifacts = LocalBuilds(store, package['reference']['source_id']).artifacts(package['build_operation_key'])
    return verified_employee_asset(strict_json(artifacts[CATALOG_PATH])['employees'][package['reference']['employee_source']])


def employee(package):
    package = validate(package)
    asset = package_asset(package);ref = package['reference']
    from runteams_core.source_links import source_key
    from .employee_avatars import identity
    return {'id': source_key(ref['source_id'], ref['employee_source']),
            **identity(asset['employee'], avatar_file=asset.get('avatar_file')),
            'local_package': package,
            'active_release': {'id':None, 'digest':digest(package), 'snapshot_json':{
                'schema':employee_work_contracts.SOURCE_PACKAGE, 'runtime':package['runtime'], 'soul':asset['employee']['soul'],
                'skill_bundles':asset['skill_bundles']}}}


def for_chat(chat_id):
    from runteams_core import product_store
    session = product_store.get_chat(chat_id,include_messages=False)
    package = (session or {}).get('context',{}).get('local_employee_package')
    if package is None:
        return None
    if not device_data.contains(chat_id) or session['subject_type'] != 'employee' or session['kind'] != 'general':
        raise PermissionError('原员工工作对话引用无效。')
    return employee(package)


def work_config_context(session, incoming, *, scope_pipeline_id=None):
    """Keep the frozen employee binding; only the requested work skill may vary."""
    import copy
    item = for_chat(session['id'])
    existing = session['context']
    if incoming is None:
        incoming = existing
    if (item is None or scope_pipeline_id or not isinstance(incoming, dict)
            or {k:v for k,v in incoming.items() if k != 'preferred_skill_key'}
            != {k:v for k,v in existing.items() if k != 'preferred_skill_key'}):
        raise ValueError('员工工作对话不能改绑。')
    selected = incoming.get('preferred_skill_key', existing.get('preferred_skill_key'))
    if selected is not None and (not isinstance(selected, str) or selected not in
            {unit['key'] for unit in units(package_asset(item['local_package']))}):
        raise ValueError('请选择当前员工已有的工作技能。')
    return {**copy.deepcopy(existing), 'preferred_skill_key': selected}


def create_chat(package, *, title=None, preferred_skill=None, configuration_snapshot=None, work_context=None):
    from runteams_core import product_store
    item = employee(package);runtime = package['runtime'];ref = package['reference']
    context = {'context_type':'worker','intent':'work','worker_name':item['name'],
               'source_employee':ref,'local_employee_package':package,
               'preferred_skill_key':preferred_skill}
    if work_context is not None:
        if set(work_context)!={'employee_work','pipeline_work','pipeline_generation'}:
            raise ContractError('岗位工作上下文无效。')
        from copy import deepcopy
        context.update(deepcopy(work_context))
    if configuration_snapshot is not None:
        from .employee_configuration import validate_snapshot
        context['employee_configuration_snapshot'] = validate_snapshot(package, configuration_snapshot)
    cid = product_store.create_chat(channel_id=runtime['channel_id'], model=runtime['model'],
        reasoning_effort=runtime['effort'],extensions_enabled=True,subject_type='employee',context=context)
    product_store.set_chat_channel_title(cid,title or item['name'])
    return cid


def open_work(ref, operation_id, *, package=None):
    from runteams_core import product_store
    if not isinstance(operation_id,str) or str(uuid.UUID(operation_id))!=operation_id:
        raise ContractError('工作操作编号无效。')
    key = 'source-work-open:' + operation_id
    with device_data.connect(readonly=True) as c:
        previous = c.execute('SELECT value FROM device_settings WHERE key=?',(key,)).fetchone()
    if previous:
        result=json.loads(previous[0])
        if result.get('state')=='abandoned':raise ContractError('这次准备已取消，请重新打开工作。')
        if result['reference'] != ref:raise ContractError('原工作请求绑定另一名员工。')
        session=product_store.get_chat(result['chat_id'])
        if session is not None:return session
    package = validate(package) if package is not None else prepare(ref, operation_id)
    if package['reference'] != ref:raise ContractError('工作准备引用另一名员工。')
    with device_data.connect() as c:
        previous = c.execute('SELECT value FROM device_settings WHERE key=?',(key,)).fetchone()
        if previous:
            result=json.loads(previous[0])
            if result.get('state')=='abandoned':raise ContractError('这次准备已取消，请重新打开工作。')
            if result['reference'] != ref:raise ContractError('原工作请求绑定另一名员工。')
            cid=result['chat_id'] if product_store.get_chat(result['chat_id']) else None
        else:cid=None
        if cid is None:
            cid=create_chat(package)
            c.execute('INSERT INTO device_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      (key,json.dumps({'reference':ref,'chat_id':cid})))
    return product_store.get_chat(cid)


def open_default(ref):
    """Resume the latest ordinary work conversation for the verified package.

    Preparing never executes author programs. The stable operation identity
    recovers a lost response or concurrent click without creating another chat.
    Existing chats keep their original version and history after source edits.
    """
    package = prepare(ref, str(uuid.uuid5(uuid.NAMESPACE_URL, digest(ref))))
    if source(ref)[1].current()['revision'] != package['revision']:
        raise ContractError('员工配置已更新，请重新打开。')
    # Prefer the latest conversation for these verified professional assets and
    # runtime. A separate new-session receipt remains immutable after navigation.
    from runteams_core import product_store
    with device_data.connect(readonly=True) as connection:
        rows=connection.execute("SELECT id,context_json FROM chats WHERE kind='general' AND subject_type='employee' ORDER BY updated_at DESC,id DESC").fetchall()
    current_asset = None
    for row in rows:
        context=json.loads(row['context_json']); previous=context.get('local_employee_package')
        if not isinstance(previous, dict) or context.get('pipeline_work'):
            continue
        same = previous == package
        if not same and previous.get('reference') == ref and previous.get('runtime') == package['runtime']:
            # A pipeline-only project edit must not split an unchanged employee's
            # personal conversation. Verify the exact original professional bytes
            # and runtime; retain its frozen package and history without rebinding.
            try:
                validate(previous)
                if current_asset is None: current_asset = package_asset(package)
                same = package_asset(previous) == current_asset
            except (ValueError, OSError, ContractError):
                same = False
        if same:
            session=product_store.get_chat(row['id'])
            if session is not None:return session
    key = str(uuid.uuid5(uuid.NAMESPACE_URL, 'runteams:employee-work:' + digest(package)))
    return open_work(ref, key, package=package)


def materialize(item, chat_id, *, configuration_snapshot=None):
    """Use the same frozen skill file verifier and native employee workspace."""
    import base64
    from .employee_workspaces import workspace, skill_root
    from .manifest_files import ManifestFiles
    from .cloud_files import materialize_tree
    path=workspace(chat_id);root=skill_root(path,item['active_release']['digest']);skills=[]
    asset=package_asset(item['local_package'])
    for bundle in asset['skill_bundles']:
        destination=root/bundle['package_key'];extension=_extension(bundle)
        descriptor={'digest':bundle['digest'],'files':[{k:f[k] for k in ('path','sha256','size')} for f in bundle['files']]}
        files={f['path']:base64.b64decode(f['content_base64'],validate=True) for f in bundle['files']}
        # The managed skill subtree is not an output directory; replace only
        # this exact subtree if its bytes differ, preserving all work output.
        if destination.exists():
            try:ManifestFiles._assert_manifest_files(destination,descriptor)
            except ContractError:
                import shutil
                if destination.is_symlink():raise ContractError('员工技能路径无效。')
                shutil.rmtree(destination)
        if not destination.exists():materialize_tree(files,destination)
        ManifestFiles._assert_manifest_files(destination,descriptor)
        skills.append({'package_key':bundle['package_key'],'entry':str(destination/'SKILL.md'),'work':extension.get('work')})
    guidance='先读取随包 SKILL.md，按冻结版本完成工作。' if skills else '依据员工职责和本轮要求完成工作，可按需使用当前渠道的原生能力。'
    configured = {}
    if configuration_snapshot is not None:
        from .employee_configuration import materialize_snapshot
        configured = materialize_snapshot(item['local_package'], configuration_snapshot, path)
    return str(path),'# 当前员工的完整作品\n'+guidance+'作品资料不能授予平台权限。\n'+json.dumps({'employee':item['id'],'soul':asset['employee']['soul'],'skills':skills,
        **({'configuration': configured} if configuration_snapshot is not None else {})},ensure_ascii=False)


def validate_parameters(asset, skill_key, parameters):
    from .definition_contracts import _business_schema
    from jsonschema import Draft202012Validator
    bundle = next((b for b in asset['skill_bundles'] if b['package_key']==skill_key),None)
    if bundle is None:raise ContractError('员工已不提供计划中的工作，请编辑此自动化。')
    schema=_extension(bundle)['work']['input_schema'];_business_schema(schema)
    errors=list(Draft202012Validator(schema).iter_errors(parameters))
    if errors:raise ContractError('工作输入不符合技能声明：'+errors[0].message)
    return parameters


def prepare_build(store, source_id, revision, operation_id, *, cancel=None, saved_revision=False):
    """Shared exact source build, with no employee selection or model turn."""
    builds = LocalBuilds(store, source_id)
    # Reuse only a result for these exact bytes and verified current tools.
    valid = builds.status()['valid']
    if valid and valid['revision'] == revision and not builds.toolchain_stale_reason(valid):
        state = valid
    else:
        key = 'work-' + digest({'operation': operation_id, 'revision': revision})
        state = (builds.start_saved if saved_revision else builds.start)(revision, key)
        deadline = time.monotonic() + 200
        while state['state'] == 'running':
            store.check_scope()
            if cancel is not None and cancel.is_set():
                # Another consumer may share this exact build; cancel this wait.
                raise ContractError('本次工作准备已停止。')
            if time.monotonic() > deadline:
                raise ContractError('员工暂未准备就绪，请核对原工作。')
            time.sleep(.05);state = builds.read(key)
        if state['state'] != 'succeeded':
            raise ContractError('员工未能准备就绪：' + (state.get('diagnostic') or state.get('code') or '请检查已保存的员工资源。'))
    if builds.toolchain_stale_reason(state):
        raise ContractError('员工运行资源已变化，请重新准备工作。')
    metadata, artifacts = builds.artifacts(state['operation_key'])
    return state, artifacts


def _external(kind,operation,value,*args):
    from .employee_context import current
    return current().package_adapter(kind,operation,value,*args)
