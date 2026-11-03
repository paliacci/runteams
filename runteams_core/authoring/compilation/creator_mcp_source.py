"""Deterministic MCPB packing of complete author sources; never runs author code."""
import base64
import io
import re
import zipfile
from pathlib import PurePosixPath

from runteams_core.authoring.creator_contracts import CreatorContractError, relative, strict_json
from runteams_core.employees.mcp.employee_mcp_package import MCPBundle, sha256

PROJECT = 'runteams.creator-project/2'
LOCK = 'dependencies.lock.json'


def mcp_project(files):
    return strict_json(files['project.json']).get('schema') == PROJECT


def package_files(files, directory):
    prefix = relative(directory)+'/mcp/'
    values = {p[len(prefix):]:b for p,b in files.items() if p.startswith(prefix)}
    if not values:return None
    if 'employee.mcpb' in values:raise CreatorContractError('mcp_generated_path_reserved')
    if 'manifest.json' not in values:raise CreatorContractError('missing_mcp_manifest')
    manifest = strict_json(values['manifest.json'])
    if manifest.get('server',{}).get('type')!='node':
        raise CreatorContractError('mcp_source_runtime_unavailable','当前源码构建支持随包完整的 Node 程序；其他运行附件尚未验收。')
    entry=relative(manifest['server']['entry_point'])
    if PurePosixPath(entry).suffix not in ('.js','.cjs','.mjs'):
        raise CreatorContractError('mcp_javascript_entry_required','入口须是可直接运行的 JavaScript；不能把源码编译留给使用者。')
    vendors={p:b for p,b in values.items() if p.startswith('vendor/') or '/node_modules/' in '/'+p}
    if vendors:
        lock=strict_json(values.get(LOCK,b'{}'))
        expected={p:{'sha256':sha256(b),'size':len(b)} for p,b in sorted(vendors.items())}
        if lock!={'schema':'runteams.mcp-dependencies/1','files':expected}:
            raise CreatorContractError('mcp_dependency_integrity')
    # Inventory/lock admission is pure. The fixed platform parser resolves
    # literal JS imports during build; text regexes misread strings in bundled
    # compilers such as AJV as actual require calls. No author code runs there.
    # Canonical stored ZIP makes the derived attachment independently
    # reproducible on the client/download validator without a compiler.
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
        for name,body in sorted(values.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0));info.external_attr=(0o100644)<<16
            archive.writestr(info,body)
    raw=output.getvalue()
    try:MCPBundle.inspect(raw)
    except ValueError as error:raise CreatorContractError('invalid_mcp_package',str(error)) from error
    return raw


def packages(files, compiled):
    if compiled['project']['schema']!=PROJECT:return {}
    result={}
    for employee in compiled['employees'].values():
        for directory in employee['skill_dirs']:
            if directory not in result:
                raw=package_files(files,directory)
                if raw is not None:result[directory]=raw
            if directory in result:MCPBundle.inspect(result[directory]).verify_credential_configuration(employee.get('configuration',{'groups':[]}))
    for pipeline in compiled['pipelines'].values():
        for program in program_sources(pipeline):
            directory=program['source']
            if directory not in result:
                raw=package_files(files,directory)
                if raw is None:raise CreatorContractError('missing_pipeline_program')
                result[directory]=raw
            MCPBundle.inspect(result[directory]).verify_credential_configuration(pipeline.get('configuration',{'groups':[]}))
    return result


def program_sources(pipeline):
    """Validated attachments owned by a pipeline, never synthetic employees."""
    result=pipeline.get('programs',[]);keys=set();sources=set()
    if not isinstance(result,list) or len(result)>64:raise CreatorContractError('invalid_pipeline_programs')
    for item in result:
        if (not isinstance(item,dict) or set(item)!={'key','source'} or
                not isinstance(item['key'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,79}',item['key'])):
            raise CreatorContractError('invalid_pipeline_program')
        directory=relative(item['source'])
        if item['key'] in keys or directory in sources:raise CreatorContractError('duplicate_pipeline_program')
        keys.add(item['key']);sources.add(directory)
    return result


def pipeline_programs(files,compiled):
    """Freeze complete MCPB bytes, with exactly the source-declared ownership."""
    result={};raw_by_source={};encoded={};size=0
    for path,pipeline in compiled['pipelines'].items():
        values=[]
        for program in program_sources(pipeline):
            directory=program['source']
            if directory not in raw_by_source:raw_by_source[directory]=package_files(files,directory)
            raw=raw_by_source[directory]
            if raw is None:raise CreatorContractError('missing_pipeline_program')
            MCPBundle.inspect(raw).verify_credential_configuration(pipeline.get('configuration',{'groups':[]}))
            size+=4*((len(raw)+2)//3)
            if size>32*1024*1024:raise CreatorContractError('artifact_limit')
            if directory not in encoded:encoded[directory]=base64.b64encode(raw).decode('ascii')
            values.append({**program,'sha256':sha256(raw),'size':len(raw),
                'content_base64':encoded[directory]})
        if values:result[path]=values
    return result


def verify_pipeline_programs(values):
    """Inspect pinned bytes; listing/verification never starts author code."""
    from jsonschema import Draft202012Validator
    from runteams_core.authoring.definition_contracts import contract_catalog
    schema=contract_catalog()['extensions']['marketplace_pipeline']['$defs']['pipeline_program_bundle']
    if not isinstance(values,list) or len(values)>64:raise CreatorContractError('invalid_pipeline_programs')
    keys=set();sources=set()
    for item in values:
        if next(Draft202012Validator(schema).iter_errors(item),None):raise CreatorContractError('invalid_pipeline_program_bundle')
        directory=relative(item['source'])
        if item['key'] in keys or directory in sources:raise CreatorContractError('duplicate_pipeline_program')
        try:raw=base64.b64decode(item['content_base64'],validate=True)
        except ValueError:raise CreatorContractError('invalid_pipeline_program_bundle') from None
        if (len(raw)!=item['size'] or sha256(raw)!=item['sha256'] or
                base64.b64encode(raw).decode('ascii')!=item['content_base64']):
            raise CreatorContractError('pipeline_program_integrity')
        try:MCPBundle.inspect(raw)
        except ValueError as error:raise CreatorContractError('invalid_mcp_package',str(error)) from error
        keys.add(item['key']);sources.add(directory)
    return values


def definition_files(files, compiled):
    result=dict(files)
    for directory,raw in packages(files,compiled).items():result[directory+'/mcp/employee.mcpb']=raw
    return result


def execution(files, compiled):
    return {'kind':'skills-and-mcp','packages':[{'source':directory,'artifact':'mcp/'+sha256(directory.encode())+'.mcpb',
        'sha256':sha256(raw)} for directory,raw in sorted(packages(files,compiled).items())]}
