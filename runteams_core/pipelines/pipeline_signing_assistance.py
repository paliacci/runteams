"""Task-bound handoff from a pipeline conversation to device signing verification."""
import datetime
import json
import plistlib
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from runteams_core.authoring.creator_contracts import digest
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_work_access as access
from runteams_core.storage import device_data

TOOL = 'runteams_verify_pipeline_signing'
INPUT = {'type': 'object', 'properties': {
    'workflow_id': {'type': 'integer', 'minimum': 1, 'maximum': 2**53 - 1},
    'app_path': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
    'device': {'type': 'string', 'pattern': '^[0-9A-Fa-f-]{8,64}$'},
}, 'required': ['workflow_id', 'app_path', 'device'], 'additionalProperties': False}


def _key(chat_id):
    return 'pipeline-signing-assistance:' + device_data.epoch(chat_id)


def _load(connection, key):
    row = connection.execute("SELECT data_json FROM events WHERE stream=? "
                             "AND type='pipeline.signing_assistance_opened' ORDER BY id DESC LIMIT 1", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def binding(core, chat_id):
    key = _key(chat_id)
    with core.repository.read_snapshot() as connection:
        return _load(connection, key)


def guidance(assistance):
    target = assistance['target']
    return (
        f"\n本对话从任务 {target['workflow_id']} 的真机签名阻塞打开。用户要求处理该阻塞时，"
        "先核对原工作；实际完成开发签名、安装并启动后，调用 runteams_verify_pipeline_signing "
        "提交原任务编号、本机已签名 App 的绝对路径和该 iPhone 的设备标识。工具会直接核对设备与签名，"
        "只有收到成功回执才说明任务已更新。不要用工具代做人工决定或更新其他工作。")


def _target(row, frozen):
    from runteams_core.pipelines.source_pipeline_flow import signing_setup

    waiting = frozen.get('pipeline_waiting') or {}
    state = row['state'] if row['state'] != 'paused' else (frozen.get('pipeline_pause') or {}).get('previous_state')
    if (state not in ('blocked', 'needs_human') or not signing_setup(frozen)
            or not waiting.get('source_run_id') or (frozen.get('pipeline_execution') or {}).get('active')
            or frozen.get('pipeline_unresolved') or frozen.get('pipeline_recovery_pending')):
        raise ContractError('这项工作的签名阻塞已变化，请重新打开任务卡。')
    bundle = frozen.get('pipeline_input', {}).get('parameters', {}).get('bundle_id')
    if not isinstance(bundle, str) or not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle):
        raise ContractError('请先在任务卡保存项目的 Bundle ID。')
    return {'workflow_id': row['id'], 'visit': frozen['pipeline_visit'], 'bundle_id': bundle,
            'generation': frozen['pipeline_generation'], 'blocker': digest(waiting)}


def bind(core, chat_id, reference, workflow_id):
    if access.bound(chat_id) != reference:
        raise PermissionError('对话不属于这条流水线。')
    key = _key(chat_id)
    with core.repository.connect() as connection:
        row, frozen = access._row(connection, reference, workflow_id)
        target = _target(row, frozen)
        existing = _load(connection, key)
        if existing and existing['target'] == target:
            return
        core.repository.event(key, 'pipeline.signing_assistance_opened',
                              {'id': str(uuid.uuid4()), 'target': target}, connection=connection)


def _command(*args):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=25).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ContractError('本机未能核验签名或读取这台 iPhone，请检查构建和设备连接。') from error


def _device(directory, action, selector, *args):
    output = directory / (action + '.json')
    _command('/usr/bin/xcrun', 'devicectl', 'device', 'info', action, '--device', selector,
             '--timeout', '15', '--json-output', str(output), *args)
    response = json.loads(output.read_bytes())
    if response['info']['outcome'] != 'success':
        raise ContractError('iPhone 未返回可核验的设备结果。')
    return response['result']


def _url_path(url):
    return unquote(urlparse(url).path).rstrip('/')


