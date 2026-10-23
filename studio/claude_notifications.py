"""Install one reversible Claude Code Stop hook, preserving every other hook."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import uuid

from notifications import validate_sound

HOOK = '''#!/usr/bin/env python3
"""Pet Studio Claude Code completion sound. No transcript access or blocking output."""
import json
from pathlib import Path
import subprocess
import sys
try:
    event = json.loads(sys.stdin.read(1024 * 1024))
    settings = json.loads(Path(__file__).with_name('sound.json').read_text())
    if not isinstance(event, dict) or event.get('hook_event_name') != 'Stop':
        raise SystemExit(0)
    if event.get('stop_hook_active'):
        raise SystemExit(0)
    if any(task.get('status') in {'running', 'pending'} for task in event.get('background_tasks', []) if isinstance(task, dict)):
        raise SystemExit(0)
    sound = Path(settings['sound'])
    if sound.is_file():
        subprocess.Popen(['/usr/bin/afplay', str(sound)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
except (ValueError, OSError, KeyError, TypeError):
    pass
'''


def atomic_json(path, value, mode=0o600):
    temporary = path.with_name(path.name + '-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.chmod(mode)
    temporary.replace(path)


class ClaudeNotifications:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).expanduser().resolve()
        self.config = self.home / 'settings.json'
        self.folder = self.home / 'pet-studio'
        self.script = self.folder / 'stop.py'
        self.state = self.folder / 'sound.json'
        self.command = shlex.join([sys.executable, str(self.script)])

    def _read(self):
        source = self.config.read_text() if self.config.exists() else ''
        data = json.loads(source) if source else {}
        if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict):
            raise ValueError('Claude Code 설정의 hooks 형식을 확인해 주세요.')
        groups = data.get('hooks', {}).get('Stop', [])
        if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks', []), list) for g in groups):
            raise ValueError('Claude Code Stop 훅 형식을 확인해 주세요.')
        return source, data

    def _ours(self, hook):
        if not isinstance(hook, dict) or hook.get('type') != 'command':
            return False
        try:
            args = shlex.split(hook.get('command', ''))
            return len(args) == 2 and Path(args[1]).resolve() == self.script.resolve()
        except (ValueError, TypeError):
            return False

    def _remove(self, groups):
        result = []
        for group in groups:
            hooks = group.get('hooks', [])
            kept = [hook for hook in hooks if not self._ours(hook)]
            if len(kept) == len(hooks):
                result.append(group)
            elif kept:
                result.append({**group, 'hooks': kept})
        return result

    def status(self):
        try:
            _, data = self._read()
            active = any(self._ours(h) for g in data.get('hooks', {}).get('Stop', []) for h in g.get('hooks', []))
            return {'supported': sys.platform == 'darwin', 'active': active,
                    'hooks_disabled': data.get('disableAllHooks', False),
                    'installed': bool(shutil.which('claude') or (Path.home() / '.local/bin/claude').is_file())}
        except (OSError, ValueError):
            return {'supported': sys.platform == 'darwin', 'active': False, 'error': 'Claude Code 설정을 읽을 수 없습니다.'}

    def _write(self, source, data):
        if (self.config.read_text() if self.config.exists() else '') != source:
            raise ValueError('다른 곳에서 Claude Code 설정을 수정했습니다. 다시 시도해 주세요.')
        backup = self.home / ('settings.json.before-pet-studio-' + str(time.time_ns()))
        backup.write_text(source)
        backup.chmod(0o600)
        atomic_json(self.config, data, self.config.stat().st_mode & 0o777 if self.config.exists() else 0o600)

    def apply(self, sound):
        if sys.platform != 'darwin':
            raise ValueError('자동 알림음 설정은 macOS에서 지원합니다.')
        validate_sound(sound)
        source, data = self._read()
        if data.get('disableAllHooks'):
            raise ValueError('Claude Code의 훅이 비활성화돼 있습니다. Claude 설정에서 확인해 주세요.')
        groups = data.get('hooks', {}).get('Stop', [])
        active = any(self._ours(h) for group in groups for h in group.get('hooks', []))
        prior = json.loads(self.state.read_text()) if active and self.state.exists() else None
        if active and not prior:
            raise ValueError('기존 Pet Studio 연결 기록이 없습니다. 설정 백업을 확인해 주세요.')
        state = {'had_hooks': 'hooks' in data, 'had_stop': 'Stop' in data.get('hooks', {})}
        if prior:
            state = {key: prior[key] for key in ['had_hooks', 'had_stop']}
        self.folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        target = self.folder / ('sound-' + uuid.uuid4().hex + sound.suffix)
        shutil.copyfile(sound, target)
        state['sound'] = str(target)
        self.script.write_text(HOOK)
        self.script.chmod(0o600)
        atomic_json(self.state, state)
        data.setdefault('hooks', {})['Stop'] = self._remove(groups) + [{'hooks': [{'type': 'command', 'command': self.command, 'timeout': 5}]}]
        try:
            self._write(source, data)
        except Exception:
            if prior:
                atomic_json(self.state, prior)
            raise
        return self.status()

    def restore(self):
        source, data = self._read()
        if not self.state.exists():
            raise ValueError('복원할 Claude Code 연결 기록이 없습니다.')
        groups = data.get('hooks', {}).get('Stop', [])
        if not any(self._ours(h) for group in groups for h in group.get('hooks', [])):
            raise ValueError('현재 Claude Code에 Pet Studio 완료 훅이 없습니다.')
        state = json.loads(self.state.read_text())
        kept = self._remove(groups)
        data['hooks']['Stop'] = kept
        if not kept and not state['had_stop']:
            del data['hooks']['Stop']
        if not data['hooks'] and not state['had_hooks']:
            del data['hooks']
        self._write(source, data)
        return self.status()
