"""Build the self-contained community AppKit application and optional DMG."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.macos_signing import Signer, macho, executable_macho, sign_runtime, seal_runtime, verify_release_app

BUNDLE_ID = 'ai.runteams.community'
from runteams_core.devtools.community_source import load_contract


def dependency_plan(python):
    requirements = dict(line.split('==') for line in
        (ROOT / 'requirements-community.txt').read_text().splitlines() if line and not line.startswith('#'))
    probe = '''import importlib,importlib.metadata,json,sys
from pathlib import Path
records=[];seen=set()
for distribution,name in json.loads(sys.argv[1]):
 dist=importlib.metadata.distribution(distribution)
 info=next(p.parent for p in dist.files if p.name=='METADATA' and p.parent.name.endswith('.dist-info'))
 source=Path(importlib.import_module(name).__file__)
 if source.name=='__init__.py':source=source.parent
 for package,path in [(source.name,source),(info.name,Path(dist.locate_file(info)))]:
  if package in seen:continue
  seen.add(package);records.append({'distribution':distribution,'version':dist.version,'package':package,'source':str(path)})
print(json.dumps(records))'''
    result = subprocess.run([str(python), '-I', '-c', probe, json.dumps(load_contract(ROOT)['python_packages'])],
                            capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError('Install requirements-community.txt in the chosen build Python environment')
    records = json.loads(result.stdout)
    inputs = []
    for record in records:
        if requirements.get(record['distribution']) != record['version']:
            raise ValueError('Community dependency version differs from requirements-community.txt')
        source = Path(record['source'])
        for path in sorted(source.rglob('*')) if source.is_dir() else [source]:
            if '__pycache__' in path.parts or path.suffix == '.pyc':continue
            if path.is_symlink():raise ValueError('Dependency packages must not contain symbolic links')
            if path.is_file():
                relative=record['package']+('/'+path.relative_to(source).as_posix() if source.is_dir() else '')
                inputs.append({'path':relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return records, inputs


def application_site(runtime, packages):
    """Let native Python children use the same sealed application dependencies."""
    runtime, packages = Path(runtime).resolve(), Path(packages).resolve()
    result = subprocess.run([str(runtime/'bin/python3'), '-I', '-B', '-c',
        'import sysconfig;print(sysconfig.get_path("purelib"))'],
        check=True, capture_output=True, text=True, timeout=15)
    site = Path(result.stdout.strip()).resolve()
    if not site.is_relative_to(runtime) or not site.is_dir() or not packages.is_dir():
        raise ValueError('Application dependency directory must belong to the staged Python layout')
    entry = site/'runteams-application.pth'
    if entry.exists() or entry.is_symlink():
        raise ValueError('Application dependency entry already exists')
    relative = os.path.relpath(packages, site)
    if '\n' in relative or '\r' in relative:
        raise ValueError('Application dependency path is invalid')
    with entry.open('x') as target:
        target.write(relative+'\n')
    return entry


def plan(output=None, build_python=None, data_directory=None, python_runtime=None, *, local=False, sign_identity=None, sign_keychain=None, creator_builder=None, mcp_runtime=None):
    signer=Signer.resolve(local=local,identity=sign_identity,keychain=sign_keychain)
    if data_directory and not local:raise ValueError("Release builds cannot pin an acceptance library; --data-dir requires --local")
    subprocess.run([sys.executable,str(ROOT/'runteams_core/devtools/build_community_web_manifest.py'),'--check'],
                   check=True,capture_output=True,timeout=20)
    contract=load_contract(ROOT)
    inputs=contract['runtime_sources']+contract['runtime_assets']
    files=[]
    for relative in inputs:
        source=ROOT/relative
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(ROOT):
            raise ValueError('Invalid community runtime input: '+relative)
        files.append({'path':relative,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    target=Path(output or ROOT/'.build/community/RunTeams Local.app').expanduser().absolute()
    if target.suffix!='.app' or target.exists() or target.is_symlink():
        raise ValueError('Choose a new .app output; existing applications are never replaced')
    python=Path(build_python or sys.executable).expanduser().absolute()
    lock=json.loads((ROOT/'contracts/agent-python.lock.json').read_text())
    version=subprocess.run([str(python),'-I','-S','-c','import json,sys;print(json.dumps(list(sys.version_info[:2])))'],capture_output=True,text=True,timeout=10)
    if version.returncode or json.loads(version.stdout)!=[int(v) for v in lock['version'].split('.')[:2]]:
        raise ValueError('Build dependencies require Python 3.12, matching the bundled runtime ABI')
    dependencies,package_inputs=dependency_plan(python)
    from desktop.community.sdk_resources import snapshot
    sdk_resources=snapshot(creator_builder,mcp_runtime)
    runtime=Path(python_runtime).expanduser().absolute() if python_runtime else ROOT/'runtime-dependencies/agent-python'
    if python_runtime or runtime.exists():
        from agent_environment import verify_runtime
        verify_runtime(runtime)
    else:runtime=None
    return target,{'schema':'runteams.community-desktop/3','version':(ROOT/'VERSION').read_text().strip(),
        'python_version':lock['version'],
        'data_directory':str(Path(data_directory).expanduser().resolve()) if data_directory else None,
        '_signer':signer,'_source_inputs':files,'_notice_inputs':[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in contract['notices']],'_package_inputs':package_inputs,'_dependency_sources':dependencies,
        '_runtime_source':str(runtime) if runtime else None, '_sdk_resources':sdk_resources}


def inventory(root):
    values=[]
    for path in sorted(Path(root).rglob('*')):
        relative=path.relative_to(root).as_posix()
        if '__pycache__' in path.parts:continue
        if path.is_symlink():
            if not path.resolve().is_relative_to(Path(root).resolve()):raise ValueError('Bundle link leaves resources')
            values.append({'path':relative,'link':path.readlink().as_posix()})
        elif path.is_file():values.append({'path':relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return values


def build(output=None, build_python=None, data_directory=None, validate_only=False, python_runtime=None, *, local=False, sign_identity=None, sign_keychain=None, creator_builder=None, mcp_runtime=None):
    target,config=plan(output,build_python,data_directory,python_runtime,local=local,sign_identity=sign_identity,sign_keychain=sign_keychain,creator_builder=creator_builder,mcp_runtime=mcp_runtime)
    signer=config.pop("_signer")
    if sys.platform!='darwin':raise ValueError('The native shell currently targets macOS')
    if validate_only:return {'output':str(target),'runtime_inputs':len(config['_source_inputs']),'self_contained_installer':True,'python_version':config['python_version'],'distribution':'local' if signer.local else 'developer-id','notarized':False}
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.community-build-',dir=target.parent) as td:
        app=Path(td)/target.name;resources=app/'Contents/Resources';core=resources/'core';core.mkdir(parents=True)
        sources=config.pop('_source_inputs')
        for item in sources:
            source=ROOT/item['path'];path=core/item['path'];path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Source changed during snapshot; retry after the current edit')
        for item in config.pop('_notice_inputs'):
            path=resources/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/item['path'],path)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Notice changed during copy')
        runtime=core/'runtime-dependencies/agent-python';runtime.parent.mkdir(parents=True)
        from runteams_core.devtools.prepare_agent_python import stage,prepare
        runtime_source=config.pop('_runtime_source')
        if runtime_source:stage(runtime_source,runtime)
        else:prepare(runtime)
        from desktop.community.sdk_resources import stage as stage_sdk
        config['sdk_build_resources']=stage_sdk(core,config.pop('_sdk_resources'),signer)
        packages=resources/'python-packages';packages.mkdir()
        for record in config.pop('_dependency_sources'):
            source=Path(record['source']);target_package=packages/record['package']
            if source.is_dir():shutil.copytree(source,target_package,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else:shutil.copyfile(source,target_package)
        for item in config.pop('_package_inputs'):
            if hashlib.sha256((packages/item['path']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Dependency changed during copy')
        for path in sorted(packages.rglob('*')):
            if macho(path):signer.sign(path,executable=executable_macho(path))
        application_site(runtime,packages)
        seal_runtime(runtime)
        if not signer.local:sign_runtime(runtime,signer)
        # Execute the packaged interpreter with packaged modules, never the builder's site directory.
        python=runtime/'bin/python3'
        probe='import sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];import ssl,sqlite3,tomllib,PIL.Image,pypdfium2,yaml,jsonschema,agent_environment;assert agent_environment.managed_python()["status"]=="ready"'
        env={k:v for k,v in __import__('os').environ.items() if k not in ('PYTHONHOME','PYTHONPATH') and not k.startswith(('RUNTEAMS_','DYLD_','_PYI'))}
        subprocess.run([str(python),'-I','-S','-B','-c',probe,str(core),str(packages)],env=env,check=True,capture_output=True,timeout=30)
        subprocess.run([str(python),'-E','-s','-B',str(core/'agent_python.py'),'--help'],env=env,check=True,capture_output=True,timeout=30)
        sdk_probe='import sys;sys.path.insert(0,sys.argv[1]);from runteams_core.creator_build_tools import load;from runteams_core.employee_mcp import platform_runtime;from runteams_core.creator_worker_process import WORKERS;from pathlib import Path;load();r=platform_runtime();r.verify();assert all((Path(sys.argv[1])/"runteams_core"/n).is_file() for n in WORKERS.values())'
        subprocess.run([str(python),'-I','-B','-c',sdk_probe,str(core)],env=env,check=True,timeout=30)
        executable=app/'Contents/MacOS/RunTeamsLocal';executable.parent.mkdir()
        subprocess.run(['/usr/bin/xcrun','swiftc','-swift-version','5','-target',
            ('arm64' if platform.machine()=='arm64' else 'x86_64')+'-apple-macosx12.0',
            *[str(ROOT/'desktop/community'/name) for name in ('Policy.swift','Bootstrap.swift','main.swift')],
            *[str(ROOT/'desktop/creator'/name) for name in ('CreatorDesktopHost.swift','CreatorCloudWork.swift','CreatorWebHost.swift')],
            '-framework','AppKit','-framework','WebKit','-o',str(executable)],check=True)
        picker=resources/'RunTeamsPicker.app';binary=picker/'Contents/MacOS/RunTeamsPicker';binary.parent.mkdir(parents=True)
        subprocess.run(['/usr/bin/xcrun','swiftc','-swift-version','5',str(ROOT/'desktop/attachment_picker.swift'),'-framework','AppKit','-o',str(binary)],check=True)
        info=plistlib.loads((ROOT/'desktop/RunTeamsPicker-Info.plist').read_bytes());info.update(CFBundleIdentifier='ai.runteams.community.picker',CFBundleDisplayName='RunTeams 本机文件选择器')
        (picker/'Contents/Info.plist').write_bytes(plistlib.dumps(info));signer.sign(picker,executable=True)
        shutil.copyfile(ROOT/'desktop/RunTeams.icns',resources/'RunTeams.icns')
        config['inputs']=inventory(resources)
        (resources/'bootstrap.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'RunTeamsLocalBuild':signer.local,'CFBundleIdentifier':BUNDLE_ID,'CFBundleName':'RunTeams Local','CFBundleDisplayName':'RunTeams 本机版','CFBundleExecutable':'RunTeamsLocal','CFBundlePackageType':'APPL','CFBundleVersion':config['version'],'CFBundleShortVersionString':config['version'],'CFBundleIconFile':'RunTeams.icns','LSMinimumSystemVersion':'12.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}))
        signer.sign(app,executable=True)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
        subprocess.run([str(executable),'--check-bootstrap'],check=True,capture_output=True,timeout=30)
        if not signer.local:verify_release_app(app,signer)
        app.rename(target)
    return {'output':str(target),'runtime_inputs':len(sources),'sealed_resource_files':len(config['inputs']),'self_contained_installer':True,'python_version':config['python_version'],'distribution':'local' if signer.local else 'developer-id','notarized':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path);parser.add_argument('--build-python',type=Path)
    parser.add_argument('--python-runtime',type=Path,help='Verified prepared runtime; otherwise prepare the pinned release during build')
    parser.add_argument('--creator-builder',type=Path,help='Verified prepared platform parser directory; build-time input only')
    parser.add_argument('--mcp-runtime',type=Path,help='Verified complete Node24/MCP resources; build-time input only')
    parser.add_argument('--data-dir',type=Path,help='Explicit isolated library for acceptance testing')
    parser.add_argument('--validate-only',action='store_true');parser.add_argument('--dmg',type=Path)
    parser.add_argument('--local',action='store_true',help='Explicit ad-hoc acceptance build; never a distributable release')
    parser.add_argument('--sign-identity',help='Exact Developer ID Application identity name or SHA1')
    parser.add_argument('--sign-keychain',type=Path)
    parser.add_argument('--notary-profile',help='Existing notarytool keychain profile; no password arguments')
    parser.add_argument('--notary-keychain',type=Path)
    parser.add_argument('--notary-state',type=Path)
    parser.add_argument('--resume',action='store_true',help='Continue the exact original notarization receipt without another upload')
    args=parser.parse_args()
    try:
        if args.local:
            if args.notary_profile or args.notary_keychain or args.notary_state or args.resume:
                raise ValueError('--local cannot notarize or resume a release')
            if args.validate_only and args.dmg:raise ValueError('Local --validate-only cannot package a DMG')
        else:
            if not args.dmg or not args.notary_profile:
                raise ValueError('Release requires --dmg and --notary-profile; local acceptance requires explicit --local')
            if args.data_dir:raise ValueError('Release cannot pin an acceptance library')
        if args.resume:
            if args.local or args.validate_only:
                raise ValueError('--resume requires the original release destinations and credentials')
            result={'output':str(args.output or ROOT/'.build/community/RunTeams Local.app'),'distribution':'developer-id'}
        else:
            if args.dmg and (args.dmg.exists() or args.dmg.suffix!='.dmg'):raise ValueError('Choose a new .dmg output')
            if args.notary_state and args.notary_state.exists():raise ValueError('Notary receipt already exists; use --resume')
            result=build(args.output,args.build_python,args.data_dir,args.validate_only,args.python_runtime,
                         local=args.local,sign_identity=args.sign_identity,sign_keychain=args.sign_keychain,creator_builder=args.creator_builder,mcp_runtime=args.mcp_runtime)
        if args.dmg and not args.validate_only:
            if args.local:
                from runteams_core.devtools.package_desktop_dmg import package
                result['package']=package(result['output'],args.dmg)
            else:
                from desktop.community.notarization import Workflow
                signer=Signer.resolve(identity=args.sign_identity,keychain=args.sign_keychain)
                workflow=Workflow(result['output'],args.dmg,signer,args.notary_profile,
                    args.notary_state or args.dmg.with_suffix('.notarization.json'),keychain=args.notary_keychain,resume=args.resume)
                result['package']=workflow.finish();result['notarized']=True
    except (ValueError,OSError,subprocess.SubprocessError) as error:parser.exit(2,str(error)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
