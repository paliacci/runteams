// Isolated protocol fixture; never a delivered employee or business backend.
import {McpServer} from '@modelcontextprotocol/server';
import {StdioServerTransport} from '@modelcontextprotocol/server/stdio';
import {registerAppTool, registerAppResource} from '@modelcontextprotocol/ext-apps/server';
import {z} from 'zod';
import {appendFileSync, writeFileSync, readFileSync, existsSync} from 'node:fs';
import {dirname, join} from 'node:path';

writeFileSync('started', String(process.pid));
const server = new McpServer({name: 'runteams-isolated-fixture', version: '1.0.0'});
registerAppTool(server, 'calculate', {description: 'Add two numbers',
  inputSchema: z.object({a: z.number(), b: z.number()}),
  _meta: {ui: {resourceUri: 'ui://fixture/calculator.html'}}}, async ({a, b}) => {
    appendFileSync('calls', 'calculate\n');
    return {content: [{type: 'text', text: String(a + b)}], structuredContent: {total: a + b}};
  });
server.registerTool('environment', {description: 'Fixture environment', inputSchema: z.object({})}, async () => ({
  content: [{type: 'text', text: JSON.stringify({cwd: process.cwd(), secret: process.env.RUNTEAMS_TEST_SECRET ?? null,
    nodeOptions: process.env.NODE_OPTIONS ?? null, platformToken: process.env.SUPABASE_SERVICE_ROLE_KEY ?? null})}]
}));
server.registerTool('write_then_wait', {description: 'Unknown outcome fixture', inputSchema: z.object({})}, async () => {
  appendFileSync('calls', 'write_then_wait\n');
  await new Promise(() => {});
});
registerAppResource(server, 'Calculator', 'ui://fixture/calculator.html', {}, async uri => ({contents: [{
  uri: uri.href, mimeType: 'text/html;profile=mcp-app', text: existsSync(join(dirname(process.argv[1]), 'view.html'))
    ? readFileSync(join(dirname(process.argv[1]), 'view.html'), 'utf8')
    : '<!doctype html><html><body>Calculator</body></html>'
}]}));
server.connect(new StdioServerTransport()).catch(() => {process.exitCode = 1;});
