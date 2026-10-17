"""D38 semantic and consultation acceptance with deterministic source-shaped cases."""
import itertools
import json
import unittest

import test_workflow as f
from knowledge.conditions import ExpectedValue, FeatureCondition, QuestionTemplate, numeric_match
from knowledge.graph import OW
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.rules.selection import answer_patch, answer_regions, decision_value, QuestionEvaluation, question_key
from workflow.state.evidence import EvidenceIndex
from workflow.state.models import ClinicalValue, Fact, InteractionEntry, ParseResult, RecordItem


def snapshot(k, state):
    state.case.select_primary()
    reasoner = ClinicalReasoner(k)
    return reasoner, reasoner.evaluate(EvidenceIndex.from_case(state.case), reasoner.anchor(state.case))


def clinical(snapshot):
    return {"hypotheses": [h.model_dump() for h in snapshot.hypotheses],
            "patterns": {key: value.model_dump() for key, value in snapshot.pattern_matches.items()},
            "associations": [value.model_dump() for value in snapshot.association_matches]}


class Algorithm(unittest.TestCase):
    def test_delta_equals_isolated_full_evaluation_and_preserves_real_state(self):
        for status, context in itertools.product(("present", "absent"), ("present", "absent", "unknown")):
            with self.subTest(status=status, context=context):
                k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
                f.record(state)
                f.record(state, "context", OW.Context, "context", context, "S.pmh")
                reasoner, base = snapshot(k, state)
                planner = f.make_planner(k, f.CONFIG)
                specs = [planner._spec(state, str(OW.Complaint), str(OW.Location), "obs1", "episode1"),
                         planner._spec(state, str(OW.ExamX), episode="episode1"),
                         planner._spec(state, str(OW.Context), purpose="context", field="S.pmh", time_context="current")]
                before = state.model_dump()
                for spec in specs:
                    patch = (answer_patch(spec, status=status, values=[str(OW.Here)] if spec["attribute_id"] else []),)
                    projected = reasoner.evaluate_delta(base, patch)
                    isolated = state.model_copy(deep=True)
                    for field, item in patch:
                        isolated.case.put(field, item.model_copy(deep=True))
                    _, full = snapshot(k, isolated)
                    self.assertEqual(clinical(projected), clinical(full))
                self.assertEqual(state.model_dump(), before)

    def test_false_and_unknown_prerequisites_cannot_create_phantom_support(self):
        for context in ("absent", "unknown", "present"):
            k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
            f.add_v5_pattern(k, "conditional", OW.Other, [], applicability=[{
                "concept_id": str(OW.Context), "status": "present", "subject": "patient", "time_context": "current"}])
            f.record(state)
            f.record(state, "context", OW.Context, "context", context, "S.pmh")
            reasoner, base = snapshot(k, state)
            spec = f.make_planner(k, f.CONFIG)._spec(state, str(OW.Other), episode="episode1")
            after = reasoner.evaluate_delta(base, (answer_patch(spec),))
            a = next(h for h in base.hypotheses if h.disease_id == str(OW.Alpha))
            b = next(h for h in after.hypotheses if h.disease_id == str(OW.Alpha))
            self.assertEqual(b.score - a.score, 4 if context == "present" else 0)

    def test_delta_replacement_recomputes_old_and_new_dependency_scopes(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.add_v5_pattern(k, "newSupport", OW.Other, [])
        f.record(state)
        f.record(state, "changing", OW.Other, field="S.ros")
        f.record(state, "context", OW.Context, "context", "present", "S.pmh")
        reasoner, base = snapshot(k, state)
        for record_id in ("changing", "context"):
            for status in ("present", "absent", "unknown"):
                field = "S.pmh" if record_id == "context" else "S.ros"
                item = state.case.get(record_id).model_copy(deep=True)
                item.value.status = status
                item.value.time_context = "past"
                patch = ((field, item),)
                after = reasoner.evaluate_delta(base, patch)
                isolated = state.model_copy(deep=True)
                isolated.case.put(field, item)
                _, full = snapshot(k, isolated)
                self.assertEqual(clinical(after), clinical(full))

    def test_score_components_cap_support_and_anchor_exact_occurrence(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        k._graph.add((OW.Third, f.RDF.type, OW.Symptom))
        f.add_v5_pattern(k, "otherSupport", OW.Other, [])
        f.add_v5_pattern(k, "thirdSupport", OW.Third, [])
        f.add_v5_pattern(k, "chiefElsewhere", OW.Complaint, [(OW.Location, {"kind": "concept", "concept": str(OW.Elsewhere)})])
        f.record(state)
        f.record(state, "other", OW.Other, field="S.ros")
        f.record(state, "third", OW.Third, field="S.ros")
        f.record(state, "other-episode", OW.Complaint, field="S.ros", episode="episode2")
        f.record(state, "detailed-other-episode", field="S.hpi", kind="attribute", episode="episode2",
                 attribute=OW.Location, values=[OW.Elsewhere])
        _, result = snapshot(k, state)
        alpha = next(h for h in result.hypotheses if h.disease_id == str(OW.Alpha))
        self.assertEqual((alpha.chief_score, alpha.supporting_raw, alpha.supporting_score, alpha.score), (1, 8, 4, 5))

    def test_common_support_has_zero_discrimination_and_duplicate_rows_do_not_inflate(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.add_v5_pattern(k, "commonAlpha", OW.Other, [])
        f.add_v5_pattern(k, "commonBeta", OW.Other, [], disease=OW.Beta)
        f.record(state)
        reasoner, base = snapshot(k, state)
        planner = f.make_planner(k, f.CONFIG)
        common = planner._spec(state, str(OW.Other), episode="episode1")
        outcomes = [reasoner.evaluate_delta(base, (answer_patch(common, status=status),)) for status in ("present", "absent")]
        candidates = [h.disease_id for h in base.hypotheses]
        self.assertEqual(decision_value(base, outcomes, candidates, k.reasoning), (0, 0))
        exam = planner._spec(state, str(OW.ExamX), episode="episode1")
        outcomes = [reasoner.evaluate_delta(base, (answer_patch(exam, status=status),)) for status in ("present", "absent")]
        value = decision_value(base, outcomes, candidates, k.reasoning)
        self.assertGreater(value[0], 0)
        self.assertEqual(value, decision_value(base, outcomes * 3, list(reversed(candidates)), k.reasoning))

    def test_numeric_regions_keep_threshold_order_calendar_units_and_ranges(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        patterns = []
        for index, cut in enumerate((2, 4)):
            _, pattern = f.add_v5_pattern(k, f"duration{index}", OW.Other,
                [(OW.EpisodeDuration, {"kind": "quantity", "value": cut, "unit": "day", "operator": "gt"})])
            patterns.append(str(pattern))
        reasoner = ClinicalReasoner(k)
        k.questions[str(OW.Other) + "|" + str(OW.EpisodeDuration)] = QuestionTemplate(text="얼마나 지속되나요?", answer_type="duration")
        spec = f.make_planner(k, f.CONFIG)._spec(state, str(OW.Other), str(OW.EpisodeDuration), "observation", "episode1")
        answers, complete = answer_regions(spec, k, reasoner, patterns, 512)
        checks = set()
        for patch in answers:
            items = [item for _, item in patch]
            checks.add(tuple(reasoner._match(k.get_pattern_features(p)[1] if k.get_pattern_features(p)[0].attribute is None
                else k.get_pattern_features(p)[0], str(OW.Other), "present", [], items)[0] for p in patterns))
        self.assertTrue(complete)
        self.assertIn(("contradicted", "contradicted"), checks)
        self.assertIn(("matched", "contradicted"), checks)
        self.assertIn(("matched", "matched"), checks)
        from knowledge.conditions import numeric_match
        self.assertEqual(numeric_match(ExpectedValue(kind="quantity", value=2.0, unit="month", operator="gt"),
            ExpectedValue(kind="quantity", value=90.0, unit="day")), "unknown")

    def test_independent_numeric_and_concept_set_truth_tables(self):
        numeric_rows = [
            ({"kind":"quantity","value":2,"unit":"day","operator":"gt"}, 2, "day", "contradicted"),
            ({"kind":"quantity","value":2,"unit":"day","operator":"ge"}, 2, "day", "matched"),
            ({"kind":"quantity","value":2,"unit":"day","operator":"lt"}, 2, "day", "contradicted"),
            ({"kind":"quantity","value":2,"unit":"day","operator":"le"}, 2, "day", "matched"),
            ({"kind":"interval","lower":5,"upper":14,"unit":"day","lower_inclusive":False}, 5, "day", "contradicted"),
            ({"kind":"interval","lower":5,"upper":14,"unit":"day","upper_inclusive":False}, 14, "day", "contradicted"),
            ({"kind":"quantity","value":1,"unit":"year"}, 12, "month", "matched"),
            ({"kind":"quantity","value":1,"unit":"month"}, 30, "day", "unknown"),
            ({"kind":"quantity","value":1.5,"unit":"h"}, 90, "min", "matched"),
            ({"kind":"quantity","value":0,"unit":"NRS"}, 0, "NRS", "matched")]
        for expected, value, unit, answer in numeric_rows:
            self.assertEqual(numeric_match(ExpectedValue.model_validate(expected),
                ExpectedValue(kind="quantity", value=value, unit=unit)), answer)
        k, reasoner = f.knowledge(), ClinicalReasoner(f.knowledge())
        concept_rows = [("any_of", [OW.Here], [], "matched"),
            ("any_of", [], [OW.Here], "unknown"), ("any_of", [], [OW.Here, OW.Elsewhere], "contradicted"),
            ("all_of", [OW.Here], [], "unknown"), ("all_of", [OW.Here, OW.Elsewhere], [], "matched"),
            ("all_of", [OW.Here], [OW.Elsewhere], "contradicted")]
        for selection, positive, negative, answer in concept_rows:
            feature = FeatureCondition(id="truth-table", attribute=str(OW.Location), expected=ExpectedValue(
                kind="concept_set", concepts=[str(OW.Here), str(OW.Elsewhere)], selection=selection))
            records = [RecordItem(id=status, scope="ChiefComplaint", status="done", source_refs=["table"],
                value=ClinicalValue(kind="attribute", text="table", status=status, concept_ids=[str(OW.Complaint)],
                                   attribute_id=str(OW.Location), values=[str(v) for v in values]))
                for status, values in (("present", positive),("absent", negative)) if values]
            self.assertEqual(reasoner._match(feature, str(OW.Complaint), "present", [], records)[0], answer)

    def test_broader_mapping_preserves_presence_while_ambiguous_mapping_cannot_score(self):
        for mapping, confirmed in (("broader", True), ("ambiguous", False), ("unmapped", False)):
            state = f.state()
            f.record(state)
            state.case.get("chief").value.mapping_status = mapping
            self.assertEqual(state.case.get("chief").value.status, "present")
            self.assertEqual(bool(state.case.chief(confirmed=True)), confirmed)
        state = f.state()
        f.record(state)
        f.record(state, "ambiguous-negative", status="absent")
        state.case.get("ambiguous-negative").value.mapping_status = "ambiguous"
        self.assertEqual(state.case.chief(confirmed=True).id, "chief")

    def test_lookup_repair_can_change_mapping_without_changing_presence(self):
        original = Fact.model_validate(f.fact("S.cc", "symptom", OW.Complaint, "분명히 있어요"))
        original.value.concept_ids = []
        original.value.mapping_status = "unmapped"
        repaired = original.model_copy(deep=True)
        repaired.value.concept_ids = [str(OW.Complaint)]
        repaired.value.mapping_status = "broader"
        merged = f.make_interpreter(f.CONFIG)._merge_recovery(f.state(),
            ParseResult(accepted_facts=[original], unresolved_links=[0]), ParseResult(accepted_facts=[repaired]))
        self.assertEqual(merged.unresolved_links, [])
        self.assertEqual(merged.accepted_facts[0].value.mapping_status, "broader")
        self.assertEqual(merged.accepted_facts[0].value.status, "present")

    def test_nonexclusive_categorical_reports_and_explicit_value_conflicts(self):
        state = f.state()
        f.record(state, "here", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        f.record(state, "elsewhere", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Elsewhere])
        self.assertEqual({i.value.status for _, i in state.case.current_entries()}, {"present"})
        state.case.get("elsewhere").value.status = "absent"
        self.assertEqual({i.value.status for _, i in state.case.current_entries()}, {"present", "absent"})
        state.case.get("elsewhere").value.values = [str(OW.Here)]
        self.assertEqual({i.value.status for _, i in state.case.current_entries()}, {"uncertain"})
        state = f.state()
        for ident, value, unit in (("days",7,"day"),("hours",168,"h")):
            f.record(state, ident, kind="attribute", field="S.hpi", attribute=OW.EpisodeDuration)
            state.case.get(ident).value.measurement = ExpectedValue(kind="quantity", value=value, unit=unit)
        self.assertEqual({i.value.status for _, i in state.case.current_entries()}, {"present"})

    def test_batch_occurrence_ids_bind_incidental_attributes_without_merging_symptoms(self):
        k, state = f.knowledge(), f.state()
        k._graph.add((OW.Other, OW.hasAttribute, OW.Quality))
        k.validate_graph()
        facts = [f.fact("S.cc", "symptom", OW.Complaint, "가상 증상과 별도 증상이 있어요"),
                 f.fact("S.hpi", "attribute", OW.Complaint, "가상 증상과 별도 증상이 있어요", attribute=OW.Location, values=[OW.Here]),
                 f.fact("S.cc", "symptom", OW.Other, "가상 증상과 별도 증상이 있어요"),
                 f.fact("S.hpi", "attribute", OW.Other, "가상 증상과 별도 증상이 있어요", attribute=OW.Quality, values=[OW.Dull])]
        for fact in facts:
            fact["value"].pop("observation_id")
            fact["value"].pop("episode_id")
        parser = f.make_interpreter(f.CONFIG)
        result = parser._validate_facts({"facts": facts}, state, k, facts[0]["quote"])
        self.assertEqual(result.rejected_facts, [])
        a, b, c, d = [fact.value for fact in result.accepted_facts]
        self.assertEqual((a.observation_id, a.episode_id), (b.observation_id, b.episode_id))
        self.assertEqual((c.observation_id, c.episode_id), (d.observation_id, d.episode_id))
        self.assertNotEqual(a.observation_id, c.observation_id)

    def test_past_context_cannot_complete_current_question(self):
        state, k = f.state("ContextFactor", True), f.knowledge()
        q = f.question(state, purpose="context", target=OW.Context, field="S.pmh")
        f.pending(state, q)
        report = f.fact("S.pmh", "context", OW.Context, "예전에 있었어요")
        report["value"]["time_context"] = "past"
        parser = f.make_interpreter(f.CONFIG)
        result = parser._validate_facts({"facts": [report]}, state, k, report["quote"])
        parser._apply_facts(state, result, "past-context")
        self.assertEqual(state.case.get(q.item_id).status, "unasked")
        self.assertFalse(f.make_planner(k, f.CONFIG).has_resolved_evidence(state, str(OW.Context), time_context="current"))

    def test_patient_selects_one_primary_and_other_reports_survive(self):
        state, k = f.state("ChiefComplaint", True), f.knowledge()
        f.record(state)
        f.record(state, "other-chief", OW.Other)
        planner = f.make_planner(k, f.CONFIG)
        self.assertFalse(planner.prepare_chief_complaint(state))
        q = state.questions.questions[0]
        self.assertTrue(q.primary_choice)
        f.pending(state, q)
        report = f.fact("S.cc", "symptom", OW.Other, "별도 증상이 더 불편해요")
        parser = f.make_interpreter(f.CONFIG)
        result = parser._validate_facts({"facts": [report]}, state, k, report["quote"])
        self.assertFalse(result.rejected_facts)
        parser._apply_facts(state, result, "priority-answer")
        self.assertEqual(state.case.primary_chief.target_id, str(OW.Other))
        self.assertIsNotNone(state.case.get("chief"))
        self.assertIn("chief", state.case.S["ros"])

    def test_initial_automatic_anchor_cannot_hide_a_second_chief_report(self):
        k, state = f.knowledge(), f.state("Initiation", True)
        f.record(state)
        state.case.select_primary()
        q = f.question(state, purpose="chief", field="S.cc", target=None)
        f.pending(state, q)
        report = f.fact("S.cc", "symptom", OW.Other, "다른 증상도 있어요", q=q.model_dump())
        parser = f.make_interpreter(f.CONFIG)
        parsed = parser._validate_facts({"facts": [report]}, state, k, report["quote"])
        self.assertFalse(parsed.rejected_facts)
        parser._apply_facts(state, parsed, "invitation")
        self.assertIsNone(state.case.primary_chief)
        state.interaction.pending = None
        state.session.current = "ChiefComplaint"
        planner = f.make_planner(k, f.CONFIG)
        self.assertFalse(planner.prepare_chief_complaint(state))
        self.assertTrue(any(q.primary_choice for q in state.questions.questions))

    def test_unresolved_priority_has_no_first_report_fallback(self):
        state, k = f.state("ChiefComplaint", True), f.knowledge()
        f.record(state)
        f.record(state, "other-chief", OW.Other)
        state.session.clarifications = 2
        f.make_planner(k, f.CONFIG).prepare_chief_complaint(state)
        self.assertIsNone(state.case.primary_chief)
        self.assertEqual(state.interaction.reason, "primary_chief_unresolved")

    def test_full_chief_attributes_skip_acquired_and_expose_blocks_and_cap(self):
        k, state = f.knowledge(), f.state("ChiefComplaint", True)
        f.record(state)
        for attribute in (OW.Onset, OW.RadiationLocation, OW.TemporalPattern):
            k._graph.add((attribute, f.RDF.type, OW.FindingAttribute))
            k._graph.add((OW.Complaint, OW.hasAttribute, attribute))
            k.questions[str(OW.Complaint) + "|" + str(attribute)] = QuestionTemplate(text="특성을 알려주세요")
        k.questions[str(OW.Complaint) + "|" + str(OW.TemporalPattern)] = QuestionTemplate(
            text="", interviewable=False, reason="explicit_test_gap")
        k.validate_graph()
        f.record(state, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        planner = f.make_planner(k, f.CONFIG)
        planner.prepare_chief_complaint(state)
        self.assertEqual(state.questions.chief_total, 5)
        self.assertEqual(state.questions.chief_acquired, 1)
        self.assertEqual(state.questions.chief_attributes[str(OW.TemporalPattern)], "blocked_asset")
        self.assertTrue(any(q.attribute_id == str(OW.Onset) for q in state.questions.questions))
        quality = next(q for q in state.questions.questions if q.attribute_id == str(OW.Quality))
        state.questions.blocked_keys.append(quality.semantic_key())
        planner.prepare_chief_complaint(state)
        self.assertTrue(state.questions.chief_attribute_reasons[str(OW.Quality)])
        f.WorkflowState.model_validate(state.model_dump())
        state.session.usage["ChiefComplaint"].actions = 13
        planner.prepare_chief_complaint(state)
        self.assertEqual(state.questions.chief_attributes[str(OW.Onset)], "budget_stopped")
        consultation = f.make_consultation(prepared=f.resources(k))
        consultation.check_budget(state)
        consultation.planner.select_question(state)
        self.assertEqual(state.interaction.selected.question.purpose, "open_inquiry")

    def test_two_and_three_step_paths_have_value_without_premature_support(self):
        for count in (1, 2):
            k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
            k._graph.remove((OW.Alpha, OW.hasSupportingContext, OW.Context))
            k._graph.set((OW.betaExamAssociation, OW.predictiveness, f.Literal("zero")))
            conditions = [(OW.Quality, {"kind": "concept", "concept": str(OW.Dull)})]
            if count == 2:
                conditions.append((OW.Location, {"kind": "concept", "concept": str(OW.Here)}))
            f.add_v5_pattern(k, "jointOther", OW.Other, conditions, disease=OW.Beta)
            f.record(state)
            consultation = f.make_consultation(prepared=f.resources(k))
            consultation.reasoner.retrieve_candidates(state)
            before = state.case.model_dump()
            consultation.planner.replan(state)
            question = next(q for q in state.questions.questions if q.target_id == str(OW.Other))
            self.assertIsNone(question.attribute_id)
            self.assertEqual(question.assessment["direct_value"], 0)
            self.assertGreater(question.assessment["plan_value"], 0)
            self.assertEqual(state.case.get("chief").model_dump(), f.RecordItem.model_validate(before["S"]["cc"]["chief"]).model_dump())
            self.assertTrue(all(h.supporting_score == 0 for h in state.differential.hypotheses))
            self.assertLessEqual(state.questions.selection_report["simulations"], 512)

    def test_current_and_unspecified_occurrences_cannot_complete_each_other(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.record(state)
        f.record(state, "other-time", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        state.case.get("other-time").value.time_context = "unspecified"
        _, result = snapshot(k, state)
        self.assertTrue(all(h.chief_score == 1 for h in result.hypotheses))
        self.assertFalse(f.make_planner(k, f.CONFIG).has_resolved_evidence(state, str(OW.Complaint), str(OW.Location),
            "obs1", "episode1", time_context="current"))

    def test_six_question_completion_path_respects_actual_session_capacity(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        k._graph.remove((OW.Alpha, OW.hasSupportingContext, OW.Context))
        for index in range(2):
            context = OW[f"JointContext{index}"]
            k._graph.add((context, f.RDF.type, OW.ContextFactor))
            k._graph.add((context, OW.contextType, f.Literal("past_medical_history")))
            k.questions[str(context)] = QuestionTemplate(text="해당 병력이 있나요?", answer_type="presence", affirmative=True)
        conditions = []
        for index in range(3):
            attr, value = OW[f"JointAttribute{index}"], OW[f"JointValue{index}"]
            k._graph.add((attr, f.RDF.type, OW.FindingAttribute))
            k._graph.add((value, f.RDF.type, OW.AttributeValue))
            k._graph.add((attr, OW.canHaveValue, value))
            k.questions[str(attr)] = QuestionTemplate(text="해당 특성을 알려주세요", answer_type="category")
            conditions.append((attr,{"kind":"concept","concept":str(value)}))
        f.add_v5_pattern(k, "sixStep", OW.Other, conditions, disease=OW.Beta, applicability=[{
            "concept_id":str(OW[f"JointContext{i}"]),"status":"present","subject":"patient","time_context":"current"}
            for i in range(2)])
        f.record(state)
        reasoner, base = snapshot(k,state)
        planner = f.make_planner(k,f.CONFIG)
        paths, _ = planner._frontier(state,base,[str(OW.Beta)])
        path = next(p for p in paths if p.pattern_id == str(OW.sixStep))
        self.assertEqual(len(path.specs),6)
        state.session.usage["DifferentialDiagnosis"].actions = 4
        self.assertTrue(planner._plan_fits(state,path))
        engine = QuestionEvaluation(reasoner,base,[h.disease_id for h in base.hypotheses])
        key = question_key(path.specs[0])
        result = engine.assess({key:path.specs[0]},[path])[key]
        self.assertGreater(result["plan_value"],0)
        self.assertEqual(result["paths"][0]["evaluation"],"complete")
        self.assertLessEqual(engine.used,512)
        state.session.usage["DifferentialDiagnosis"].actions = 5
        self.assertFalse(planner._plan_fits(state,path))

    def test_explicit_chief_correction_rebuilds_collection_after_open(self):
        k, state = f.knowledge(), f.state("ChiefComplaint", True)
        k._graph.add((OW.Other, OW.hasAttribute, OW.Quality))
        k.validate_graph()
        f.record(state)
        f.record(state, "other", OW.Other, field="S.ros")
        planner = f.make_planner(k, f.CONFIG)
        planner.prepare_chief_complaint(state)
        opening = next(q for q in state.questions.questions if q.purpose == "open_inquiry")
        state.interaction.history.append(InteractionEntry(id="open", kind="SAY", question=opening, delivered=True,
            request={"content": opening.text}, response={"content": "없어요"}))
        parser = f.make_interpreter(f.CONFIG)
        report = f.fact("S.cc", "symptom", OW.Other, "이 증상이 가장 불편해요")
        report["value"]["primary_concern"] = True
        accepted = parser._validate_facts({"facts": [report]}, state, k, report["quote"])
        self.assertFalse(accepted.rejected_facts)
        parser._apply_facts(state, accepted, "correction")
        planner.replan(state)
        self.assertEqual(state.case.primary_chief.target_id, str(OW.Other))
        self.assertEqual(set(state.questions.chief_attributes), {str(OW.Quality)})
        self.assertTrue(any(q.target_id == str(OW.Other) and q.attribute_id == str(OW.Quality)
            for q in state.pending_questions()))
        self.assertEqual(sum(e.delivered and e.question.purpose == "open_inquiry" for e in state.interaction.history), 1)

    def test_evaluation_snapshot_owns_its_evidence(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.record(state)
        reasoner, base = snapshot(k, state)
        before = clinical(base)
        state.case.get("chief").value.status = "absent"
        self.assertEqual(clinical(reasoner.evaluate(base.evidence, base.chief)), before)
        self.assertEqual(base.evidence.records(str(OW.Complaint))[0].value.status, "present")

    def test_applicable_lower_refinement_replaces_unconditional_ancestor(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        k._graph.set((OW.alphaBase, OW.predictiveness, f.Literal("very_high")))
        k._graph.set((OW.alphaLocation, OW.predictiveness, f.Literal("low")))
        k._graph.set((OW.alphaLocation, OW.applicability, f.Literal(json.dumps([{
            "concept_id": str(OW.Context), "status": "present", "subject": "patient", "time_context": "current"}]),
            datatype=f.RDF.JSON)))
        k.validate_graph()
        f.record(state)
        f.record(state, "context", OW.Context, "context", "present", "S.pmh")
        f.record(state, "location", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        _, result = snapshot(k, state)
        alpha = next(h for h in result.hypotheses if h.disease_id == str(OW.Alpha))
        self.assertEqual(alpha.chief_score, 1)
        self.assertEqual([c.association_id for c in alpha.contributions], [str(OW.alphaLocation)])

    def test_computation_exhaustion_is_not_information_exhaustion(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.record(state)
        k.reasoning = k.reasoning.model_copy(update={"simulation_limit": 1})
        consultation = f.make_consultation(prepared=f.resources(k))
        consultation.reasoner.retrieve_candidates(state)
        consultation.planner.replan(state)
        self.assertEqual(state.questions.selection_report["reason"], "computation_limit")
        self.assertTrue(state.questions.selection_report["limited"])
        self.assertLessEqual(state.questions.selection_report["simulations"], 1)
        self.assertFalse(state.pending_questions())

    def test_generic_binding_clarification_cannot_turn_acknowledgement_into_presence(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        f.record(state)
        planner = f.make_planner(k, f.CONFIG)
        spec = planner._spec(state, str(OW.Other), episode="episode1")
        planner._register(state, spec, 0, 1)
        original = state.questions.questions[-1]
        state.interaction.history.append(InteractionEntry(id="unparsed", kind="SAY", question=original,
            delivered=True, request={"content":original.text}, response={"content":"잘못 들었어요"}))
        item = state.case.get(original.item_id)
        item.status, item.source_refs = "done", ["unparsed"]
        item.value = ClinicalValue(kind="text", text="Unresolved binding", status="unknown")
        self.assertTrue(planner._eligible(state, spec))
        self.assertEqual(spec["purpose"], "clarification")
        self.assertFalse(spec["affirmative_presence"])
        planner._register(state, spec, 0, 1)
        f.pending(state, state.questions.questions[-1])
        state.session.gateway_successes = 1
        self.assertIsNone(f.fixed_reply(f.CONFIG, state, "네", k))

    def test_new_evidence_can_reenter_a_previously_omitted_candidate(self):
        k, state = f.knowledge(), f.state("DifferentialDiagnosis", True)
        for index in range(14):
            disease = OW[f"Candidate{index:02}"]
            k._graph.add((disease, f.RDF.type, OW.Disease))
            f.add_v5_pattern(k, f"candidate{index}", OW.Complaint, [], disease=disease, label="low")
        late = OW.Candidate13
        f.add_v5_pattern(k, "lateClue", OW.Other, [], disease=late)
        f.record(state)
        reasoner, initial = snapshot(k, state)
        planner = f.make_planner(k, f.CONFIG)
        _, paths = planner._frontier(state, initial, [h.disease_id for h in initial.hypotheses])
        selected, _ = planner._comparison(initial, paths)
        self.assertNotIn(str(late), selected)
        f.record(state, "new-clue", OW.Other, field="S.ros")
        _, changed = snapshot(k, state)
        _, paths = planner._frontier(state, changed, [h.disease_id for h in changed.hypotheses])
        selected, _ = planner._comparison(changed, paths)
        self.assertIn(str(late), selected)
        self.assertEqual(len(changed.hypotheses), len(initial.hypotheses))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Algorithm))
    (f.HERE / "algorithm-verification.json").write_text(json.dumps({"tests": result.testsRun,
        "successful": result.wasSuccessful(), "failures": [str(case) for case, _ in result.failures],
        "errors": [str(case) for case, _ in result.errors], "network": "none", "real_model": "not_run"}, indent=2))
    raise SystemExit(not result.wasSuccessful())
