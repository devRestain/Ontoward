"""Use production candidate assessment and QuestionTools for augmentation gates."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from knowledge.graph import ClinicalKnowledge
from workflow.rules.assessment import graph_candidates
from workflow.rules.budget import BudgetPolicy
from workflow.rules.questions import QuestionTools
from workflow.state.interactions import InteractionLifecycle
from workflow.state.questions import QuestionLifecycle
from workflow.state.models import CaseFact, GraphBinding, SessionContext, WorkflowState
from workflow.text_config import TextConfig


def runtime_tools(knowledge):
    now = datetime.now(timezone.utc)
    interactions = InteractionLifecycle(lambda: str(uuid4()))
    return QuestionTools(knowledge, TextConfig.load(), QuestionLifecycle(interactions), interactions,
                         BudgetPolicy(lambda: now))


def runtime_state():
    state = WorkflowState(session=SessionContext(session_id='augmentation-offline-probe',
        deadline=datetime.now(timezone.utc) + timedelta(minutes=25), turns_remaining=50))
    state.interview.current = 'DifferentialDiagnosis'
    state.interview.status = 'collecting'
    return state


def runtime_fact(knowledge, ident, *, status='present', subject='patient', member=None,
                 time='current', attribute=None, values=(), measurement=None, **kwargs):
    kind = ('attribute' if attribute else 'context' if knowledge.has_type(ident, 'ContextFactor')
            else 'finding' if knowledge.has_type(ident, 'ExamFinding') else 'symptom')
    source = 'probe:' + str(uuid4())
    return CaseFact(id=source, source_ref=source, graph_binding=GraphBinding(kind=kind,
        target=knowledge.term(ident), attribute=knowledge.term(attribute) if attribute else None,
        values=tuple(knowledge.term(i) for i in values)), measurement=measurement, status=status,
        subject=subject, subject_member=member, time_context=time, observation_id='probe-observation',
        episode_id='probe-episode', acquisition='EXAM' if kind == 'finding' else 'SAY', **kwargs)


def verify_reachability(manifest, plan):
    knowledge = ClinicalKnowledge.load(manifest)
    tools = runtime_tools(knowledge)
    rows = []
    for cluster in plan['seed']['clusters']:
        for need in cluster['required_concepts']:
            if not any(knowledge.has_type(i, need['kind']) for i in knowledge.resolve_concept(need['name'])):
                raise ValueError('required_concept_missing:' + need['name'])
        for name in cluster['required_candidates']:
            disease = knowledge.term_id(name, 'Disease')
            if not disease:
                raise ValueError('required_candidate_missing:' + name)
            for target in cluster['target_ids']:
                state = runtime_state()
                state.case.apply([runtime_fact(knowledge, target)])
                candidates = graph_candidates(state.case, knowledge, state.interview)
                if disease not in candidates:
                    raise ValueError('required_candidate_unreachable:' + name + ':' + target)
                candidate = candidates[disease]
                options = tools._options(state, {disease: candidate})
                if candidate.entry.unresolved and not options:
                    raise ValueError('required_candidate_has_no_executable_unresolved_question:' + name)
                rows.append(dict(cluster=cluster['id'], disease_id=disease, target_id=target,
                    supports=len(candidate.entry.supports), unresolved=len(candidate.entry.unresolved),
                    executable_questions=len(options)))
    controls = verify_first_seed_controls(knowledge, tools, plan)
    return dict(status='pass', probes=rows, controls=controls,
        boundary='Production functions with synthetic facts; actual-model quality and clinical accuracy are not evaluated',
        applicability_drug_episode_join='not_implemented')


def verify_first_seed_controls(knowledge, tools, plan):
    """Finite seed-specific counterexamples, outside the consultation runtime."""
    clusters = {c['id']: c for c in plan['seed']['clusters']}
    results = []
    def require(condition, label):
        if not condition:
            raise ValueError('augmentation_clinical_structure_control_failed:' + label)
        results.append(label)
    def ident(name, kind='ContextFactor'):
        result = knowledge.term_id(name, kind)
        if not result:
            raise ValueError('control_concept_missing:' + name)
        return result
    def candidates(facts):
        state = runtime_state()
        state.case.apply(facts)
        return state, graph_candidates(state.case, knowledge)
    if 'insomnia_medication' in clusters:
        cluster = clusters['insomnia_medication']
        use = ident(cluster['required_candidates'][0], 'Disease')
        hypnotic = cluster['reference_ids'][0]
        failed = ident('Unsuccessful attempts to reduce hypnotic use')
        harm = ident('Continued hypnotic use despite harm')
        failed_time = knowledge.question_contract(failed).time_context
        harm_time = knowledge.question_contract(harm).time_context
        base = [runtime_fact(knowledge, cluster['target_ids'][0]), runtime_fact(knowledge, hypnotic)]
        state, found = candidates(base)
        require(use in found and not found[use].entry.supports, 'insomnia_behavior_unknown_candidate_without_support')
        options = tools._options(state, {use: found[use]})
        require(failed in {s['target_id'] for s, _ in options.values()}, 'impaired_control_dd_context_question')
        _, found = candidates([*base, runtime_fact(knowledge, failed, status='absent', time=failed_time), runtime_fact(knowledge, harm, status='absent', time=harm_time)])
        require(use not in found or not found[use].entry.supports, 'normal_use_not_use_disorder_support')
        dependence = CaseFact(id='dependence-note', source_ref='offline-probe', category='medication',
            value='Tolerance or physical dependence reported during prescribed use; behavior criteria not established',
            status='present', time_context='past', acquisition='SAY')
        _, found = candidates([*base, dependence])
        require(use not in found or not found[use].entry.supports, 'dependence_note_not_automatic_use_disorder_support')
        _, found = candidates([runtime_fact(knowledge, hypnotic), runtime_fact(knowledge, failed, time=failed_time), runtime_fact(knowledge, harm, time=harm_time)])
        require(use in found, 'behavior_candidate_without_insomnia')
        weight = knowledge.term_id('Weight loss', 'Symptom')
        heat = knowledge.term_id('Heat intolerance', 'Symptom')
        thyroid = knowledge.term_id('Hyperthyroidism', 'Disease')
        if weight and heat and thyroid:
            _, found = candidates([runtime_fact(knowledge, weight), runtime_fact(knowledge, heat)])
            require(thyroid in found, 'pathological_thyroid_candidate_control')
            require(use not in found or not found[use].entry.supports, 'thyroid_findings_not_automatic_use_disorder_support')
    if 'short_stature' in clusters:
        cluster = clusters['short_stature']
        cdgp, fss = [ident(name, 'Disease') for name in cluster['required_candidates']]
        late = ident('Family history of late growth or maturation')
        parental = ident('Parental short stature')
        velocity = ident('Height velocity', 'FindingAttribute')
        trajectory = ident('Linear growth trajectory', 'FindingAttribute')
        declining = knowledge.value_id('Linear growth trajectory', 'Declining linear growth trajectory')
        require(bool(declining), 'registered_declining_growth_value')
        for target in cluster['target_ids']:
            family_state,family_candidates=candidates([runtime_fact(knowledge,target)])
            require(late in {s['target_id'] for s,_ in tools._options(family_state,{cdgp:family_candidates[cdgp]}).values()},
                    'family_late_maturation_dd_question:' + target)
            require(velocity in knowledge.get_symptom_attributes(target) and knowledge.numeric_units(target, velocity) == ['cm/year'],
                    'height_velocity_quantity_units:' + target)
            _, found = candidates([runtime_fact(knowledge, target), runtime_fact(knowledge, late, status='absent', subject='family', time='past')])
            require(cdgp in found, 'negative_family_history_keeps_cdgp_path:' + target)
            state, found = candidates([runtime_fact(knowledge, target),
                runtime_fact(knowledge, target, attribute=trajectory, values=[declining]),
                runtime_fact(knowledge, target, attribute=velocity, measurement=dict(kind='quantity', value=1.0, unit='cm/year')),
                runtime_fact(knowledge, late, subject='family', time='past'),
                runtime_fact(knowledge, parental, subject='family', time='past')])
            require(all(d not in found or not found[d].entry.supports for d in (cdgp, fss)),
                    'declining_growth_not_automatic_normal_variant:' + target)
            require(not any(s['attribute_id'] == velocity for s, _ in tools._options(state, found).values()),
                    'provided_velocity_not_reasked:' + target)
    return results
