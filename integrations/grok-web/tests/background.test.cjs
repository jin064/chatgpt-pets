const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8');
const event = () => ({addListener() {}});
function setup({permission = true, enabled = true, audioOK = true, stored = {}} = {}) {
  const data = {enabled, ...stored};
  const calls = [];
  let receiver;
  const chrome = {
    permissions: {contains: async () => permission, onAdded:event(), onRemoved:event()},
    storage: {local:{get:async () => data, set:async values => Object.assign(data, values)}},
    scripting: {getRegisteredContentScripts:async () => [], registerContentScripts:async () => {}, unregisterContentScripts:async () => {}},
    runtime: {id:'test', getURL:p => 'chrome-extension://test/' + p, getContexts:async () => [],
      sendMessage:async message => {calls.push(message); return {ok:audioOK};},
      onMessage:{addListener:fn => {receiver = fn;}}, onInstalled:event(), onStartup:event()},
    offscreen:{createDocument:async value => calls.push(value)}, action:{onClicked:event()}
  };
  vm.runInNewContext(code, {chrome, URL, Date});
  const send = (message, sender) => new Promise(resolve => receiver(message, sender, resolve));
  return {data, calls, send};
}
const grok = {tab:{id:1}, frameId:0, url:'https://grok.com/c/test'};
const options = {id:'test', url:'chrome-extension://test/options.html'};
test('completion uses offscreen audio and stores only event time', async () => {
  const {send,calls,data} = setup();
  assert.equal((await send({type:'grok-completed'}, grok)).ok, true);
  assert.equal(calls[0].reasons[0], 'AUDIO_PLAYBACK');
  assert.equal(calls[1].source, 'chrome-extension://test/una.mp3');
  assert.equal(typeof data.lastCompletion, 'number');
  assert.equal(data.lastError, '');
});
test('no permission or disabled settings suppress completion', async () => {
  for (const config of [{permission:false}, {enabled:false}]) {
    const {send,calls} = setup(config);
    assert.equal((await send({type:'grok-completed'}, grok)).ok, false);
    assert.equal(calls.length, 0);
  }
});
test('unrelated origins and subframes cannot trigger audio', async () => {
  const {send,calls} = setup();
  for (const sender of [{...grok,url:'https://example.com/'},{...grok,frameId:1},options]) {
    assert.equal((await send({type:'grok-completed'}, sender)).ok, false);
  }
  assert.equal(calls.length, 0);
});
test('test sound is limited to extension settings page', async () => {
  const {send,calls} = setup({enabled:false,permission:false});
  assert.equal((await send({type:'test-sound'}, grok)).ok, false);
  assert.equal((await send({type:'test-sound'}, options)).ok, true);
  assert.equal(calls.length, 2);
});
test('invalid stored sources cannot become network requests', async () => {
  const {send,calls} = setup({stored:{sound:'https://example.com/sound.mp3'}});
  assert.equal((await send({type:'test-sound'}, options)).ok, false);
  assert.equal(calls.length, 0);
});
test('options opened as a full tab can test audio', async () => {
  const {send} = setup();
  assert.equal((await send({type:'test-sound'}, {...options,tab:{id:2},frameId:0})).ok, true);
});
test('audio failure is visible in settings, not claimed as completed playback', async () => {
  const {send,data} = setup({audioOK:false});
  assert.equal((await send({type:'grok-completed'}, grok)).ok, false);
  assert.equal(data.lastCompletion, undefined);
  assert.match(data.lastError, /재생/);
});
