/** Display metadata only. It never grants business permissions. */
export function connectHostTheme(host, root = globalThis.document?.documentElement) {
  if (!host || host.version !== '0.1.0' || host.kind !== 'platform' ||
      typeof host.getSnapshot !== 'function' || typeof host.subscribe !== 'function' || !root?.dataset) {
    throw new Error('ui_host_unavailable');
  }
  let disposed = false;
  const apply = () => {
    if (disposed) return;
    const state = host.getSnapshot();
    if (!state || !['light', 'dark'].includes(state.theme)) throw new Error('ui_host_theme_invalid');
    root.dataset.theme = state.theme;
  };
  apply();
  const unsubscribe = host.subscribe(apply);
  if (typeof unsubscribe !== 'function') throw new Error('ui_host_subscription_invalid');
  return {dispose() {if (!disposed) {disposed = true; unsubscribe();}}};
}

const connected = new WeakSet();
/** Native platform controls. Native acknowledgement owns completion and deadlines. */
export function createHostControls(host) {
  if (!host || host.version !== '0.1.0' || host.kind !== 'platform' ||
      !['presentation','drawer-header'].every(name => host.capabilities?.includes(name)) ||
      typeof host.request !== 'function' || typeof host.onAction !== 'function' ||
      typeof host.subscribe !== 'function' || typeof host.getSnapshot !== 'function') throw new Error('ui_host_controls_unavailable');
  const initial = host.getSnapshot()?.presentation;
  if (!initial || !['panel','full'].includes(initial.mode) ||
      (initial.mode === 'panel' ? initial.viewId !== null : typeof initial.viewId !== 'string')) throw new Error('ui_host_snapshot_invalid');
  if (connected.has(host)) throw new Error('ui_host_controls_already_connected');
  connected.add(host);
  let disposed = false, ticket = null, callbacks = new Map(), revision = null;
  let state = Object.freeze({...initial,pending:false,error:null});
  const listeners = new Set();
  const notify = patch => {
    state = Object.freeze({...state,...patch});
    for (const listener of listeners) {try {listener(state);} catch {}}
  };
  const off = host.subscribe(() => {if (!disposed) notify(host.getSnapshot().presentation);});
  const offAction = host.onAction(action => {
    if (!disposed && !ticket && action?.revision === revision) callbacks.get(action.id)?.();
  });
  async function request(method, params) {
    if (disposed) throw new Error('ui_host_disposed');
    if (ticket) throw new Error('ui_host_busy');
    const own = crypto.randomUUID();ticket = own;notify({pending:true,error:null});
    try {
      const result = await host.request(method,{...params,ticket:own});
      if (disposed) throw new Error('ui_host_disposed');
      if (!result || !['panel','full'].includes(result.mode) ||
          (result.mode === 'panel' ? result.viewId !== null : typeof result.viewId !== 'string')) throw new Error('ui_host_ack_invalid');
      if (method === 'present' && (result.mode !== params.mode || result.viewId !== params.viewId)) throw new Error('ui_host_ack_invalid');
      notify(result);return own;
    } catch (error) {if (!disposed) notify({error:'unavailable'});throw error;}
    finally {ticket = null;if (!disposed) notify({pending:false});}
  }
  return {
    version:'0.1.0', getSnapshot:()=>state,
    subscribe(listener) {if (disposed) throw new Error('ui_host_disposed');listeners.add(listener);return ()=>listeners.delete(listener);},
    async openFull(viewId) {
      if (typeof viewId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(viewId)) throw new TypeError('invalid-view-id');
      if (state.mode === 'full' && state.viewId !== viewId) throw new Error('return-required');
      await request('present',{mode:'full',viewId});return state;
    },
    async returnToPanel() {await request('present',{mode:'panel',viewId:null});return state;},
    async setHeader({text='', actions=[]} = {}) {
      if (typeof text !== 'string' || [...text].length > 256 || !Array.isArray(actions) || actions.length > 8) throw new TypeError('invalid-header');
      const next = new Map();
      const descriptors = actions.map(action => {
        if (!action || typeof action.id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(action.id) || next.has(action.id) ||
            typeof action.label !== 'string' || !action.label.trim() || [...action.label].length > 80 ||
            typeof action.onPress !== 'function' || (action.disabled !== undefined && typeof action.disabled !== 'boolean')) throw new TypeError('invalid-header-action');
        if (!action.disabled) next.set(action.id,action.onPress);else next.set(action.id,()=>{});
        return {id:action.id,label:action.label,disabled:!!action.disabled};
      });
      const own = await request('header',{text,actions:descriptors});
      if (!disposed) {revision = own;callbacks = next;}
    },
    /** Await disposal when replacing a controller in the same live document. */
    async dispose() {
      if (disposed) return;
      disposed = true;off();offAction();listeners.clear();callbacks.clear();
      try {
        if (ticket) await host.request('cancel',{ticket});
        else await host.request('header',{ticket:crypto.randomUUID(),text:'',actions:[]});
      } finally {connected.delete(host);}
    }
  };
}
