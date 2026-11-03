import {build} from 'esbuild';
import {mkdir, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const flags = process.argv.slice(2);
if (flags.some(flag => !flag.startsWith('--outfile='))) throw new Error('Only --outfile=<path> is accepted');
const target = flags.find(flag => flag.startsWith('--outfile='))?.slice('--outfile='.length);
const result = await build({
  absWorkingDir: root, entryPoints: ['src/main.jsx'], bundle: true, minify: true,
  legalComments: 'linked', format: 'iife', globalName: 'RunTeamsResourceViewer',
  outfile: resolve(root, target || '../../web/vendor/resource-viewer.js'),
  // The viewer only uses vanilla, read-only Sandpack with autorun disabled.
  // Do not distribute the unused Nodebox runtime or replace it with a shim.
  external: ['./clients/node/index.mjs'], metafile: true,
});
if (Object.keys(result.metafile.inputs).some(name => /nodebox|clients\/node\//.test(name))) {
  throw new Error('Unsupported Nodebox runtime entered the resource viewer');
}
await mkdir(resolve(root, '.build'), {recursive: true});
await writeFile(resolve(root, '.build/metafile.json'), JSON.stringify(result.metafile, null, 2) + '\n');
