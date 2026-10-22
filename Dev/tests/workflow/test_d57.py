"""Verify input binding and scoped collection with scripted Context output offline."""
import copy
import unittest

from rdflib import Literal, RDF, RDFS

import fixtures as f
from initiation_fixtures import OPENING, VITAL_SIGNS, opening_context, quantity
from knowledge.conditions import AttributeRole, QuestionTemplate
from workflow.input_types import ContextStatement
from workflow.rules.collection import answered, slot_resolved
from workflow.rules.normalization import candidate_contracts, exact_mapping, validate_mapping, measurement_value
from workflow.state.evidence import EvidenceIndex
from workflow.state.models import Answer, ObservedNumber, Question, TurnContext

TARGET = 'Weight loss'
INTENT = 'Intentionality of weight change'
COMBINED = 'Weight loss amount and time period'
AMOUNT = 'Absolute weight change (kg)'
ONSET = 'Duration since onset'
MAGNITUDE = 'Weight loss magnitude'
EPISODE = 'Episode duration'


def knowledge():
    k = f.knowledge()
    k._graph.set((f.OW.Complaint, RDFS.label, Literal(TARGET, lang='en')))
    for index, (ident, name, category, text, answer_type, units) in enumerate([
        ('Intent', INTENT, 'other', '체중 변화는 의도한 것인가요?', 'category', []),
        ('Combined', COMBINED, 'measurement', '체중이 얼마 동안 얼마나 줄었나요?', 'free_text', []),
        ('Amount', AMOUNT, 'measurement', '체중이 몇 킬로그램 변했나요?', 'quantity', ['kg']),
        ('Onset', ONSET, 'onset', '증상 시작 후 얼마나 지났나요?', 'duration', ['month']),
        ('Magnitude', MAGNITUDE, 'measurement', '최근 6개월간 체중이 몇 퍼센트 줄었나요?', 'quantity', ['%']),
        ('Episode', EPISODE, 'duration', '한 번에 얼마나 지속되나요?', 'duration', ['min']),
    ]):
        node = f.OW[ident]
        k._graph.add((node, RDF.type, f.OW.FindingAttribute))
        k._graph.add((node, RDFS.label, Literal(name, lang='en')))
        k._graph.add((f.OW.Complaint if ident != 'Episode' else f.OW.Other, f.OW.hasAttribute, node))
        k.questions[str(node)] = QuestionTemplate(text=text, answer_type=answer_type, units=units)
        k.attribute_roles[str(node)] = AttributeRole(order=index + 2, category=category)
    for ident, label, owner in [('Unintentional', 'Unintentional', 'Intent'), ('Intentional', 'Intentional', 'Intent'),
                                ('Significant', 'More than ten percent over six months', 'Combined')]:
        k._graph.add((f.OW[ident], RDF.type, f.OW.AttributeValue))
        k._graph.add((f.OW[ident], RDFS.label, Literal(label, lang='en')))
        k._graph.add((f.OW[owner], f.OW.canHaveValue, f.OW[ident]))
    key = f'{f.OW.Complaint}|{f.OW.Combined}'
    k.questions[key] = k.questions[str(f.OW.Combined)].model_copy(update={
        'collect_via': [str(f.OW.Amount), str(f.OW.Onset)]})
    f.add_pattern(k, 'weightCriterion', f.OW.Complaint,
        [(f.OW.Combined, dict(kind='concept', concept=str(f.OW.Significant)))])
    k.validate_question_assets()
    return k


def chief(s, **changes):
    s.case.apply([f.fact(target=TARGET, **changes)])
    return s


def detail(ident, attribute, measurement=None, *, values=(), **changes):
    return f.fact(ident, kind='attribute', target=TARGET, attribute=attribute,
                  measurement=measurement, values=values, category='onset' if attribute == ONSET else 'measurement', **changes)


