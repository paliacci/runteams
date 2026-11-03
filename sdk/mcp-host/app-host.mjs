// Trusted parent document. The author app only receives standard MCP Apps RPC.
import {AppBridge, PostMessageTransport} from '@modelcontextprotocol/ext-apps/app-bridge';
import {createHostControls} from '../ui/host.js';

const config = JSON.parse(document.getElementById('mcp-app-data').textContent);
const frame = document.createElement('iframe');
frame.title = config.title;
frame.setAttribute('sandbox', 'allow-scripts');
frame.setAttribute('referrerpolicy', 'no-referrer');
Object.assign(frame.style, {width: '100%', height: '100%', border: '0', display: 'block'});
const native = window.runteamsUI;
if (!native?.methods?.includes('mcp.tools.call')) throw new Error('mcp_native_host_unavailable');
const host = window.runteamsHost;
const presentation = host?.capabilities?.includes('presentation') && host?.capabilities?.includes('drawer-header')
  ? createHostControls(host) : null;
const hostContext = () => ({theme: window.runteamsHost?.getSnapshot()?.theme ?? 'light',
  displayMode: presentation?.getSnapshot().mode === 'full' ? 'fullscreen' : 'inline',
  availableDisplayModes: presentation ? ['inline', 'fullscreen'] : ['inline'], platform: 'desktop',
  containerDimensions: {width: window.innerWidth, height: window.innerHeight}});
const bridge = new AppBridge(null, {name: 'RunTeams', version: '0.1.0'},
  {serverTools: {}}, {hostContext: hostContext()});
bridge.oncalltool = async params => {
  // Native authority checks precede every call. The frame cannot supply a
  // work/account/release, a consent flag or an arbitrary protocol method.
  const reply = await native.call('mcp.tools.call', {name: params.name, arguments: params.arguments ?? {}});
  if (!reply?.ok) throw new Error('mcp_call_unavailable');
  return reply.result;
};
if (presentation) bridge.onrequestdisplaymode = async ({mode}) => {
  if (mode === 'fullscreen') await presentation.openFull('mcp-workbench');
  else if (mode === 'inline') await presentation.returnToPanel();
  return {mode: hostContext().displayMode};
};
bridge.onlisttools = async () => ({tools: config.tools.filter(t => t._meta?.ui?.visibility?.includes('app') ?? true)});
let initialized = false, teardown = null, teardownReady = false;
bridge.oninitialized = async () => { initialized = true; await bridge.sendToolInput({arguments: config.input}); };
// Private trusted-parent lifecycle, called only by the native window owner.
// Author code receives the standard MCP request, never a native close API.
Object.defineProperty(window, 'runteamsMCPClose', {value: Object.freeze({
  async prepare() {
    if (!initialized) throw new Error('mcp_app_not_initialized');
    if (!teardown) {
      teardown = bridge.teardownResource({}, {timeout: 115000, maxTotalTimeout: 115000}).catch(error => {
        // Numeric JSON-RPC errors are completed replies. Local SDK transport,
        // timeout and cancellation errors have string codes and remain sticky:
        // another Quit cannot silently issue the uncertain cleanup again.
        if (Number.isInteger(error?.code)) teardown = null;
        throw error;
      });
    }
    await teardown;
    teardownReady = true;
    frame.inert = true;
    return 'ready';
  },
  cancel() {
    frame.inert = false;
    // A completed acknowledgement can be checked again after the user edits.
    // Pending/uncertain cleanup keeps the original promise and request identity.
    if (teardownReady) {teardown = null; teardownReady = false;}
    return true;
  },
}), writable: false, configurable: false});
window.runteamsHost?.subscribe(() => bridge.setHostContext(hostContext()));
window.addEventListener('resize', () => bridge.setHostContext(hostContext()));
window.addEventListener('pagehide', () => {presentation?.dispose();bridge.close();}, {once: true});
document.body.replaceChildren();
if (config.previews?.length > 1 && native.methods.includes('mcp.preview.select')) {
  const label = document.createElement('label');label.textContent = '预览界面 ';label.style.cssText = 'padding:12px;flex:none;font:inherit';
  const select = document.createElement('select');select.setAttribute('aria-label','预览界面');
  for (const item of config.previews) {
    const option = document.createElement('option');option.value = item.id;option.textContent = item.label;option.selected = item.selected;select.append(option);
  }
  select.onchange = async () => {select.disabled = true;try {await native.call('mcp.preview.select',{id:select.value});location.reload();} catch {select.disabled = false;}};
  label.append(select);document.body.append(label);document.body.style.cssText = 'display:flex;flex-direction:column;height:100dvh';
  frame.style.cssText += ';flex:1;min-height:0';
}
document.body.append(frame);
await bridge.connect(new PostMessageTransport(frame.contentWindow, frame.contentWindow));
// The resource is never inserted in the trusted parent DOM. No same-origin,
// popups, top-navigation, forms, downloads or device permissions are granted.
frame.src = '/views/mcp-app.html';
