"""Native-terminal entry point for a work's bound Python, not a host exec tool."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from runteams_core import agent_environment
from runteams_core.work_environment import BindingStore, EnvironmentError, file_identity

_MODULE = re.compile(r'^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$')
_MARKER = 'RUNTEAMS_ENVIRONMENT_PROBE='
_PROBE = '''import importlib,json,sys,sysconfig
modules={}
for name in json.loads(sys.argv[1]):
 try:
  module=importlib.import_module(name)
  modules[name]={'ok':True,'origin':getattr(module,'__file__',None)}
 except Exception as error:
  modules[name]={'ok':False,'error':str(error)[:1000]}
print('RUNTEAMS_ENVIRONMENT_PROBE='+json.dumps({'version':sys.version.split()[0],
 'prefix':sys.prefix,'modules':modules,'library':sysconfig.get_config_var('LDLIBRARY'),
 'library_directory':sysconfig.get_config_var('LIBDIR'),'base_prefix':sys.base_prefix,
 'framework_prefix':sysconfig.get_config_var('PYTHONFRAMEWORKPREFIX')}))
'''


def compatible(version, requirement):
    if requirement.get('status') == 'unreadable':
        raise EnvironmentError('项目 Python 版本约定未能读取，不能冒称兼容。')
    current = Version(version)
    spec = requirement.get('requires_python')
    if spec and current not in SpecifierSet(spec):
        raise EnvironmentError('绑定的 Python {} 不满足项目要求 {}。'.format(version, spec))
    declared = requirement.get('python_version_file')
    if declared:
        if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', declared):
            raise EnvironmentError('.python-version 无法自动核对，请明确项目解释器。')
        spec = '==' + declared + ('.*' if len(declared.split('.')) == 2 else '')
        if current not in SpecifierSet(spec):
            raise EnvironmentError('绑定的 Python {} 不满足 .python-version {}。'.format(version, declared))


def _origin_valid(item):
    if not item.get('origin'):
        return True
    try:
        return file_identity(item['origin']) == item['identity']
    except (OSError, ValueError):
        return False


def _runtime_files(info):
    name = info.get('library') or ''
    candidates = [Path(prefix) / name for prefix in (
        info.get('library_directory'), info.get('framework_prefix')) if prefix and name]
    if info.get('base_prefix') and name:
        candidates.extend([Path(info['base_prefix']) / name, Path(info['base_prefix']) / 'lib' / name])
    return [{'origin': str(path), 'identity': file_identity(path)}
            for path in dict.fromkeys(candidates) if path.is_file()]


def _inspect(executable, cwd, python, modules, no_site=False):
    env = agent_environment.execution_env(os.environ, cwd, {'python': python})
    result = subprocess.run([executable, '-I', '-B', *(['-S'] if no_site else []),
        '-c', _PROBE, json.dumps(modules)], cwd=cwd, capture_output=True,
        text=True, timeout=20, env=env)
    line = next(line[len(_MARKER):] for line in reversed(result.stdout.splitlines()) if line.startswith(_MARKER))
    if result.returncode:
        raise EnvironmentError('Python 环境校验失败。')
    return json.loads(line)


def verify(store, expected, modules, readonly=False):
    if len(modules) > 30 or any(not _MODULE.fullmatch(name) for name in modules):
        raise EnvironmentError('模块要求格式无效。')
    with store.locked(readonly=readonly):
        record = store.load()
        if record['binding_id'] != expected:
            raise EnvironmentError('绑定已变化，请读取当前环境，不要继续使用旧入口。')
        store.check(record)
        contract = record['contract']
        previous = record.get('verification') or {}
        cached = previous.get('status') == 'passed' and all(
            name in previous.get('modules', {}) and _origin_valid(previous['modules'][name]) for name in modules)
        if cached:
            for item in previous.get('runtime_files', []):
                if not _origin_valid(item):
                    raise EnvironmentError('已验证的 Python 运行库发生变化，请明确重新选择环境。')
            return contract['python']['executable'], contract['cwd'], record, True
        executable = contract['python']['executable']
        try:
            def probe(requested, no_site=False):
                return _inspect(executable, contract['cwd'], contract['python'], requested, no_site)
            # Check version without loading project site hooks or requested
            # packages first. An incompatible environment must not import them.
            basic = probe([], no_site=True)
            if record.get('observed_runtime') and record['observed_runtime']['version'] != basic['version']:
                raise EnvironmentError('绑定的 Python 实际版本发生变化，请明确重新选择环境。')
            record['observed_runtime'] = {'version': basic['version'], 'runtime_files': _runtime_files(basic)}
            compatible(basic['version'], contract['requirements'])
            info = probe(modules)
            if info['version'] != basic['version']:
                raise EnvironmentError('Python 启动后的版本事实不一致，未执行脚本。')
            runtime_files = _runtime_files(info)
            observed = record.get('observed_runtime')
            if observed and observed['version'] != info['version']:
                raise EnvironmentError('绑定的 Python 实际版本发生变化，请明确重新选择环境。')
            record['observed_runtime'] = {'version': info['version'], 'prefix': info['prefix'], 'runtime_files': runtime_files}
            compatible(info['version'], contract['requirements'])
            if contract['python'].get('environment') and Path(info['prefix']).resolve() != Path(contract['python']['environment']).resolve():
                raise EnvironmentError('Python 实际运行环境与绑定的项目虚拟环境不一致。')
            if contract['python'].get('source') == 'managed' and info['version'] != contract['python']['version']:
                raise EnvironmentError('Python 实际版本与绑定的托管版本不一致。')
            failed = [name for name in modules if not info['modules'][name]['ok']]
            if failed:
                raise EnvironmentError('绑定环境缺少或无法导入模块：' + ', '.join(failed) + '；未切换解释器。')
            checked = ({name: item for name, item in previous.get('modules', {}).items() if name not in modules}
                       if previous.get('status') == 'passed' else {})
            checked = dict(list(checked.items())[-(128 - len(modules)):])
            for name, item in info['modules'].items():
                checked[name] = {'origin': item.get('origin')}
                if item.get('origin'):
                    checked[name]['identity'] = file_identity(item['origin'])
            store.check(record)
            record['verification'] = {'status': 'passed', 'version': info['version'],
                'modules': checked, 'runtime_files': runtime_files, 'checked_at': time.time()}
            if not readonly:
                store.save(record)
            return executable, contract['cwd'], record, False
        except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
            failure = {'status': 'failed', 'reason': str(error)[:1000], 'checked_at': time.time()}
            record['verification'] = ({**previous, 'last_failure': failure}
                if previous.get('status') == 'passed' else failure)
            if not readonly:
                store.save(record)
            if isinstance(error, EnvironmentError):
                raise
            raise EnvironmentError('绑定的 Python 校验未通过；未执行脚本，也未切换环境。') from None


def prepare(store, expected, packages, modules, reason, readonly=False):
    """An explicit native-terminal dependency action, never a run-time fallback.

    A base interpreter gets a fresh work-owned venv from that exact interpreter.
    Existing project venvs retain their binding. Failed preparations never bind
    a replacement, and no user script is retried by this operation.
    """
    if readonly:
        raise EnvironmentError('只读验收不能准备或安装依赖。')
    if not packages or len(packages) > 20 or not str(reason).strip() or len(reason) > 1000:
        raise EnvironmentError('准备依赖需要明确的包、所需模块和原因。')
    if not modules or len(modules) > 30 or any(not _MODULE.fullmatch(name) for name in modules):
        raise EnvironmentError('请声明准备后要验证的模块。')
    for package in packages:
        if len(package) > 2048:
            raise EnvironmentError('依赖声明过长。')
        Requirement(package)
    verify(store, expected, [])
    created = None
    try:
        with store.locked():
            previous = store.load()
            if previous['binding_id'] != expected:
                raise EnvironmentError('环境已被其他操作更新，请读取当前绑定后再准备依赖。')
            store.check(previous)
            contract = previous['contract']; python = dict(contract['python']); cwd = contract['cwd']
            executable = python['executable']
            environment = python.get('environment')
            base = not environment or Path(environment).resolve() == agent_environment.runtime_root().resolve()

            def execute(argv, target_python, timeout=180):
                env = agent_environment.execution_env(os.environ, cwd, {'python': target_python})
                # Dependency preparation cannot inherit an unrelated pip target,
                # prefix, user install or configuration from the backend/CLI.
                env = {key: value for key, value in env.items() if not key.startswith('PIP_')}
                env.update(PIP_CONFIG_FILE=os.devnull, PIP_REQUIRE_VIRTUALENV='true')
                result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
                if result.returncode:
                    raise EnvironmentError('依赖准备未完成：' + (result.stderr or result.stdout)[-2000:])

            if base:
                parent = store.root.parent / 'python-environments' / store.key
                from runteams_core.work_environment import _directory
                _directory(parent)
                created = parent / uuid.uuid4().hex
                execute([executable, '-I', '-B', '-m', 'venv', str(created)], python, 60)
                executable = str(created / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python'))
                python = {'source': 'explicit', 'status': 'detected', 'verified': False,
                          'environment': str(created), 'executable': executable}
            else:
                # A successful/partial pip operation can change transitive
                # dependencies too, so invalidate the old module receipt first.
                previous['verification'] = None
                store.save(previous)
            info = _inspect(executable, cwd, python, ['pip'])
            if Path(info['prefix']).resolve() != Path(python['environment']).resolve():
                raise EnvironmentError('依赖安装目标与工作虚拟环境不一致。')
            if not info['modules']['pip']['ok']:
                execute([executable, '-I', '-B', '-m', 'ensurepip', '--upgrade'], python, 60)
            execute([executable, '-I', '-B', '-m', 'pip', '--disable-pip-version-check',
                'install', '--no-input', '--no-user', '--', *packages], python)
            info = _inspect(executable, cwd, python, modules)
            compatible(info['version'], contract['requirements'])
            if info['version'] != previous['observed_runtime']['version']:
                raise EnvironmentError('依赖准备改变了 Python 版本，未采用新环境。')
            failed = [name for name in modules if not info['modules'][name]['ok']]
            if failed:
                raise EnvironmentError('安装后仍无法导入模块：' + ', '.join(failed))
            store.check(previous)
            record = store._new(cwd, 'explicit', previous, reason, executable) if base else previous
            record['preparation'] = {'packages': packages, 'modules': modules,
                                     'reason': reason, 'prepared_at': time.time()}
            store.save(record)
            created = None  # The new binding now owns this directory.
        verify(store, record['binding_id'], modules)
        return store.current()
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as error:
        if isinstance(error, EnvironmentError):
            raise
        raise EnvironmentError('依赖准备未完成；请核对原生终端回执，不会自动更换 Python。') from None
    finally:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--binding-id', required=True)
    parser.add_argument('--read-only-state', action='store_true')
    commands = parser.add_subparsers(dest='action', required=True)
    for name in ('run', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('--require', action='append', default=[])
        if name == 'run':
            command.add_argument('python_args', nargs=argparse.REMAINDER)
    select = commands.add_parser('select')
    select.add_argument('--source', choices=['project', 'managed', 'explicit'], required=True)
    select.add_argument('--executable')
    select.add_argument('--reason', required=True)
    preparation = commands.add_parser('prepare')
    preparation.add_argument('--package', action='append', required=True)
    preparation.add_argument('--require', action='append', required=True)
    preparation.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    try:
        store = BindingStore.record(args.record)
        if args.action == 'prepare':
            print(json.dumps(prepare(store, args.binding_id, args.package,
                list(dict.fromkeys(args.require)), args.reason, args.read_only_state), ensure_ascii=False))
            return 0
        if args.action == 'select':
            if args.read_only_state:
                raise EnvironmentError('只读验收不能切换工作的执行环境。')
            print(json.dumps(store.select(args.binding_id, args.source, args.reason, args.executable), ensure_ascii=False))
            return 0
        executable, cwd, record, cached = verify(store, args.binding_id, list(dict.fromkeys(args.require)), args.read_only_state)
        if args.action == 'verify':
            print(json.dumps({'binding_id': record['binding_id'], 'verification': store.present(record)['verification'], 'cached': cached}, ensure_ascii=False))
            return 0
        arguments = args.python_args
        if arguments[:1] == ['--']:
            arguments = arguments[1:]
        if not arguments:
            raise EnvironmentError('请提供 Python 脚本、-c 或 -m 参数。')
        if arguments[:2] == ['-m', 'pip'] and any(value in arguments[2:] for value in ('install', 'uninstall')):
            prefix = (record.get('observed_runtime') or {}).get('prefix')
            managed_base = prefix and Path(prefix).resolve() == agent_environment.runtime_root().resolve()
            if not record['contract']['python'].get('environment') or managed_base or '--user' in arguments:
                raise EnvironmentError('请在工作区自己的虚拟环境安装依赖，不修改托管底座或用户全局包。')
        snapshot = store.present(record)
        if snapshot['python']['status'] != 'ready' or any(
                name not in snapshot['python'].get('modules', {}) for name in args.require):
            raise EnvironmentError('环境在校验后发生变化，未执行脚本；请重新核对绑定。')
        env = agent_environment.execution_env(os.environ, cwd, snapshot)
        os.chdir(cwd)
        os.execve(executable, [executable, *arguments], env)
    except (OSError, ValueError) as error:
        print('RunTeams Python：' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