def accept_opening(k):
    def reply(payload):
        if payload['task'] == 'input_context':
            return opening_context()
        if payload['task'] == 'input_mapping':
            result = []
            for row in payload['statements']:
                target = next((c for c in row['candidates'] if c['id'] == TARGET), None)
                if not target:
                    result.append({})
                    continue
                hints = row['meaning'].get('attribute_terms', [])
                attribute = next((a for a in target['attributes'] if a['id'] in hints), None)
                if attribute and row.get('measurement'):
                    result.append({TARGET: {attribute['id']: {'use_measurement': True}}})
                elif attribute and attribute['id'] == INTENT:
                    result.append({TARGET: {INTENT: 'Unintentional'}})
                elif row['quote'] == opening_context()['statements'][0]['quote'] and not target['attributes']:
                    result.append({TARGET: '(+)'})
                else:
                    result.append({})
            return result
    client = f.FakeSDK(chat_handler=reply)
    c = f.consultation(client, f.resources(k))
    s = f.state()
    s.turn = TurnContext(kind='initial', response=dict(opening=OPENING, vital_signs=VITAL_SIGNS))
    c.ear.process_input(s, k, client)
    return s, c, client


class MeasurementReferenceTests(unittest.TestCase):
    def setUp(self):
        self.contracts = [dict(id=TARGET, attributes=[dict(id=ONSET, units=['month', 'year'], values=[dict(id='Long')])])]
        self.row = ContextStatement(**f.statement(target_terms=[TARGET], focus='attribute', attribute_terms=[ONSET],
            measurement=quantity(3, 'month')))

    def decode(self, selected, *, row=None, contracts=None):
        return validate_mapping({TARGET: {ONSET: selected}}, row or self.row,
                                contracts or self.contracts, external=True)

    def test_reference_keeps_context_quantity_and_mixed_interval_exactly(self):
        numbers = [ObservedNumber(**quantity(7, 'month', approximate=True)), ObservedNumber(kind='interval',
            lower=6, upper=2, unit='month', upper_unit='year', lower_inclusive=False,
            upper_inclusive=True, approximate=True), ObservedNumber(kind='interval', upper=3, unit='year', upper_inclusive=False)]
        for measured in numbers:
            with self.subTest(measured=measured):
                row = self.row.model_copy(update={'measurement': measured})
                self.assertEqual(self.decode({'use_measurement': True}, row=row)[0][3], measured)
        self.assertEqual(validate_mapping({}, self.row, self.contracts, external=True), [])

    def test_marker_rejects_coercion_extra_fields_and_regenerated_numbers(self):
        for selected in ({'use_measurement': 1}, {'use_measurement': 'true'}, {'use_measurement': False},
                         {'use_measurement': True, 'value': 3}, {'use_measurement': True, 'unit': 'month'},
                         {'use_measurement': True, 'kind': 'quantity'}, 'Long', {'Long': '(+)'},
                         measurement_value(self.row.measurement), {'value': 3, 'unit': 'month', 'operator': 'eq'}):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                self.decode(selected)

    def test_marker_requires_reported_measurement_registered_units_and_assertion(self):
        for changes in ({'measurement': None}, {'assertion': 'absent'},
                        {'measurement': ObservedNumber(**quantity(3, 'kg'))},
                        {'measurement': ObservedNumber(kind='interval', lower=1, upper=3, unit='year', upper_unit='day')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.decode({'use_measurement': True}, row=self.row.model_copy(update=changes))
        for mapping in ({'Other': {ONSET: {'use_measurement': True}}},
                        {TARGET: {'Other': {'use_measurement': True}}},
                        {TARGET: {ONSET: {'use_measurement': True}, 'Other': {'use_measurement': True}}}):
            with self.assertRaises(ValueError):
                validate_mapping(mapping, self.row, self.contracts, external=True)

    def test_exact_python_mapping_retains_canonical_numeric_validator(self):
        k = knowledge()
        contracts = candidate_contracts(k, self.row, None)
        mapping = exact_mapping(k, self.row, contracts, None)
        self.assertEqual(mapping[TARGET][ONSET]['kind'], 'quantity')
        self.assertEqual(validate_mapping(mapping, self.row, contracts)[0][3], self.row.measurement)

    def test_external_repair_keeps_valid_numeric_sibling_and_meaning_hints(self):
        k = knowledge()
        rows = [f.statement('Since then', focus='attribute', target_terms=[TARGET], attribute_terms=['Duration since'],
                    measurement=quantity(3, 'month'), note_value='Elapsed complaint time'),
                f.statement('Amount lost', focus='attribute', target_terms=[TARGET], attribute_terms=['weight change'],
                    measurement=quantity(7, 'kg', approximate=True), note_value='Loss of body weight')]
        calls = []
        def reply(payload):
            calls.append(copy.deepcopy(payload))
            if payload['task'] == 'input_context':
                return {'statements': rows}
            if payload['phase'] == 'mapping':
                return [{TARGET: {ONSET: {'use_measurement': True}}}, {TARGET: {AMOUNT: {'value': 7, 'unit': 'kg'}}}]
            self.assertEqual(payload['statement_indices'], [1])
            return [{TARGET: {AMOUNT: {'use_measurement': True}}}]
        s, c, _ = f.interpret([], text='Since then Amount lost', responses=reply, k=k)
        self.assertEqual([p['phase'] for p in calls], ['context', 'mapping', 'mapping_repair'])
        first = calls[1]['statements'][0]
        self.assertEqual(first['normalized_claim'], 'Elapsed complaint time')
        self.assertEqual(first['meaning']['attribute_terms'], ['Duration since'])
        self.assertEqual({fact.attribute for fact in s.case.facts.values()}, {ONSET, AMOUNT})
        self.assertTrue(next(fact for fact in s.case.facts.values() if fact.attribute == AMOUNT).measurement.approximate)


class InputScopeTests(unittest.TestCase):
    def test_reviewed_opening_is_accepted_before_any_say_without_duplicate_detail_questions(self):
        s, c, client = accept_opening(knowledge())
        self.assertEqual(s.case.chief(confirmed=True).target, TARGET)
        self.assertFalse(client.actions)
        self.assertEqual([p['task'] for p in client.requests], ['input_context'])
        scope = (s.case.chief().observation_id, s.case.chief().episode_id)
        for name in (ONSET, AMOUNT, INTENT):
            fact = next(fact for fact in s.case.current_facts() if fact.attribute == name)
            self.assertEqual((fact.observation_id, fact.episode_id), scope)
            self.assertEqual(fact.status, 'present')
        self.assertTrue(slot_resolved(s.case, 'onset'))
        self.assertFalse(slot_resolved(s.case, 'recurrence'))
        self.assertFalse(slot_resolved(s.case, 'previous_care'))
        self.assertFalse(slot_resolved(s.case, 'course'))
        c.sessions['Initiation'].prepare(s)
        self.assertNotIn('onset', {q.category for q in s.interview.queue})
        s.interview.current, s.interview.queue = 'ChiefComplaint', []
        c.sessions['ChiefComplaint'].prepare(s)
        attrs = {q.attribute for q in s.interview.queue}
        self.assertFalse({INTENT, AMOUNT, ONSET, COMBINED} & attrs)
        self.assertIn(MAGNITUDE, attrs)
        numbers = {fact.value: fact for fact in s.case.current_facts() if fact.kind == 'note' and fact.measurement}
        self.assertEqual(numbers['Baseline body weight'].measurement.value, 56)
        self.assertEqual(numbers['Baseline body weight'].time_context, 'past')
        self.assertEqual(numbers['Current body weight'].measurement.value, 49)
        self.assertEqual(numbers['Reported height'].measurement.value, 164)
        for name in ('Baseline body weight', 'Current body weight'):
            self.assertTrue(numbers[name].measurement.approximate)
        self.assertFalse(any(fact.acquisition == 'EXAM' for fact in s.case.facts.values()))
        self.assertEqual({fact.source_ref for fact in s.case.facts.values() if fact.category == 'objective_observation'}, {'initial:vital_signs'})
        self.assertFalse(any(fact.target == 'Lack of physical exercise' for fact in s.case.facts.values()))
        self.assertFalse(any(fact.attribute == COMBINED for fact in s.case.facts.values()))

    def test_current_and_baseline_weights_never_expand_by_unit_alone(self):
        k = knowledge()
        q = Question(item_id='q', purpose='hpi', target=TARGET, attribute=AMOUNT, text='어느 정도인가요?')
        for expanded in (False, True):
            for name, time, value in [('Baseline body weight', 'past', 56), ('Current body weight', 'current', 49)]:
                row = ContextStatement(**f.statement(name, target_terms=['body weight'], record_category='measurement',
                    time_context=time, measurement=quantity(value, 'kg', approximate=True), note_value=name))
                for question in (None, q):
                    self.assertFalse(candidate_contracts(k, row, question, expanded=expanded))

    def test_unbound_anchor_notes_remain_independent_and_do_not_create_graph_evidence(self):
        rows = [f.statement('Complaint', target_terms=[TARGET], primary_concern=True),
            f.statement('Time', target_terms=[TARGET], focus='attribute', anchor=0, record_category='duration',
                attribute_terms=['unregistered time detail'], measurement=quantity(3, 'month')),
            f.statement('Loss', target_terms=[TARGET], focus='attribute', anchor=0, record_category='measurement',
                attribute_terms=['unregistered change detail'], measurement=quantity(7, 'kg'))]
        s, c, _ = f.interpret(rows, k=knowledge())
        notes = [fact for fact in s.case.current_facts() if fact.kind == 'note']
        self.assertEqual(len(notes), 2)
        self.assertEqual({fact.status for fact in notes}, {'present'})
        self.assertEqual({(fact.observation_id, fact.episode_id) for fact in notes},
            {(s.case.chief().observation_id, s.case.chief().episode_id)})
        self.assertTrue(all(fact.id not in {r.id for r in EvidenceIndex.from_case(s.case, c.knowledge).entries} for fact in notes))
        self.assertFalse(slot_resolved(s.case, 'onset'))

    def test_real_bound_numeric_conflicts_are_still_detected(self):
        s = chief(f.state())
        s.case.apply([detail('a', AMOUNT, ObservedNumber(**quantity(3, 'kg'))),
                      detail('b', AMOUNT, ObservedNumber(**quantity(7, 'kg')))])
        self.assertEqual({fact.status for fact in s.case.current_facts() if fact.attribute}, {'uncertain'})

    def test_local_anchor_wins_over_prior_observation_and_preserves_note_binding_scope(self):
        s = chief(f.state())
        rows = [f.statement('New episode', target_terms=[TARGET], primary_concern=True),
                f.statement('Time', target_terms=[TARGET], focus='attribute', attribute_terms=[ONSET], anchor=0,
                    measurement=quantity(3, 'month')),
                f.statement('Course', target_terms=[TARGET], record_category='course', anchor=0, note_value='Progressive loss')]
        s, c, _ = f.interpret(rows, k=knowledge(), s=s)
        new = s.case.chief()
        self.assertNotEqual(new.observation_id, 'obs1')
        self.assertEqual({fact.observation_id for fact in s.case.facts.values() if fact.id != 'chief'}, {new.observation_id})

    def test_onset_and_episode_duration_are_not_aliases(self):
        k = knowledge()
        k._graph.add((f.OW.Complaint, f.OW.hasAttribute, f.OW.Episode))
        rows = [f.statement('Headaches', target_terms=[TARGET], primary_concern=True),
            f.statement('One week ago', focus='attribute', target_terms=[TARGET], attribute_terms=[ONSET], anchor=0,
                record_category='duration', measurement=quantity(1, 'week')),
            f.statement('Twenty minutes each', focus='attribute', target_terms=[TARGET], attribute_terms=[EPISODE], anchor=0,
                record_category='duration', measurement=quantity(20, 'min'))]
        s, c, _ = f.interpret(rows, k=k)
        attrs = {fact.attribute: fact for fact in s.case.facts.values() if fact.attribute}
        self.assertEqual(attrs[ONSET].category, 'onset')
        self.assertEqual(attrs[EPISODE].category, 'duration')
        self.assertTrue(slot_resolved(s.case, 'onset'))
        s.case.facts.pop(attrs[ONSET].id)
        self.assertFalse(slot_resolved(s.case, 'onset'))

    def test_intake_requires_current_chief_complete_report_scope(self):
        for changes in ({'subject': 'family', 'subject_member': 'mother'}, {'time_context': 'past'},
                        {'episode_id': 'earlier'}, {'observation_id': None}, {'target': 'Other symptom'},
                        {'acquisition': 'EXAM'}, {'source_ref': 'initial:vital_signs'}, {'polarity_scope': 'qualified'}):
            s = chief(f.state())
            s.case.apply([f.fact('other-onset', category='onset', **changes)])
            self.assertFalse(slot_resolved(s.case, 'onset'), changes)
        s = chief(f.state())
        s.case.apply([f.fact('valid', target=TARGET, category='onset')])
        self.assertTrue(slot_resolved(s.case, 'onset'))

    def test_initial_unknown_amount_remains_unknown_without_a_numeric_or_composite_assertion(self):
        rows = [f.statement('Weight loss', target_terms=[TARGET], primary_concern=True),
            f.statement('Not intended', focus='attribute', target_terms=[TARGET], attribute_terms=[INTENT],
                value_terms=['Unintentional'], anchor=0),
            f.statement('Amount unknown', role='unknown', assertion='unknown', focus='attribute',
                target_terms=[TARGET], attribute_terms=[AMOUNT], record_category='measurement',
                note_value='Amount of weight loss is unknown', anchor=0)]
        s, c, client = f.interpret(rows, k=knowledge())
        self.assertEqual(c.tools.chief_statuses(s)[INTENT], 'acquired')
        unknown = next(fact for fact in s.case.facts.values() if fact.value == 'Amount of weight loss is unknown')
        self.assertEqual(unknown.status, 'unknown')
        self.assertIsNone(unknown.measurement)
        self.assertFalse(any(fact.attribute in {AMOUNT, COMBINED} for fact in s.case.facts.values()))
        self.assertEqual([p['task'] for p in client.requests], ['input_context'])

    def test_supplied_previous_episode_never_inherits_current_question_observation(self):
        s = chief(f.state())
        s.case.apply([f.fact('prior', target=TARGET, observation_id='prior-observation', episode_id='prior-episode')])
        q = Question(item_id='q', purpose='hpi', target=TARGET, attribute=ONSET, text='언제부터인가요?',
            observation_id='obs1', episode_id='episode1', time_context='current')
        rows = [f.statement('Prior elapsed time', target_terms=[TARGET], focus='attribute', attribute_terms=[ONSET],
            episode_id='prior-episode', measurement=quantity(3, 'month'))]
        s, c, _ = f.interpret(rows, s=s, q=q, k=knowledge())
        fact = next(fact for fact in s.case.facts.values() if fact.attribute == ONSET)
        self.assertEqual((fact.observation_id, fact.episode_id), ('prior-observation', 'prior-episode'))
        self.assertFalse(slot_resolved(s.case, 'onset'))

    def test_observation_and_episode_cannot_be_spliced_from_different_transmitted_facts(self):
        s = chief(f.state())
        s.case.apply([f.fact('prior', target=TARGET, observation_id='prior-observation', episode_id='prior-episode')])
        def reply(payload):
            return {'statements': [f.statement('Wrong scope', target_terms=[TARGET], focus='attribute',
                attribute_terms=[ONSET], observation_id='obs1', episode_id='prior-episode', measurement=quantity(3, 'month'))]}
        s, c, client = f.interpret([], text='Wrong scope', responses=reply, s=s, k=knowledge())
        self.assertEqual([p['phase'] for p in client.requests], ['context', 'context_repair'])
        self.assertFalse(any(fact.attribute == ONSET for fact in s.case.facts.values()))

    def test_intake_answer_history_requires_the_current_chief_complete_scope(self):
        key = ('SAY', TARGET, '', 'patient', '', 'current', 'obs1', 'episode1')
        for index, value in ((0, 'EXAM'), (3, 'family'), (4, 'mother'), (5, 'past'), (6, 'another'), (7, 'earlier')):
            changed = list(key)
            changed[index] = value
            s = chief(f.state())
            s.interview.answers.append(Answer(question_id='prior', source_ref='reply', scope='Initiation',
                purpose='intake', category='onset', outcome='unknown', key=tuple(changed)))
            self.assertFalse(answered(s, 'onset'))


class AtomicCollectionTests(unittest.TestCase):
    def setUp(self):
        self.k = knowledge()
        self.c = f.consultation(prepared=f.resources(self.k))

    def state(self, *attributes):
        s = chief(f.state('ChiefComplaint'))
        for name in attributes:
            s.case.apply([detail(name, name, ObservedNumber(**quantity(7 if name == AMOUNT else 3, 'kg' if name == AMOUNT else 'month')))])
        return s

    def test_partial_collection_asks_only_missing_components_and_counts_each_once(self):
        for known in ((), (ONSET,), (AMOUNT,), (AMOUNT, ONSET)):
            with self.subTest(known=known):
                s = self.state(*known)
                statuses = self.c.tools.chief_statuses(s)
                self.assertNotIn(COMBINED, statuses)
                self.assertEqual(self.c.sessions['ChiefComplaint'].required_actions(s),
                    min(5, sum(value == 'unasked' for value in statuses.values()) + 1))
                self.c.sessions['ChiefComplaint'].prepare(s)
                attrs = [q.attribute for q in s.interview.queue if q.attribute]
                self.assertNotIn(COMBINED, attrs)
                for name in (AMOUNT, ONSET):
                    self.assertEqual(attrs.count(name), 0 if name in known else 1)
                self.assertIn(MAGNITUDE, attrs)
                self.assertFalse(any(fact.attribute == COMBINED for fact in s.case.facts.values()))

    def test_extra_details_in_one_answer_remove_pending_atomic_questions(self):
        s = self.state()
        self.c.sessions['ChiefComplaint'].prepare(s)
        q = next(q for q in s.interview.queue if q.attribute == AMOUNT)
        self.c.interactions.select_question(s, q)
        s.turn.stage, s.turn.response = 'received', dict(content='Three months seven kg unintentional', turn=1)
        rows = [f.statement('Three months', focus='attribute', target_terms=[TARGET], attribute_terms=[ONSET], measurement=quantity(3, 'month')),
                f.statement('seven kg', focus='attribute', target_terms=[TARGET], attribute_terms=[AMOUNT], measurement=quantity(7, 'kg')),
                f.statement('unintentional', focus='attribute', target_terms=[TARGET], attribute_terms=[INTENT], value_terms=['Unintentional'])]
        client = f.FakeSDK(chat_handler=lambda p: {'statements': rows} if p['task'] == 'input_context' else None)
        self.c.ear.process_input(s, self.k, client)
        self.c.sessions['ChiefComplaint'].prepare(s)
        self.c.tools.select_question(s)
        self.assertFalse({AMOUNT, ONSET, INTENT, COMBINED} & {q.attribute for q in s.interview.queue})
        self.assertEqual([p['phase'] for p in client.requests], ['context'])
        self.assertEqual(len(s.interview.answers), 1)

    def test_unknown_quantity_and_known_intent_do_not_repeat_or_invent_amount(self):
        s = self.state()
        s.case.apply([detail('intent', INTENT, values=('Unintentional',))])
        key = ('SAY', TARGET, AMOUNT, 'patient', '', 'current', 'obs1', 'episode1')
        s.interview.answers.append(Answer(question_id='q', source_ref='reply', scope='ChiefComplaint',
            purpose='hpi', key=key, outcome='unknown'))
        self.c.sessions['ChiefComplaint'].prepare(s)
        self.assertFalse({AMOUNT, INTENT, COMBINED} & {q.attribute for q in s.interview.queue})
        self.assertIn(ONSET, {q.attribute for q in s.interview.queue})
        self.assertFalse(any(fact.measurement for fact in s.case.facts.values()))

    def test_other_scope_or_acquisition_never_satisfies_atomic_question(self):
        for changes in ({'subject': 'family', 'subject_member': 'mother'}, {'time_context': 'past'},
                        {'episode_id': 'previous'}, {'observation_id': 'another'},
                        {'acquisition': 'EXAM'}, {'source_ref': 'initial:vital_signs'}, {'polarity_scope': 'qualified'}):
            s = self.state()
            s.case.apply([detail('other', AMOUNT, ObservedNumber(**quantity(7, 'kg')), **changes)])
            self.assertEqual(self.c.tools.chief_statuses(s)[AMOUNT], 'unasked', changes)

    def test_dd_expands_compound_questions_and_preserves_full_clinical_expectation(self):
        s = self.state(ONSET)
        s.interview.current = 'DifferentialDiagnosis'
        work = self.c.differential.prepare_decision(s)
        questions = [row for row in work.payload['questions'] if row.get('attribute') == AMOUNT]
        self.assertEqual(len(questions), 1)
        self.assertFalse(any(row.get('attribute') in {COMBINED, ONSET} for row in work.payload['questions']))
        entries = [entry for values in questions[0]['expected_by_disease'].values() for entry in values]
        self.assertTrue(entries)
        self.assertTrue(any(entry.get('collection_only') for entry in entries))
        criterion = next(entry for entry in entries if entry.get('collection_only'))
        relation = work.payload['relations'][criterion['relation']]
        self.assertEqual(relation['full_pattern'][criterion['feature']]['attribute'], COMBINED)
        self.assertFalse(any(fact.attribute == COMBINED for fact in s.case.facts.values()))
        s.case.apply([detail('amount', AMOUNT, ObservedNumber(**quantity(7, 'kg')))])
        work = self.c.differential.prepare_decision(s)
        self.assertFalse(any(row.get('attribute') in {COMBINED, AMOUNT, ONSET} for row in work.payload['questions']))
        self.assertTrue(any(ref.scope[2] == COMBINED for candidate in work.candidates.values() for ref in candidate.entry.unresolved))

    def test_stale_compound_queue_is_removed_without_fake_answer(self):
        s = self.state()
        self.c.questions.register(s, Question(item_id='old', purpose='hpi', target=TARGET, attribute=COMBINED,
            text='체중이 얼마 동안 얼마나 줄었나요?', observation_id='obs1', episode_id='episode1', time_context='current'))
        self.c.sessions['ChiefComplaint'].prepare(s)
        self.c.tools.select_question(s)
        self.assertNotIn(COMBINED, {q.attribute for q in s.interview.queue})
        self.assertFalse(s.interview.answers)
        self.assertNotIn('budget_stopped', s.interview.collection.values())

    def test_intentional_loss_is_not_unintentional(self):
        rows = [f.statement('Weight loss', target_terms=[TARGET], primary_concern=True),
                f.statement('Diet and exercise', target_terms=[TARGET], focus='attribute', anchor=0,
                    attribute_terms=[INTENT], value_terms=['Intentional'])]
        s, _, _ = f.interpret(rows, k=self.k)
        self.assertEqual(next(fact.values for fact in s.case.facts.values() if fact.attribute == INTENT), ('Intentional',))

    def test_mixed_episode_onset_does_not_answer_current_episode(self):
        s = self.state()
        s.case.apply([detail('old-duration', ONSET, ObservedNumber(**quantity(3, 'month')), episode_id='dieting'),
                      detail('new-duration', ONSET, ObservedNumber(**quantity(1, 'week'))),
                      detail('old-intent', INTENT, values=('Intentional',), episode_id='dieting'),
                      detail('new-intent', INTENT, values=('Unintentional',))])
        self.assertEqual(self.c.tools.chief_statuses(s)[ONSET], 'acquired')
        self.assertEqual({fact.status for fact in s.case.current_facts()}, {'present'})
        self.assertFalse(any(fact.attribute == AMOUNT for fact in s.case.facts.values()))


class CollectionContractTests(unittest.TestCase):
    def test_absent_collection_metadata_preserves_existing_question_wire(self):
        self.assertNotIn('collect_via', QuestionTemplate(text='어떤가요?').model_dump())
        self.assertEqual(QuestionTemplate(text='어떤가요?', collect_via=['a']).model_dump()['collect_via'], ['a'])

    def test_invalid_collect_via_is_rejected_at_preparation(self):
        key = f'{f.OW.Complaint}|{f.OW.Combined}'
        for components in ([str(f.OW.Combined)], [str(f.OW.Other)], [str(f.OW.Episode)], ['foreign'],
                           [str(f.OW.Amount), str(f.OW.Amount)]):
            with self.subTest(components=components), self.assertRaises(ValueError):
                k = knowledge()
                k.questions[key] = QuestionTemplate(text='어떻게 변했나요?', collect_via=components)
                k.validate_question_assets()
        for nested in (str(f.OW.Amount), str(f.OW.Combined)):
            k = knowledge()
            k.questions[f'{f.OW.Complaint}|{f.OW.Amount}'] = QuestionTemplate(text='어떻게 변했나요?', collect_via=[nested])
            with self.assertRaises(ValueError):
                k.validate_question_assets()
        k = knowledge()
        k.questions[str(f.OW.Combined)] = QuestionTemplate(text='어떻게 변했나요?', collect_via=[str(f.OW.Amount)])
        with self.assertRaises(ValueError):
            k.validate_question_assets()

    def test_missing_or_blocked_atomic_question_is_rejected(self):
        for template in (None, QuestionTemplate(text='', interviewable=False, reason='missing')):
            k = knowledge()
            if template is None:
                del k.questions[str(f.OW.Amount)]
            else:
                k.questions[str(f.OW.Amount)] = template
            with self.assertRaises(ValueError):
                k.validate_question_assets()


if __name__ == '__main__':
    unittest.main()
