"""Explicit native-envelope answers exercise disposition gates, never model reasoning."""
import json
import unittest

import test_policy as fixtures

policy = fixtures.policy
runtime = policy.rt


class AcknowledgmentDispositionTests(unittest.TestCase):
    setUp = fixtures.PolicyTests.setUp
    initialize = fixtures.PolicyTests.initialize
    scenario = fixtures.PolicyTests.scenario
    seed = fixtures.PolicyTests.seed
    check = fixtures.PolicyTests.check
    fail_policy = fixtures.PolicyTests.fail_policy
    discovery = fixtures.PolicyTests.discovery

    def prepare(self, disposition='refuted', mode='etp', prior_disagreement=False):
        self.run = self.root / ('disposition-' + str(len(list(self.root.iterdir()))))
        (self.source / 'artifact.py').write_text('def add(a, b): return a - b\n')
        self.scenario({})
        self.initialize(mode=mode)
        self.seed()
        fid = ('spec' if mode == 'etp' else 'plan-1') + ':claude:ADD-1'
        if disposition == 'fixed':
            self.scenario({'critic_verdict': 'AGREE'})
            policy.do_review(self.run, 'critic')
            policy.fix(self.run, {'writer_provider': 'codex', 'writer_session_id': 'author-session',
                                 'finding_ids': [fid], 'reason': 'Correct subtraction', 'next_check': 'unit'})
            (self.source / 'artifact.py').write_text('def add(a, b): return a + b\n')
            policy.refresh(self.run)
            self.scenario({})
            policy.do_review(self.run, 'review')
        elif prior_disagreement:
            self.scenario({'critic_verdict': 'DISAGREE_EVIDENCE'})
            policy.do_review(self.run, 'critic')
        self.check()
        policy.propose(self.run, {'dispositions': [{
            'finding_id': fid, 'disposition': disposition,
            'rationale': 'Evaluate this proposed disposition against the supplied evidence.',
            'evidence': [{'path': 'spec.md', 'quote': 'two integers'}],
        }]})
        self.scenario({})
        return fid

    def answer(self, fid, verdict='AGREE'):
        return {'status': 'CLEAN', 'summary': 'Evidence supports the proposed disposition.',
                'verdicts': [{'finding_id': fid, 'verdict': verdict,
                              'evidence': [{'path': 'spec.md', 'quote': 'two integers'}]}]}

    def assert_pair_blocked(self, before, fid, transport_status='REVIEWED'):
        _, state, _ = runtime.load(self.run)
        self.assertEqual(before['invocations'] + 2, state['invocations'])
        self.assertEqual(before['deadline'], state['deadline'])
        self.assertEqual('REVIEWED', state['calls'][-2]['status'])
        self.assertEqual(transport_status, state['calls'][-1]['status'])
        for call in state['calls'][-2:]:
            self.assertEqual({'input_tokens': 10, 'output_tokens': 5}, call['identity']['usage'])
            self.assertTrue(call['identity']['session_id'])
        self.assertEqual('PROPOSED', state['policy']['findings'][fid]['state'])
        self.assertEqual({}, state['policy']['acks'])
        self.assertFalse(policy.current_stage(state['policy']).get('acks'))
        self.assertFalse(policy.status(self.run)['execution_ready'])
        self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.advance(self.run))
        return state

    def test_supporting_summary_and_prior_finding_disagreement_cannot_acknowledge_refutation(self):
        fid = self.prepare(prior_disagreement=True)
        capture = self.root / 'ack-prompts.jsonl'
        self.scenario({'capture_prompt': str(capture), 'payload': self.answer(fid),
                       'payload_by_role': {'critic': self.answer(fid, 'DISAGREE_EVIDENCE')}})
        before = runtime.load(self.run)[1]
        self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
        state = self.assert_pair_blocked(before, fid)
        rejected = policy.report_for(self.run, state, state['calls'][-1]['report'])
        self.assertEqual('CLEAN', rejected['result']['status'])
        self.assertEqual('Evidence supports the proposed disposition.', rejected['result']['summary'])
        self.assertEqual('DISAGREE_EVIDENCE', rejected['result']['verdicts'][0]['verdict'])
        prompts = [json.loads(line) for line in capture.read_text().splitlines()]
        self.assertEqual(2, len(prompts))
        for prompt in prompts:
            self.assertIn('Verdict target: proposed disposition.', prompt['preamble'])
            context = json.loads(prompt['data']['context'])
            self.assertEqual('stage-ack', context['purpose'])
            self.assertIsNone(context['all_selected_reports'][1])
            self.assertEqual('refuted', context['findings'][fid]['proposal']['disposition'])
            self.assertEqual('DISAGREE_EVIDENCE', context['findings'][fid]['verdicts']['codex']['verdict']['verdict'])

    def test_each_disposition_can_be_accepted_or_rejected_with_evidence(self):
        for disposition in ('fixed', 'refuted', 'duplicate', 'outside_scope'):
            for verdict in ('AGREE', 'DISAGREE_EVIDENCE', 'DISAGREE_CONCERN'):
                with self.subTest(disposition=disposition, verdict=verdict):
                    fid = self.prepare(disposition)
                    second = self.answer(fid, verdict)
                    if verdict == 'DISAGREE_CONCERN':
                        second.update(status='NEEDS_EVIDENCE', evidence_requests=['Supply a discriminating check.'])
                    self.scenario({'payload': self.answer(fid), 'payload_by_role': {'critic': second}})
                    before = runtime.load(self.run)[1]
                    if verdict == 'AGREE':
                        policy.acknowledge(self.run)
                        _, state, _ = runtime.load(self.run)
                        self.assertEqual('CLOSED', state['policy']['findings'][fid]['state'])
                        self.assertEqual(set(runtime.PROVIDERS), set(policy.current_stage(state['policy'])['acks']))
                        self.assertEqual(before['invocations'] + 2, state['invocations'])
                        self.assertEqual(before['deadline'], state['deadline'])
                    else:
                        expected = 'INVALID_RESULT' if verdict == 'DISAGREE_EVIDENCE' else 'UNRESOLVED_DISPUTE'
                        self.fail_policy(expected, lambda: policy.acknowledge(self.run))
                        self.assert_pair_blocked(before, fid)

    def test_final_ack_objection_withholds_handoff_after_an_earlier_valid_stage_pair(self):
        fid = self.prepare(mode='plan')
        self.scenario({'payload': self.answer(fid)})
        policy.acknowledge(self.run)
        policy.advance(self.run)
        # A new recorded check changes the final acknowledgment basis.
        self.check()
        capture = self.root / 'final-prompts.jsonl'
        self.scenario({'capture_prompt': str(capture), 'payload': self.answer(fid),
                       'payload_by_role': {'critic': self.answer(fid, 'DISAGREE_EVIDENCE')}})
        before = runtime.load(self.run)[1]
        self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
        _, state, _ = runtime.load(self.run)
        self.assertEqual(before['invocations'] + 2, state['invocations'])
        self.assertEqual(before['deadline'], state['deadline'])
        self.assertEqual({}, state['policy']['acks'])
        self.assertIsNone(state['policy'].get('handoff'))
        self.assertFalse(policy.status(self.run)['execution_ready'])
        for prompt in map(json.loads, capture.read_text().splitlines()):
            self.assertEqual('final-ack', json.loads(prompt['data']['context'])['purpose'])
            self.assertIn('Audit the completed selected workflow.', prompt['preamble'])
            self.assertIn('Verdict target: proposed disposition.', prompt['preamble'])

    def test_incomplete_and_malformed_second_acknowledgments_preserve_the_existing_gates(self):
        for failure in ('omitted-verdict', 'malformed-verdict', 'identity', 'citation', 'concern-without-request'):
            with self.subTest(failure=failure):
                fid = self.prepare()
                second = self.answer(fid)
                if failure == 'omitted-verdict':
                    second['verdicts'] = []
                elif failure == 'malformed-verdict':
                    second['verdicts'] = 'AGREE'
                elif failure == 'identity':
                    second['context_sha256'] = 'wrong-context'
                elif failure == 'citation':
                    second['verdicts'][0]['evidence'][0]['quote'] = 'not in the frozen evidence'
                else:
                    second['verdicts'][0]['verdict'] = 'DISAGREE_CONCERN'
                self.scenario({'payload': self.answer(fid), 'payload_by_role': {'critic': second}})
                before = runtime.load(self.run)[1]
                self.fail_policy('INVALID_RESULT', lambda: policy.acknowledge(self.run))
                status = 'REVIEWED' if failure == 'omitted-verdict' else 'INVALID_RESULT'
                state = self.assert_pair_blocked(before, fid, status)
                self.assertEqual(failure == 'omitted-verdict', 'report' in state['calls'][-1])

    def test_new_finding_and_evidence_request_remain_possible_during_acknowledgment(self):
        for outcome in ('FINDINGS', 'NEEDS_EVIDENCE'):
            with self.subTest(outcome=outcome):
                fid = self.prepare()
                second = self.answer(fid)
                second['status'] = outcome
                if outcome == 'FINDINGS':
                    second['findings'] = [self.discovery('Independent new requirement')]
                else:
                    second['evidence_requests'] = ['Supply the missing acceptance result.']
                self.scenario({'payload': self.answer(fid), 'payload_by_role': {'critic': second}})
                before = runtime.load(self.run)[1]
                self.fail_policy('UNRESOLVED_DISPUTE', lambda: policy.acknowledge(self.run))
                state = self.assert_pair_blocked(before, fid)
                if outcome == 'FINDINGS':
                    self.assertEqual('OPEN', state['policy']['findings']['spec:codex:F1']['state'])

    def test_failed_required_check_refuses_acknowledgment_before_a_native_call(self):
        self.prepare()
        self.check(outcome=1)
        before = runtime.load(self.run)[1]
        self.fail_policy('NEEDS_CHECKS', lambda: policy.acknowledge(self.run))
        after = runtime.load(self.run)[1]
        self.assertEqual(before['calls'], after['calls'])
        self.assertEqual(before['deadline'], after['deadline'])
        self.assertEqual(before['invocations'], after['invocations'])


if __name__ == '__main__':
    unittest.main()
