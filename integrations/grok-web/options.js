const $ = id => document.getElementById(id);
const origins = ['https://grok.com/*'];
const say = text => { $('status').textContent = text; };
async function refresh() {
  const allowed = await chrome.permissions.contains({origins});
  const data = await chrome.storage.local.get(['enabled', 'soundName', 'lastCompletion', 'lastError']);
  $('connection').textContent = allowed ? '사이트 권한 연결됨' : '연결 전';
  $('connect').hidden = allowed;
  $('disconnect').hidden = !allowed;
  $('enabled').disabled = !allowed;
  $('enabled').checked = !!(allowed && data.enabled);
  $('sound-name').textContent = data.soundName || '우사기의 “우나!” · 기본 음성';
  $('last-event').textContent = data.lastError || (data.lastCompletion ? '최근 감지·재생: ' + new Date(data.lastCompletion).toLocaleString() : '아직 감지한 완료가 없어요.');
}
function action(fn) { return async () => { try { await fn(); await refresh(); } catch (error) { say(error.message || '설정을 처리하지 못했어요.'); } }; }
if (!globalThis.chrome?.runtime?.id) {
  $('connection').textContent = '설정 화면 미리보기';
  document.querySelectorAll('button,input').forEach(el => { el.disabled = true; });
  say('Chrome에서 확장 기능을 설치한 뒤 이 설정 화면을 열어 주세요.');
} else {
  $('connect').onclick = action(async () => {
    // Request is the first operation, retaining the explicit user gesture.
    const granted = await chrome.permissions.request({origins});
    if (!granted) { say('사이트 접근 권한을 허용해야 연결할 수 있어요.'); return; }
    await chrome.storage.local.set({enabled: true});
    const result = await chrome.runtime.sendMessage({type: 'sync-permission'});
    if (!result?.ok) throw new Error('연결을 마치지 못했어요. 확장 기능을 다시 열어 주세요.');
    say('연결됐어요. Grok 탭을 새로고침하고 테스트해 주세요.');
  });
  $('disconnect').onclick = action(async () => {
    await chrome.storage.local.set({enabled: false});
    await chrome.permissions.remove({origins});
    say('Grok 접근 권한과 완료 알림을 해제했어요.');
  });
  $('enabled').onchange = action(async () => { await chrome.storage.local.set({enabled: $('enabled').checked}); say('알림 설정을 저장했어요.'); });
  $('sound-file').onchange = action(async () => {
    const file = $('sound-file').files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024 || !file.size) throw new Error('음성은 0바이트 초과, 5MB 이하여야 해요.');
    const types = {mp3:'mpeg',wav:'wav',m4a:'mp4',ogg:'ogg',flac:'flac'};
    const type = types[file.name.split('.').pop().toLowerCase()];
    if (!type) throw new Error('MP3 · WAV · M4A · OGG · FLAC 파일을 선택해 주세요.');
    const source = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(new Blob([file], {type: 'audio/' + type})); });
    const audio = new Audio(source);
    await new Promise((resolve, reject) => { audio.onloadedmetadata = resolve; audio.onerror = () => reject(new Error('재생 가능한 음성 파일을 선택해 주세요.')); });
    await chrome.storage.local.set({sound: source, soundName: file.name});
    say('목소리를 이 브라우저에 저장했어요.');
  });
  $('reset-sound').onclick = action(async () => { await chrome.storage.local.remove(['sound', 'soundName']); $('sound-file').value = ''; say('우나! 기본 음성으로 바꿨어요.'); });
  $('test').onclick = action(async () => {
    const result = await chrome.runtime.sendMessage({type: 'test-sound'});
    if (!result?.ok) throw new Error(result?.error || '재생하지 못했어요. 음성과 음량을 확인해 주세요.');
    say('알림음을 재생했어요.');
  });
  chrome.storage.onChanged.addListener(refresh);
  refresh().catch(() => say('설정을 불러오지 못했어요.'));
}
