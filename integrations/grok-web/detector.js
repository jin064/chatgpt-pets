/* Pure control-state tracker; never receives conversation text. */
(function (root) {
  class CompletionTracker {
    constructor({settleMs = 1600, minimumBusyMs = 400} = {}) {
      this.settleMs = settleMs;
      this.minimumBusyMs = minimumBusyMs;
      this.reset();
    }
    reset() { this.startedAt = null; this.idleAt = null; this.cancelled = false; }
    cancel() { this.cancelled = true; }
    observe({busy, ready, failed = false}, now) {
      if (busy) {
        if (this.startedAt === null) { this.startedAt = now; this.cancelled = false; }
        this.idleAt = null;
        return false;
      }
      if (this.startedAt === null) return false;
      if (failed || !ready) { this.reset(); return false; }
      if (this.idleAt === null) this.idleAt = now;
      if (now - this.idleAt < this.settleMs) return false;
      const complete = !this.cancelled && this.idleAt - this.startedAt >= this.minimumBusyMs;
      this.reset();
      return complete;
    }
  }
  // Button labels are language dependent; no response/message DOM is inspected.
  const stopLabel = /^(stop( generating| generation| response| responding)?|cancel response|중지|응답 중지|생성 중지|응답 생성 중지|멈추기|停止|停止生成|応答を停止)$/i;
  function isStopControl(control) {
    return stopLabel.test((control.label || '').trim()) ||
      /^(stop-button|stop-response|chat-stop|stop-generating)$/.test(control.testId || '');
  }
  const api = {CompletionTracker, isStopControl};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PetStudioDetector = api;
})(typeof globalThis === 'undefined' ? this : globalThis);
