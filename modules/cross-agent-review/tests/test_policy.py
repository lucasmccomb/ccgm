import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_runtime as fixtures
MODULE, import_file = fixtures.MODULE, fixtures.import_file

policy = import_file(MODULE / 'skills/cross-agent-review/scripts/review_policy.py', 'policy')


class PolicyTests(unittest.TestCase):
    scenario = fixtures.RuntimeTests.scenario
    # Reuse only isolated fixture construction/helpers, not the runtime test cases.
    def setUp(self):
        fixtures.RuntimeTests.setUp(self)
        self.request['limits'] = {'max_invocations': 24, 'invocation_seconds': 2, 'total_seconds': 120}

    def initialize(self, mode='plan', count=1, report_only=False, light=False):
        self.request['workflow'] = 'plan' if mode == 'plan' else 'work'
        self.request['adversarial_review_count'] = count
        return policy.initialize(self.request, self.run, mode, {'required': [] if report_only else ['unit']},
                                 'author-session', light_review=light, report_only=report_only)

    def fail_policy(self, status, function):
        with self.assertRaises(policy.rt.ReviewError) as caught:
            function()
        self.assertEqual(status, caught.exception.status)

    def check(self, outcome=0):
        _, state, bundle = policy.rt.load(self.run)
        value = {'name': 'unit', 'argv': ['python3', '-m', 'unittest'], 'exit_code': outcome,
                 'output': 'Ran independent fixture assertion: pass' if not outcome else 'FAILED',
                 'started_at': state['created_at'], 'finished_at': time.time(), **policy.stamp(bundle)}
        return policy.record_check(self.run, value)

    def deliver(self):
        packet = policy.status(self.run)['handoff']
        receipt = {key: packet[key] for key in ('origin_provider', 'origin_session_id', 'artifact_sha256',
                                               'evidence_sha256', 'handoff_sha256', 'nonce')}
        policy.receive(self.run, receipt)
        return policy.finish(self.run)

    def review_advance(self):
        policy.do_review(self.run, 'review')
        return policy.advance(self.run)

    def seed(self):
        finding = {'id': 'ADD-1', 'severity': 'high', 'requirement': 'spec.md: addition',
                   'evidence': [{'path': 'artifact.py', 'quote': 'return a - b'}], 'remedy': 'Use addition.'}
        self.scenario({'findings': [finding]})
        policy.do_review(self.run, 'review')
        self.scenario({})
        return finding

    def discovery(self, requirement, local_id='F1'):
        return {'id': local_id, 'severity': 'low', 'requirement': requirement,
                'evidence': [{'path': 'artifact.py', 'quote': 'def add'}], 'remedy': 'Check ' + requirement}

    def refute_open(self):
        findings = policy.status(self.run)['findings']
        policy.propose(self.run, {'dispositions': [
            {'finding_id': fid, 'disposition': 'refuted', 'rationale': 'Evidence-backed refutation fixture.',
             'evidence': [{'path': 'spec.md', 'quote': 'two integers'}]}
            for fid, row in findings.items() if row['state'] != 'CLOSED']})

    def test_selection_pending_explicit_interactive_unattended_resume_no_writes(self):
        before = set(self.root.rglob('*'))
        self.assertEqual('NEEDS_SELECTION', policy.selection()['status'])
        self.assertEqual(1, policy.selection()['recommended'])
        self.assertEqual('unattended-default', policy.selection(unattended=True)['review_count_source'])
        self.assertEqual(3, policy.selection('3')['adversarial_review_count'])
        self.assertEqual('interactive', policy.selection(2, 'interactive')['review_count_source'])
        self.assertEqual(before, set(self.root.rglob('*')))
        for value in ('', '0', 0, 4, '1.0', True, 'auto'):
            self.fail_policy('INVALID_REQUEST', lambda value=value: policy.selection(value))
        self.initialize(count=2)
        before = {p: p.stat().st_mtime_ns for p in self.run.rglob('*')}
        self.assertEqual(2, policy.selection(resume_dir=self.run)['adversarial_review_count'])
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.run.rglob('*')})

    def test_startup_cli_rejects_contradictory_missing_and_invalid_without_mkdir(self):
        script = MODULE / 'lib/cross_agent_review_policy.py'
        for args in (['--count', '2', '--count', '3'], ['--count'], ['--count', '0']):
            result = subprocess.run([sys.executable, str(script), 'select', *args],
                                    cwd=self.source, capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
            self.assertFalse(self.run.exists())
        result = subprocess.run([sys.executable, str(script), 'select'], cwd=self.source,
                                capture_output=True, text=True, check=True)
        self.assertEqual('NEEDS_SELECTION', json.loads(result.stdout)['status'])

    def test_six_sequences_exact_count_current_reports_fresh_sessions_and_handback(self):
        for origin in policy.rt.PROVIDERS:
            for count in (1, 2, 3):
                with self.subTest(origin=origin, count=count):
                    self.run = self.root / (origin + str(count))
                    self.request['origin_provider'] = self.request['producer_provider'] = origin
                    self.request['provenance'][0]['provider'] = origin
                    self.initialize(count=count)
                    self.check()
                    seen = []
                    for number in range(1, count + 1):
                        current = policy.status(self.run)['current_stage']
                        self.assertEqual(number == count, current['is_final'])
                        result = policy.do_review(self.run, 'review')
                        seen.append(result['result']['provider'])
                        policy.advance(self.run)
                    self.assertEqual([policy.rt.opposite(origin), origin, policy.rt.opposite(origin)][:count], seen)
                    self.fail_policy('HANDOFF_PENDING', lambda: policy.finish(self.run))
                    policy.acknowledge(self.run)
                    self.fail_policy('HANDOFF_PENDING', lambda: policy.finish(self.run))
                    result = self.deliver()
                    self.assertTrue(result['execution_ready'])
                    self.assertEqual('CONSENSUS', result['status'])
                    _, state, _ = policy.rt.load(self.run)
                    self.assertEqual(count, len(state['policy']['stages']))
                    self.assertEqual(count + 2, state['invocations'])
                    self.assertEqual(len(state['policy']['sessions']), len(set(state['policy']['sessions'])))

    def test_work_spec_quality_actual_producer_and_mixed_both_perspectives(self):
        for producer in ('claude', 'codex', 'mixed', 'unknown'):
            self.run = self.root / ('work-' + producer)
            self.request['origin_provider'] = 'claude'
            self.request['producer_provider'] = producer
            self.request['provenance'][0]['provider'] = producer if producer in policy.rt.PROVIDERS else 'unknown'
            self.initialize(mode='etp')
            self.check()
            expected = ['spec', 'quality'] if producer in policy.rt.PROVIDERS else ['spec-claude', 'spec-codex', 'quality-claude', 'quality-codex']
            providers = []
            for key in expected:
                self.assertEqual(key, policy.status(self.run)['current_stage']['key'])
                result = policy.do_review(self.run, 'review')
                providers.append(result['result']['provider'])
                policy.advance(self.run)
            if producer in policy.rt.PROVIDERS:
                self.assertEqual([policy.rt.opposite(producer)] * 2, providers)
            else:
                self.assertEqual(['claude', 'codex', 'claude', 'codex'], providers)
            policy.acknowledge(self.run)
            self.assertEqual('CONSENSUS', self.deliver()['status'])

    def test_delegated_plan_preserves_origin_schedule_actual_writer_and_opposite_ack(self):
        self.request['origin_provider'] = 'claude'
        self.initialize(count=3)  # Actual producer remains Codex.
        self.assertEqual('codex', policy.rt.load(self.run)[1]['policy']['writer_provider'])
        self.check()
        seen = []
        for _ in range(3):
            seen.append(policy.do_review(self.run, 'review')['result']['provider'])
            policy.advance(self.run)
        self.assertEqual(['codex', 'claude', 'codex'], seen)
        policy.acknowledge(self.run)
        state = policy.rt.load(self.run)[1]
        self.assertEqual({'claude', 'codex'}, set(state['policy']['acks']))
        self.assertEqual('claude', policy.status(self.run)['handoff']['origin_provider'])
        self.assertEqual('CONSENSUS', self.deliver()['status'])

    def test_light_review_is_explicit_spec_only(self):
        self.initialize(mode='etp', light=True)
        self.assertEqual(1, policy.status(self.run)['total_stages'])
        self.assertEqual('spec', policy.status(self.run)['current_stage']['key'])

    def test_etp_native_ack_can_cite_exact_recorded_check_context(self):
        self.initialize(mode='etp')
        self.check()
        self.review_advance()
        self.review_advance()
        self.scenario({'payload': {'verification': [{'check': 'unit', 'outcome': 'pass', 'evidence': [
            {'path': policy.rt.CONTEXT_EVIDENCE_PATH, 'quote': 'Ran independent fixture assertion: pass'}]}]}})
        policy.acknowledge(self.run)
        self.assertEqual('CONSENSUS', self.deliver()['status'])

    def test_missing_or_failed_required_check_blocks_advance_and_final_ack(self):
        self.initialize()
        policy.do_review(self.run, 'review')
        self.fail_policy('NEEDS_CHECKS', lambda: policy.advance(self.run))
        self.check(outcome=1)
        self.fail_policy('NEEDS_CHECKS', lambda: policy.acknowledge(self.run))
        self.check()
        policy.advance(self.run)
        policy.acknowledge(self.run)
        self.assertEqual('CONSENSUS', self.deliver()['status'])

    def test_report_only_delivers_findings_without_claiming_consensus_or_apply(self):
        self.initialize(mode='adrev', report_only=True)
        self.seed()
        self.fail_policy('INVALID_REQUEST', lambda: policy.fix(self.run, {
            'writer_provider': 'codex', 'writer_session_id': 'author-session', 'finding_ids': ['plan-1:claude:ADD-1'],
            'reason': 'Fix', 'next_check': 'unit'}))
        policy.advance(self.run)
        result = self.deliver()
        self.assertEqual('REPORT_DELIVERED', result['status'])
        self.assertFalse(result['execution_ready'])
        self.assertEqual('OPEN', result['findings']['adrev:claude:ADD-1']['state'])

    def test_valid_finding_critic_fix_current_revalidation_and_two_provider_closure(self):
        self.initialize()
        self.seed()
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.advance(self.run))
        self.scenario({'critic_verdict': 'AGREE'})
        policy.do_review(self.run, 'critic')
        ticket = policy.fix(self.run, {'writer_provider': 'codex', 'writer_session_id': 'author-session',
                                       'finding_ids': ['plan-1:claude:ADD-1'], 'reason': 'Correct subtraction', 'next_check': 'unit'})
        self.assertEqual(3, ticket['number'])
        (self.source / 'artifact.py').write_text('def add(a,b): return a + b\n')
        policy.refresh(self.run)
        policy.propose(self.run, {'dispositions': [{'finding_id': 'plan-1:claude:ADD-1', 'disposition': 'fixed',
                                                  'rationale': 'Now adds the inputs.',
                                                  'evidence': [{'path': 'artifact.py', 'quote': 'return a + b'}]}]})
        self.check()
        self.scenario({})
        policy.do_review(self.run, 'review')
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.advance(self.run))
        policy.acknowledge(self.run)
        policy.advance(self.run)
        policy.acknowledge(self.run)
        result = self.deliver()
        self.assertEqual('CONSENSUS', result['status'])
        self.assertEqual('CLOSED', result['findings']['plan-1:claude:ADD-1']['state'])
        self.assertEqual(1, result['fix_rounds'])
        self.assertEqual(6, result['invocations'])

    def test_refuted_finding_needs_native_mutual_support_not_manual_proposal(self):
        self.initialize()
        self.seed()
        self.check()
        policy.propose(self.run, {'dispositions': [{'finding_id': 'plan-1:claude:ADD-1', 'disposition': 'refuted',
                                                  'rationale': 'Fixture intentionally demonstrates a refutation flow.',
                                                  'evidence': [{'path': 'spec.md', 'quote': 'two integers'}]}]})
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.advance(self.run))
        self.scenario({'payload': {'status': 'NEEDS_EVIDENCE', 'evidence_requests': ['Provide a discriminating test.']}})
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.acknowledge(self.run))
        self.scenario({})
        policy.acknowledge(self.run)
        policy.advance(self.run)
        policy.acknowledge(self.run)
        self.assertEqual('CONSENSUS', self.deliver()['status'])

    def test_no_manual_provider_ack_and_wrong_origin_receipt_rejected(self):
        self.initialize()
        self.check()
        self.review_advance()
        self.fail_policy('HANDOFF_PENDING', lambda: policy.finish(self.run))
        policy.acknowledge(self.run)
        packet = policy.status(self.run)['handoff']
        value = {key: packet[key] for key in ('origin_provider', 'origin_session_id', 'artifact_sha256',
                                             'evidence_sha256', 'handoff_sha256', 'nonce')}
        value['origin_session_id'] = 'different-host'
        self.fail_policy('INVALID_REQUEST', lambda: policy.receive(self.run, value))
        self.assertFalse(policy.status(self.run)['execution_ready'])

    def test_outside_scope_proposal_cannot_override_supported_native_objection(self):
        self.initialize()
        self.seed()
        self.check()
        policy.propose(self.run, {'dispositions': [{'finding_id': 'plan-1:claude:ADD-1', 'disposition': 'outside_scope',
                                                  'rationale': 'Author wants to skip it.',
                                                  'evidence': [{'path': 'spec.md', 'quote': 'return the sum'}]}]})
        self.scenario({'critic_verdict': 'DISAGREE_EVIDENCE'})
        self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
        self.assertNotEqual('CLOSED', policy.status(self.run)['findings']['plan-1:claude:ADD-1']['state'])

    def test_no_progress_and_five_exchange_limits_hold(self):
        self.initialize()
        self.seed()
        self.scenario({'critic_verdict': 'AGREE'})
        for _ in range(3):
            policy.do_review(self.run, 'critic')
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.do_review(self.run, 'critic'))
        self.check()
        for _ in range(2):
            policy.do_review(self.run, 'critic')
        self.check()
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.do_review(self.run, 'critic'))

    def test_repeated_identical_check_with_new_timestamp_is_not_new_evidence(self):
        self.initialize()
        self.seed()
        self.check()
        self.scenario({'critic_verdict': 'AGREE'})
        for _ in range(3):
            policy.do_review(self.run, 'critic')
        self.check()
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.do_review(self.run, 'critic'))

    def test_acknowledgment_pairs_are_subject_to_five_exchange_cap(self):
        self.initialize()
        self.check()
        policy.do_review(self.run, 'review')
        _, state, _ = policy.rt.load(self.run)
        policy.current_stage(state['policy'])['exchanges'] = 5
        policy.persist(self.run, state)
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.acknowledge(self.run))

    def test_changed_artifact_invalidates_completed_pass_and_ack(self):
        self.initialize(count=2)
        self.check()
        self.review_advance()
        (self.source / 'artifact.py').write_text('changed outside designated writer admission')
        self.fail_policy('STALE_ARTIFACT', lambda: policy.finish(self.run))
        self.fail_policy('INVALID_REQUEST', lambda: policy.refresh(self.run))

    def test_status_never_reports_stale_consensus_execution_ready(self):
        self.initialize()
        self.check()
        self.review_advance()
        policy.acknowledge(self.run)
        self.assertTrue(self.deliver()['execution_ready'])
        (self.source / 'artifact.py').write_text('material user edit after closure')
        result = policy.status(self.run)
        self.assertFalse(result['execution_ready'])
        self.assertEqual('STALE_ARTIFACT', result['status'])

    def test_budget_and_resume_preserve_deadline_and_counter(self):
        self.request['limits']['max_invocations'] = 1
        self.initialize()
        self.check()
        self.review_advance()
        before = policy.status(self.run)
        self.fail_policy('UNRESOLVED_BUDGET', lambda: policy.acknowledge(self.run))
        self.fail_policy('UNRESOLVED_BUDGET', lambda: policy.resume(self.run))
        after = policy.status(self.run)
        self.assertEqual(before['deadline'], after['deadline'])
        self.assertEqual(1, after['invocations'])

    def test_independent_passes_can_discover_different_findings_with_same_raw_id(self):
        self.initialize(count=2)
        self.seed()
        self.check()
        policy.propose(self.run, {'dispositions': [{'finding_id': 'plan-1:claude:ADD-1', 'disposition': 'refuted',
                                                  'rationale': 'Evidence-backed refutation fixture.',
                                                  'evidence': [{'path': 'spec.md', 'quote': 'two integers'}]}]})
        policy.acknowledge(self.run)
        policy.advance(self.run)
        self.scenario({'findings': [{'id': 'ADD-1', 'severity': 'medium', 'requirement': 'A separate requirement',
                                    'evidence': [{'path': 'artifact.py', 'quote': 'def add'}], 'remedy': 'Another fix'}]})
        policy.do_review(self.run, 'review')
        self.assertEqual({'plan-1:claude:ADD-1', 'plan-2:codex:ADD-1'}, set(policy.status(self.run)['findings']))

    def test_critic_and_rebuttal_discoveries_can_share_local_id_without_collision(self):
        self.initialize()
        policy.do_review(self.run, 'review')
        self.scenario({'findings': [self.discovery('Requirement A')]})
        critic = policy.do_review(self.run, 'critic')
        self.scenario({'findings': [self.discovery('Requirement B')], 'critic_verdict': 'DISAGREE_EVIDENCE'})
        rebuttal = policy.do_review(self.run, 'rebuttal')
        self.assertEqual(('codex', 'claude'), (critic['result']['provider'], rebuttal['result']['provider']))
        findings = policy.status(self.run)['findings']
        self.assertEqual({'plan-1:codex:F1', 'plan-1:claude:F1'}, set(findings))
        self.assertEqual('Requirement A', findings['plan-1:codex:F1']['finding']['requirement'])
        self.assertEqual('Requirement B', findings['plan-1:claude:F1']['finding']['requirement'])
        self.assertEqual('DISAGREE_EVIDENCE', findings['plan-1:codex:F1']['verdicts']['claude']['verdict']['verdict'])

    def test_revalidation_discoveries_in_separate_stages_use_stage_scope(self):
        self.initialize(count=2)
        self.check()
        self.review_advance()
        self.review_advance()
        policy.amend(self.run, {'writer_provider': 'codex', 'writer_session_id': 'author-session',
                               'reason': 'Explicit user clarification', 'next_check': 'unit',
                               'authorization': 'explicit-user-update'})
        (self.source / 'artifact.py').write_text('def add(a,b): return a + b\n')
        policy.refresh(self.run)
        self.check()
        self.scenario({'findings': [self.discovery('Requirement A')]})
        policy.do_review(self.run, 'review')
        self.refute_open()
        self.scenario({})
        policy.acknowledge(self.run)
        policy.advance(self.run)
        self.scenario({'findings': [self.discovery('Requirement B')]})
        policy.do_review(self.run, 'review')
        self.assertEqual({'plan-1:claude:F1', 'plan-2:codex:F1'}, set(policy.status(self.run)['findings']))
        history = policy.rt.load(self.run)[1]['policy']['history']
        self.assertEqual(['plan-1', 'plan-2'], [row['stage'] for row in history if row['purpose'] == 'revalidation'])

    def test_same_provider_after_fix_discovers_distinct_local_id_with_report_suffix(self):
        self.initialize()
        self.scenario({'findings': [self.discovery('Requirement A')]})
        policy.do_review(self.run, 'review')
        self.scenario({'critic_verdict': 'AGREE'})
        policy.do_review(self.run, 'critic')
        policy.fix(self.run, {'writer_provider': 'codex', 'writer_session_id': 'author-session',
                              'finding_ids': ['plan-1:claude:F1'], 'reason': 'Correct addition', 'next_check': 'unit'})
        (self.source / 'artifact.py').write_text('def add(a,b): return a + b\n')
        policy.refresh(self.run)
        self.scenario({'findings': [self.discovery('Requirement B')]})
        result = policy.do_review(self.run, 'review')
        findings = policy.status(self.run)['findings']
        second_id = 'plan-1:claude:F1:' + result['report']
        self.assertEqual({'plan-1:claude:F1', second_id}, set(findings))
        self.assertEqual('Requirement A', findings['plan-1:claude:F1']['finding']['requirement'])
        self.assertEqual('Requirement B', findings[second_id]['finding']['requirement'])
        self.assertEqual(1, len(findings['plan-1:claude:F1']['observations']))
        # A new local spelling can itself equal an occupied report suffix.
        self.scenario({'findings': [self.discovery('Requirement C', 'F1:' + result['report'])]})
        rebuttal = policy.do_review(self.run, 'rebuttal')
        third_id = second_id + ':' + rebuttal['report']
        self.assertEqual({*findings, third_id}, set(policy.status(self.run)['findings']))

    def test_native_ack_discoveries_are_scoped_and_remain_unresolved(self):
        self.initialize()
        self.check()
        self.review_advance()
        for requirement in ('Requirement A', 'Requirement B'):
            if policy.status(self.run)['findings']:
                self.refute_open()
            self.scenario({'findings': [self.discovery(requirement)]})
            self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.acknowledge(self.run))
        findings = policy.status(self.run)['findings']
        self.assertEqual({'plan-1:claude:F1', 'plan-1:claude:F1:report-003.json'}, set(findings))
        self.assertEqual({'Requirement A', 'Requirement B'}, {row['finding']['requirement'] for row in findings.values()})
        self.assertTrue(all(row['state'] != 'CLOSED' for row in findings.values()))
        self.assertFalse(policy.status(self.run)['execution_ready'])

    def test_discovery_suffix_cannot_overwrite_an_existing_suffix_shaped_local_id(self):
        self.initialize()
        self.scenario({'findings': [self.discovery('Requirement A'),
                                    self.discovery('Requirement B', 'F1:report-002.json')]})
        policy.do_review(self.run, 'review')
        self.scenario({'findings': [self.discovery('Requirement C')]})
        policy.do_review(self.run, 'rebuttal')
        findings = policy.status(self.run)['findings']
        self.assertEqual({'plan-1:claude:F1', 'plan-1:claude:F1:report-002.json',
                          'plan-1:claude:F1:report-002.json:2'}, set(findings))
        self.assertEqual({'Requirement A', 'Requirement B', 'Requirement C'},
                         {row['finding']['requirement'] for row in findings.values()})

    def test_exact_global_ids_keep_identity_but_cannot_change_requirement(self):
        self.initialize()
        finding = self.seed()
        fid = 'plan-1:claude:ADD-1'
        for action in ('critic', 'rebuttal'):
            self.scenario({'findings': [{**finding, 'id': fid}]})
            policy.do_review(self.run, action)
            self.assertEqual({fid}, set(policy.status(self.run)['findings']))
        before = policy.status(self.run)['findings']
        self.assertEqual(3, len(before[fid]['observations']))
        self.scenario({'findings': [{**finding, 'id': fid, 'requirement': 'An unrelated requirement'}]})
        self.fail_policy('INVALID_RESULT', lambda: policy.do_review(self.run, 'rebuttal'))
        self.assertEqual(before, policy.status(self.run)['findings'])

    def test_rebuttal_routes_to_reviewer_and_preserves_exchange_admission_limits(self):
        self.initialize()
        self.fail_policy('INVALID_REQUEST', lambda: policy.do_review(self.run, 'rebuttal'))
        self.assertEqual(0, policy.status(self.run)['invocations'])
        self.seed()
        self.scenario({'critic_verdict': 'DISAGREE_EVIDENCE'})
        critic = policy.do_review(self.run, 'critic')
        self.assertEqual('codex', critic['result']['provider'])
        for expected in (1, 2):
            rebuttal = policy.do_review(self.run, 'rebuttal')
            self.assertEqual('claude', rebuttal['result']['provider'])
            stage = policy.status(self.run)['current_stage']
            self.assertEqual(expected, stage['no_progress'])
            self.assertEqual(expected + 1, stage['exchanges'])
        spent = policy.status(self.run)['invocations']
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.do_review(self.run, 'rebuttal'))
        self.assertEqual(spent, policy.status(self.run)['invocations'])
        self.check()  # A discriminating check permits two remaining exchanges.
        policy.do_review(self.run, 'rebuttal')
        policy.do_review(self.run, 'rebuttal')
        self.check(outcome=1)  # New evidence cannot reset the five-exchange cap.
        spent = policy.status(self.run)['invocations']
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.do_review(self.run, 'rebuttal'))
        self.assertEqual(5, policy.status(self.run)['current_stage']['exchanges'])
        self.assertEqual(spent, policy.status(self.run)['invocations'])

    def test_new_requested_evidence_refreshes_all_selected_pass_records(self):
        self.initialize(count=2)
        self.check()
        self.review_advance()
        (self.source / 'additional.txt').write_text('Independently captured additional evidence')
        state = policy.status(self.run)
        policy.refresh(self.run, ['additional.txt'])
        result = policy.status(self.run)
        self.assertEqual(0, result['completed_stages'])
        self.assertEqual(state['invocations'], result['invocations'])
        self.assertEqual(state['deadline'], result['deadline'])
        self.assertNotEqual(state['evidence_sha256'], result['evidence_sha256'])
        self.assertEqual('additional.txt', policy.rt.load(self.run)[0]['evidence'][-1])

    def test_user_amendment_needs_authorization_preserves_limits_invalidates_acks(self):
        self.initialize()
        self.check()
        self.review_advance()
        policy.acknowledge(self.run)
        before = policy.status(self.run)
        value = {'writer_provider': 'codex', 'writer_session_id': 'author-session', 'reason': 'Explicit user deepen request',
                 'next_check': 'unit', 'authorization': 'explicit-user-update'}
        self.fail_policy('INVALID_REQUEST', lambda: policy.amend(self.run, dict(value, authorization='inferred')))
        ticket = policy.amend(self.run, value)
        self.assertEqual('before-author-dispatch', ticket['accounting'])
        self.assertEqual(before['invocations'] + 1, ticket['number'])
        (self.source / 'artifact.py').write_text('def add(a,b): return a + b\n')
        policy.refresh(self.run)
        after = policy.status(self.run)
        self.assertEqual(0, after['completed_stages'])
        self.assertIsNone(after['handoff'])
        self.assertEqual(before['deadline'], after['deadline'])
        self.assertFalse(after['execution_ready'])

    def test_amendment_cannot_retroactively_admit_untracked_source_drift(self):
        self.initialize()
        self.check()
        self.review_advance()
        before = policy.rt.load(self.run)[1]
        (self.source / 'artifact.py').write_text('def add(a,b): return a + b\n')
        value = {'writer_provider': 'codex', 'writer_session_id': 'author-session',
                 'reason': 'User update', 'next_check': 'unit', 'authorization': 'explicit-user-update'}
        self.fail_policy('STALE_ARTIFACT', lambda: policy.amend(self.run, value))
        self.assertEqual(before, policy.rt.load(self.run)[1])
        self.fail_policy('INVALID_REQUEST', lambda: policy.refresh(self.run))

    def test_stage_ack_reuse_requires_identical_final_check_and_ledger_evidence(self):
        self.initialize()
        self.check()
        policy.do_review(self.run, 'review')
        policy.acknowledge(self.run)
        policy.advance(self.run)
        before = policy.status(self.run)['invocations']
        policy.acknowledge(self.run)
        self.assertEqual(before, policy.status(self.run)['invocations'])
        self.check()  # A new independent check record changes the signed context.
        policy.acknowledge(self.run)
        self.assertEqual(before + 2, policy.status(self.run)['invocations'])

    def test_fix_checkpoint_extensions_need_novel_evidence_and_keep_global_cap(self):
        self.initialize()
        _, state, _ = policy.rt.load(self.run)
        state['policy']['fix_rounds'] = 3
        policy.persist(self.run, state)
        before = policy.status(self.run)
        extension = {'reason': 'A specific discriminating source check is now available', 'next_check': 'unit',
                     'evidence': [{'path': 'artifact.py', 'quote': 'return a - b'}]}
        policy.extend(self.run, extension)
        _, state, _ = policy.rt.load(self.run)
        self.assertEqual(6, state['policy']['fix_allowance'])
        self.assertEqual(before['deadline'], state['deadline'])
        self.assertEqual(before['invocations'], state['invocations'])
        state['policy']['fix_rounds'] = 6
        policy.persist(self.run, state)
        self.fail_policy('INVALID_REQUEST', lambda: policy.extend(self.run, extension))

    def test_payload_paths_are_private_bounded_and_cannot_traverse(self):
        self.initialize()
        for relative in ('../spec.md', str(self.source / 'spec.md')):
            self.fail_policy('INVALID_REQUEST', lambda relative=relative: policy.payload(self.run, relative))
        (self.run / 'alias.json').symlink_to(self.source / 'spec.md')
        self.fail_policy('INVALID_REQUEST', lambda: policy.payload(self.run, 'alias.json'))


if __name__ == '__main__':
    unittest.main()
