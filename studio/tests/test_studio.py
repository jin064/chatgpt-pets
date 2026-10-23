"""No model calls, no real account mutation. Exercise local trust boundaries."""
import base64
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tomllib
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notifications import Notifications, replace_notify
from runner import JobManager, STATES, collect_previews, decode_upload, safe_file, write_json
from server import MAX_BODY, Server


class StudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.manager = JobManager(self.root / 'jobs')

    def tearDown(self):
        self.temp.cleanup()

    def make_job(self):
        with patch.object(self.manager, 'run'):
            return self.manager.create({'name': '우사기', 'style': 'auto'})

    def test_reject_path_escape_and_symlinks(self):
        secret = self.root / 'secret'
        secret.write_text('private')
        (self.manager.data / 'link').symlink_to(secret)
        for path in ['../secret', str(secret), 'link']:
            with self.assertRaises(ValueError):
                safe_file(self.manager.data, path)

    def test_reject_fake_or_oversized_upload(self):
        for data in [b'not audio', b'ID3' + b'0' * (10 * 1024 * 1024), b'']:
            with self.assertRaises(ValueError):
                decode_upload({'data': base64.b64encode(data).decode()}, 'audio')
        with self.assertRaises(ValueError):
            decode_upload({'data': 'not-base64!'}, 'image')
        with self.assertRaises(ValueError):
            decode_upload({'data': base64.b64encode(b'\x89PNG\r\n\x1a\ninvalid').decode()}, 'image')

    def test_name_is_data_not_shell(self):
        with patch.object(self.manager, 'run'):
            job = self.manager.create({'name': '$(touch HACKED); `echo nope`', 'style': 'auto'})
        request = json.loads((self.manager.data / job['id'] / 'request.json').read_text())
        self.assertEqual(request['name'], '$(touch HACKED); `echo nope`')
        self.assertFalse((self.manager.data / 'HACKED').exists())

    def test_only_one_job_runs(self):
        self.make_job()
        with self.assertRaises(ValueError):
            self.make_job()

    def test_interrupted_restart_cannot_register(self):
        job = self.make_job()
        restarted = JobManager(self.manager.data)
        self.assertEqual(restarted.get(job['id'])['status'], 'interrupted')
        with self.assertRaises(ValueError):
            restarted.register(job['id'])

    def test_zero_exit_without_artifacts_is_not_success(self):
        job = self.make_job()
        folder = self.manager.data / job['id']
        write_json(folder / 'build-result.json', {'status': 'ready'})
        with patch.object(self.manager, 'execute'):
            self.manager.run(self.manager.jobs[job['id']], 'build')
        self.assertEqual(self.manager.get(job['id'])['status'], 'blocked')
        self.assertFalse((folder / 'pet.zip').exists())

    def test_resume_preserves_approved_artifacts_and_request(self):
        job = self.make_job()
        folder = self.manager.data / job['id']
        (folder / 'approved.png').write_bytes(b'approved-artifact')
        before = (folder / 'request.json').read_bytes()
        self.manager.update(self.manager.jobs[job['id']], status='blocked')
        self.assertTrue(self.manager.get(job['id'])['can_resume'])
        with patch.object(self.manager, 'run'):
            self.manager.resume(job['id'])
        self.assertEqual(self.manager.get(job['id'])['status'], 'building')
        self.assertEqual((folder / 'approved.png').read_bytes(), b'approved-artifact')
        self.assertEqual((folder / 'request.json').read_bytes(), before)

    def test_resume_cannot_repeat_uncertain_registration(self):
        job = self.make_job()
        self.manager.update(self.manager.jobs[job['id']], status='blocked', operation='register')
        with self.assertRaises(ValueError):
            self.manager.resume(job['id'])
        self.manager.update(self.manager.jobs[job['id']], operation='build')
        (self.manager.data / job['id'] / 'registration-attempt.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.manager.resume(job['id'])

    def test_server_restart_during_registration_requires_reconciliation(self):
        job = self.make_job()
        self.manager.update(self.manager.jobs[job['id']], status='registering', operation='register')
        restarted = JobManager(self.manager.data)
        record = restarted.get(job['id'])
        self.assertEqual(record['status'], 'interrupted')
        self.assertFalse(record['can_resume'])
        self.assertIn('등록 여부', record['message'])
        with self.assertRaises(ValueError):
            restarted.resume(job['id'])
    def test_registration_requires_verified_result(self):
        job = self.make_job()
        folder = self.manager.data / job['id']
        write_json(folder / 'register-result.json', {'status': 'registered', 'pet_id': 'pet_test', 'verified': False})
        with patch.object(self.manager, 'execute'):
            self.manager.run(self.manager.jobs[job['id']], 'register')
        self.assertEqual(self.manager.get(job['id'])['status'], 'blocked')

    def test_bundled_renderer_preview_layout_is_supported(self):
        previews = self.root / 'previews'
        (previews / 'states').mkdir(parents=True)
        for state in STATES:
            (previews / 'states' / (state + '.gif')).write_bytes(b'fixture')
        for name in ['all-states.mp4', 'idle-jump-idle.gif', 'look-loop.gif', 'still-01-idle.png',
                     'still-02-waving.png', 'still-03-jumping.png', 'still-04-review.png']:
            (previews / name).write_bytes(b'fixture')
        index = collect_previews(self.root, previews)
        self.assertEqual(index['idle.gif'], 'previews/states/idle.gif')
        self.assertEqual(len([name for name in index if name.startswith('still-')]), 4)
        (previews / 'states/jumping.gif').unlink()
        with self.assertRaises(ValueError):
            collect_previews(self.root, previews)

    def test_registration_rejects_changed_atlas(self):
        job = self.make_job()
        folder = self.manager.data / job['id']
        (folder / 'atlas.png').write_bytes(b'changed')
        write_json(folder / 'verified.json', {'atlas': 'atlas.png', 'sha256': 'old-hash'})
        self.manager.update(self.manager.jobs[job['id']], status='ready')
        with self.assertRaises(ValueError):
            self.manager.register(job['id'])

    def test_replace_multiline_notify_preserves_all_other_settings(self):
        source = '# my config\nnotify = [\n "old",\n "argument"\n]\nmodel = "example"\n[section]\nvalue = 3\n'
        result = replace_notify(source, ['python', 'new.py'])
        expected = tomllib.loads(source)
        expected['notify'] = ['python', 'new.py']
        self.assertEqual(tomllib.loads(result), expected)
        self.assertIn('# my config', result)

    def test_sound_switch_and_restore_preserve_notifier(self):
        notification = Notifications(self.root)
        source = 'notify = ["original", "arg"]\nmodel = "example"\n[section]\nvalue = true\n'
        notification.config.write_text(source)
        sound = self.root / 'voice.mp3'
        sound.write_bytes(b'ID3test')
        with patch('notifications.sys.platform', 'darwin'), patch('notifications.validate_sound'):
            notification.apply(sound)
            # A restart under a different Python must not recursively wrap this hook.
            notification.command[0] = '/another/python3'
            notification.apply(sound)
            settings = json.loads(notification.settings.read_text())
            self.assertEqual(settings['previous'], ['original', 'arg'])
            notification.restore()
        self.assertEqual(tomllib.loads(notification.config.read_text()), tomllib.loads(source))
        self.assertEqual(len(list(self.root.glob('config.toml.before-pet-studio-*'))), 3)

    def test_unplayable_sound_does_not_change_config(self):
        notification = Notifications(self.root)
        source = 'notify = ["original"]\n'
        notification.config.write_text(source)
        with patch('notifications.sys.platform', 'darwin'), patch('notifications.validate_sound', side_effect=ValueError('invalid audio')):
            with self.assertRaises(ValueError):
                notification.apply(self.root / 'broken.mp3')
        self.assertEqual(notification.config.read_text(), source)

    def test_restore_refuses_external_change(self):
        notification = Notifications(self.root)
        notification.config.write_text('notify = ["another-app"]\n')
        with self.assertRaises(ValueError):
            notification.restore()
        self.assertEqual(tomllib.loads(notification.config.read_text())['notify'], ['another-app'])

    def test_http_csrf_host_body_and_private_files(self):
        server = Server(('127.0.0.1', 0), self.manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            status, data = response.status, response.read()
            connection.close()
            return status, data
        try:
            self.assertEqual(request('GET', '/')[0], 200)
            status, package = request('GET', '/downloads/grok-extension.zip')
            self.assertEqual(status, 200)
            with zipfile.ZipFile(io.BytesIO(package)) as archive:
                names = archive.namelist()
                self.assertTrue(all(name.startswith('pet-studio-grok/') and name.count('/') == 1 for name in names))
                manifest = json.loads(archive.read('pet-studio-grok/manifest.json'))
                self.assertEqual(manifest['optional_host_permissions'], ['https://grok.com/*'])
                self.assertNotIn('host_permissions', manifest)
                self.assertEqual(archive.read('pet-studio-grok/una.mp3'), (Path(__file__).resolve().parents[2] / 'pets/usagi/audio/chiikawa-usagi-una.mp3').read_bytes())
                self.assertNotIn('pet-studio-grok/tests', names)
            self.assertEqual(request('GET', '/integrations/grok-web/options.html')[0], 200)
            self.assertEqual(request('GET', '/integrations/grok-web/background.js')[0], 404)
            self.assertEqual(request('GET', '/', headers={'Host': 'evil.example'})[0], 403)
            self.assertEqual(request('POST', '/api/jobs', '{}', {'Content-Type': 'application/json'})[0], 403)
            headers = {'Content-Type': 'application/json', 'X-Pet-Studio-Token': server.token,
                       'Origin': 'https://evil.example'}
            self.assertEqual(request('POST', '/api/jobs', '{}', headers)[0], 403)
            headers.pop('Origin')
            headers['Content-Length'] = str(MAX_BODY + 1)
            self.assertEqual(request('POST', '/api/jobs', '{}', headers)[0], 413)
            job = self.make_job()
            self.assertEqual(request('GET', f'/files/{job["id"]}/request.json')[0], 404)
            self.assertEqual(request('GET', '/pets/../../README.md')[0], 404)
            self.assertEqual(request('GET', '/api/jobs/no-such-job')[0], 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
