from nova_sdk import RECORD_FIELDS, NovaError

from .rules.action import failure_outcome
from .rules.collection import CATEGORY_FIELDS
from .rules.limits import LIMITS
from .rules.submission import validate_payload, validate_wire_payload
from .rules.minimal_record import minimal_payload
from .rules.input import objective
from .state.models import TurnContext


class SubmissionWriter:
    def __init__(self, client, knowledge, config, executor, nova_session, new_request_id):
        self.client, self.knowledge, self.config = client, knowledge, config
        self.executor, self.nova_session, self.new_request_id = executor, nova_session, new_request_id

    def _line(self, category, content):
        content = '; '.join(line.strip() for line in str(content).splitlines() if line.strip())
        return self.config.texts.category_format.format(category=category, content=content)

    def _unit(self, unit, value):
        label = self.config.texts.unit_labels.get(unit, unit)
        return label + 's' if unit in {'day', 'week', 'month', 'year'} and value != 1 else label

    def _measurement(self, measured):
        texts = self.config.texts
        prefix = texts.approximate_label + ' ' if measured.approximate else ''
        if measured.kind == 'quantity':
            if measured.unit.casefold() == 'nrs':
                return prefix + texts.nrs_format.format(value=f'{measured.value:g}')
            return prefix + texts.measurement_format.format(operator=texts.operator_labels['eq'],
                value=f'{measured.value:g}', unit=self._unit(measured.unit, measured.value)).strip()
        upper_unit = measured.upper_unit or measured.unit
        if measured.lower is not None and measured.upper is not None and measured.lower_inclusive and measured.upper_inclusive and upper_unit == measured.unit:
            return prefix + texts.range_format.format(lower=f'{measured.lower:g}', upper=f'{measured.upper:g}',
                unit=self._unit(measured.unit, measured.upper))
        return prefix + texts.interval_format.format(lower_bound='[' if measured.lower_inclusive else '(',
            upper_bound=']' if measured.upper_inclusive else ')',
            lower=f'{measured.lower:g} {self._unit(measured.unit, measured.lower)}' if measured.lower is not None else '−∞',
            upper=f'{measured.upper:g} {self._unit(upper_unit, measured.upper)}' if measured.upper is not None else '∞')

    def _context(self, fact, episodes):
        texts = self.config.texts
        parts = []
        if fact.subject == 'family':
            parts.append(texts.subject_labels['family'] + (': ' + fact.subject_member if fact.subject_member else ''))
        if fact.time_context == 'past':
            parts.append(texts.time_labels['past'])
        if getattr(fact, 'polarity_scope', 'general') == 'qualified':
            parts.append(texts.qualified_scope_label)
        target = getattr(fact, 'target', '')
        related = {key[2] for key in episodes if key[0] == fact.subject and key[1] == target}
        if len(related) > 1 and fact.episode_id:
            parts.append(texts.episode_format.format(number=episodes[(fact.subject, target, fact.episode_id)]))
        return ' (' + '; '.join(parts) + ')' if parts else ''

    def _details(self, fact):
        return '; '.join([*fact.values, *([self._measurement(fact.measurement)] if fact.measurement else [])])

    def _describe(self, fact, episodes):
        status = self.config.texts.status_labels[fact.status]
        if fact.attribute:
            content = self._details(fact)
            if fact.status != 'present':
                content = f'({status})' + ('; ' + content if content else '')
            return f'{fact.target} - {fact.attribute}: {content}' + self._context(fact, episodes)
        return f'{fact.target} ({status})' + self._context(fact, episodes)

    def _destination(self, fact):
        if objective(fact.acquisition,fact.source_ref) and (fact.kind=='finding' or fact.kind=='attribute'):
            return 'O.exam'
        if fact.subject == 'family':
            return 'S.fh'
        if fact.category in CATEGORY_FIELDS:
            return CATEGORY_FIELDS[fact.category]
        if fact.kind == 'context':
            ident = self.knowledge.term_id(fact.target, 'ContextFactor')
            kind = self.knowledge.get_context_type(ident)
            return 'S.sh' if kind in {'social_history', 'occupational_history', 'psychosocial_history', 'demographic'} else 'S.pmh'
        if fact.time_context == 'past':
            return 'S.pmh'
        return 'S.hpi' if fact.attribute else 'S.ros'

    def build_record_view(self, case):
        texts = self.config.texts
        fields = {f'{section}.{name}':[] for section,names in RECORD_FIELDS.items() for name in names}
        references, episodes, groups = {}, {}, {}
        facts = tuple(f for f in case.current_facts() if f.graph_binding)
        for fact in facts:
            if fact.episode_id:
                episodes.setdefault((fact.subject,fact.target,fact.episode_id),len(episodes)+1)
        chief = case.chief(confirmed=True)
        if chief:
            fields['S.cc'].append(self._line(texts.soap_labels['cc'],chief.target))
        used = set()
        for key, label in [('age','Age'),('sex','Sex'),('reporter','Historian')]:
            for note in case.current_facts():
                if note.context_key!=key or note.subject!='patient':
                    continue
                content = self._measurement(note.measurement) if note.measurement else note.value
                if note.status!='present':
                    content += f' ({texts.status_labels[note.status]})'
                fields['S.hpi'].append(self._line(label,content)); used.add(note.id)
        for fact in facts:
            destination = ('S.hpi' if chief and fact.id==chief.id else self._destination(fact))
            if chief and destination not in {'O.exam','S.fh'} and (
                fact.target,fact.observation_id,fact.episode_id,fact.time_context)==(
                chief.target,chief.observation_id,chief.episode_id,chief.time_context):
                destination = 'S.hpi'
            acquired = (fact.acquisition,fact.source_ref,fact.turn) if destination=='O.exam' else ()
            key = (destination,fact.subject,fact.subject_member,fact.target,fact.observation_id,
                fact.episode_id,fact.time_context,fact.polarity_scope,acquired)
            groups.setdefault(key,[]).append(fact)
        ordered = sorted(groups.items(),key=lambda pair:(pair[0][0],
            not any(chief and f.id==chief.id for f in pair[1]),min(f.turn for f in pair[1]),pair[1][0].id))
        for key, members in ordered:
            destination = key[0]
            parts = []
            for fact in sorted(members,key=lambda f:(bool(f.attribute),f.turn,f.id)):
                phrase = self._describe(fact,episodes)
                if fact.value:
                    phrase += ' (' + fact.value + ')'
                if destination=='O.exam':
                    phrase = (texts.initial_exam_format.format(text=phrase) if fact.acquisition=='initial'
                        else texts.exam_turn_format.format(text=phrase,turn=fact.turn))
                references[fact.id] = phrase
                if phrase not in parts:
                    parts.append(phrase)
            fields[destination].append(self._line(texts.soap_labels['exam'] if destination=='O.exam' else
                texts.soap_labels['hpi'] if destination=='S.hpi' else members[0].target,'; '.join(parts)))
        for note in case.current_facts():
            if note.id in used or note.graph_binding:
                continue
            if note.category=='objective_observation' and objective(note.acquisition,note.source_ref):
                destination='O.exam'
            else:
                destination='S.fh' if note.subject=='family' else CATEGORY_FIELDS.get(note.category,'S.hpi')
            content = '; '.join(filter(None,(note.value,self._measurement(note.measurement) if note.measurement else '')))
            phrase = content + f' ({texts.status_labels[note.status]})' + self._context(note,episodes)
            if destination=='O.exam':
                phrase = (texts.initial_exam_format.format(text=phrase) if note.acquisition=='initial'
                    else texts.exam_turn_format.format(text=phrase,turn=note.turn))
            fields[destination].append(self._line(texts.record_labels.get(note.category,'Patient report'),phrase))
        return fields, references

    def _assessment_text(self, entry, references):
        parts = []
        for label, refs in [('Supporting findings',entry.supports),('Less compatible findings',entry.against)]:
            whole, partial = [], []
            for ref in refs:
                if any(i not in references for i in ref.fact_ids):
                    raise ValueError('dangling_frozen_evidence')
                phrases = [references[i] for i in ref.fact_ids]
                (partial if ref.graph_ref.kind=='feature' and label=='Supporting findings' else whole).extend(phrases)
            if whole:
                parts.append(self._line(label,'; '.join(dict.fromkeys(whole))))
            if partial:
                parts.append(self._line('Partially compatible findings','; '.join(dict.fromkeys(partial))))
        unresolved = []
        for ref in entry.unresolved:
            if ref.scope:
                _,target,attribute,subject,member,timing,_,_ = ref.scope
                description = target + (' - '+attribute if attribute else '')
                if subject=='family': description += ' (family'+(': '+member if member else '')+')'
                if timing=='past': description += ' (past)'
                unresolved.append(description+': '+ref.reason)
        if unresolved:
            parts.append(self._line('Unconfirmed','; '.join(dict.fromkeys(unresolved))))
        return self.config.texts.record_separator.join(parts)

    def build_soap(self, state):
        if state.session.termination == 'submitted':
            return
        if state.turn and state.turn.kind!='submission':
            raise ValueError('pending_action_at_finalization')
        primary = state.case.primary()
        assessment = state.case.assessment
        if (assessment.based_on_case_revision,assessment.based_on_chief_fact_id)!=(state.case.revision,state.case.chief_fact_id):
            raise ValueError('stale_frozen_assessment')
        fields, references = self.build_record_view(state.case)
        texts = self.config.texts
        fields['A.evidence'] = [self._line('Diagnosis','#1. '+primary.name),self._line('Certainty','Working diagnosis'),
            self._assessment_text(primary,references)]
        if primary.kind=='symptom':
            fields['A.evidence'].append(self._line('Assessment',texts.symptom_assessment))
        if assessment.limitations:
            fields['A.evidence'].append(self._line('Incomplete assessment','; '.join(assessment.limitations)))
        fields['A.differential'] = [self._line('r/o '+entry.name,self._assessment_text(entry,references))
            for entry in assessment.differential[1:]]
        for sentence in state.case.plan:
            if sentence.field=='education' and not self.config.education_enabled:
                continue
            label = texts.soap_labels[sentence.field]
            if sentence.field=='education':
                answers = [a for a in state.interview.answers if a.plan_sentence_id==sentence.id]
                pending = any(q.plan_sentence_id == sentence.id for q in state.interview.queue)
                expected = state.interview.education_utterances.get(sentence.id)
                delivered = bool(expected) and len(answers) == expected and not pending and all(a.outcome=='delivered' for a in answers)
                label = 'Education delivered' if delivered else 'Education planned (not delivered)'
            fields['P.'+sentence.field].append(self._line(label,sentence.text))
        note = {section:{name:texts.record_separator.join(filter(None,fields[f'{section}.{name}']))
            for name in names} for section,names in RECORD_FIELDS.items()}
        payload = {'note':note,'diagnosis':primary.name}
        state.session.final_payload = payload
        if state.turn is None:
            state.turn = TurnContext(kind='submission',stage='ready',payload=payload)
        else:
            state.turn.payload,state.turn.error = payload,None

    def build_minimal(self, state, reason):
        state.interview.collection['submission:minimal'] = reason
        repairs = state.turn.repairs if state.turn and state.turn.kind == 'submission' else 0
        payload = minimal_payload(state.case, state.interview, state.case.diagnosis, compact=bool(repairs))
        state.turn = TurnContext(kind='submission', stage='ready', payload=payload, repairs=repairs)
        state.session.final_payload = payload

    def validate_submission(self, state):
        if state.session.termination == 'submitted':
            return
        state.turn.error = None
        try:
            if 'submission:minimal' in state.interview.collection:
                validate_wire_payload(state.turn.payload)
            else:
                validate_payload(state)
        except (KeyError, TypeError, ValueError) as error:
            state.turn.error = str(error)

    def submit_diagnosis(self, state):
        if state.session.termination:
            return
        refreshed = False
        try:
            self.nova_session.refresh_snapshot(state, self.client, final=True)
            refreshed = True
        except (NovaError, TypeError, ValueError) as error:
            state.interview.collection['submission:refresh'] = getattr(error, 'code', str(error))
        try:
            if state.session.termination:
                return
            if refreshed and 'DIAGNOSE' not in state.session.allowed_actions:
                state.stop('closed', 'diagnosis_not_allowed')
                return
            validate_wire_payload(state.turn.payload)
            turn = state.turn
            turn.request_id = turn.request_id or self.new_request_id()
            state.session.submission_request_id = turn.request_id
            request = {**turn.payload, 'request_id':turn.request_id}
            attempts = []
            turn.response = self.executor.execute(state, self.client, self.client.diagnose, request, attempts, final=True)
            turn.stage = 'received'
        except NovaError as error:
            if error.code == 'INVALID_RECORD_FIELDS' and state.turn and state.turn.repairs < LIMITS.submission_repairs:
                state.turn.error = error.code
            else:
                state.stop(failure_outcome(error), error.code)
                if state.turn:
                    state.turn.error = error.code
        except (TypeError, ValueError):
            state.stop('unknown', 'invalid_submission_response')

    def confirm_submission(self, state):
        if state.session.termination:
            return
        turn = state.turn
        if (turn and isinstance(turn.response, dict) and turn.response.get('status') == 'completed'
                and turn.response.get('request_id', turn.request_id) == turn.request_id):
            state.session.receipt = {**turn.response, 'request_id':turn.request_id}
            state.session.termination = 'submitted'
            state.turn = None
        else:
            state.stop('unknown', 'unconfirmed_submission')

    def begin_repair(self, state):
        if state.turn.repairs >= LIMITS.submission_repairs:
            raise ValueError('Submission repair limit reached')
        state.turn.repairs += 1
        state.turn.request_id = None
