import {build} from 'esbuild';
import {mkdir, writeFile, readFile, readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const out = resolve(process.argv[2] ?? '../../runtime-dependencies/mcp-host');
await mkdir(out, {recursive: true});
await build({entryPoints: [resolve(root, 'worker.mjs')], outfile: resolve(out, 'worker.cjs'),
  bundle: true, platform: 'node', format: 'cjs', target: 'node22', legalComments: 'linked'});
await build({entryPoints: [resolve(root, 'app-host.mjs')], outfile: resolve(out, 'app-host.js'),
  bundle: true, platform: 'browser', format: 'esm', target: 'es2022', legalComments: 'linked'});
// Reusable official authoring libraries, prepared by the platform. Authors
// edit ordinary JS beside these pinned complete offline bundles.
await build({stdin:{contents:"export {McpServer} from '@modelcontextprotocol/server'; export {StdioServerTransport} from '@modelcontextprotocol/server/stdio'; export {registerAppTool,registerAppResource} from '@modelcontextprotocol/ext-apps/server'; export {z} from 'zod';",resolveDir:root,sourcefile:'creator-server.mjs'},
  outfile:resolve(out,'creator-server.cjs'),bundle:true,platform:'node',format:'cjs',target:'node24',legalComments:'linked'});
await build({stdin:{contents:"export {App} from '@modelcontextprotocol/ext-apps'; export * from '../ui/index.js';",resolveDir:root,sourcefile:'creator-app.mjs'},
  outfile:resolve(out,'creator-app.js'),bundle:true,platform:'browser',format:'iife',globalName:'RunTeamsMCP',target:'es2022',legalComments:'linked'});
// Reproducible platform resources, not author-supplied dependencies.
const lock = await readFile(resolve(root, 'package-lock.json'));
await writeFile(resolve(out, 'provenance.json'), JSON.stringify({
  schema: 'runteams.mcp-host-build/1',
  lock_sha256: createHash('sha256').update(lock).digest('hex'),
  client: '2.4.0', apps: '2.0.3',
  files: Object.fromEntries(await Promise.all(['worker.cjs','app-host.js','creator-server.cjs','creator-app.js'].map(async name=>[name,createHash('sha256').update(await readFile(resolve(out,name))).digest('hex')]))),
}, null, 2) + '\n');
const packages = JSON.parse(lock).packages;
const notices = [];
for (const [path, info] of Object.entries(packages)) {
  if (!path || info.dev || info.optional) continue;
  const files = await readdir(resolve(root, path));
  const name = files.find(name => /^(licen[cs]e|copying)(\..*)?$/i.test(name));
  if (!name) throw new Error('Missing dependency license: ' + path);
  notices.push(path + '@' + info.version + '\n' + await readFile(resolve(root, path, name), 'utf8'));
}
await writeFile(resolve(out, 'THIRD_PARTY_NOTICES.txt'), notices.join('\n\n'));
