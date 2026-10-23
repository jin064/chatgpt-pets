"""Real Codex CLI adapter. No simulated generation or automatic API fallback."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATES = ['idle', 'running-right', 'running-left', 'waving', 'jumping', 'failed', 'waiting', 'running', 'review']
STYLES = {'auto', 'pixel', 'plush', 'clay', 'sticker', 'flat-vector', '3d-toy', 'painterly'}
ACTIVE = {'building', 'checking', 'registering'}


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def safe_file(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('결과 파일 경로가 올바르지 않습니다.')
    path = root / relative
    # Resolve both traversal and symlinks; generated files may not expose other local files.
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('작업 폴더 안의 실제 파일만 사용할 수 있습니다.')
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError('심볼릭 링크는 결과물로 사용할 수 없습니다.')
    return path


def collect_previews(folder, preview_dir):
    previews = {}
    for state in STATES:
        filename = state + '.gif'
        candidates = [preview_dir / 'states' / filename, preview_dir / filename]
        path = next((path for path in candidates if path.is_file()), None)
        if path is None:
            raise ValueError('필수 동작 미리보기가 없습니다: ' + state)
        safe_file(folder, str(path.relative_to(folder)))
        previews[filename] = str(path.relative_to(folder))
    for filename in ['all-states.mp4', 'idle-jump-idle.gif', 'look-loop.gif']:
        path = safe_file(folder, str((preview_dir / filename).relative_to(folder)))
        previews[filename] = str(path.relative_to(folder))
    # The bundled renderer writes four separate labeled stills; older packs use a board.
    stills = (['four-stills.png'] if (preview_dir / 'four-stills.png').is_file() else
              ['still-01-idle.png', 'still-02-waving.png', 'still-03-jumping.png', 'still-04-review.png'])
    for filename in stills:
        path = safe_file(folder, str((preview_dir / filename).relative_to(folder)))
        previews[filename] = str(path.relative_to(folder))
    return previews


def codex_binary():
    candidates = [os.environ.get('CODEX_BIN'), shutil.which('codex'),
                  '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
                  '/Applications/Codex.app/Contents/Resources/codex']
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def skill_directory():
    override = os.environ.get('PET_SKILL_DIR')
    if override:
        return Path(override).expanduser().resolve()
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    options = list(home.glob('plugins/cache/*/work-pets/*/skills/create-pet'))
    return max(options, key=lambda p: p.stat().st_mtime) if options else None


def preflight():
    cli = codex_binary()
    skill = skill_directory()
    checks = {'codex': bool(cli), 'login': False, 'pets': False, 'imagegen': False,
              'pipeline': bool(skill and (skill / 'scripts/validate_pet_quality.py').is_file()),
              'pillow': importlib.util.find_spec('PIL') is not None}
    issues = []
    if cli:
        try:
            checks['login'] = subprocess.run([cli, 'login', 'status'], capture_output=True, timeout=10).returncode == 0
            installed = subprocess.run([cli, 'plugin', 'list', '--json'], capture_output=True, timeout=15, text=True)
            if installed.returncode == 0:
                checks['pets'] = any(p.get('name') == 'work-pets' and p.get('enabled') for p in json.loads(installed.stdout).get('installed', []))
            features = subprocess.run([cli, 'features', 'list'], capture_output=True, timeout=10, text=True)
            checks['imagegen'] = any(line.split()[0] == 'image_generation' and line.split()[-1] == 'true'
                                     for line in features.stdout.splitlines() if line.split())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            issues.append('Codex 연결 확인에 실패했습니다. 잠시 후 다시 확인해 주세요.')
    labels = {'codex': 'Codex CLI 설치 또는 CODEX_BIN 설정', 'login': '터미널에서 codex login',
              'pets': 'Codex에 Pets 플러그인 설치·활성화', 'imagegen': 'Codex 내장 이미지 생성 활성화 확인',
              'pipeline': 'Pets 제작 스킬 파일 확인',
              'pillow': '실행 중인 Python에 Pillow 설치'}
    issues.extend(labels[k] for k, v in checks.items() if not v)
    return {'ready': all(checks.values()), 'checks': checks, 'issues': issues,
            'note': '이미지 생성과 Pets 계정 연결은 제작 실행 시 확인합니다. 기존 Codex 사용 한도가 적용됩니다.'}


def decode_upload(value, kind):
    if not isinstance(value, dict):
        raise ValueError('파일을 선택해 주세요.')
    try:
        data = base64.b64decode(value.get('data', ''), validate=True)
    except (ValueError, TypeError):
        raise ValueError('파일 전송 형식이 올바르지 않습니다.') from None
    limit = (8 if kind == 'image' else 10) * 1024 * 1024
    if not data or len(data) > limit:
        raise ValueError(f'{kind} 파일은 0바이트보다 크고 {limit // 1024 // 1024}MB 이하여야 합니다.')
    if kind == 'image':
        formats = [(data.startswith(b'\x89PNG\r\n\x1a\n'), '.png'),
                   (data.startswith(b'\xff\xd8\xff'), '.jpg'),
                   (data[:4] == b'RIFF' and data[8:12] == b'WEBP', '.webp')]
    else:
        formats = [(data.startswith(b'ID3') or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224), '.mp3'),
                   (data[:4] == b'RIFF' and data[8:12] == b'WAVE', '.wav'),
                   (data[4:8] == b'ftyp', '.m4a'), (data.startswith(b'OggS'), '.ogg'),
                   (data.startswith(b'fLaC'), '.flac')]
    ext = next((ext for matches, ext in formats if matches), None)
    if not ext:
        raise ValueError('지원하는 이미지(PNG/JPEG/WebP) 또는 음성(MP3/WAV/M4A/OGG/FLAC) 파일을 선택해 주세요.')
    if kind == 'image':
        from PIL import Image
        import io
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 32_000_000:
                    raise ValueError('이미지는 3,200만 화소 이하여야 합니다.')
                image.verify()
        except Exception as exc:
            raise ValueError('이미지 파일을 읽을 수 없습니다.') from exc
    return data, ext


class JobManager:
    def __init__(self, data_dir):
        self.data = Path(data_dir).resolve()
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.jobs = {}
        self.processes = {}
        self.cancelled = set()
        for path in self.data.glob('*/job.json'):
            try:
                job = json.loads(path.read_text())
                if job['status'] in ACTIVE:
                    if job['status'] == 'registering' or job.get('operation') == 'register':
                        job['operation'] = 'register'
                        message = '등록 중 서버가 종료됐습니다. 중복 생성을 피하려면 먼저 Pets 목록에서 등록 여부를 확인해 주세요.'
                    else:
                        message = '서버가 종료되어 제작이 중단됐습니다. 이어서 만들기로 남은 작업을 진행할 수 있습니다.'
                    job.update(status='interrupted', message=message)
                    write_json(path, job)
                self.jobs[job['id']] = job
            except (ValueError, KeyError, OSError):
                continue

    def save(self, job):
        job['updated'] = time.time()
        write_json(self.data / job['id'] / 'job.json', job)

    def update(self, job, **values):
        with self.lock:
            job.update(values)
            self.save(job)

    def log(self, job, message):
        with self.lock:
            job['events'] = (job.get('events', []) + [{'time': time.time(), 'text': str(message)[:4000]}])[-80:]
            self.save(job)

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('작업을 찾을 수 없습니다.')
            snapshot = json.loads(json.dumps(self.jobs[job_id]))
            if snapshot['status'] == 'building':
                run = self.data / job_id / 'run'
                if (run / 'decoded/base.png').is_file() or (run / 'references/canonical-base.png').is_file():
                    snapshot['stage'] = 3
                elif (run / 'pet_request.json').is_file():
                    snapshot['stage'] = 2
            folder = self.data / job_id
            snapshot['can_resume'] = (snapshot['status'] in {'blocked', 'interrupted', 'cancelled'} and
                                      snapshot.get('operation', 'build') == 'build' and
                                      not (folder / 'registration-attempt.json').exists() and
                                      not (folder / 'created-pet.json').exists())
            return snapshot

    def list(self):
        with self.lock:
            return [self.get(j['id']) for j in sorted(self.jobs.values(), key=lambda j: j['created'], reverse=True)]

    def busy(self):
        return any(j['status'] in ACTIVE for j in self.jobs.values())

    def create(self, payload):
        name = payload.get('name', '')
        description = payload.get('description', '')
        style = payload.get('style', 'auto')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60 or any(ord(c) < 32 for c in name):
            raise ValueError('이름을 1~60자로 입력해 주세요.')
        if not isinstance(description, str) or len(description) > 1500 or style not in STYLES:
            raise ValueError('설명 또는 스타일이 올바르지 않습니다.')
        audio = decode_upload(payload['audio'], 'audio') if payload.get('audio') else None
        image = decode_upload(payload['image'], 'image') if payload.get('image') else None
        with self.lock:
            if self.busy():
                raise ValueError('진행 중인 제작이 있습니다. 완료하거나 중지한 뒤 시작해 주세요.')
            job_id = uuid.uuid4().hex
            folder = self.data / job_id
            folder.mkdir(mode=0o700)
            request = {'name': name.strip(), 'description': description.strip(), 'style': style,
                       'audio': '', 'image': ''}
            for key, upload in [('audio', audio), ('image', image)]:
                if upload:
                    data, ext = upload
                    request[key] = key + ext
                    (folder / request[key]).write_bytes(data)
            write_json(folder / 'request.json', request)
            job = {'id': job_id, 'name': name.strip(), 'created': time.time(), 'status': 'building',
                   'message': '제작을 시작합니다.', 'events': [], 'audio': request['audio'],
                   'image': request['image'], 'stage': 1, 'operation': 'build'}
            self.jobs[job_id] = job
            self.save(job)
            threading.Thread(target=self.run, args=(job, 'build'), daemon=True).start()
            return self.get(job_id)

    def register(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if self.busy() or job['status'] != 'ready':
                raise ValueError('검증이 끝난 펫만 등록할 수 있습니다.')
            folder = self.data / job_id
            verified = json.loads((folder / 'verified.json').read_text())
            atlas = safe_file(folder, verified['atlas'])
            if hashlib.sha256(atlas.read_bytes()).hexdigest() != verified['sha256']:
                raise ValueError('검증 이후 파일이 바뀌었습니다. 등록할 수 없습니다.')
            self.update(job, status='registering', operation='register', message='Pets 계정에 등록하고 있습니다.')
            threading.Thread(target=self.run, args=(job, 'register'), daemon=True).start()

    def resume(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if self.busy() or not self.get(job_id)['can_resume']:
                raise ValueError('중단된 제작만 이어서 실행할 수 있습니다. 등록 여부가 불확실한 작업은 먼저 Pets 목록에서 확인해 주세요.')
            self.cancelled.discard(job_id)
            self.update(job, status='building', operation='build', last_error='',
                        message='남아 있는 이미지와 검증 기록에서 제작을 이어갑니다.')
            threading.Thread(target=self.run, args=(job, 'build'), daemon=True).start()

    def cancel(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job['status'] == 'registering':
                raise ValueError('등록 중에는 중지할 수 없습니다. 중복 생성을 막기 위해 결과를 기다려 주세요.')
            if job['status'] not in ACTIVE:
                return
            self.cancelled.add(job_id)
            process = self.processes.get(job_id)
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    self.ensure_stopped(process)
                except ProcessLookupError:
                    pass
            self.update(job, status='cancelled', message='제작을 중지했습니다. 지금까지 만든 파일은 보관됩니다.')

    def execute(self, job, mode):
        folder = self.data / job['id']
        cli = codex_binary()
        if not cli:
            raise ValueError('Codex CLI를 찾을 수 없습니다.')
        command = [cli, 'exec', '--json', '--color', 'never', '--skip-git-repo-check',
                   '--sandbox', 'workspace-write', '-c', 'approval_policy="never"',
                   '-c', 'sandbox_workspace_write.network_access=true', '-c', 'notify=[]',
                   '--cd', str(folder), '--output-schema', str(HERE / 'schemas' / f'{mode}.json'),
                   '--output-last-message', str(folder / f'{mode}-result.json'), '-']
        prompt = (HERE / 'templates' / f'{mode}.md').read_text()
        if mode == 'build' and (folder / 'run').exists():
            prompt += ('\nRESUMING AN INTERRUPTED CREATION: inspect existing run/imagegen-jobs.json, '
                       'the canonical base, approved state frames and saved QA before any new generation. '
                       'Preserve approved artifacts and their geometry. Do not rerun preparation over '
                       'the existing run or regenerate the base or rows that passed. Continue from '
                       'the first incomplete or failed gate, then perform all final validation normally.\n')
        skill = skill_directory()
        if skill:
            prompt += f'\nInstalled creation skill: {skill / "SKILL.md"}\nPython with Pillow: {sys.executable}\n'
        output = folder / f'{mode}-result.json'
        if output.exists():
            output.rename(folder / f'{mode}-result-before-{time.time_ns()}.json')
        with (folder / f'{mode}-stderr.log').open('a') as stderr:
            with self.lock:
                if job['id'] in self.cancelled:
                    return
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=stderr, text=True, start_new_session=True, bufsize=1)
                self.processes[job['id']] = process
            process.stdin.write(prompt)
            process.stdin.close()
            timer = threading.Timer(45 * 60, lambda: self._timeout(job, process))
            timer.start()
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    item = event.get('item') or {}
                    if event.get('type') == 'thread.started':
                        self.update(job, codex_thread_id=event.get('thread_id', ''))
                    elif item.get('type') == 'agent_message' and event.get('type') == 'item.completed':
                        self.log(job, item.get('text', ''))
                    elif event.get('type') == 'item.started' and item.get('type') in {'mcp_tool_call', 'command_execution'}:
                        # Deliberately exclude tool arguments, shell commands, tokens and raw payloads.
                        self.log(job, '도구 실행: ' + (item.get('tool') or '로컬 제작·검증'))
                    elif event.get('type') in {'error', 'turn.failed'}:
                        error = event.get('error') or {}
                        detail = str(event.get('message') or (error.get('message') if isinstance(error, dict) else error) or 'Codex 실행 오류')
                        detail = re.sub(r'(?i)bearer\s+\S+|sk-[A-Za-z0-9_-]{16,}', '[redacted]', detail)[:1000]
                        self.update(job, last_error=detail)
                        if re.search(r'reconnect|retry|stream disconnect', detail, re.I):
                            self.log(job, '연결이 잠시 끊겨 재연결하고 있습니다.')
                        else:
                            self.log(job, 'Codex: ' + detail)
                code = process.wait()
            finally:
                timer.cancel()
                process.stdout.close()
                self.processes.pop(job['id'], None)
            if job['id'] in self.cancelled:
                return
            if code != 0:
                detail = job.get('last_error') or '로그인·도구 연결·사용 한도를 확인해 주세요.'
                phase = '등록' if mode == 'register' else '제작'
                raise ValueError(phase + ' 실행이 중단됐습니다. ' + detail + ' 작업 파일과 오류 로그는 보관됩니다.')

    def _timeout(self, job, process):
        with self.lock:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    self.ensure_stopped(process)
                except ProcessLookupError:
                    pass
                self.log(job, '45분 실행 제한에 도달해 중지했습니다.')

    @staticmethod
    def ensure_stopped(process):
        def force_stop():
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        timer = threading.Timer(5, force_stop)
        timer.daemon = True
        timer.start()

    def run(self, job, mode):
        try:
            self.execute(job, mode)
            if job['id'] in self.cancelled:
                return
            folder = self.data / job['id']
            result = json.loads(safe_file(folder, f'{mode}-result.json').read_text())
            if result.get('status') == 'blocked':
                self.update(job, status='blocked', message=result.get('summary', '제작 연결을 확인해 주세요.'))
                return
            if mode == 'build':
                if result.get('status') != 'ready':
                    raise ValueError('완료 결과 형식이 올바르지 않습니다.')
                self.update(job, status='checking', stage=4, message='완성 파일을 다시 검증하고 있습니다.')
                verified = self.verify(folder, result)
                if job['id'] in self.cancelled:
                    return
                write_json(folder / 'verified.json', verified)
                self.package(folder, verified)
                with self.lock:
                    if job['id'] not in self.cancelled:
                        self.update(job, status='ready', stage=4, result=verified,
                                    message=result.get('summary') or '동작을 확인한 뒤 등록해 주세요.')
            else:
                if result.get('status') != 'registered' or result.get('verified') is not True or not re.fullmatch(r'pet_[a-zA-Z0-9_-]+', result.get('pet_id', '')):
                    raise ValueError('등록 확인을 완료하지 못했습니다. Pets 목록에서 확인해 주세요. 같은 작업을 자동으로 재등록하지 않습니다.')
                self.update(job, status='registered', message=result['summary'], pet_id=result['pet_id'])
        except Exception as exc:
            if job['id'] not in self.cancelled:
                self.update(job, status='blocked', message=str(exc)[:1500])

    def verify(self, folder, result):
        skill = skill_directory()
        if not skill:
            raise ValueError('Pets 검증 스크립트를 찾을 수 없습니다.')
        required = ['atlas', 'preview', 'contact_sheet', 'directions', 'chroma_report',
                    'frame_review', 'direction_semantics', 'continuity_report']
        files = {key: safe_file(folder, result.get(key)) for key in required}
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', result.get('chroma_key', '')):
            raise ValueError('제작에 사용한 크로마 키를 확인할 수 없습니다.')
        if files['atlas'].suffix.lower() not in {'.png', '.webp'} or files['preview'].suffix.lower() != '.gif':
            raise ValueError('최종 스프라이트 또는 GIF 형식이 올바르지 않습니다.')
        scripts = skill / 'scripts'
        structural = folder / 'studio-atlas-validation.json'
        quality = folder / 'studio-quality-validation.json'
        commands = [
            [sys.executable, str(scripts / 'validate_atlas.py'), str(files['atlas']), '--require-v2',
             '--chroma-key', result['chroma_key'], '--json-out', str(structural)],
            [sys.executable, str(scripts / 'validate_pet_quality.py'), str(files['atlas']),
             '--atlas-validation', str(structural), '--chroma-report', str(files['chroma_report']),
             '--frame-review', str(files['frame_review']), '--direction-semantics', str(files['direction_semantics']),
             '--continuity', str(files['continuity_report']), '--json-out', str(quality)]
        ]
        for command, report in zip(commands, [structural, quality]):
            completed = subprocess.run(command, capture_output=True, timeout=120, text=True)
            if completed.returncode or not report.is_file() or json.loads(report.read_text()).get('ok') is not True:
                raise ValueError('최종 검증을 통과하지 못했습니다. QA 보고서를 확인하고 해당 제작 행을 수정해야 합니다.')
        # Require the complete motion set rather than a lone static preview.
        preview_dir = files['preview'].parent
        previews = collect_previews(folder, preview_dir)
        # Decode the preview and final image to reject corrupt output.
        from PIL import Image
        with Image.open(files['preview']) as image:
            if getattr(image, 'n_frames', 1) < 2:
                raise ValueError('동작 미리보기에 애니메이션이 없습니다.')
        return {**{key: str(path.relative_to(folder)) for key, path in files.items()},
                'sha256': hashlib.sha256(files['atlas'].read_bytes()).hexdigest(),
                'previews': previews, 'structural': structural.name, 'quality': quality.name,
                'warnings': json.loads(quality.read_text()).get('warnings', [])}

    def package(self, folder, result):
        request = json.loads((folder / 'request.json').read_text())
        with zipfile.ZipFile(folder / 'pet.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(safe_file(folder, result['atlas']), 'spritesheet' + Path(result['atlas']).suffix.lower())
            archive.write(safe_file(folder, result['preview']), 'previews/all-states.gif')
            archive.write(safe_file(folder, result['contact_sheet']), 'contact-sheet.png')
            archive.write(safe_file(folder, result['directions']), 'directions.png')
            for name, relative in result['previews'].items():
                archive.write(safe_file(folder, relative), 'previews/' + name)
            if request['audio']:
                archive.write(safe_file(folder, request['audio']), 'audio/notification' + Path(request['audio']).suffix)
            archive.writestr('metadata.json', json.dumps({'name': request['name'], 'description': request['description'],
                                                        'spriteVersion': 2, 'sha256': result['sha256'],
                                                        'warnings': result['warnings']}, ensure_ascii=False, indent=2))

    def shutdown(self):
        for job in self.list():
            if job['status'] in ACTIVE and job['status'] != 'registering':
                self.cancel(job['id'])
