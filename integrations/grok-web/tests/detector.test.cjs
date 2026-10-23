const {test} = require('node:test');
const assert = require('node:assert/strict');
const {CompletionTracker, isStopControl} = require('../detector.js');
const idle = {busy: false, ready: true};
const busy = {busy: true, ready: true};

test('opening or revisiting idle history never plays', () => {
  const t = new CompletionTracker();
  [0, 3000, 9000].forEach(now => assert.equal(t.observe(idle, now), false));
});
test('one stable completion plays once', () => {
  const t = new CompletionTracker();
  assert.equal(t.observe(busy, 0), false);
  assert.equal(t.observe(busy, 1000), false);
  assert.equal(t.observe(idle, 1500), false);
  assert.equal(t.observe(idle, 3099), false);
  assert.equal(t.observe(idle, 3100), true);
  assert.equal(t.observe(idle, 9000), false);
});
test('transient button disappearance does not finish a stream', () => {
  const t = new CompletionTracker();
  t.observe(busy, 0); t.observe(idle, 1000); t.observe(busy, 1200);
  assert.equal(t.observe(busy, 3500), false);
  t.observe(idle, 4000);
  assert.equal(t.observe(idle, 5600), true);
});
test('user stopping a stream suppresses sound, next response works', () => {
  const t = new CompletionTracker();
  t.observe(busy, 0); t.cancel(); t.observe(idle, 1000);
  assert.equal(t.observe(idle, 3000), false);
  t.observe(busy, 4000); t.observe(idle, 5000);
  assert.equal(t.observe(idle, 7000), true);
});
test('navigation, missing composer, or error suppress completion', () => {
  for (const reason of ['navigation', 'missing', 'error']) {
    const t = new CompletionTracker(); t.observe(busy, 0);
    if (reason === 'navigation') t.reset();
    else t.observe({busy:false, ready:reason !== 'missing', failed:reason === 'error'}, 1000);
    t.observe(idle, 3000);
    assert.equal(t.observe(idle, 5000), false, reason);
  }
});
test('very brief UI flashes do not trigger', () => {
  const t = new CompletionTracker();
  t.observe(busy, 0); t.observe(idle, 100);
  assert.equal(t.observe(idle, 2000), false);
});
test('background polling gap can settle normally', () => {
  const t = new CompletionTracker();
  t.observe(busy, 0); t.observe(idle, 10000);
  assert.equal(t.observe(idle, 30000), true);
});
test('control matching does not mistake ordinary send/settings buttons for stop', () => {
  for (const label of ['제출', '설정', 'Send', 'stop this from happening']) assert.equal(isStopControl({label}), false);
  for (const label of ['중지', '응답 중지', 'Stop generating', 'Stop response', '停止生成']) assert.equal(isStopControl({label}), true);
  assert.equal(isStopControl({testId:'chat-stop'}), true);
});
