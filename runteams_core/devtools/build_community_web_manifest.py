"""Register the canonical business UI's static files without creating a UI fork."""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runteams_core.devtools.source_root import root as source_root

import argparse
import json
from pathlib import Path
import sys

ROOT=source_root()
sys.path.insert(0,str(ROOT))
from runteams_core.local_web import OFFICIAL_ASSETS


def expected():
    result={'/':['web/index.html','text/html; charset=utf-8']}
    types={'.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml',
           '.woff2':'font/woff2','.html':'text/html; charset=utf-8','.json':'application/json','.wasm':'application/wasm',
           '.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.txt':'text/plain; charset=utf-8'}
    for directory in ('web/ui','web/modules','web/vendor','web/fonts','web/worker-avatars','web/provider-icons','web/rich-document'):
        for path in sorted((ROOT/directory).rglob('*')):
            if not path.is_file() or path.is_symlink() or path.suffix not in types:continue
            url='/'+path.relative_to(ROOT/'web').as_posix()
            if url not in OFFICIAL_ASSETS:result[url]=[path.relative_to(ROOT).as_posix(),types[path.suffix]]
    for path,mime in [('web/runteams.css','text/css; charset=utf-8'),('web/favicon.svg','image/svg+xml')]:result['/'+path.removeprefix('web/')]=[path,mime]
    for name in ('application.js','bootstrap.js','client.js','native.js'):result['/community/'+name]=['frontend/community/'+name,types['.js']]
    for path in ('/chat/new','/chats/new','/docs','/documents','/trash','/pipelines','/pipelines/new'):result[path]=result['/']
    result['/ui/page-routes-contract.js']=['contracts/page-routes.json',types['.js']]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    target=ROOT/'runteams_core/community_web_assets.json';contract=ROOT/'contracts/community-build.json'
    assets=expected();sources=list(dict.fromkeys(row[0] for row in assets.values()));state=json.loads(contract.read_text())
    if args.check:
        if json.loads(target.read_text())!=assets or state['runtime_assets']!=sources:parser.exit(2,'Shared UI asset register changed; run this script before building.\n')
    else:
        target.write_text(json.dumps(assets,ensure_ascii=False,indent=2)+'\n');state['runtime_assets']=sources;contract.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'shared_entry':'web/index.html','assets':len(sources),'checked':args.check}))


if __name__=='__main__':main()
