'use strict';
const $ = id => document.getElementById(id);
const stateLabels = {idle:'대기', waving:'인사', jumping:'점프', 'running-right':'달리기', running:'작업', 'look-loop':'둘러보기'};
const statuses = {building:'제작 중', checking:'검증 중', ready:'미리보기 준비', registering:'등록 중', registered:'등록 완료', blocked:'확인 필요', cancelled:'중지됨', interrupted:'중단됨'};
let token, ready = false, job = null, activeExample = 'usagi', jobs = [], polling = false;
let imageUrl = null, audioUrl = null, toastTimer;

function toast(text) {
  $('toast').textContent = text; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6500);
}
async function api(path, payload) {
  const options = payload === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Pet-Studio-Token':token}, body:JSON.stringify(payload)};
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { throw new Error('서버에 연결할 수 없습니다. 실행 중인 터미널을 확인해 주세요.'); }
  if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.');
  return data;
}
function setImage(src, alt) {
  const image = $('pet-preview');
  image.hidden = !src;
  if (src && image.getAttribute('src') !== src) image.src = src;
  image.alt = alt;
}
function setVoice(src, title) {
  $('voice-title').textContent = title;
  $('voice-preview').hidden = !src; $('voice-empty').hidden = !!src;
  if (src && $('voice-preview').getAttribute('src') !== src) {
    $('voice-preview').src = src;
  } else if (!src) {
    $('voice-preview').pause(); $('voice-preview').removeAttribute('src'); $('voice-preview').load();
  }
}
function buttonState() {
  const busy = jobs.some(j => ['building','checking','registering'].includes(j.status));
  $('create').disabled = !ready || busy;
  $('create').firstChild.textContent = busy ? '친구를 만들고 있어요 ' : '나만의 펫 만들기 ';
}
async function check() {
  $('check').disabled = true;
  try {
    const info = await api('/api/status'); ready = info.ready;
    $('connection-dot').className = 'dot ' + (ready ? 'good' : 'bad');
    $('connection-title').textContent = ready ? '제작 준비 완료 · Codex + Pets' : '제작 환경을 연결해 주세요';
    $('connection-detail').textContent = ready ? info.note : info.issues.join(' · ');
    $('restore-sound').hidden = !info.notifications.active;
    $('apply-sound').disabled = !info.notifications.supported;
  } catch (error) {
    ready = false; $('connection-title').textContent = '연결을 확인해 주세요';
    $('connection-detail').textContent = error.message; $('connection-dot').className = 'dot bad';
  } finally { $('check').disabled = false; buttonState(); }
}
function fileUrl(j, relative) {
  return '/files/' + j.id + '/' + relative.split('/').map(encodeURIComponent).join('/');
}
function showExample(key, scroll = false) {
  job = null; activeExample = key;
  const usagi = key === 'usagi';
  $('preview-title').textContent = usagi ? '먼작귀 우사기' : '시나모롤';
  $('preview-badge').textContent = '완성 예시'; $('stage-caption').textContent = '함께할 준비가 됐어요.';
  $('preview-help').textContent = '완성 예시예요. 새 친구를 만들면 여기에 나타나요.';
  $('preview-controls').hidden = false; $('result-actions').hidden = true; $('progress-panel').hidden = true;
  setImage('/pets/' + key + '/previews/idle.gif', $('preview-title').textContent + ' 대기 동작');
  setVoice(usagi ? '/pets/usagi/audio/chiikawa-usagi-una.mp3' : '', usagi ? '우사기의 “우나!”' : '아직 목소리가 없어요');
  document.querySelectorAll('[data-state]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.state === 'idle')));
  if (scroll) $('preview-title').scrollIntoView({behavior:'smooth', block:'center'});
}
function selectState(state) {
  let src;
  if (job?.result) {
    const file = job.result.previews[state + '.gif'];
    if (!file) return;
    src = fileUrl(job, file);
  } else if (!job && activeExample) src = '/pets/' + activeExample + '/previews/' + state + '.gif';
  else return;
  setImage(src, $('preview-title').textContent + ' ' + stateLabels[state] + ' 동작');
  document.querySelectorAll('[data-state]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.state === state)));
}
function renderHistory() {
  const list = $('history-list'); list.replaceChildren();
  $('history-section').hidden = !jobs.length;
  for (const j of jobs) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'history-item';
    const title = document.createElement('strong'); title.textContent = j.name;
    const detail = document.createElement('span'); detail.textContent = (statuses[j.status] || j.status) + ' · ' + new Date(j.created * 1000).toLocaleDateString('ko-KR');
    button.append(title, detail); button.addEventListener('click', () => { showJob(j); $('preview-title').scrollIntoView({behavior:'smooth', block:'center'}); });
    list.append(button);
  }
  buttonState();
}
async function loadJobs() {
  const data = await api('/api/jobs'); jobs = data.jobs; renderHistory();
  if (job) {
    const updated = jobs.find(j => j.id === job.id);
    if (updated) showJob(updated, true);
  }
}
function showJob(j, keepPreview = false) {
  const same = job?.id === j.id, hadResult = !!job?.result; job = j; activeExample = null;
  $('preview-title').textContent = j.name;
  $('preview-badge').textContent = statuses[j.status] || j.status;
  $('progress-panel').hidden = false; $('progress-title').textContent = j.name + ' · ' + (statuses[j.status] || j.status);
  const buildingMessages = {1:'참고 이미지와 음성을 확인하고 제작을 준비하고 있어요.', 2:'캐릭터의 기본 모습을 만들고 있어요.', 3:'기본 모습을 만들었어요. 아홉 가지 동작과 열여섯 방향의 시선을 제작·검증하고 있어요.'};
  $('job-message').textContent = j.status === 'building' ? buildingMessages[j.stage] || j.message : j.message;
  $('job-events').textContent = (j.events || []).map(event => event.text).join('\n\n');
  $('cancel').hidden = !['building','checking'].includes(j.status);
  $('resume').hidden = !j.can_resume;
  document.querySelectorAll('[data-step]').forEach(el => {
    const step = Number(el.dataset.step);
    el.classList.toggle('done', ['ready','registered','registering'].includes(j.status) || step < j.stage);
    el.classList.toggle('current', !['ready','registered','registering'].includes(j.status) && step === j.stage);
    if (el.classList.contains('current')) el.setAttribute('aria-current','step');
    else el.removeAttribute('aria-current');
  });
  if (j.result) {
    if (!same || !keepPreview || !hadResult) {
      setImage(fileUrl(j, j.result.preview), j.name + ' 전체 동작 미리보기');
      document.querySelectorAll('[data-state]').forEach(b => b.setAttribute('aria-pressed','false'));
    }
    $('stage-caption').textContent = j.status === 'registered' ? 'Pets에 등록됐어요.' : '움직임을 하나씩 살펴보세요.';
    $('preview-controls').hidden = false; $('result-actions').hidden = false;
    $('register').hidden = j.status !== 'ready';
    $('download').href = fileUrl(j, 'pet.zip');
    $('apply-sound').hidden = !j.audio;
    $('preview-help').textContent = j.result.warnings.length ? '중간 시선의 일부 변화는 미세할 수 있어요. 둘러보기 동작을 확인해 주세요.' : '구조와 동작 품질 검증을 통과했어요.';
  } else {
    setImage(j.image ? fileUrl(j, j.image) : '', j.name + ' 참고 이미지');
    $('stage-caption').textContent = j.image ? '참고 이미지 · 아직 제작 중이에요.' : '새 친구의 모습을 상상하고 있어요.';
    $('preview-controls').hidden = true; $('result-actions').hidden = true;
    $('preview-help').textContent = ['blocked','cancelled','interrupted'].includes(j.status) ? '제작 메시지에서 진행 상황을 확인해 주세요.' : '완성된 동작이 준비되면 여기에서 확인할 수 있어요.';
  }
  setVoice(j.audio ? fileUrl(j, j.audio) : '', j.audio ? j.name + '의 알림 목소리' : '선택한 목소리가 없어요');
}
async function upload(file, limit) {
  if (!file) return null;
  if (!file.size || file.size > limit * 1024 * 1024) throw new Error(`파일은 0바이트보다 크고 ${limit}MB 이하여야 해요.`);
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onerror = () => reject(new Error('파일을 읽지 못했어요.'));
    reader.onload = () => resolve({data:reader.result.split(',')[1]}); reader.readAsDataURL(file);
  });
}
$('pet-form').addEventListener('submit', async event => {
  event.preventDefault(); $('create').disabled = true;
  try {
    const [image, audio] = await Promise.all([upload($('image').files[0], 8), upload($('audio').files[0], 10)]);
    const result = await api('/api/jobs', {name:$('name').value, description:$('description').value, style:$('style').value, image, audio});
    jobs.unshift(result); renderHistory(); showJob(result); $('progress-panel').scrollIntoView({behavior:'smooth', block:'nearest'});
  } catch (error) { toast(error.message); } finally { buttonState(); }
});
for (const kind of ['image','audio']) {
  $(kind).addEventListener('change', () => {
    const file = $(kind).files[0]; if (!file) return;
    const limit = kind === 'image' ? 8 : 10;
    if (!file.size || file.size > limit * 1024 * 1024) { toast(`파일은 ${limit}MB 이하로 선택해 주세요.`); $(kind).value = ''; return; }
    $(kind + '-label').textContent = file.name; $('clear-' + kind).hidden = false;
    if (kind === 'image') {
      if (imageUrl) URL.revokeObjectURL(imageUrl); imageUrl = URL.createObjectURL(file);
      job = null; activeExample = null; setImage(imageUrl, '새 펫의 참고 이미지');
      $('preview-title').textContent = $('name').value || '새로운 친구'; $('preview-badge').textContent = '참고 이미지';
      $('stage-caption').textContent = '이 모습에서 시작해요.'; $('preview-controls').hidden = true; $('result-actions').hidden = true;
      $('preview-help').textContent = '제작을 시작하면 완성된 동작을 확인할 수 있어요.'; $('progress-panel').hidden = true;
    } else {
      job = null;
      $('result-actions').hidden = true; $('progress-panel').hidden = true;
      if (audioUrl) URL.revokeObjectURL(audioUrl); audioUrl = URL.createObjectURL(file); setVoice(audioUrl, file.name);
    }
  });
  $('clear-' + kind).addEventListener('click', () => {
    $(kind).value = ''; $(kind + '-label').textContent = kind === 'image' ? '이미지 선택' : '음성 선택'; $('clear-' + kind).hidden = true;
    if (kind === 'image') showExample('usagi'); else setVoice('', '선택한 목소리가 없어요');
  });
}
document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => showExample(button.dataset.example, true)));
document.querySelectorAll('[data-state]').forEach(button => button.addEventListener('click', () => selectState(button.dataset.state)));
$('check').addEventListener('click', check);
$('refresh-jobs').addEventListener('click', () => loadJobs().catch(e => toast(e.message)));
for (const [id, action] of [['cancel','cancel'],['resume','resume'],['register','register'],['apply-sound','sound']]) {
  $(id).addEventListener('click', async () => {
    if (!job) return;
    $(id).disabled = true;
    try {
      const result = await api('/api/jobs/' + job.id + '/' + action, {});
      showJob(result, true); await loadJobs();
      if (action === 'sound') { toast('내 Codex 알림음으로 설정했어요. 다음 알림부터 적용돼요.'); await check(); }
    } catch (error) { toast(error.message); } finally { $(id).disabled = false; }
  });
}
$('restore-sound').addEventListener('click', async () => {
  try { await api('/api/notifications/restore', {}); await check(); toast('이전 알림 설정으로 복원했어요.'); }
  catch (error) { toast(error.message); }
});
async function init() {
  try {
    ({token} = await api('/api/session'));
    await Promise.all([check(), loadJobs()]);
    const active = jobs.find(j => ['building','checking','registering'].includes(j.status));
    if (active) showJob(active);
  } catch (error) { toast(error.message); }
  setInterval(async () => {
    if (polling) return; polling = true;
    try { await loadJobs(); } catch { /* Preserve current UI through a temporary disconnect. */ }
    finally { polling = false; }
  }, 2500);
}
init();
