"""Lifecycle, preflight and measured-input boundaries; only fixture providers run."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_policy as fixtures

policy = fixtures.policy
runtime = policy.rt
POLICY_CLI = fixtures.MODULE / 'lib/cross_agent_review_policy.py'


class ReviewBoundaryTests(unittest.TestCase):
    scenario = fixtures.PolicyTests.scenario

    def setUp(self):
        fixtures.fixtures.RuntimeTests.setUp(self)
        self.request['limits'] = {'max_invocations': 8, 'invocation_seconds': 2, 'total_seconds': 120}

    def state(self):
        return runtime.load(self.run)[1]

    def fail_review(self, expected, operation):
        with self.assertRaises(runtime.ReviewError) as caught:
            operation()
        self.assertEqual(expected, caught.exception.status)

    def initialize(self):
        self.request['workflow'] = 'plan'
        return policy.initialize(self.request, self.run, 'plan', {'required': ['unit']},
                                 'author-session', cross_provider=True)

    def files(self, root=None):
        return {str(path.relative_to(root or self.root)): path.read_bytes()
                for path in (root or self.root).rglob('*') if path.is_file()}

    def test_default_initialize_uses_lead_review_without_validation_files_or_dispatch(self):
        before = self.files()
        with patch.object(runtime, 'create_run') as create, \
             patch.object(runtime, 'validate_request') as validate, \
             patch.object(runtime, 'run_process') as provider, \
             patch.object(policy, 'preflight') as preflight:
            result = policy.initialize(None, self.run, None, None, None)
        self.assertEqual('LEAD_REVIEW', result['status'])
        self.assertEqual('lead', result['review_mode'])
        self.assertFalse(result['execution_ready'])
        for mock in (create, validate, provider, preflight):
            mock.assert_not_called()
        self.assertFalse(self.run.exists())
        self.assertEqual(before, self.files())

    def test_default_cli_init_needs_no_request_files_and_never_starts_a_provider(self):
        marker = self.root / 'provider-was-started'
        for name in runtime.PROVIDERS:
            (self.bin / name).write_text('#!' + sys.executable + '\nfrom pathlib import Path\n'
                                         + 'Path(%r).write_text("started")\n' % str(marker))
        before = self.files()
        for args in ([], ['--request', str(self.root / 'absent.json'),
                          '--checks', str(self.root / 'also-absent.json'), '--run-dir', str(self.run)]):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(POLICY_CLI), 'init', *args],
                                        cwd=self.source, capture_output=True, text=True, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual('LEAD_REVIEW', json.loads(result.stdout)['status'])
                self.assertFalse(json.loads(result.stdout)['execution_ready'])
                self.assertFalse(marker.exists())
                self.assertEqual(before, self.files())
        result = subprocess.run([sys.executable, str(POLICY_CLI), 'init', '--cross-provider'],
                                cwd=self.source, capture_output=True, text=True, timeout=10)
        self.assertEqual(2, result.returncode)
        self.assertEqual('INVALID_REQUEST', json.loads(result.stderr)['status'])
        self.assertFalse(self.run.exists())
        self.assertFalse(marker.exists())

    def preflight_result(self, claude_output, claude_code=0, codex_code=0, exception=None):
        def auth(argv, **kwargs):
            if exception:
                raise exception
            if Path(argv[0]).name == 'claude':
                return subprocess.CompletedProcess(argv, claude_code, claude_output, 'fixture-auth-secret')
            return subprocess.CompletedProcess(argv, codex_code, 'fixture-auth-secret', 'fixture-auth-secret')
        before = self.files()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(runtime.subprocess, 'run', side_effect=auth) as calls, \
             patch.object(runtime, 'run_process') as generation, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = policy.preflight()
        self.assertFalse(result['generation_tested'])
        self.assertNotIn('fixture-auth-secret', json.dumps(result) + stdout.getvalue() + stderr.getvalue())
        self.assertEqual('', stdout.getvalue() + stderr.getvalue())
        self.assertEqual(before, self.files())
        generation.assert_not_called()
        self.assertEqual(2, calls.call_count)
        self.assertEqual(['auth', 'status', '--json'], calls.call_args_list[0].args[0][1:])
        self.assertEqual(['login', 'status'], calls.call_args_list[1].args[0][1:])
        for call in calls.call_args_list:
            self.assertEqual(10, call.kwargs['timeout'])
            self.assertTrue(call.kwargs['capture_output'])
        return result

    def test_preflight_missing_binaries_skips_auth_and_generation(self):
        before = self.files()
        with patch.object(runtime.shutil, 'which', return_value=None), \
             patch.object(runtime.subprocess, 'run') as auth, \
             patch.object(runtime, 'run_process') as generation:
            result = policy.preflight()
        self.assertEqual('NEEDS_PROVIDER', result['status'])
        self.assertEqual({name: {'binary_found': False, 'authenticated': False}
                          for name in runtime.PROVIDERS}, result['providers'])
        self.assertFalse(result['generation_tested'])
        auth.assert_not_called()
        generation.assert_not_called()
        self.assertEqual(before, self.files())

    def test_preflight_auth_status_is_truthful_and_never_exposes_auth_output(self):
        self.assertEqual('AVAILABLE', self.preflight_result('{"loggedIn":true,"token":"fixture-auth-secret"}')['status'])
        for output in ('not-json fixture-auth-secret', '[]', 'null', 'false', '123',
                       '"fixture-auth-secret"', '{}', '{"loggedIn":false}',
                       '{"loggedIn":"true"}', '{"loggedIn":1}'):
            with self.subTest(output=output):
                result = self.preflight_result(output)
                self.assertEqual('NEEDS_PROVIDER', result['status'])
                self.assertFalse(result['providers']['claude']['authenticated'])
                self.assertTrue(result['providers']['codex']['authenticated'])
        for failed in runtime.PROVIDERS:
            result = self.preflight_result('{"loggedIn":true}', claude_code=int(failed == 'claude'),
                                           codex_code=int(failed == 'codex'))
            self.assertEqual('NEEDS_PROVIDER', result['status'])
            self.assertFalse(result['providers'][failed]['authenticated'])

    def test_preflight_launch_errors_and_timeouts_do_not_leak_auth_details(self):
        for exception in (OSError('fixture-auth-secret'),
                          subprocess.TimeoutExpired(['auth', 'status'], 10, output='fixture-auth-secret')):
            with self.subTest(error=type(exception).__name__):
                result = self.preflight_result('', exception=exception)
                self.assertEqual('NEEDS_PROVIDER', result['status'])
                self.assertTrue(all(entry['binary_found'] and not entry['authenticated']
                                    for entry in result['providers'].values()))

    def test_expired_ready_and_reviewed_status_resume_refresh_preserve_history(self):
        for layer in ('transport', 'policy'):
            for reviewed in (False, True):
                with self.subTest(layer=layer, reviewed=reviewed):
                    self.run = self.root / (layer + str(reviewed))
                    if layer == 'policy':
                        self.initialize()
                    else:
                        runtime.create_run(self.request, self.run)
                    if reviewed:
                        (policy.do_review(self.run, 'review') if layer == 'policy' else runtime.invoke(self.run))
                    # The first locked transport operation may create its empty
                    # lock file; request/evidence/history files must stay exact.
                    with runtime.run_lock(self.run):
                        pass
                    before = self.files(self.run)
                    state = self.state()
                    self.assertEqual('REVIEWED' if reviewed else 'READY', state['status'])
                    (self.source / 'new-evidence.txt').write_text('independently recorded extra evidence')
                    with patch.object(runtime.time, 'time', return_value=state['deadline'] + 1), \
                         patch.object(runtime, 'run_process') as generation:
                        self.assertEqual('UNRESOLVED_BUDGET', runtime.transport_status(self.run)['status'])
                        if layer == 'policy':
                            self.assertEqual('UNRESOLVED_BUDGET', policy.status(self.run)['status'])
                            self.assertFalse(policy.status(self.run)['execution_ready'])
                        api = policy if layer == 'policy' else runtime
                        self.fail_review('UNRESOLVED_BUDGET', lambda: api.resume(self.run))
                        self.fail_review('UNRESOLVED_BUDGET', lambda: api.refresh(self.run, add_evidence=['new-evidence.txt']))
                        generation.assert_not_called()
                    self.assertEqual(before, self.files(self.run))
                    self.assertEqual(state, self.state())

    def test_stop_expired_run_preserves_reports_and_cannot_approve_or_restart(self):
        self.initialize()
        policy.do_review(self.run, 'review')
        before = self.state()
        reports = {path.name: path.read_bytes() for path in self.run.glob('report-*.json')}
        with patch.object(runtime.time, 'time', return_value=before['deadline'] + 1), \
             patch.object(runtime, 'run_process') as generation:
            result = policy.stop(self.run, {'reason': 'Optional review exhausted its original deadline.'})
            self.assertEqual('STOPPED', result['status'])
            self.assertFalse(result['execution_ready'])
            self.assertEqual('STOPPED', runtime.transport_status(self.run)['status'])
            for action in (lambda: policy.resume(self.run), lambda: policy.finish(self.run),
                           lambda: policy.acknowledge(self.run), lambda: policy.advance(self.run),
                           lambda: policy.do_review(self.run, 'review'),
                           lambda: policy.do_review(self.run, 'critic'), lambda: policy.refresh(self.run),
                           lambda: runtime.resume(self.run), lambda: runtime.refresh(self.run),
                           lambda: runtime.invoke(self.run)):
                self.fail_review('STOPPED', action)
            generation.assert_not_called()
        after = self.state()
        for key in ('calls', 'invocations', 'deadline', 'handoff', 'request_sha256', 'snapshot_sha256'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(reports, {path.name: path.read_bytes() for path in self.run.glob('report-*.json')})
        self.assertIsNone(after['policy']['receipt'])
        self.assertFalse(after['policy']['acks'])
        self.assertEqual('STOPPED', policy.status(self.run)['status'])

    def test_third_identical_failed_request_is_unspent_and_never_launched(self):
        runtime.create_run(self.request, self.run)
        self.scenario({'raw': 'malformed provider response'})
        with patch.object(runtime, 'run_process', wraps=runtime.run_process) as generation:
            for _ in range(2):
                self.fail_review('INVALID_RESULT', lambda: runtime.invoke(self.run))
                runtime.resume(self.run)
            before = self.state()
            self.fail_review('UNRESOLVED_DISPUTE', lambda: runtime.invoke(self.run))
        self.assertEqual(2, generation.call_count)
        self.assertEqual(2, self.state()['invocations'])
        self.assertEqual(before['calls'], self.state()['calls'])
        self.assertEqual(before['deadline'], self.state()['deadline'])
        self.assertEqual(1, len({call['request_fingerprint'] for call in before['calls']}))
        self.assertFalse(list(self.run.glob('report-*.json')))

    def test_failed_critic_and_rebuttal_attempts_spend_shared_stage_exchanges(self):
        self.initialize()
        policy.do_review(self.run, 'review')
        initial = copy.deepcopy(self.state())
        self.scenario({'raw': 'malformed provider response'})
        with patch.object(runtime, 'run_process', wraps=runtime.run_process) as generation:
            for number, action in enumerate(('critic', 'rebuttal', 'critic'), start=1):
                self.fail_review('INVALID_RESULT', lambda action=action: policy.do_review(self.run, action))
                self.assertEqual(number, policy.status(self.run)['current_stage']['exchanges'])
                self.assertEqual(number + 1, self.state()['invocations'])
                policy.resume(self.run)
            before = self.state()
            self.fail_review('UNRESOLVED_DISPUTE', lambda: policy.do_review(self.run, 'rebuttal'))
        self.assertEqual(3, generation.call_count)
        self.assertEqual(3, policy.status(self.run)['current_stage']['exchanges'])
        self.assertEqual(before['calls'], self.state()['calls'])
        self.assertEqual(initial['deadline'], self.state()['deadline'])
        self.assertEqual(1, len(list(self.run.glob('report-*.json'))))

    def prepare_prompt_size(self, size, context=None):
        """Measure real serialization overhead, then fill with unescaped UTF-8."""
        (self.source / 'artifact.py').write_text('', encoding='utf-8')
        calibration = self.root / 'calibration'
        runtime.create_run(self.request, calibration)
        with patch.object(runtime, 'run_process', wraps=runtime.run_process) as generation:
            runtime.invoke(calibration, context_data=context)
        overhead = len(generation.call_args.args[1].encode('utf-8'))
        payload_bytes = size - overhead
        self.assertGreater(payload_bytes, 0)
        content = '\U0001f33f' * (payload_bytes // 4) + 'x' * (payload_bytes % 4)
        (self.source / 'artifact.py').write_text(content, encoding='utf-8')
        runtime.create_run(self.request, self.run)

    def test_exact_96000_utf8_prompt_bytes_are_admitted_and_measured(self):
        self.prepare_prompt_size(96_000)
        with patch.object(runtime, 'run_process', wraps=runtime.run_process) as generation:
            report = runtime.invoke(self.run)
        prompt = generation.call_args.args[1]
        self.assertEqual(96_000, len(prompt.encode('utf-8')))
        self.assertLess(len(prompt), 96_000)
        self.assertEqual(96_000, self.state()['calls'][0]['prompt_bytes'])
        self.assertEqual(96_000, report['resources']['prompt_bytes'])
        self.assertEqual(96_000, report['resources']['total_prompt_bytes'])
        self.assertEqual(384_000, report['resources']['max_total_prompt_bytes'])

    def test_96001_utf8_prompt_bytes_fail_before_admission_or_launch(self):
        self.prepare_prompt_size(96_001)
        before = self.state()
        with patch.object(runtime, 'run_process') as generation:
            self.fail_review('UNRESOLVED_BUDGET', lambda: runtime.invoke(self.run))
        generation.assert_not_called()
        self.assertEqual(0, self.state()['invocations'])
        self.assertEqual(before['calls'], self.state()['calls'])
        self.assertEqual(before['deadline'], self.state()['deadline'])
        self.assertFalse(list(self.run.glob('report-*.json')))

    def test_cumulative_384000_input_bytes_count_failed_calls_and_block_next_launch(self):
        self.prepare_prompt_size(96_000, context='{"round":"A"}')
        with patch.object(runtime, 'run_process', wraps=runtime.run_process) as generation:
            for number, label in enumerate('ABCD'):
                self.scenario({'raw': 'malformed response'} if label == 'B' else {})
                if label == 'B':
                    self.fail_review('INVALID_RESULT', lambda: runtime.invoke(self.run, context_data='{"round":"B"}'))
                    runtime.resume(self.run)
                else:
                    report = runtime.invoke(self.run, context_data='{"round":"' + label + '"}')
                    self.assertEqual((number + 1) * 96_000, report['resources']['total_prompt_bytes'])
            before = copy.deepcopy(self.state())
            self.fail_review('UNRESOLVED_BUDGET', lambda: runtime.invoke(self.run, context_data='{"round":"E"}'))
        self.assertEqual(4, generation.call_count)
        self.assertEqual([96_000] * 4, [len(call.args[1].encode('utf-8')) for call in generation.call_args_list])
        self.assertEqual(384_000, runtime.prompt_spend(self.state()))
        self.assertEqual(4, self.state()['invocations'])
        self.assertEqual('INVALID_RESULT', self.state()['calls'][1]['status'])
        self.assertEqual(before['calls'], self.state()['calls'])
        self.assertEqual(before['deadline'], self.state()['deadline'])
        self.assertEqual(3, len(list(self.run.glob('report-*.json'))))

    def test_unmetered_legacy_calls_do_not_become_free_input_budget(self):
        runtime.create_run(self.request, self.run)
        runtime.invoke(self.run)
        state = self.state()
        state['calls'][0].pop('prompt_bytes')
        runtime.save(self.run / 'state.json', state)
        before = copy.deepcopy(state['calls'])
        with patch.object(runtime, 'run_process') as generation:
            self.fail_review('UNRESOLVED_BUDGET', lambda: runtime.invoke(self.run, context_data='{"new":true}'))
        generation.assert_not_called()
        self.assertEqual(before, self.state()['calls'])
        self.assertEqual(1, self.state()['invocations'])
        self.assertEqual(1, len(list(self.run.glob('report-*.json'))))

    def test_default_limits_apply_to_plan_and_work_without_mutating_request(self):
        self.request.pop('limits')
        for workflow in ('plan', 'work'):
            with self.subTest(workflow=workflow):
                self.request['workflow'] = workflow
                before = copy.deepcopy(self.request)
                self.run = self.root / ('defaults-' + workflow)
                with patch.object(runtime.time, 'time', return_value=1000):
                    state = runtime.create_run(self.request, self.run)
                self.assertEqual({'max_invocations': 8, 'invocation_seconds': 120, 'total_seconds': 900},
                                 runtime.load(self.run)[0]['limits'])
                self.assertEqual(1900, state['deadline'])
                self.assertEqual(before, self.request)
                self.assertEqual(0, state['invocations'])


if __name__ == '__main__':
    unittest.main()
