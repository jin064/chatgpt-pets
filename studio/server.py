#!/usr/bin/env python3
"""Loopback-only Pet Studio. Python 3.11+, Pillow for final QA."""
from __future__ import annotations
import argparse
import json
import mimetypes
import os
from pathlib import Path
import secrets
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit
import webbrowser

from notifications import Notifications
from runner import HERE, ROOT, JobManager, preflight, safe_file

MAX_BODY = 26 * 1024 * 1024


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager):
        super().__init__(address, Handler)
        self.manager = manager
        self.token = secrets.token_urlsafe(32)
        self.notifications = Notifications()
        self.notification_lock = threading.Lock()
        self.checks = None
        self.check_time = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

    def send(self, data, content_type='application/json; charset=utf-8', status=200, attachment=False):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if attachment:
            self.send_header('Content-Disposition', 'attachment; filename="pet.zip"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def file(self, path, attachment=False):
        if path.stat().st_size > 80 * 1024 * 1024:
            raise ValueError('다운로드 가능한 크기를 초과했습니다.')
        self.send(path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream', attachment=attachment)

    def do_GET(self):
        if not self.valid_host():
            return self.send({'error': '로컬 주소로 접속해 주세요.'}, status=403)
        path = unquote(urlsplit(self.path).path)
        try:
            if path == '/api/session':
                return self.send({'token': self.server.token})
            if path == '/api/status':
                if time.time() - self.server.check_time > 30:
                    self.server.checks = preflight()
                    self.server.check_time = time.time()
                return self.send({**self.server.checks, 'notifications': self.server.notifications.status()})
            if path == '/api/jobs':
                return self.send({'jobs': self.server.manager.list()})
            if path.startswith('/api/jobs/'):
                return self.send(self.server.manager.get(path.removeprefix('/api/jobs/')))
            if path.startswith('/files/'):
                parts = path.removeprefix('/files/').split('/', 1)
                if len(parts) != 2:
                    raise ValueError('파일 경로가 올바르지 않습니다.')
                job = self.server.manager.get(parts[0])
                folder = self.server.manager.data / job['id']
                allowed = {job['audio'], job['image']}
                result = job.get('result', {})
                allowed.update(result.get(key, '') for key in ['atlas', 'preview', 'contact_sheet', 'directions'])
                allowed.update(result.get('previews', {}).values())
                if job['status'] in {'ready', 'registered', 'registering'}:
                    allowed.add('pet.zip')
                if parts[1] not in allowed or not parts[1]:
                    raise ValueError('공개된 결과 파일이 아닙니다.')
                return self.file(safe_file(folder, parts[1]), parts[1] == 'pet.zip')
            if path.startswith('/pets/'):
                return self.file(safe_file(ROOT / 'pets', path.removeprefix('/pets/')))
            return self.file(safe_file(HERE / 'static', 'index.html' if path == '/' else path.lstrip('/')))
        except (ValueError, OSError, KeyError):
            self.send({'error': '찾을 수 없습니다.'}, status=404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        valid_origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or (origin and origin not in valid_origins) or self.headers.get('X-Pet-Studio-Token') != self.server.token:
            return self.send({'error': '이 화면에서 다시 시도해 주세요.'}, status=403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send({'error': 'JSON 형식이 필요합니다.'}, status=415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > MAX_BODY:
                return self.send({'error': '전송 파일이 너무 큽니다.'}, status=413)
            self.connection.settimeout(20)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('전송이 완료되지 않았습니다.')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('입력 형식이 올바르지 않습니다.')
            path = urlsplit(self.path).path
            manager = self.server.manager
            if path == '/api/jobs':
                checks = preflight()
                if not checks['ready']:
                    return self.send({'error': ' · '.join(checks['issues'])}, status=409)
                return self.send(manager.create(payload), status=201)
            if path == '/api/notifications/restore':
                with self.server.notification_lock:
                    return self.send(self.server.notifications.restore())
            parts = path.strip('/').split('/')
            if len(parts) != 4 or parts[:2] != ['api', 'jobs']:
                return self.send({'error': '찾을 수 없습니다.'}, status=404)
            job = manager.get(parts[2])
            if parts[3] == 'cancel':
                manager.cancel(job['id'])
            elif parts[3] == 'register':
                manager.register(job['id'])
            elif parts[3] == 'sound':
                if not job['audio']:
                    raise ValueError('이 펫에 음성 파일이 없습니다.')
                with self.server.notification_lock:
                    self.server.notifications.apply(safe_file(manager.data / job['id'], job['audio']))
            else:
                return self.send({'error': '찾을 수 없습니다.'}, status=404)
            self.send(manager.get(job['id']))
        except (ValueError, KeyError, OSError) as exc:
            self.send({'error': str(exc)[:1000]}, status=400)
        except Exception:
            self.send({'error': '요청을 처리하지 못했습니다. 서버 터미널을 확인해 주세요.'}, status=500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    manager = JobManager(os.environ.get('PET_STUDIO_DATA', str(ROOT / '.pet-studio' / 'jobs')))
    server = Server(('127.0.0.1', args.port), manager)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Pet Studio: {url}', flush=True)
    if args.open:
        webbrowser.open(url)
    def stop(*_):
        # Active registration must finish to avoid creating an uncertain duplicate.
        if any(j['status'] == 'registering' for j in manager.list()):
            print('Pets 등록 중입니다. 결과 확인 후 종료해 주세요.', flush=True)
            return
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        manager.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
