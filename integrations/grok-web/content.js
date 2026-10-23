(() => {
  if (window.__petStudioGrok) return;
  window.__petStudioGrok = true;
  const {CompletionTracker, isStopControl} = PetStudioDetector;
  const tracker = new CompletionTracker();
  let enabled = false;
  const visible = el => !!el && el.getClientRects().length > 0 && !el.closest('[hidden],[aria-hidden="true"]');
  const stop = el => isStopControl({label: el.getAttribute('aria-label') || el.getAttribute('title'), testId: el.getAttribute('data-testid')});
  const send = message => chrome.runtime.sendMessage(message).catch(() => {});
  async function settings() {
    const saved = await chrome.storage.local.get({enabled: false});
    enabled = saved.enabled && await chrome.runtime.sendMessage({type: 'permission-status'}).then(r => r.allowed).catch(() => false);
    tracker.reset();
  }
  chrome.storage.onChanged.addListener((changes, area) => { if (area === 'local' && changes.enabled) settings(); });
  settings();
  function sample() {
    if (!enabled) return;
    const buttons = [...document.querySelectorAll('button')].filter(visible);
    const busy = buttons.some(stop);
    const ready = buttons.some(b => b.getAttribute('data-testid') === 'chat-submit' || b.type === 'submit' && b.closest('form')?.querySelector('textarea,[contenteditable="true"]'));
    // Role and presence only; never copy an alert or message's contents.
    const failed = [...document.querySelectorAll('[role="alert"]')].some(visible);
    if (tracker.observe({busy, ready, failed}, Date.now())) send({type: 'grok-completed'});
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button && stop(button)) tracker.cancel();
    if (event.target.closest('a[href]')) tracker.reset();
  }, true);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') tracker.cancel(); }, true);
  window.addEventListener('popstate', () => tracker.reset());
  window.addEventListener('pagehide', () => tracker.reset());
  // Polling avoids mutation callbacks for every streamed token; also settles in background tabs.
  setInterval(sample, 350);
})();
