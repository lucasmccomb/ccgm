"""An unexpected exception inside the guard must deny, never fail open.

Claude Code treats a hook exit of 1 as non-blocking, so a crash in a check
would let the whole command run. Runs in a temporary fake HOME.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

GUARD = Path(__file__).resolve().parents[1] / 'hooks/advisor-guard.py'


def load_guard():
    spec = importlib.util.spec_from_file_location('advisor_guard_under_test', GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        home = Path(self.temporary.name)
        flag = home / '.claude/advisor-mode/failclosed-test'
        flag.parent.mkdir(parents=True)
        flag.touch()
        env = {k: v for k, v in os.environ.items() if k != 'ADVISOR_DIRECT'}
        env['HOME'] = str(home)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.guard = load_guard()

    def run_hook(self, tool, tool_input):
        data = json.dumps(dict(tool_name=tool, tool_input=tool_input, session_id='failclosed-test'))
        with mock.patch.object(sys, 'stdin', io.StringIO(data)), \
                mock.patch.object(sys, 'stderr', io.StringIO()) as err:
            with self.assertRaises(SystemExit) as raised:
                self.guard.main()
        return raised.exception.code, err.getvalue()

    def test_bash_check_error_denies(self):
        with mock.patch.object(self.guard, 'check_command', side_effect=ValueError('boom')):
            code, err = self.run_hook('Bash', {'command': 'git status'})
        self.assertEqual(2, code)
        self.assertIn('guard error', err)

    def test_file_check_error_denies(self):
        with mock.patch.object(self.guard, 'path_allowed', side_effect=ValueError('boom')):
            code, err = self.run_hook('Edit', {'file_path': '/x/y'})
        self.assertEqual(2, code)
        self.assertIn('guard error', err)


if __name__ == '__main__':
    unittest.main()
