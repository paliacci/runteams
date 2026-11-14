// Private platform subprocess. MCP framing/negotiation belongs to the official SDK.
// This channel is never exposed to author pages or accepted as a network endpoint.
import {Client, InMemoryTransport, StreamableHTTPClientTransport, UnauthorizedError} from '@modelcontextprotocol/client';
import {StdioClientTransport} from '@modelcontextprotocol/client/stdio';
import {createInterface} from 'node:readline';
import {Server} from '@modelcontextprotocol/server';
import {StdioServerTransport} from '@modelcontextprotocol/server/stdio';
import {request as httpRequest} from 'node:http';
import {testServer} from './test-tools.mjs';

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
async function testConnection() {
  const sendTest = reply => {
    const line = JSON.stringify(reply);
    send(Buffer.byteLength(line) > 1024 * 1024 ? {error:'response_too_large'} : reply);
  };
  const input = createInterface({input: process.stdin, crlfDelay: Infinity});
  for await (const line of input) {
    input.close();
    const {url, token, tool, arguments: args} = JSON.parse(line);
    const testClient = new Client({name:'RunTeams',version:'1.0.0'});
    let testTransport, server;
    let authRejected = false;
    const unauthorized = error => authRejected || error instanceof UnauthorizedError;
    try {
      if (url) {
        testTransport = new StreamableHTTPClientTransport(new URL(url), {
          requestInit: {redirect: 'error', headers: token ? {Authorization: 'Bearer '+token} : {}},
          fetch: async (input, options) => {
            const response = await fetch(input, options);
            if (response.status === 401 || response.status === 403) authRejected = true;
            return response;
          },
          reconnectionOptions: {maxRetries: 0}
        });
      } else {
        const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
        testTransport = clientSide;
        server = testServer();
        await server.connect(serverSide);
      }
      await testClient.connect(testTransport, {timeout: 8000});
      const options = {timeout: 12000};
      if (tool) {
        try {
          const result = await testClient.callTool({name:tool,arguments:args}, undefined, options);
          sendTest({result});
        } catch (error) {
          send({error: unauthorized(error) ? 'authentication'
            : [-32601, -32602].includes(error.code) ? 'tool_error' : 'outcome_unknown'});
        }
      } else {
        const tools = [];
        const cursors = new Set();
        let cursor;
        do {
          const page = await testClient.listTools(cursor ? {cursor} : {}, options);
          tools.push(...page.tools);
          cursor = page.nextCursor;
          if (tools.length > 1000 || cursors.size >= 20 || cursors.has(cursor)) throw new Error('tool_budget');
          if (cursor) cursors.add(cursor);
        } while (cursor);
        if (new Set(tools.map(item=>item.name)).size !== tools.length) throw new Error('duplicate_tool');
        sendTest({result:{tools}});
      }
    } catch (error) {
      send({error: unauthorized(error) ? 'authentication' : 'connection'});
    } finally {
      await testClient.close().catch(() => {});
      await server?.close().catch(() => {});
    }
    return;
  }
}

const mode = process.argv[2];
(mode === '--employee-proxy' ? proxy(process.argv[3]) : mode === '--test-connection' ? testConnection() : main())
  .catch(() => { process.exitCode = 1; });
