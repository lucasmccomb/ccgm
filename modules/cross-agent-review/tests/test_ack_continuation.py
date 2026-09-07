"""Fixture-only continuation regressions; these do not certify provider reasoning."""
import copy
import json
import unittest
from unittest.mock import patch

import test_policy as fixtures

policy = fixtures.policy
rt = policy.rt


class AckContinuationTests(unittest.TestCase):
    setUp = fixtures.PolicyTests.setUp
    initialize = fixtures.PolicyTests.initialize
    scenario = fixtures.PolicyTests.scenario
    check = fixtures.PolicyTests.check
    seed = fixtures.PolicyTests.seed
    refute_open = fixtures.PolicyTests.refute_open
    fail_policy = fixtures.PolicyTests.fail_policy

    def partial(self):
        self.initialize(mode='etp')
        self.seed()
        self.check()
        self.refute_open()
        self.scenario({'payload_by_role': {'critic': {'context_sha256': '0' * 64}}})
        self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
        state = rt.load(self.run)[1]
        self.assertEqual({'claude'}, set(state['policy']['ack_checkpoint']['acks']))
        self.assertEqual({}, state['policy']['acks'])
        self.assertEqual('PROPOSED', state['policy']['findings']['spec:claude:ADD-1']['state'])
        policy.resume(self.run)
        self.scenario({})
        return state

    def test_retry_reuses_only_successful_provider_and_keeps_original_evidence(self):
        before = self.partial()
        original = {p.name: p.read_bytes() for p in self.run.glob('report-*.json')}
        policy.acknowledge(self.run)
        after = rt.load(self.run)[1]
        self.assertEqual(before['invocations'] + 1, after['invocations'])
        self.assertEqual('codex', after['calls'][-1]['provider'])
        self.assertEqual(before['calls'], after['calls'][:-1])
        self.assertEqual(before['deadline'], after['deadline'])
        self.assertEqual(original, {name: (self.run / name).read_bytes() for name in original})
        self.assertEqual('CLOSED', after['policy']['findings']['spec:claude:ADD-1']['state'])

    def test_complete_basis_changes_require_fresh_pair(self):
        for change in ('check', 'required-checks', 'proposal', 'finding', 'observations', 'verdicts',
                       'goal', 'model', 'coordinator'):
            with self.subTest(change=change):
                self.run = self.root / change
                before = self.partial()
                request, state, bundle = rt.load(self.run)
                row = state['policy']['findings']['spec:claude:ADD-1']
                if change == 'check':
                    self.check()  # Even a new timestamp changes the exact evidence basis.
                elif change == 'required-checks':
                    state['policy']['checks']['extra'] = {**state['policy']['checks']['unit'], 'name': 'extra'}
                    state['policy']['required_checks'].append('extra')
                elif change == 'proposal':
                    row['proposal']['rationale'] += ' Additional evidence explanation.'
                elif change == 'finding':
                    row['finding']['remedy'] += ' Include the edge case.'
                elif change == 'observations':
                    row['observations'].append(copy.deepcopy(row['observations'][0]))
                elif change == 'verdicts':
                    row['verdicts']['codex'] = {'verdict': {'finding_id': 'spec:claude:ADD-1',
                        'verdict': 'DISAGREE_EVIDENCE', 'evidence': [{'path': 'spec.md', 'quote': 'two integers'}]},
                        'report': row['observations'][0]['report'], **policy.stamp(bundle)}
                elif change == 'goal':
                    request['goal'] += '; confirm integer edge cases'
                elif change == 'model':
                    request['models']['claude'] = 'fixture-v2'
                if change not in ('check', 'coordinator'):
                    rt.save(self.run / 'request.json', request)
                    policy.persist(self.run, state)
                if change in ('goal', 'model'):
                    # Immutable request identity rejects these changes before reuse.
                    self.fail_policy('INVALID_REQUEST', lambda: policy.acknowledge(self.run))
                    self.assertEqual(before['invocations'], rt.read_json(self.run / 'state.json')['invocations'])
                    continue
                if change == 'coordinator':
                    with patch.object(rt, 'coordinator_revision', return_value='new-implementation'):
                        policy.acknowledge(self.run)
                else:
                    policy.acknowledge(self.run)
                after = rt.load(self.run)[1]
                self.assertEqual(before['invocations'] + 2, after['invocations'])
                self.assertEqual(['claude', 'codex'], [c['provider'] for c in after['calls'][-2:]])
                self.assertEqual(before['deadline'], after['deadline'])

    def test_tampered_accepted_report_or_context_is_rejected_without_dispatch(self):
        for target in ('accepted-report', 'accepted-context', 'selected-report'):
            with self.subTest(target=target):
                self.run = self.root / target
                before = self.partial()
                ack = before['policy']['ack_checkpoint']['acks']['claude']
                call = next(c for c in before['calls'] if c.get('report') == ack['report'])
                if target == 'accepted-context':
                    path = self.run / ('policy-context-' + str(call['number']) + '.json')
                    value = rt.read_json(path)
                    value['criteria'] += ' Forged.'
                else:
                    path = self.run / (ack['report'] if target == 'accepted-report'
                                       else before['policy']['stages'][0]['report'])
                    value = rt.read_json(path)
                    value['result']['summary'] += ' Forged.'
                rt.save(path, value)
                expected = 'INVALID_RESULT' if target == 'accepted-context' else 'INVALID_REQUEST'
                self.fail_policy(expected, lambda: policy.acknowledge(self.run))
                self.assertEqual(before['invocations'], rt.load(self.run)[1]['invocations'])
                self.assertFalse(policy.status(self.run)['execution_ready'])

    def test_finish_rechecks_complete_basis_after_both_acceptances(self):
        self.initialize()
        self.seed()
        self.check()
        self.refute_open()
        policy.acknowledge(self.run)
        policy.advance(self.run)
        policy.acknowledge(self.run)
        packet = policy.status(self.run)['handoff']
        policy.receive(self.run, {key: packet[key] for key in ('origin_provider', 'origin_session_id',
            'artifact_sha256', 'evidence_sha256', 'handoff_sha256', 'nonce')})
        _, state, _ = rt.load(self.run)
        row = state['policy']['findings']['plan-1:claude:ADD-1']
        row['observations'].append(copy.deepcopy(row['observations'][0]))
        policy.persist(self.run, state)
        self.fail_policy('INVALID_RESULT', lambda: policy.finish(self.run))
        self.assertFalse(policy.status(self.run)['execution_ready'])

    def test_substantive_rejection_changes_basis_and_requires_both_providers_again(self):
        self.initialize(mode='etp')
        self.seed()
        self.check()
        self.refute_open()
        fid = 'spec:claude:ADD-1'
        self.scenario({'payload_by_role': {'critic': {'status': 'CLEAN',
            'summary': 'This prose is not acceptance.', 'verdicts': [{
            'finding_id': fid, 'verdict': 'DISAGREE_EVIDENCE',
            'evidence': [{'path': 'spec.md', 'quote': 'two integers'}]}]}}})
        self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
        before = rt.load(self.run)[1]
        rejection = before['policy']['findings'][fid]['verdicts']['codex']
        self.assertEqual('proposed_disposition', rejection['judgment_target'])
        self.assertEqual('DISAGREE_EVIDENCE', rejection['verdict']['verdict'])
        original_report = (self.run / rejection['report']).read_bytes()
        self.scenario({})
        policy.acknowledge(self.run)
        after = rt.load(self.run)[1]
        self.assertEqual(before['invocations'] + 2, after['invocations'])
        self.assertEqual(original_report, (self.run / rejection['report']).read_bytes())
        for call in after['calls'][-2:]:
            context = rt.read_json(self.run / ('policy-context-' + str(call['number']) + '.json'))
            self.assertEqual(rejection, context['findings'][fid]['verdicts']['codex'])

    def test_completed_consensus_cannot_accept_new_checks_or_dispatch(self):
        self.initialize()
        self.check()
        policy.do_review(self.run, 'review')
        policy.advance(self.run)
        policy.acknowledge(self.run)
        packet = policy.status(self.run)['handoff']
        policy.receive(self.run, {key: packet[key] for key in ('origin_provider', 'origin_session_id',
            'artifact_sha256', 'evidence_sha256', 'handoff_sha256', 'nonce')})
        self.assertEqual('CONSENSUS', policy.finish(self.run)['status'])
        before = (self.run / 'state.json').read_bytes()
        for action in (self.check, lambda: rt.invoke(self.run), lambda: policy.refresh(self.run)):
            self.fail_policy('INVALID_REQUEST', action)
        self.assertEqual(before, (self.run / 'state.json').read_bytes())
        self.assertTrue(policy.status(self.run)['execution_ready'])

    def test_expired_interrupted_run_can_stop_after_child_exit_without_rewriting_calls(self):
        self.initialize()
        _, state, _ = rt.load(self.run)
        state['status'] = 'RUNNING'
        state['deadline'] = state['created_at'] - 1
        state['calls'] = [{'number': 1, 'status': 'RUNNING', 'child_pid': 424242}]
        state['invocations'] = 1
        policy.persist(self.run, state)
        with patch.object(rt.os, 'killpg', return_value=None):
            self.fail_policy('BUSY', lambda: policy.stop(self.run, {'reason': 'Abandon interrupted review'}))
        with patch.object(rt.os, 'killpg', side_effect=ProcessLookupError):
            result = policy.stop(self.run, {'reason': 'Abandon interrupted review'})
        self.assertEqual('STOPPED', result['status'])
        self.assertFalse(result['execution_ready'])
        after = rt.load(self.run)[1]
        self.assertEqual(state['calls'], after['calls'])
        self.assertEqual(state['deadline'], after['deadline'])

    def test_repeated_identity_failure_has_no_third_identical_dispatch(self):
        before = self.partial()
        self.scenario({'payload_by_role': {'critic': {'context_sha256': '0' * 64}}})
        self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
        policy.resume(self.run)
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.acknowledge(self.run))
        after = rt.load(self.run)[1]
        self.assertEqual(before['invocations'] + 1, after['invocations'])
        self.assertEqual({'claude'}, set(after['policy']['ack_checkpoint']['acks']))
        self.assertEqual('PROPOSED', after['policy']['findings']['spec:claude:ADD-1']['state'])
        self.assertFalse(policy.status(self.run)['execution_ready'])


if __name__ == '__main__':
    unittest.main()
