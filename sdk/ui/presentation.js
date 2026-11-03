/** Versioned display adapter. This is independent of the frozen business ui-v2 bridge. */
export const presentationVersion = '0.1.0';
export class PresentationError extends Error {
  constructor(code) { super(code); this.name = 'PresentationError'; this.code = code; }
}
const failure = code => new PresentationError(code);
function checkViewId(id) {
  if (typeof id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id)) throw failure('invalid-view-id');
}
/**
 * The adapter must finish only after presentation succeeds and honor cancellation.
 * No automatic retry; failures retain the previous acknowledged presentation.
 */
export function createPresentationClient(adapter, {timeoutMs = 5000} = {}) {
  if (!adapter || adapter.version !== presentationVersion || typeof adapter.transition !== 'function') throw failure('unsupported-adapter');
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1) throw failure('invalid-timeout');
  let snapshot = Object.freeze({mode: 'panel', viewId: null, pending: false, error: null});
  const listeners = new Set();
  let disposed = false;
  let pendingController = null;
  const notify = patch => {
    snapshot = Object.freeze({...snapshot, ...patch});
    for (const listener of listeners) {
      // One consumer cannot prevent the state machine or other consumers advancing.
      try { listener(snapshot); } catch { /* Consumers own their rendering errors. */ }
    }
  };
  async function transition(mode, viewId) {
    if (disposed) throw failure('disposed');
    if (snapshot.pending) throw failure('busy');
    if (mode === 'full') {
      checkViewId(viewId);
      if (snapshot.mode === 'full' && snapshot.viewId !== viewId) throw failure('return-required');
    }
    if (snapshot.mode === mode && snapshot.viewId === viewId) return snapshot;
    const previous = snapshot;
    const controller = new AbortController();
    pendingController = controller;
    let timer;
    let abortListener;
    const cancelled = new Promise((_, reject) => {
      abortListener = () => reject(failure(disposed ? 'disposed' : 'timeout'));
      controller.signal.addEventListener('abort', abortListener, {once:true});
    });
    timer = setTimeout(() => controller.abort(), timeoutMs);
    notify({pending:true, error:null});
    try {
      const request = Object.freeze({mode, viewId});
      const result = await Promise.race([
        Promise.resolve().then(() => {
          if (controller.signal.aborted) throw failure('disposed');
          return adapter.transition(request, {signal:controller.signal});
        }), cancelled
      ]);
      if (controller.signal.aborted || disposed) throw failure('disposed');
      if (!result || result.mode !== mode || result.viewId !== viewId) throw failure('invalid-acknowledgement');
      notify({mode, viewId, pending:false, error:null});
      return snapshot;
    } catch (error) {
      const normalized = error instanceof PresentationError ? error : failure('unavailable');
      if (!disposed) notify({...previous, pending:false, error:normalized.code});
      throw normalized;
    } finally {
      clearTimeout(timer);
      controller.signal.removeEventListener('abort', abortListener);
      if (pendingController === controller) pendingController = null;
    }
  }
  return {
    version:presentationVersion,
    getSnapshot:() => snapshot,
    subscribe(listener) {
      if (disposed) throw failure('disposed');
      if (typeof listener !== 'function') throw new TypeError('Listener must be a function');
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    openFull:viewId => transition('full', viewId),
    returnToPanel:() => transition('panel', null),
    dispose() { disposed = true; pendingController?.abort(); listeners.clear(); }
  };
}
