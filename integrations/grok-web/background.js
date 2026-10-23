const ORIGINS = ['https://grok.com/*'];
const SCRIPT = {id: 'pet-studio-grok', matches: ORIGINS, js: ['detector.js', 'content.js'], runAt: 'document_idle', persistAcrossSessions: true};
let creating;
async function allowed() { return chrome.permissions.contains({origins: ORIGINS}); }
async function syncScripts() {
  const existing = await chrome.scripting.getRegisteredContentScripts({ids: [SCRIPT.id]});
  if (await allowed()) {
    if (!existing.length) await chrome.scripting.registerContentScripts([SCRIPT]);
  } else if (existing.length) await chrome.scripting.unregisterContentScripts({ids: [SCRIPT.id]});
}
async function offscreen() {
  const contexts = await chrome.runtime.getContexts({contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [chrome.runtime.getURL('offscreen.html')]});
  if (contexts.length) return;
  if (!creating) creating = chrome.offscreen.createDocument({url: 'offscreen.html', reasons: ['AUDIO_PLAYBACK'], justification: 'Play the user-selected completion sound.'}).finally(() => { creating = null; });
  await creating;
}
function validSound(value) {
  return typeof value === 'string' && value.length <= 7 * 1024 * 1024 && /^data:audio\/(mpeg|wav|x-wav|mp4|ogg|flac);base64,[A-Za-z0-9+/=]+$/.test(value);
}
async function play() {
  const {sound} = await chrome.storage.local.get('sound');
  if (sound && !validSound(sound)) throw new Error('저장한 음성 파일을 다시 선택해 주세요.');
  await offscreen();
  const result = await chrome.runtime.sendMessage({target: 'offscreen', type: 'play', source: sound || chrome.runtime.getURL('una.mp3')});
  if (!result?.ok) throw new Error('소리를 재생하지 못했어요. 음성 파일과 음량을 확인해 주세요.');
}
async function handle(message, sender) {
  const options = sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL('options.html');
  const grok = sender.tab && sender.frameId === 0 && new URL(sender.url || 'about:blank').origin === 'https://grok.com';
  if (message.type === 'permission-status' && (options || grok)) return {allowed: await allowed()};
  if (message.type === 'sync-permission' && options) { await syncScripts(); return {ok: true}; }
  if (message.type === 'test-sound' && options) { await play(); return {ok: true}; }
  if (message.type === 'grok-completed' && grok && await allowed()) {
    const {enabled, lastPlayed = 0} = await chrome.storage.local.get(['enabled', 'lastPlayed']);
    if (!enabled || Date.now() - lastPlayed < 2000) return {ok: false};
    await chrome.storage.local.set({lastPlayed: Date.now()});
    try {
      await play();
      await chrome.storage.local.set({lastCompletion: Date.now(), lastError: ''});
      return {ok: true};
    } catch (error) {
      await chrome.storage.local.set({lastError: error.message});
      return {ok: false};
    }
  }
  return {ok: false};
}
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (!message || message.target === 'offscreen') return;
  handle(message, sender).then(reply, () => reply({ok: false, error: '설정을 처리하지 못했어요.'}));
  return true;
});
chrome.runtime.onInstalled.addListener(() => { syncScripts().catch(() => {}); });
chrome.runtime.onStartup.addListener(() => { syncScripts().catch(() => {}); });
chrome.permissions.onAdded.addListener(() => { syncScripts().catch(() => {}); });
chrome.permissions.onRemoved.addListener(() => {
  chrome.storage.local.set({enabled: false});
  syncScripts().catch(() => {});
});
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
