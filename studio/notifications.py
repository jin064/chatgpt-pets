"""Explicit, reversible macOS notification sound installation."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib
import uuid

HOOK = '''#!/usr/bin/env python3
"""Pet Studio notification hook. Settings are data, never shell commands."""
import json
from pathlib import Path
import subprocess
import sys
settings = json.loads(Path(__file__).with_name('settings.json').read_text())
try:
    event = json.loads(sys.argv[-1])
except (ValueError, IndexError):
    event = {}
if not isinstance(event, dict):
    event = {}
if event.get('type') == 'agent-turn-complete':
    subprocess.Popen(['/usr/bin/afplay', settings['sound']], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
if settings['previous']:
    try:
        raise SystemExit(subprocess.call(settings['previous'] + sys.argv[1:]))
    except OSError:
        raise SystemExit(1)
'''


def validate_sound(sound):
    try:
        result = subprocess.run(['/usr/bin/afinfo', str(sound)], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('이 Mac에서 음성 파일을 확인할 수 없습니다.') from None
    if result.returncode:
        raise ValueError('이 Mac에서 재생할 수 없는 음성입니다. MP3·WAV·M4A로 변환해 주세요.')


def replace_notify(source, command):
    parsed = tomllib.loads(source)
    lines = source.splitlines(keepends=True)
    start = None
    end = None
    import re
    for index, line in enumerate(lines):
        if re.match(r'^\s*\[', line):
            break
        if re.match(r'^\s*notify\s*=', line):
            start = index
            for last in range(index + 1, len(lines) + 1):
                try:
                    fragment = tomllib.loads(''.join(lines[index:last]))
                except tomllib.TOMLDecodeError:
                    continue
                if 'notify' in fragment:
                    end = last
                    break
            break
    if 'notify' in parsed and (start is None or end is None):
        raise ValueError('기존 notify 항목을 안전하게 수정할 수 없습니다. config.toml을 확인해 주세요.')
    replacement = '' if command is None else 'notify = ' + json.dumps(command, ensure_ascii=False) + '\n'
    updated = ''.join(lines[:start] + [replacement] + lines[end:]) if start is not None else replacement + source
    expected = dict(parsed)
    if command is None:
        expected.pop('notify', None)
    else:
        expected['notify'] = command
    if tomllib.loads(updated) != expected:
        raise ValueError('알림음 이외의 설정이 바뀌어 저장을 중단했습니다.')
    return updated


class Notifications:
    def __init__(self, codex_home=None):
        self.home = Path(codex_home or os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).resolve()
        self.folder = self.home / 'pet-studio'
        self.config = self.home / 'config.toml'
        self.settings = self.folder / 'settings.json'
        self.command = [sys.executable, str(self.folder / 'notify.py')]

    def is_own_hook(self, command):
        return (isinstance(command, list) and len(command) == 2 and all(isinstance(x, str) for x in command) and
                Path(command[1]).resolve() == (self.folder / 'notify.py').resolve())

    def status(self):
        try:
            active = self.is_own_hook(tomllib.loads(self.config.read_text()).get('notify'))
            return {'supported': sys.platform == 'darwin', 'active': active}
        except (OSError, ValueError):
            return {'supported': sys.platform == 'darwin', 'active': False}

    def _write_config(self, source, updated):
        if (self.config.read_text() if self.config.exists() else '') != source:
            raise ValueError('다른 곳에서 Codex 설정을 수정했습니다. 다시 시도해 주세요.')
        backup = self.home / ('config.toml.before-pet-studio-' + str(time.time_ns()))
        backup.write_text(source)
        backup.chmod(0o600)
        temp = self.home / ('config-' + uuid.uuid4().hex + '.tmp')
        temp.write_text(updated)
        temp.chmod(self.config.stat().st_mode & 0o777 if self.config.exists() else 0o600)
        temp.replace(self.config)

    def apply(self, sound):
        if sys.platform != 'darwin':
            raise ValueError('자동 알림음 설정은 macOS에서 지원합니다. 음성 파일은 ZIP으로 받을 수 있습니다.')
        validate_sound(sound)
        self.home.mkdir(exist_ok=True)
        source = self.config.read_text() if self.config.exists() else ''
        previous = tomllib.loads(source).get('notify')
        if previous is not None and (not isinstance(previous, list) or not all(isinstance(x, str) for x in previous)):
            raise ValueError('기존 notify 명령 형식을 확인해 주세요.')
        restore = previous
        settings = json.loads(self.settings.read_text()) if self.settings.exists() else {}
        if self.is_own_hook(previous):
            if 'previous' not in settings:
                raise ValueError('이전 알림 설정 기록이 없습니다. 설정 백업을 확인해 주세요.')
            previous = settings['previous']
            restore = settings.get('restore')
        elif previous and len(previous) >= 2:
            # Migrate the known Usagi hook made in this project, avoiding two sounds.
            # Parse a constant; never execute the previous script to inspect it.
            old = Path(previous[1])
            if old.is_file() and old.suffix == '.py':
                text = old.read_text()
                if '"""Play Usagi on agent completion, preserving the previous notifier."""' in text:
                    tree = ast.parse(text)
                    for statement in tree.body:
                        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PREVIOUS' for t in statement.targets):
                            candidate = ast.literal_eval(statement.value)
                            if isinstance(candidate, list) and all(isinstance(x, str) for x in candidate):
                                previous = candidate
        updated = replace_notify(source, self.command)
        self.folder.mkdir(mode=0o700, exist_ok=True)
        target = self.folder / ('sound-' + uuid.uuid4().hex + sound.suffix)
        shutil.copyfile(sound, target)
        (self.folder / 'notify.py').write_text(HOOK)
        new_settings = {'sound': str(target), 'previous': previous or [], 'restore': restore}
        # Config is changed only after the hook and its settings are durable.
        self.settings.write_text(json.dumps(new_settings, ensure_ascii=False))
        self.settings.chmod(0o600)
        try:
            self._write_config(source, updated)
        except Exception:
            if settings:
                self.settings.write_text(json.dumps(settings))
            raise
        for old_sound in self.folder.glob('sound-*'):
            if old_sound != target:
                old_sound.unlink()
        return self.status()

    def restore(self):
        source = self.config.read_text()
        if not self.is_own_hook(tomllib.loads(source).get('notify')):
            raise ValueError('현재 알림 설정이 Pet Studio 설정과 다릅니다. 다른 변경을 덮어쓰지 않았습니다.')
        settings = json.loads(self.settings.read_text())
        self._write_config(source, replace_notify(source, settings.get('restore')))
        return self.status()
