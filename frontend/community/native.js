// The shell reads a close decision; it cannot save or discard a stored asset.
export class NativeCloseGuard {
  constructor(snapshot, freeze) { this.snapshot = snapshot; this.freeze = freeze; }
  checkClose(discardDraft = false) {
    const state = this.snapshot();
    if (state.pending) return 'pending';
    if (state.dirty && discardDraft !== true) return 'dirty';
    return 'ready';
  }
  prepareClose(discardDraft = false) {
    const decision = this.checkClose(discardDraft);
    if (decision !== 'ready') return decision;
    this.freeze();
    return 'ready';
  }
}
