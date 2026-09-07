"""Identity generation constraints and rejection telemetry; fixture binaries only."""
import copy
import json
import unittest

import test_runtime as fixtures

runtime = fixtures.runtime
IDENTITY_FIELDS = ('provider', 'artifact_sha256', 'evidence_sha256', 'context_sha256',
                   'role', 'pass_number')


class IdentitySchemaTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp
    scenario = fixtures.RuntimeTests.scenario
    create = fixtures.RuntimeTests.create
    state = fixtures.RuntimeTests.state
    failure = fixtures.RuntimeTests.failure

    def test_both_launch_paths_constrain_exact_identity_without_mutating_public_schema(self):
        public_schema = copy.deepcopy(runtime.RESULT_SCHEMA)
        self.request.update(workflow='plan', adversarial_review_count=3)
        capture = self.root / 'captured-schema.json'
        self.scenario({'capture_schema': str(capture)})
        number = 0
        for origin in runtime.PROVIDERS:
            for role, pass_number in (('reviewer', 1), ('critic', 2), ('validation', 3)):
                for context in (None, '', '{"output":"café 🌿"}'):
                    with self.subTest(origin=origin, role=role, context=context):
                        number += 1
                        self.run = self.root / ('schema-' + str(number))
                        self.request['origin_provider'] = self.request['producer_provider'] = origin
                        self.request['provenance'][0]['provider'] = origin
                        self.create()
                        report = runtime.invoke(self.run, role, pass_number, context_data=context)
                        observed = json.loads(capture.read_text())
                        schema = observed['native_schema']
                        self.assertEqual(schema, observed['prompt_schema'])
                        self.assertEqual(set(IDENTITY_FIELDS), set(observed['identity']))
                        for field in IDENTITY_FIELDS:
                            self.assertEqual(observed['identity'][field], schema['properties'][field]['const'])
                            self.assertEqual(report['result'][field], schema['properties'][field]['const'])
                            schema['properties'][field].pop('const')
                        self.assertEqual(public_schema, schema)
                        self.assertEqual(public_schema, runtime.RESULT_SCHEMA)
                        expected_context = '' if context is None else runtime.digest(context.encode())
                        self.assertEqual(expected_context, report['result']['context_sha256'])
                        self.assertNotEqual(report['result']['artifact_sha256'], report['result']['evidence_sha256'])
                        self.assertNotIn('identity_mismatches', self.state()['calls'][-1])

    def rejected_identity(self, field, override, omitted=False):
        self.run = self.root / ('mismatch-' + str(len(list(self.root.iterdir()))))
        before = self.create()
        self.scenario({'omit_fields': [field]} if omitted else {'payload': {field: override}})
        with self.assertRaises(runtime.ReviewError) as caught:
            runtime.invoke(self.run, context_data='{"output":"café"}')
        self.assertEqual('INVALID_RESULT', caught.exception.status)
        state = self.state()
        self.assertEqual('INVALID_RESULT', state['status'])
        self.assertEqual(1, state['invocations'])
        self.assertEqual(before['deadline'], state['deadline'])
        self.assertEqual(before['request_sha256'], state['request_sha256'])
        self.assertEqual(before['snapshot_sha256'], state['snapshot_sha256'])
        self.assertFalse(list(self.run.glob('report-*')))
        call = state['calls'][-1]
        self.assertEqual('INVALID_RESULT', call['status'])
        self.assertNotIn('report', call)
        self.assertEqual(runtime.opposite(self.request['producer_provider']), call['identity']['provider'])
        self.assertTrue(call['identity']['session_id'])
        self.assertEqual({'input_tokens': 10, 'output_tokens': 5}, call['identity']['usage'])
        self.assertEqual('reported', call['identity']['usage_completeness'])
        self.assertEqual(1, len(call['identity_mismatches']))
        mismatch = call['identity_mismatches'][0]
        self.assertEqual(field, mismatch['field'])
        self.assertEqual(call[field], mismatch['expected'])
        self.assertLess(len(json.dumps(mismatch)), 400)
        return mismatch['actual'], json.dumps(state) + str(caught.exception)

    def test_every_identity_mismatch_is_rejected_and_retains_bounded_native_evidence(self):
        for origin in runtime.PROVIDERS:
            self.request['origin_provider'] = self.request['producer_provider'] = origin
            self.request['provenance'][0]['provider'] = origin
            values = {'provider': origin, 'artifact_sha256': '0' * 64, 'evidence_sha256': '1' * 64,
                      'context_sha256': '2' * 64, 'role': 'critic', 'pass_number': 2}
            for field, value in values.items():
                with self.subTest(origin=origin, field=field):
                    actual, _ = self.rejected_identity(field, value)
                    self.assertEqual({'type': type(value).__name__, 'value': value}, actual)

    def test_malformed_identity_values_reveal_only_type_length_and_json_digest(self):
        values = [None, True, 1.0, {}, ['fixture-private'], {'secret': 'fixture-private'},
                  'Bearer fixture-private', 'sk-' + 'fixture-private' * 3, 'x' * 10000, '\ud800']
        for field in IDENTITY_FIELDS:
            for value in values:
                with self.subTest(field=field, type=type(value).__name__):
                    actual, saved = self.rejected_identity(field, value)
                    expected = {'type': type(value).__name__, 'canonical_json_sha256': runtime.digest(
                        json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode())}
                    if isinstance(value, (str, list, dict)):
                        expected['length'] = len(value)
                    self.assertEqual(expected, actual)
                    self.assertNotIn('fixture-private', saved)
                    self.assertNotIn('x' * 100, saved)
                    self.assertNotIn('\\ud800', saved)
        # Also exercise the other native envelope on the malformed path.
        self.request['origin_provider'] = self.request['producer_provider'] = 'claude'
        self.request['provenance'][0]['provider'] = 'claude'
        self.rejected_identity('context_sha256', {'secret': 'fixture-private'})

    def test_missing_identity_fields_are_attributable_without_inventing_a_value(self):
        for field in IDENTITY_FIELDS:
            with self.subTest(field=field):
                actual, _ = self.rejected_identity(field, None, omitted=True)
                self.assertEqual({'type': 'missing'}, actual)

    def test_hash_values_are_not_normalized_and_empty_context_remains_distinct(self):
        actual, _ = self.rejected_identity('context_sha256', '')
        self.assertEqual({'type': 'str', 'value': ''}, actual)
        actual, _ = self.rejected_identity('context_sha256', 'A' * 64)
        self.assertNotIn('value', actual)
        actual, _ = self.rejected_identity('artifact_sha256', '')
        self.assertNotIn('value', actual)

    def test_all_six_mismatches_stay_bounded_and_exclude_other_response_text(self):
        self.create()
        self.scenario({'payload': {
            **{field: 'Bearer fixture-private-' + 'x' * 10000 for field in IDENTITY_FIELDS},
            'summary': 'fixture-private-summary',
        }})
        self.failure('INVALID_RESULT', lambda: runtime.invoke(self.run))
        call = self.state()['calls'][-1]
        self.assertEqual(set(IDENTITY_FIELDS), {row['field'] for row in call['identity_mismatches']})
        self.assertEqual(6, len(call['identity_mismatches']))
        self.assertLess(len(json.dumps(call['identity_mismatches'])), 2400)
        self.assertNotIn('fixture-private', json.dumps(self.state()))
        self.assertFalse(list(self.run.glob('report-*')))


if __name__ == '__main__':
    unittest.main()