def verify(bundle, app_path, selector):
    """Collect evidence from macOS and the paired device, never from model output."""
    if sys.platform != 'darwin':
        raise ContractError('真机签名回写需要运行在连接 iPhone 的 Mac 上。')
    app = Path(app_path)
    if not app.is_absolute() or app.suffix != '.app' or not app.is_dir():
        raise ContractError('请选择已签名的 iPhone App 构建。')
    try:
        info = plistlib.loads((app / 'Info.plist').read_bytes())
        if info['CFBundleIdentifier'] != bundle or 'iPhoneOS' not in info['CFBundleSupportedPlatforms']:
            raise ContractError('该构建与任务的 iPhone Bundle ID 不匹配。')
        executable = info['CFBundleExecutable']
        if not isinstance(executable, str) or not executable or '/' in executable:
            raise ContractError('iPhone 构建的可执行文件信息无效。')
        _command('/usr/bin/codesign', '--verify', '--deep', '--strict', '-R', '=anchor apple generic', str(app))
        profile = plistlib.loads(_command('/usr/bin/security', 'cms', '-D', '-i', str(app / 'embedded.mobileprovision')))
        entitlements = plistlib.loads(_command('/usr/bin/codesign', '-d', '--entitlements', ':-', str(app)))
        team, = profile['TeamIdentifier']
        if (not re.fullmatch(r'[A-Z0-9]{10}', team) or 'iOS' not in profile['Platform']
                or profile['ExpirationDate'] <= datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
                or any(e.get('application-identifier') != team + '.' + bundle or e.get('get-task-allow') is not True
                       for e in (entitlements, profile['Entitlements']))):
            raise ContractError('构建没有匹配任务的有效 iOS 开发签名。')
        with tempfile.TemporaryDirectory(prefix='runteams-signing-') as folder:
            directory = Path(folder)
            prefix = directory / 'signer'
            _command('/usr/bin/codesign', '-d', '--extract-certificates=' + str(prefix), str(app))
            if (directory / 'signer0').read_bytes() not in profile['DeveloperCertificates']:
                raise ContractError('签名证书与开发描述文件不匹配。')
            device = _device(directory, 'details', selector)
            hardware = device['hardwareProperties']
            if (hardware['platform'] != 'iOS' or hardware['reality'] != 'physical'
                    or device['connectionProperties']['pairingState'] != 'paired'
                    or hardware['udid'].casefold() not in {value.casefold() for value in profile['ProvisionedDevices']}):
                raise ContractError('开发描述文件没有覆盖这台已配对的 iPhone。')
            installed = _device(directory, 'apps', hardware['udid'], '--bundle-id', bundle)
            apps = [item for item in installed['apps']
                    if item.get('bundleIdentifier') == bundle and item.get('builtByDeveloper') is True]
            if len(apps) != 1 or (apps[0].get('version'), apps[0].get('bundleVersion')) != (
                    info['CFBundleShortVersionString'], info['CFBundleVersion']):
                raise ContractError('iPhone 上还没有安装这一版本的 App。')
            processes = _device(directory, 'processes', hardware['udid'])
            installed_path = _url_path(apps[0]['url'])
            if (not installed_path.endswith('.app') or
                    not any(_url_path(p.get('executable', '')) == installed_path + '/' + executable
                            for p in processes['runningProcesses'])):
                raise ContractError('请先在这台 iPhone 上启动已安装的 App。')
        return {'team_id': team, 'bundle_id': bundle, 'version': info['CFBundleShortVersionString'],
                'build': info['CFBundleVersion'], 'device_model': hardware['marketingName']}
    except (OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError('签名或 iPhone 返回的信息不完整，任务状态未更新。') from error


def _receipt(connection, assistance):
    row = connection.execute("SELECT data_json FROM events WHERE stream=? AND type='workflow.signing_verified' "
                             "AND json_extract(data_json,'$.assistance_id')=?",
                             ('workflow_run:' + str(assistance['target']['workflow_id']), assistance['id'])).fetchone()
    return json.loads(row[0]) if row else None


def resolve(core, chat_id, assistance, arguments, *, actor_id=None, cancel=None):
    access._validate(INPUT, arguments)
    reference = access.bound(chat_id, actor_id)
    if not assistance:
        raise PermissionError('请从当前任务卡打开协助对话。')
    target = assistance['target']
    identifier = target['workflow_id']
    if arguments['workflow_id'] != identifier:
        raise PermissionError('只能更新打开本次协助的任务。')
    key = _key(chat_id)
    core._actor()
    with core.repository.read_snapshot() as connection:
        if _load(connection, key) != assistance:
            raise PermissionError('协助对话已切换到其他任务。')
        if receipt := _receipt(connection, assistance):
            return receipt
        row, frozen = access._row(connection, reference, identifier)
        if _target(row, frozen) != target:
            raise ContractError('任务已经更新，请核对当前阻塞。')
    evidence = verify(target['bundle_id'], arguments['app_path'], arguments['device'])
    if cancel is not None and cancel.is_set():
        raise ContractError('协助已停止，未更新任务。')
    from runteams_core.pipelines.source_pipeline_flow import resume_verified_signing
    with core.repository.audit_context(actor_id=actor_id, source='agent_tool'), core.repository.connect() as connection:
        if _load(connection, key) != assistance:
            raise PermissionError('协助对话已切换到其他任务。')
        if receipt := _receipt(connection, assistance):
            return receipt
        row, frozen = access._row(connection, reference, identifier)
        if _target(row, frozen) != target:
            raise ContractError('任务已经更新，请核对当前阻塞。')
        if cancel is not None and cancel.is_set():
            raise ContractError('协助已停止，未更新任务。')
        core.repository.storage.assert_executable(identifier)
        state = resume_verified_signing(core, connection, row, frozen, evidence)
        if cancel is not None and cancel.is_set():
            raise ContractError('协助已停止，未更新任务。')
        receipt = {'workflow_id': identifier, 'visit': target['visit'], 'state': state,
                   'verification': evidence, 'assistance_id': assistance['id']}
        core.repository.event('workflow_run:' + str(identifier), 'workflow.signing_verified',
                              receipt, connection=connection)
    return receipt
