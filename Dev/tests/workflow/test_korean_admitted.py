import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import unicodedata


def verify(submission, output):
    submission, output = submission.resolve(), output.resolve()
    sys.path.insert(0, str(submission))
    from knowledge.graph import OW
    from nova_sdk import RECORD_FIELDS
    from workflow.runtime import assemble_consultation, consult, prepare
    from workflow.state.models import WorkflowState

    output.mkdir(parents=True, exist_ok=True)
    checks = []

    def require(value, name):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    started = time.perf_counter()
    resources = prepare()
    elapsed = time.perf_counter() - started
    knowledge, config = resources.knowledge, resources.config
    manifest_path = submission / 'knowledge/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest['preparation_status'] == 'admitted', 'prepare_uses_admitted_manifest_without_injection')
    require(elapsed < 600 and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss < 8 * 1024 * 1024,
            'prepare_within_declared_time_and_memory')
    original = frozenset(knowledge._graph)
    target = str(OW.SymptomSnomedCT21522001)
    blocked = {key for key, template in knowledge.questions.items() if not template.interviewable}
    allowed_say = {template.text for template in knowledge.questions.values() if template.interviewable}
    allowed_say.update((config.texts.chief_question, config.texts.open_question, config.texts.provisional_education,
        config.texts.symptom_education, config.texts.understanding_question, config.texts.correction_education,
        config.texts.clarification_question, *config.texts.clarification_questions.values()))
    exam_profiles = [profile for profile in knowledge._profile_cache.values()
                     if knowledge.has_type(profile.target, 'ExamFinding')]
    require(bool(exam_profiles), 'admitted_graph_has_a_source_backed_examination')
    exam_target = exam_profiles[0].target
    exam_text = knowledge.get_exam_methods(exam_target)[0]['text']
    context_texts = {template.text for key, template in knowledge.questions.items()
                     if '|' not in key and knowledge.has_type(key, 'ContextFactor') and template.interviewable}
    attribute_texts = {template.text for key, template in knowledge.questions.items() if '|' in key}

    class ScriptedSDK:
        timeout = 120

        def __init__(self, context_status):
            self.session_id = 'app-text20-korean-' + context_status
            self.context_status = context_status
            self.remaining = 50
            self.actions, self.submissions = [], []
            self.unlinked_recoveries = 0
            self.deadline = datetime.now(timezone.utc) + timedelta(minutes=25)

        def session(self):
            return {'session_id':self.session_id, 'status':'active', 'deadline':self.deadline.isoformat(),
                'turns_remaining':self.remaining, 'initial':{'opening':'배가 아파요', 'vital_signs':{'pulse':80}},
                'allowed_actions':['SAY', 'EXAM', 'DIAGNOSE']}

        def chat(self, messages, **kwargs):
            payload = json.loads(messages[1]['content'])
            if payload.get('task') == 'terminology':
                return {'choices':[{'message':{'content':'{"facts":[],"clinical_content":false}'}}],
                        'usage':{'prompt_tokens':20, 'completion_tokens':10}}
            question, text = payload['question'], payload['input']
            facts = []
            available = {entry['id'] for entry in payload['vocabulary']}
            if payload['parser_pass'] == 'expansion' and target in available:
                for original_fact in payload.get('unlinked_facts', []):
                    if original_fact['quote'] == '배가 아파요':
                        repaired = json.loads(json.dumps(original_fact))
                        repaired['value']['concept_ids'] = [target]
                        facts.append(repaired)
                        self.unlinked_recoveries += 1
            if payload['parser_pass'] != 'expansion' and (question is None or
                    question['purpose'] in {'chief', 'hpi', 'ros', 'feature', 'context', 'clarification'}):
                is_context = question is not None and question['purpose'] == 'context'
                is_exam = question is not None and question['kind'] == 'EXAM'
                attr = question['attribute_id'] if question else None
                concept = question['target_id'] if question and question['target_id'] else target
                value = {'kind':'context' if is_context else 'attribute' if attr else 'finding' if is_exam else 'symptom',
                    'text':text, 'status':self.context_status if is_context else 'unknown' if attr else
                        'present' if concept == target or is_exam else 'absent',
                    'concept_ids':[concept] if concept in available else [], 'subject':question['subject'] if question else 'patient',
                    'time_context':question['time_context'] if question else 'current'}
                if not is_context:
                    value.update(observation_id=(question['observation_id'] if question else None) or 'abdominal',
                                 episode_id=(question['episode_id'] if question else None) or 'one')
                if attr:
                    value['attribute_id'] = attr
                fact = {'field':question['field'] if question else 'S.cc', 'quote':text, 'value':value}
                if question:
                    fact['record_id'] = question['item_id']
                facts.append(fact)
            parsed = {'facts': facts, 'clinical_content': text != '모르겠어요'}
            if any(item['field'] == 'S.cc' and not item['value']['concept_ids'] for item in facts):
                parsed.update(needs_context=True, lookup_terms=[knowledge.label(target)])
            return {'choices':[{'message':{'content':json.dumps(parsed, ensure_ascii=False)}}],
                    'usage':{'prompt_tokens':20, 'completion_tokens':10}}

        def action(self, kind, content, request_id):
            require(unicodedata.normalize('NFC', content) == content and 1 <= len(content) <= 30,
                    'delivery_nfc_1_to_30:' + request_id)
            require(any('\uac00' <= char <= '\ud7a3' for char in content), 'delivery_contains_korean:' + request_id)
            require(content in allowed_say if kind == 'SAY' else content == exam_text,
                    'deliver_exact_prepared_wording:' + request_id + ':' + content)
            self.remaining -= 1
            self.actions.append({'kind':kind, 'content':content, 'request_id':request_id})
            response = {'status':'OK', 'turn':50 - self.remaining, 'turns_remaining':self.remaining}
            response['content' if kind == 'SAY' else 'result'] = ('다리 혈관에서 잡음이 들립니다' if kind == 'EXAM' else
                '배가 아파요' if content == config.texts.chief_question else
                {'present':'네, 해당 내용이 있어요', 'absent':'그런 내용은 없어요', 'unknown':'모르겠어요'}.get(self.context_status, '모르겠어요')
                if content in context_texts else '모르겠어요' if content in attribute_texts else '다른 증상은 없어요')
            return response

        def say(self, content, request_id):
            return self.action('SAY', content, request_id)

        def exam(self, content, request_id):
            return self.action('EXAM', content, request_id)

        def diagnose(self, **payload):
            note = payload['note']
            require(set(payload) == {'note', 'diagnosis', 'request_id'} and bool(payload['diagnosis']), 'diagnose_wire_contract')
            require(set(note) == set(RECORD_FIELDS) and all(set(note[section]) == set(fields)
                    for section, fields in RECORD_FIELDS.items()), 'exact_fifteen_soap_fields')
            require(all(isinstance(text, str) for fields in note.values() for text in fields.values()) and
                    note['O']['tests'] == '', 'soap_strings_and_no_unperformed_tests')
            self.submissions.append(payload)
            return {'status':'completed'}

    cases = []
    for context_status in ('present', 'absent', 'unknown'):
        client = ScriptedSDK(context_status)
        outcome = WorkflowState.model_validate(consult(client, resources))
        delivered = [entry for entry in outcome.interaction.history if entry.delivered and entry.question]
        ros = [entry for entry in delivered if entry.question.purpose == 'ros']
        contexts = [entry for entry in delivered if entry.question.purpose == 'context']
        require(outcome.interaction.termination == 'submitted' and len(client.submissions) == 1,
                'confirmed_submission:' + context_status)
        require(client.unlinked_recoveries > 0, 'bounded_korean_complaint_link_recovery:' + context_status)
        require(outcome.session.usage['Education'].actions == 0 and outcome.session.usage['Education'].calls == 0
                and not any(entry.question.purpose == 'education' for entry in delivered)
                and client.submissions[0]['note']['P']['education'] == '', 'education_pass:' + context_status)
        require(any(entry.question.purpose == 'feature' for entry in delivered),
                'context_reaches_diagnostic_questions:' + context_status)
        require(client.actions[0]['content'] == config.texts.chief_question and
                any(entry.question.purpose == 'hpi' for entry in delivered) and
                any(entry.question.purpose == 'open_inquiry' for entry in delivered), 'greeting_hpi_and_open_inquiry:' + context_status)
        require(0 < len(ros) <= 6, 'bounded_ros:' + context_status)
        require(not any(entry.question.target_id in blocked for entry in delivered), 'exclude_noninterviewable_targets:' + context_status)
        require(all(h.context_bonus in {0, 1} for h in outcome.differential.hypotheses), 'context_bonus_cap:' + context_status)
        require(any(h.context_bonus == 1 for h in outcome.differential.hypotheses) if context_status == 'present' and contexts else
                all(h.context_bonus == 0 for h in outcome.differential.hypotheses), 'context_polarity_semantics:' + context_status)
        require(all(exchange['role'] in {'gateway', 'terminology', 'empathy'} for exchange in outcome.interaction.model_history)
                and outcome.session.gateway_successes > 0, 'bounded_designated_model_roles:' + context_status)
        for exchange in outcome.interaction.model_history:
            metrics = exchange['parser_payload']
            expanded = metrics['pass'] != 'primary'
            require(metrics['vocabulary_count'] <= (1024 if expanded else 256) and
                    metrics['vocabulary_bytes'] <= (131072 if expanded else 32768), 'bounded_gateway_projection:' + context_status)
            require(metrics['request_bytes'] <= metrics['request_byte_limit'] <= (16384 if expanded else 12288),
                    'bounded_complete_gateway_request:' + context_status)
        (output / ('case-' + context_status + '.json')).write_text(outcome.model_dump_json(indent=2))
        cases.append({'context_status':context_status, 'termination':outcome.interaction.termination,
            'diagnosis_kind':outcome.case.diagnosis_kind, 'actions':len(client.actions), 'ros_actions':len(ros),
            'context_actions':len(contexts), 'scripted_gateway_calls':outcome.session.doctor_calls})

    context_cases = []
    for context_status in ('present', 'absent', 'unknown'):
        client = ScriptedSDK(context_status)
        consultation = assemble_consultation(client, resources)
        state = consultation.nova_session.initialize_case(client)
        consultation.interpreter.process_input(state, knowledge, client)
        state.session.current = 'ContextFactor'
        state.session.initialized = True
        consultation.reasoner.retrieve_candidates(state)
        context = next(c for h in state.differential.hypotheses for c in knowledge.get_supporting_context(h.disease_id)
                       if knowledge.questions[c['id']].interviewable)
        subject = 'family' if context['type'] == 'family_history' else 'patient'
        field = 'S.fh' if subject == 'family' else 'S.sh' if context['type'] in {
            'social_history', 'occupational_history', 'psychosocial_history', 'demographic'} else 'S.pmh'
        spec = consultation.planner._spec(state, context['id'], purpose='context', field=field,
                                          subject=subject, time_context='unspecified')
        consultation.planner._register(state, spec, 0, 1)
        consultation.planner.select_question(state)
        consultation.doctor.validate_action(state)
        consultation.doctor.execute_action(state, client)
        consultation.interpreter.process_input(state, knowledge, client)
        consultation.finalize(state)
        consultation.writer.submit_diagnosis(state)
        consultation.writer.confirm_submission(state)
        require(state.interaction.termination == 'submitted' and len(client.submissions) == 1,
                'selected_context_confirmed_submission:' + context_status)
        require(any(item.value and item.value.status == context_status and context['id'] in item.value.concept_ids
                    and item.source_refs for _, item in state.case.entries()), 'selected_context_polarity:' + context_status)
        require(any(h.context_bonus == 1 for h in state.differential.hypotheses) if context_status == 'present' else
                all(h.context_bonus == 0 for h in state.differential.hypotheses), 'selected_context_bonus:' + context_status)
        section, name = field.split('.')
        require(client.submissions[0]['note'][section][name] and client.submissions[0]['note']['P']['education'] == '',
                'selected_context_soap_and_education_pass:' + context_status)
        (output / ('case-selected-context-' + context_status + '.json')).write_text(state.model_dump_json(indent=2))
        context_cases.append({'status':context_status, 'target':context['id'], 'field':field, 'termination':state.interaction.termination})

    client = ScriptedSDK('examination')
    consultation = assemble_consultation(client, resources)
    state = consultation.nova_session.initialize_case(client)
    consultation.interpreter.process_input(state, knowledge, client)
    state.session.current = 'DifferentialDiagnosis'
    state.session.initialized = True
    spec = consultation.planner._spec(state, exam_target, episode='one')
    consultation.planner._register(state, spec, 0, 1)
    consultation.planner.select_question(state)
    consultation.doctor.validate_action(state)
    consultation.doctor.execute_action(state, client)
    consultation.interpreter.process_input(state, knowledge, client)
    require(any(field == 'O.exam' and item.value and exam_target in item.value.concept_ids
                and item.source_refs for field, item in state.case.entries()), 'exam_reply_becomes_acquired_objective_evidence')
    consultation.finalize(state)
    consultation.writer.submit_diagnosis(state)
    consultation.writer.confirm_submission(state)
    require(state.interaction.termination == 'submitted' and len(client.submissions) == 1, 'exam_path_confirmed_submission')
    require('다리 혈관에서 잡음이 들립니다' in client.submissions[0]['note']['O']['exam'], 'exam_wording_and_result_reach_soap')
    require(frozenset(knowledge._graph) == original, 'shared_admitted_graph_remains_readonly')
    (output / 'case-examination.json').write_text(state.model_dump_json(indent=2))
    report = {'status':'pass', 'check_count':len(checks), 'checks':checks, 'cases':cases, 'selected_context_cases':context_cases,
        'examination':{'status':'pass', 'target':exam_target, 'scope':'separate selected-action acquisition through SOAP and confirmed submission'},
        'prepare_seconds':elapsed, 'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'graph_triples':len(original), 'associations':len(knowledge._profile_cache),
        'prepared_say_questions':sum(q.interviewable for q in knowledge.questions.values()), 'blocked_targets':len(blocked),
        'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'patient_data':'synthetic Korean', 'model_responses':'scripted', 'network':'none',
        'actual_luna':'not_run', 'authenticated_sdk':'not_run', 'official_submission':'not_run'}
    (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key:value for key, value in report.items() if key != 'checks'}, ensure_ascii=True, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--submission', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.submission, args.output)
