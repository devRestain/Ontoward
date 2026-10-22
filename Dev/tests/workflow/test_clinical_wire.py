"""D64 input semantics and final-boundary metrics; no actual model calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import fixtures as f
from clinical_wire_fixtures import assert_same_meaning, canonical, duplicate_payload
from workflow.doctor_ear import DoctorEar
from workflow.input_types import ContextStatement
from workflow.model_context import message_metrics, messages
from workflow.rules.clinical_wire import compact_clinical_payload, compact_expected, compact_feature, wire_key
from workflow.rules.decision import close_graph_input, clinical_messages, prepare_decision
from workflow.rules.normalization import validate_mapping
from protocol import decode_context


class ClinicalWireTests(unittest.TestCase):
    def test_current_bounded_work_preserves_meaning_and_internal_owners_in_all_tasks(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        s.case.apply([f.CaseFact(id='unbound', value='Normalized medication note', source_ref='reply',
            category='medication', acquisition='SAY')])
        for mode in ('rank', 'decision', 'action'):
            if mode == 'action':
                c.differential.accept(s, {'ranked_disease_refs': list(work.refs)}, work, closing=True)
            work = prepare_decision(s, c.knowledge, c.tools, mode=mode)
            original, state = deepcopy(work), s.model_dump(mode='json')
            wire = decode_context(clinical_messages(c.config, work)[-1]['content'])
            assert_same_meaning(self, work.payload, wire)
            self.assertEqual(work, original)
            self.assertEqual(s.model_dump(mode='json'), state)
            self.assertEqual(set(wire['facts']), set(work.payload['facts']))
            self.assertTrue(any(row.get('value') == 'Normalized medication note' for row in wire['facts'].values()))
            self.assertNotIn('revision', wire)
            self.assertNotIn('required', wire)
            if mode == 'rank':
                self.assertNotIn('resources', wire)
                self.assertNotIn('questions', wire)
            else:
                self.assertEqual(wire['resources'], work.payload['resources'])

    def test_exact_patterns_groups_and_observation_matches_remain_separate(self):
        logical = duplicate_payload()
        # One disease has a different complete entries array; never group its prefix.
        logical['questions'][0]['expected_by_disease']['d_2'][0]['collection_only'] = False
        wire = compact_clinical_payload(logical)
        assert_same_meaning(self, logical, wire)
        self.assertEqual(len(wire['patterns']), 1)
        self.assertEqual(len(wire['relations']), 50)
        self.assertEqual(len(wire['candidates']), 62)
        self.assertEqual(len(wire['questions'][0]['expected_groups']), 2)
        self.assertEqual(wire['questions'][0]['expected_groups'][1]['diseases'], ['d_2'])
        self.assertEqual({row['effect'] for row in wire['relations'].values()}, {'support', 'against'})
        self.assertEqual({row['rule_scope']['time_context'] for row in wire['relations'].values()}, {'past', 'current'})
        self.assertIn('condition_1', wire['conditions'])
        self.assertEqual(wire['conditions']['condition_1'][0]['member'], 'father')
        self.assertNotEqual(wire['evidence']['e_1']['facts'], wire['evidence']['e_2']['facts'])
        self.assertNotEqual(wire['evidence']['e_1']['scope'], wire['evidence']['e_2']['scope'])
        self.assertIn('s_4', wire['scopes'])  # Executable question with no fact yet.
        self.assertEqual(wire['evidence']['e_1']['feature'], 0)
        self.assertTrue(wire['questions'][0]['expected_groups'][0]['entries'][0]['collection_only'])
        self.assertEqual(wire['questions'][0]['expected_groups'][0]['entries'][1]['expected'], 'absent')

    def test_numeric_and_projected_concepts_preserve_types_units_order_and_boundaries(self):
        values = ['head', {'subsumption': 'head'}, {'any_of': ['b', 'a'], 'match': 'exact'},
            {'all_of': ['a', 'b'], 'match': 'subsumption'}, False, 0,
            *[dict(kind='quantity', value=0, unit='kg', operator=op, approximate=False,
                lower_inclusive=True, upper_inclusive=True) for op in ('eq', 'lt', 'le', 'gt', 'ge')],
            dict(kind='interval', lower=None, upper=0.0, unit='day', upper_unit=None,
                lower_inclusive=True, upper_inclusive=False, approximate=True, operator='eq'),
            dict(kind='interval', lower=0, upper=None, unit='year', lower_inclusive=False, approximate=False)]
        logical = duplicate_payload(count=1)
        features = [dict(attribute='Attribute', expected_status='absent', expected=value) for value in values]
        logical['relations']['r_1']['full_pattern'] = features
        wire = compact_clinical_payload(logical)
        assert_same_meaning(self, logical, wire)
        result = wire['patterns']['p_1']
        for feature in result:
            self.assertEqual(feature['expected_status'], 'absent')
        for before, after in zip(values[:6], result[:6]):
            self.assertEqual(canonical(before), canonical(after['expected']))
        self.assertNotIn('operator', result[6]['expected'])
        self.assertEqual([row['expected'].get('operator') for row in result[7:11]], ['lt', 'le', 'gt', 'ge'])
        self.assertIs(result[-2]['expected']['upper_inclusive'], False)
        self.assertIs(result[-2]['expected']['approximate'], True)
        self.assertNotIn('lower', result[-2]['expected'])
        self.assertNotIn('upper', result[-1]['expected'])
        self.assertEqual(result[-1]['expected']['unit'], 'year')

    def test_presence_shorthand_requires_all_three_exact_conditions(self):
        for status in ('present', 'absent'):
            self.assertEqual(compact_feature(dict(attribute=None, expected_status=status, expected=status)), {'presence': status})
        for feature in (dict(attribute='Location', expected_status='present', expected='present'),
                        dict(attribute=None, expected_status='present', expected='absent'),
                        dict(attribute=None, expected_status='unknown', expected='unknown')):
            self.assertNotIn('presence', compact_feature(feature))
            self.assertEqual(compact_feature(feature), feature)

    def test_sharing_keys_preserve_json_types_units_and_array_order(self):
        rows = [0, False, 0.0, ['a', 'b'], ['b', 'a'],
            dict(kind='quantity', value=1, unit='year'), dict(kind='quantity', value=12, unit='month')]
        self.assertEqual(len({wire_key(row) for row in rows}), len(rows))
        logical = duplicate_payload(count=4)
        for index, value in enumerate((0, False, ['a', 'b'], ['b', 'a']), 1):
            logical['relations'][f'r_{index}']['full_pattern'][1]['expected'] = value
        wire = compact_clinical_payload(logical)
        self.assertEqual(len(wire['patterns']), 4)
        assert_same_meaning(self, logical, wire)

    def test_same_work_repair_keeps_all_references_and_options(self):
        c, s = f.consultation(), f.chief(f.state('DifferentialDiagnosis'))
        work = c.differential.prepare_decision(s)
        first = decode_context(clinical_messages(c.config, work)[-1]['content'])
        options = deepcopy(work.options)
        work.payload['validation_error'] = 'invalid_question_ref'
        repaired = decode_context(clinical_messages(c.config, work)[-1]['content'])
        self.assertEqual(repaired.pop('validation_error'), 'invalid_question_ref')
        self.assertEqual(first, repaired)
        self.assertEqual(work.options, options)
        self.assertEqual({q['ref'] for q in repaired['questions']}, set(options))

    def test_all_records_above_fifty_survive_closure_and_lossless_compaction(self):
        logical = duplicate_payload(count=65)
        for index in range(5, 70):
            logical['scopes'][f's_{index}'] = dict(subject='patient', time='past', observation=f'o_{index}')
            logical['facts'][f'f_{index}'] = dict(status='unknown', value=f'Unbound {index}', scope=f's_{index}',
                category='medical_history', acquisition='SAY', reported_by='patient')
        close_graph_input(logical)
        self.assertEqual(len(logical['relations']), 65)
        self.assertEqual(len(logical['candidates']), 62)
        self.assertEqual(len(logical['facts']), 68)
        wire = compact_clinical_payload(logical)
        assert_same_meaning(self, logical, wire)
        self.assertNotIn('incomplete', wire)
        self.assertEqual(set(wire['facts']), set(logical['facts']))
        self.assertIn('r_65', wire['relations'])
        self.assertEqual(len(wire['relations']), 65)

    def test_unknown_schema_fields_and_invalid_refs_fail_explicitly(self):
        for path, value in [('feature', 999), ('feature', False), ('relation', 'r_missing'), ('facts', ['f_missing'])]:
            logical = duplicate_payload(count=1)
            logical['evidence']['e_1'][path] = value
            with self.assertRaises(ValueError):
                compact_clinical_payload(logical)
        logical = duplicate_payload(count=1)
        logical['relations']['r_1']['future_clinical_meaning'] = 'keep or reject'
        with self.assertRaisesRegex(ValueError, 'unknown_clinical_wire'):
            compact_clinical_payload(logical)


class NumericMappingWireTests(unittest.TestCase):
    def test_only_numeric_wire_omits_values_and_original_validation_stays_strict(self):
        statement = ContextStatement.model_validate(f.statement(quote='0 kg', focus='attribute',
            attribute_terms=['Body weight'], measurement=dict(kind='quantity', value=0, unit='kg')))
        categorical = ContextStatement.model_validate(f.statement(focus='attribute', value_terms=['Low']))
        contracts = {i: [dict(id='Target', kind='Symptom', attributes=[dict(id='Body weight', units=['kg'],
            values=[dict(id='Low'), dict(id='High')])])] for i in (0, 1)}
        before = deepcopy(contracts)
        for phase in ('mapping', 'mapping_repair'):
            wire = DoctorEar._mapping_payload([statement, categorical], [0, 1], contracts, phase, [])
            self.assertNotIn('values', wire['statements'][0]['candidates'][0]['attributes'][0])
            self.assertIn('values', wire['statements'][1]['candidates'][0]['attributes'][0])
            self.assertEqual(wire['statements'][0]['quote'], '0 kg')
            self.assertEqual(wire['statements'][0]['measurement']['value'], 0)
            self.assertEqual(contracts, before)
        result = validate_mapping({'Target': {'Body weight': {'use_measurement': True}}}, statement, contracts[0], external=True)
        self.assertEqual(result[0][3].value, 0)
        for selected in ('Low', {'use_measurement': False}, {'use_measurement': True, 'unit': 'kg'}):
            with self.assertRaises(ValueError):
                validate_mapping({'Target': {'Body weight': selected}}, statement, contracts[0], external=True)
        self.assertEqual(validate_mapping({'Target': {'Body weight': 'Low'}}, categorical, contracts[1], external=True)[0][2], ['Low'])


class FinalInputMetricsTests(unittest.TestCase):
    def test_final_system_user_and_nested_repair_measure_bytes_without_tokens(self):
        wire = compact_clinical_payload(duplicate_payload())
        wire['validation_error'] = '잘못된 참조 ' * 100
        request = messages('System 한글', wire)
        stats = message_metrics('clinical', request)
        self.assertEqual(stats['system_content_utf8_bytes'], len(request[0]['content'].encode()))
        self.assertEqual(stats['user_content_utf8_bytes'], len(request[1]['content'].encode()))
        self.assertEqual(stats['messages_json_bytes'], len(json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()))
        self.assertEqual((stats['role'], stats['task'], stats['phase']), ('clinical', 'clinical_decision', 'repair'))
        self.assertEqual(stats['counts']['features'], 16)
        self.assertEqual(stats['counts']['disease_expectations'], 8 * 62 * 2)
        self.assertGreater(stats['blocks']['user[1].validation_error']['json_bytes'], 100)
        self.assertNotIn('tokens', canonical(stats))
        self.assertNotIn('잘못된', canonical(stats))
        self.assertNotIn('metrics', request[-1]['content'])
        for fields, phase in ((dict(generation_error='PROVIDER_RESPONSE_INVALID', validation_errors={}), 'response_repair'),
                              (dict(validation_errors={'id': 'invalid_utterance'}), 'repair')):
            repaired = messages('Repair instructions', dict(task='education_doctor', **fields))
            self.assertEqual(message_metrics('education_doctor', repaired)['phase'], phase)

    def test_metrics_cover_every_role_at_actual_boundary_before_ids_and_guards(self):
        for role in ('gateway', 'clinical', 'education', 'education_doctor'):
            c, s = f.consultation(), f.state('Education')
            request = messages('System', dict(task='test', phase='repair', repair={'full_pattern': False, 'conditions': {'x': 0}}))
            order = []
            def measured(*args):
                order.append('metrics')
                return message_metrics(*args)
            c.brain.new_request_id = lambda: order.append('request_id') or 'new'
            c.brain.executor.execute = Mock(return_value=f.FakeSDK.completion({}))
            with patch('workflow.doctor_brain.message_metrics', side_effect=measured):
                result = c.brain.complete(s, c.client, role=role, messages=request)
            self.assertIsNone(result.error)
            self.assertEqual(order, ['metrics', 'request_id'])
            self.assertEqual(c.brain.executor.execute.call_args.args[3]['messages'], request)

    def test_test_observer_captures_stats_without_changing_response_or_state(self):
        from observe import Trace
        c, s = f.consultation(), f.state()
        request = messages('System', {'task': 'input_mapping', 'phase': 'mapping', 'statements': []})
        c.brain.executor.execute = Mock(return_value=f.FakeSDK.completion([]))
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory) / 'trace.jsonl')
            try:
                trace.attach(c, c.knowledge)
                result = c.brain.complete(s, c.client, role='gateway', messages=request)
            finally:
                trace.detach()
            events = [json.loads(line) for line in trace.path.read_text().splitlines()]
        measured = [row for row in events if row.get('owner') == 'ModelInput' and row['kind'] == 'call_end']
        self.assertEqual(len(measured), 1)
        self.assertEqual(measured[0]['output']['messages_json_bytes'], message_metrics('gateway', request)['messages_json_bytes'])
        self.assertIsNone(result.error)
        self.assertEqual(s.session.input_tokens, 20)  # Scripted usage, never a real token measurement.
        self.assertFalse(any('metrics' in key for key in vars(s.session)))
