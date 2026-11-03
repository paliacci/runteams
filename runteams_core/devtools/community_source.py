"""Validate, audit and stage the canonical community source contract.

This creates an internal source candidate, never a public release or Git remote.
It does not infer an export by walking the repository or copy private state.
"""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import ast
import hashlib
from importlib.util import resolve_name
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT=source_root()
CONTRACT='contracts/community-build.json'
GROUPS=('runtime_sources','runtime_assets','native_sources','build_sources','notices')
FORBIDDEN={'runteams_official','supabase','.git','.build','.venv','node_modules','runtime-dependencies','design','cases','dist'}
SECRET_SUFFIXES={'.p12','.pfx','.p8','.key','.sqlite3','.db','.mobileprovision'}


def valid_path(root,name):
    if not isinstance(name,str) or not name:raise ValueError('Empty source input')
    path=Path(name)
    if (path.is_absolute() or name!=path.as_posix() or '..' in path.parts or '\\' in name
        or path.parts[0] in FORBIDDEN or any(p.startswith('.env') for p in path.parts)
        or path.suffix in SECRET_SUFFIXES):raise ValueError('Forbidden source input: '+name)
    source=Path(root)/path
    linked=any((Path(root)/Path(*path.parts[:i])).is_symlink() for i in range(1,len(path.parts)+1))
    if linked or not source.is_file() or not source.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('Missing, linked or external source input: '+name)
    return source


def load_boundaries(root, contract):
    name=contract.get('dependency_boundaries')
    if not isinstance(name,str) or name not in contract['build_sources']:
        raise ValueError('Source dependency boundaries must be an explicit build input')
    value=json.loads(valid_path(root,name).read_bytes())
    if (not isinstance(value,dict) or set(value)!={'schema','owners','modules'}
            or value['schema']!='runteams.community-source-boundaries/1'
            or not isinstance(value['owners'],dict) or not isinstance(value['modules'],dict)):
        raise ValueError('Invalid source dependency boundary contract')
    for owner,info in value['owners'].items():
        if (not re.fullmatch(r'[a-z][a-z0-9-]*',owner) or not isinstance(info,dict)
                or set(info)!={'description','requires_joint_work'}
                or not isinstance(info['description'],str) or not info['description'].strip()
                or type(info['requires_joint_work']) is not bool):
            raise ValueError('Invalid source dependency owner: '+str(owner))
    for module,info in value['modules'].items():
        if (not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',module)
                or not isinstance(info,dict) or set(info)!={'path','owner','reason'}
                or info['path'] not in (module.replace('.','/')+'.py',module.replace('.','/')+'/__init__.py')
                or not isinstance(info['owner'],str) or info['owner'] not in value['owners']
                or not isinstance(info['reason'],str) or not info['reason'].strip()):
            raise ValueError('Invalid source dependency declaration: '+str(module))
    return value


def load_contract(root=ROOT):
    path=valid_path(root,CONTRACT);value=json.loads(path.read_bytes())
    if value.get('schema')!='runteams.community-build/1':raise ValueError('Unknown standalone community build contract')
    for group in GROUPS:
        names=value.get(group)
        if not isinstance(names,list) or any(not isinstance(n,str) for n in names) or len(set(names))!=len(names):
            raise ValueError('Invalid or duplicate community input group: '+group)
        for name in names:valid_path(root,name)
    if value.get('entrypoint')!='runteams_core.community' or 'runteams_core/community.py' not in value['runtime_sources']:
        raise ValueError('Community must declare its direct source entry')
    if value.get('native_build_entrypoint')!='desktop/community/build.py' or CONTRACT not in value['build_sources']:
        raise ValueError('Community must declare its direct standalone build entry and contract')
    pairs=value.get('python_packages')
    if not isinstance(pairs,list) or not pairs or any(not isinstance(p,list) or len(p)!=2 or not all(isinstance(n,str) and n for n in p) for p in pairs):
        raise ValueError('Invalid community Python distribution/module declaration')
    load_boundaries(root,value)
    return value


def inputs(contract):return sorted(set().union(*(contract[g] for g in GROUPS)))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repository_module(root,module,known=None):
    for name in (module.replace('.','/')+'.py',module.replace('.','/')+'/__init__.py'):
        if (root/name).is_file():return name
    return (known or {}).get(module)


