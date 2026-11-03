// Private platform subprocess. MCP framing/negotiation belongs to the official SDK.
// This channel is never exposed to author pages or accepted as a network endpoint.
import {Client} from '@modelcontextprotocol/client';
import {StdioClientTransport} from '@modelcontextprotocol/client/stdio';
import {createInterface} from 'node:readline';
import {Server} from '@modelcontextprotocol/server';
import {StdioServerTransport} from '@modelcontextprotocol/server/stdio';
import {request as httpRequest} from 'node:http';

let client, transport, opened = false;
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const capabilities = {extensions: {'io.modelcontextprotocol/ui': {mimeTypes: ['text/html;profile=mcp-app']}}};
async function dispatch(method, params) {
  if (method === 'open') {
    if (opened) throw new Error('already_open');
    opened = true;
    // Parent validates the immutable package, runtime and explicit enablement.
    transport = new StdioClientTransport({...params, stderr: 'pipe', maxBufferSize: 4 * 1024 * 1024});
    // Consume bounded diagnostics; author stderr can contain credentials, so it
    // is not copied to platform logs or browser messages.
    transport.stderr?.on('data', () => {});
    client = new Client({name: 'runteams', version: '0.1.0'}, {capabilities});
    await client.connect(transport, {timeout: 10000});
    return {server: client.getServerVersion(), capabilities: client.getServerCapabilities()};
  }
  if (!client) throw new Error('not_open');
  switch (method) {
    case 'tools/list': return client.listTools(params);
    case 'tools/call': return client.callTool(params, undefined, {timeout: 60000});
    case 'resources/list': return client.listResources(params);
    case 'resources/read': return client.readResource(params);
    case 'prompts/list': return client.listPrompts(params);
    case 'prompts/get': return client.getPrompt(params);
    case 'close': await client.close(); return {closed: true};
    default: throw new Error('method_unavailable');
  }
}

// One in-flight request: lifecycle/order are deterministic and no hidden retry
// is made when a tool's external effect may already have happened.
async function main() {
const input = createInterface({input: process.stdin, crlfDelay: Infinity});
for await (const line of input) {
  let frame;
  try {
    if (Buffer.byteLength(line) > 4 * 1024 * 1024) throw new Error('message_budget');
    frame = JSON.parse(line);
    const result = await dispatch(frame.method, frame.params ?? {});
    send({id: frame.id, result});
  } catch {
    // Do not echo an arbitrary SDK/server exception (it may contain a secret).
    send({id: frame?.id, error: 'mcp_request_failed'});
  }
}
await client?.close();

}

// Official Runtime connects to a private proxy, not another author process.
// The original work owner retains the only MCP client/process and durable call
// receipts. Capability lives in this managed proxy, never in the author's env.
async function proxy(endpoint) {
  const url = new URL(endpoint), token = process.env.RUNTEAMS_EMPLOYEE_PROXY;
  delete process.env.RUNTEAMS_EMPLOYEE_PROXY;
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.pathname !== '/protocol' || !token) throw Error('invalid_proxy');
  let sequence = 0;
  const invoke = (method, params) => new Promise((resolve, reject) => {
    const body = JSON.stringify({jsonrpc:'2.0', id:++sequence, method, params});
    const request = httpRequest(url, {method:'POST', headers:{'Content-Type':'application/json',
      Authorization:'Bearer '+token, 'Content-Length':Buffer.byteLength(body)}}, response => {
      let body = '';
      response.on('data', chunk => {body += chunk; if (body.length > 4*1024*1024) response.destroy();});
      response.on('end', () => {try {const result=JSON.parse(body); if(result.error) throw Error('employee_call_unknown_or_denied'); resolve(result.result);} catch(error) {reject(error);}});
      response.on('error', reject);
    });
    request.setTimeout(70000, () => request.destroy(Error('employee_call_unknown')));
    request.on('error', reject); request.end(body);
  });
  const server = new Server({name:'runteams-employee-work',version:'0.1.0'},{capabilities:{tools:{}}});
  server.setRequestHandler('tools/list', request => invoke('tools/list', request.params ?? {}));
  server.setRequestHandler('tools/call', request => invoke('tools/call', request.params ?? {}));
  await server.connect(new StdioServerTransport());
}
(process.argv[2] === '--employee-proxy' ? proxy(process.argv[3]) : main()).catch(() => { process.exitCode = 1; });
