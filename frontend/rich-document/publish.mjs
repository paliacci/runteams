// Preserve modules used by already-open editors; publish the new entry last.
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),source=path.join(here,'.build'),destination=path.resolve(here,'../../web/rich-document/dist');
await fs.mkdir(path.join(destination,'assets'),{recursive:true});
for(const file of await fs.readdir(path.join(source,'assets')))await fs.copyFile(path.join(source,'assets',file),path.join(destination,'assets',file));
await fs.copyFile(path.join(source,'index.html'),path.join(destination,'.index-next.html'));
await fs.rename(path.join(destination,'.index-next.html'),path.join(destination,'index.html'));

// Publish the chat renderer manifest only after all hashed assets are present.
const manifest=JSON.parse(await fs.readFile(path.join(source,'.vite/manifest.json'),'utf8'));
const reply=manifest['src/reply-content.jsx'];
const bundle={entry:'/rich-document/dist/'+reply.file,css:(reply.css||[]).map(file=>'/rich-document/dist/'+file)};
const bridge=path.resolve(here,'../../web/ui/reply-content-bundle.js');
await fs.writeFile(bridge+'.next','window.RunTeamsReplyBundle='+JSON.stringify(bundle)+';\n');
await fs.rename(bridge+'.next',bridge);

// Windows virtual environments expose python.exe. Unix builds use the versioned interpreter.
const python = process.platform === 'win32' ? 'python' : 'python3.12';
execFileSync(python, ['-B', '../../runteams_core/devtools/build_community_web_manifest.py'], {cwd: here, stdio: 'inherit'});