def python_edges(root,name,known=None):
    result=[];package='.'.join(Path(name).parent.parts)
    class Imports(ast.NodeVisitor):
        deferred=0
        context=[]
        def visit_FunctionDef(self,node):
            self.context.append(node.name)
            self.deferred+=1;self.generic_visit(node);self.deferred-=1
            self.context.pop()
        visit_AsyncFunctionDef=visit_FunctionDef
        def visit_ClassDef(self,node):
            self.context.append(node.name);self.generic_visit(node);self.context.pop()
        def record(self,module,node):
            target=repository_module(root,module,known)
            if target:result.append({'source':name,'line':node.lineno,'module':module,'target':target,
                'deferred':bool(self.deferred),'context':'.'.join(self.context) or '<module>'})
        def visit_Import(self,node):
            for alias in node.names:self.record(alias.name,node)
        def visit_ImportFrom(self,node):
            module=node.module or ''
            if node.level:module=resolve_name('.'*node.level+module,package)
            self.record(module,node)
            for alias in node.names:self.record(module+'.'+alias.name,node)
    Imports().visit(ast.parse((root/name).read_text(),filename=name))
    return result


def worker_entrypoints(root, selected):
    """Audit the canonical subprocess registry as well as Python imports."""
    registry='runteams_core/creator_worker_process.py'
    if registry not in selected:return []
    module=ast.parse((Path(root)/registry).read_text())
    entries=[n for n in module.body if isinstance(n,ast.Assign) and any(
        isinstance(t,ast.Name) and t.id=='WORKERS' for t in n.targets)]
    if len(entries)!=1:raise ValueError('Missing canonical creator worker registry')
    values=ast.literal_eval(entries[0].value)
    if not isinstance(values,dict) or not values:raise ValueError('Invalid creator worker registry')
    result=[]
    for kind,name in sorted(values.items()):
        if (not isinstance(kind,str) or not re.fullmatch('[a-z]+',kind) or
                not isinstance(name,str) or not re.fullmatch(r'[a-z_]+\.py',name)):
            raise ValueError('Invalid creator worker entry')
        target='runteams_core/'+name
        result.append({'kind':kind,'path':target,'included':target in selected})
    return result


def audit(root=ROOT,contract=None):
    root=Path(root);contract=contract or load_contract(root);selected=set(inputs(contract));edges=[]
    workers=worker_entrypoints(root,selected)
    boundaries=load_boundaries(root,contract)
    known={module:info['path'] for module,info in boundaries['modules'].items()}
    for name in sorted(selected):
        if name.endswith('.py'):edges.extend(python_edges(root,name,known))
    omitted=[edge for edge in edges if edge['target'] not in selected]
    unclassified=[];groups=[];used=set();independent=joint=0
    for owner,info in boundaries['owners'].items():
        owned=[]
        for edge in omitted:
            declaration=boundaries['modules'].get(edge['module'])
            if declaration and declaration['path']==edge['target'] and declaration['owner']==owner:
                used.add(edge['module'])
                owned.append({key:edge[key] for key in ('source','context','module','target')})
        count=len(owned)
        if info['requires_joint_work']:joint+=count
        else:independent+=count
        if owned:groups.append({'owner':owner,**info,'count':count,'imports':owned})
    for edge in omitted:
        declaration=boundaries['modules'].get(edge['module'])
        if not declaration or declaration['path']!=edge['target']:
            unclassified.append({key:edge[key] for key in ('source','context','module','target')})
    ownership={'fully_classified':not unclassified and not (set(known)-used),
        'independent_non_work_edges':independent,'requires_joint_work_edges':joint,
        'unclassified':unclassified,'unused_declarations':sorted(set(known)-used),'groups':groups,
        'classification_is_source_closure':False}
    # These are source-level candidates for extraction, not proof of execution.
    # Python function branches and UI capability gates remain the existing ones.
    private_routes=[]
    private_inputs=[name for name in contract['runtime_assets'] if name=='web/ui/creator-rental.js' or name.startswith('web/ui/market/')]
    route_references=[]
    route_literal=re.compile(r"['\"`](/api/(?:account|billing|organizations|market|core/marketplace)[^'\"`\n]*)")
    pattern=re.compile(r'\b(?:api|fetch)\s*\(\s*[\'\"`](/api/(?:account|billing|organizations|market|core/marketplace)[^\'\"`\n]*)')
    for name in contract['runtime_assets']:
        if Path(name).suffix not in ('.js','.html'):continue
        text=(root/name).read_text()
        for match in pattern.finditer(text):private_routes.append({'source':name,'line':text.count('\n',0,match.start())+1,'route':match[1]})
        for match in route_literal.finditer(text):route_references.append({'source':name,'line':text.count('\n',0,match.start())+1,'route':match[1]})
    report={'schema':'runteams.community-source-audit/1','public_release_ready':False,
        'selected_files':len(selected),'runtime_sources':len(contract['runtime_sources']),'ui_assets':len(contract['runtime_assets']),
        'repository_import_edges':len(edges),'source_imports_outside_candidate':omitted,'official_ui_route_calls':private_routes,'official_ui_asset_inputs':private_inputs,
        'official_api_route_references':route_references,
        'dependency_ownership':ownership,'worker_entrypoints':workers,
        'worker_entrypoints_complete':all(x['included'] for x in workers),
        'blockers':[{'id':'official-api-route-references','count':len(route_references),'scope':'All literal official API route references, including indirect constructions and classifiers, must stay out of selected free UI source.'},
                    {'id':'official-ui-asset-inputs','count':len(private_inputs),'scope':'Official rental implementation and marketplace-only artwork must not be selected free source inputs.'},
                    {'id':'worker-entrypoint-closure','count':sum(not x['included'] for x in workers),'scope':'Canonical subprocess entry points must be explicit source inputs.'},
                    {'id':'source-dependency-closure','count':len(omitted),'scope':'Full selected source, including function branches not exposed by the free service.'},
                    {'id':'official-ui-source-fragments','count':len(private_routes),'scope':'Literal official API calls in shared UI; runtime gating is not physical source separation.'},
                    {'id':'publication-snapshot-review','scope':'This source export does not audit Git history or grant publication authority; use the separately reviewed release snapshot.'}],
        'runtime_execution_claim':False,'notes':'This static audit establishes selected source/import boundaries only. Product execution and publication authority require their own delivery evidence. No source rewriting or automatic dependency expansion is performed.'}
    report['blockers']=[item for item in report['blockers'] if item.get('count',1)>0]
    return report


