import copy
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claude_notifications import ClaudeNotifications


class ClaudeNotificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.target = ClaudeNotifications(self.home)
        self.sound = self.home / 'voice.mp3'
        self.sound.write_bytes(b'local-audio-fixture')

    def tearDown(self):
        self.temp.cleanup()

    def apply(self):
        with patch('claude_notifications.sys.platform', 'darwin'), patch('claude_notifications.validate_sound'):
            return self.target.apply(self.sound)

    def test_existing_settings_and_hooks_survive_apply_switch_restore(self):
        before = {'model': 'custom', 'permissions': {'deny': ['secret']}, 'hooks': {
            'Stop': [{'matcher': '', 'hooks': [{'type': 'command', 'command': 'existing-check'}]}],
            'PreToolUse': [{'hooks': [{'type': 'command', 'command': 'another-check'}]}]}}
        self.target.config.write_text(json.dumps(before))
        self.apply()
        self.apply()
        now = json.loads(self.target.config.read_text())
        self.assertEqual(now['hooks']['Stop'][0], before['hooks']['Stop'][0])
        self.assertEqual(len(now['hooks']['Stop']), 2)
        self.assertEqual(now['permissions'], before['permissions'])
        self.target.restore()
        self.assertEqual(json.loads(self.target.config.read_text()), before)

    def test_restore_preserves_changes_made_after_install(self):
        self.target.config.write_text('{}')
        self.apply()
        now = json.loads(self.target.config.read_text())
        now['hooks']['Stop'].append({'hooks': [{'type': 'command', 'command': 'new-check'}]})
        now['new_setting'] = 7
        self.target.config.write_text(json.dumps(now))
        self.target.restore()
        self.assertEqual(json.loads(self.target.config.read_text()), {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'new-check'}]}]}, 'new_setting': 7})

    def test_empty_config_restores_to_empty(self):
        self.apply()
        self.target.restore()
        self.assertEqual(json.loads(self.target.config.read_text()), {})

    def test_disabled_hooks_are_not_silently_enabled(self):
        before = '{"disableAllHooks":true}'
        self.target.config.write_text(before)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target.config.read_text(), before)

    def test_malformed_config_is_not_overwritten(self):
        self.target.config.write_text('broken json')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.target.config.read_text(), 'broken json')

    def test_hook_sounds_only_for_completed_main_turn(self):
        self.apply()
        for event, expected in [({'hook_event_name': 'Stop'}, True),
                                ({'hook_event_name': 'Stop', 'stop_hook_active': True}, False),
                                ({'hook_event_name': 'SubagentStop'}, False),
                                ({'hook_event_name': 'Stop', 'background_tasks': [{'status': 'running'}]}, False),
                                ({'hook_event_name': 'UserPromptSubmit'}, False)]:
            with patch('sys.stdin', io.StringIO(json.dumps(event))), patch('subprocess.Popen') as player:
                try:
                    runpy.run_path(str(self.target.script), run_name='__main__')
                except SystemExit as result:
                    self.assertEqual(result.code, 0)
                self.assertEqual(player.called, expected)


if __name__ == '__main__':
    unittest.main()
