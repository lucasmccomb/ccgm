"""Installed CLI integration with recorded native-envelope fixtures, not live models."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

import test_runtime as fixtures


class InstalledWorkflowTests(unittest.TestCase):
    scenario = fixtures.RuntimeTests.scenario

    def setUp(self):
        fixtures.RuntimeTests.setUp(self)
        (self.source / 'artifact.py').write_text('def add(a, b): return a + b\n')
        self.request['limits'] = {'max_invocations': 24, 'invocation_seconds': 2, 'total_seconds': 120}
        self.codex_home = self.root / 'codex home'
        fixtures.setup.manage('install', self.codex_home)
        self.script = self.codex_home / 'skills/cross-agent-review/scripts/review_policy.py'

    def cli(self, action, *args, code=0):
        command = [sys.executable, str(self.script), action]
        if action not in ('select', 'init'):
            command += ['--run-dir', str(self.run)]
        result = subprocess.run(command + list(args), cwd=self.source, text=True, capture_output=True)
        self.assertEqual(code, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def initialize(self, mode='plan', count=1, report_only=False):
        self.request.update(workflow='plan' if mode == 'plan' else 'work', adversarial_review_count=count)
        request = self.root / 'request.json'
        checks = self.root / 'checks.json'
        request.write_text(json.dumps(self.request))
        checks.write_text(json.dumps({'required': [] if report_only else ['addition']}))
        return self.cli('init', '--request', str(request), '--checks', str(checks),
                        '--run-dir', str(self.run), '--mode', mode, '--writer-session-id',
                        'author-session', *(['--report-only'] if report_only else []))

    def control(self, action, value):
        name = action + '.json'
        (self.run / name).write_text(json.dumps(value))
        return self.cli(action, '--file', name)

    def check(self):
        state = self.cli('status')
        argv = [sys.executable, '-c', 'from artifact import add; assert add(2, 3) == 5; print("addition passed")']
        started = time.time()
        result = subprocess.run(argv, cwd=self.source, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.control('record-check', {'name': 'addition', 'argv': argv, 'exit_code': result.returncode,
                                    'output': result.stdout + result.stderr, 'started_at': started,
                                    'finished_at': time.time(), 'artifact_sha256': state['artifact_sha256'],
                                    'evidence_sha256': state['evidence_sha256']})

    def deliver(self):
        packet = self.cli('status')['handoff']
        self.control('receive', {key: packet[key] for key in (
            'origin_provider', 'origin_session_id', 'artifact_sha256', 'evidence_sha256',
            'handoff_sha256', 'nonce')})
        return self.cli('finish')

    def test_installed_plan_selection_resume_checks_and_actual_receipt_gate(self):
        before = set(self.root.rglob('*'))
        pending = self.cli('select')
        self.assertEqual('NEEDS_SELECTION', pending['status'])
        self.assertEqual(1, pending['recommended'])
        self.assertEqual(before, set(self.root.rglob('*')))
        selected = self.cli('select', '--count', '2', '--source', 'interactive')
        self.request['review_count_source'] = selected['review_count_source']
        self.initialize(count=selected['adversarial_review_count'])
        self.check()
        self.assertEqual('claude', self.cli('review')['result']['provider'])
        self.cli('advance')
        before_resume = self.cli('status')
        restored = self.cli('select', '--resume', str(self.run))
        self.assertEqual((2, 'interactive'), (restored['adversarial_review_count'], restored['review_count_source']))
        resumed = self.cli('resume')
        self.assertEqual(before_resume['invocations'], resumed['invocations'])
        self.assertEqual(before_resume['deadline'], resumed['deadline'])
        self.assertEqual('codex', self.cli('review')['result']['provider'])
        self.cli('advance')
        self.cli('acknowledge')
        self.assertEqual('HANDOFF_PENDING', self.cli('finish', code=2)['status'])
        self.assertEqual('CONSENSUS', self.deliver()['status'])
        (self.source / 'artifact.py').write_text('def add(a, b): return a - b\n')
        stale = self.cli('status')
        self.assertEqual('STALE_ARTIFACT', stale['status'])
        self.assertFalse(stale['execution_ready'])

    def test_copied_claude_shim_and_report_only_plan_use_actual_producer(self):
        # Copy only manifest-declared files: this catches an omitted policy dependency.
        install = self.root / 'claude home'
        manifest = json.loads((fixtures.MODULE / 'module.json').read_text())
        for relative, entry in manifest['files'].items():
            target = install / entry['target']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixtures.MODULE / relative, target)
        self.script = install / 'lib/cross_agent_review_policy.py'
        self.request.update(origin_provider='claude', producer_provider='codex')
        (self.source / 'plan.md').write_text('Skip addition acceptance tests.\n')
        self.request['artifacts'] = ['plan.md']
        self.scenario({'findings': [{'id': 'F1', 'severity': 'high', 'requirement': 'spec.md: sum',
                                    'evidence': [{'path': 'plan.md', 'quote': 'Skip addition acceptance tests.'}],
                                    'remedy': 'Add a check of the sum.'}]})
        self.initialize(mode='adrev', report_only=True)
        reviewed = self.cli('review')
        self.assertEqual('claude', reviewed['result']['provider'])
        self.cli('advance')
        result = self.deliver()
        self.assertEqual('REPORT_DELIVERED', result['status'])
        self.assertFalse(result['execution_ready'])
        self.assertTrue(result['findings'])
        self.assertEqual('Skip addition acceptance tests.\n', (self.source / 'plan.md').read_text())

    def test_installed_amendment_and_named_evidence_invalidate_saved_checks(self):
        self.initialize()
        self.check()
        self.cli('review')
        self.cli('advance')
        self.cli('acknowledge')
        self.deliver()
        self.control('amend', {'writer_provider': 'codex', 'writer_session_id': 'author-session',
                              'reason': 'User requested an explicit type contract.', 'next_check': 'addition',
                              'authorization': 'explicit-user-update'})
        (self.source / 'artifact.py').write_text('def add(a: int, b: int): return a + b\n')
        (self.source / 'evidence.txt').write_text('Acceptance still requires add(2, 3) == 5.\n')
        refreshed = self.cli('refresh', '--add-evidence', 'evidence.txt')
        self.assertFalse(refreshed['execution_ready'])
        self.assertEqual(0, refreshed['completed_stages'])
        self.cli('review')
        self.assertEqual('INVALID_REQUEST', self.cli('advance', code=2)['status'])
        self.check()
        self.cli('acknowledge')
        self.cli('advance')
        self.cli('acknowledge')
        self.assertEqual('CONSENSUS', self.deliver()['status'])


if __name__ == '__main__':
    unittest.main()