def stage(output,root=ROOT):
    root=Path(root).resolve();contract=load_contract(root);output=Path(output).expanduser().absolute()
    # Resolve the parent as well: a symlink must not route an export back into the source tree.
    output=output.parent.resolve()/output.name
    if output.exists() or output.is_symlink() or output.is_relative_to(root):
        raise ValueError('Choose a new candidate directory outside the shared repository')
    report=audit(root,contract);records=[]
    if not report['worker_entrypoints_complete']:
        raise ValueError('Creator worker entry points must be included before export')
    if not report['dependency_ownership']['fully_classified']:
        raise ValueError('Review unclassified or stale source dependency boundaries before export')
    for name in inputs(contract):
        source=valid_path(root,name);records.append({'path':name,'sha256':digest(source),'bytes':source.stat().st_size})
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.community-source-',dir=output.parent) as td:
        tree=Path(td)/'candidate';tree.mkdir()
        for item in records:
            source=valid_path(root,item['path']);target=tree/item['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            if digest(target)!=item['sha256'] or digest(source)!=item['sha256']:
                raise ValueError('Source changed during export; retry after the current save: '+item['path'])
        value={'schema':'runteams.community-source-candidate/1','purpose':'internal split/build acceptance only',
               'version':(tree/'VERSION').read_text().strip(),'public_release_ready':False,'inputs':records,'audit':report,
               'private_repository_required_to_build':False,'no_git_history_or_remote_created':True}
        (tree/'SOURCE_EXPORT.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        shutil.copyfile(root/'README.md',tree/'README.md')
        # Revalidate the candidate itself, without importing the product or consulting design/progress files.
        load_contract(tree)
        tree.rename(output)
    return {'output':str(output),'files':len(records),'public_release_ready':False,'audit':report}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path);parser.add_argument('--audit',type=Path);args=parser.parse_args()
    try:
        value=stage(args.output,args.root) if args.output else audit(args.root)
        if args.audit:args.audit.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    except (ValueError,OSError) as error:parser.exit(2,str(error)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k not in ('audit','source_imports_outside_candidate','official_ui_route_calls','dependency_ownership')},ensure_ascii=False))


if __name__=='__main__':main()
