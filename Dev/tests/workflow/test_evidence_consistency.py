"""Offline evidence provenance, correction and report-preservation behavior."""
import copy
import json
import unittest

from test_workflow import (CONFIG, HERE, FakeSDK, OW, fact, knowledge, make_consultation,
                           pending, question, record, resources, state)
from workflow.clinical_reasoner import ClinicalReasoner
from workflow.graph import build_graph
from workflow.interview_planner import InterviewPlanner
from workflow.state.models import WorkflowState


class Verification(unittest.TestCase):
    def setUp(self):
        self.k, self.client = knowledge(), FakeSDK()
        self.consultation = make_consultation(self.client, resources(self.k, CONFIG))
        self.interpreter = self.consultation.interpreter

    def reply(self, s, text, facts, *, kind="SAY", target=None, field="S.hpi", ident="reply", clinical_content=True):
        s.session.gateway_successes = s.session.doctor_successes = 1
        q = question(s, ident=ident, purpose="open_inquiry" if kind == "SAY" else "feature",
                     target=target, kind=kind, field=field, text="다른 내용도 알려주세요")
        pending(s, q)
        s.interaction.incoming = {"content" if kind == "SAY" else "result": text, "facts": facts,
                                  "clinical_content": clinical_content,
                                  "spans": [{"quote": text, "role": "clinical", "field": field}] if kind == "SAY" else []}
        self.interpreter.process_input(s, self.k, self.client)
        return q

    def parse(self, s, value):
        return self.interpreter._validate_facts({"facts": [value]}, s, self.k, value["quote"])

    def test_patient_text_cannot_replace_acquired_exam_through_record_id(self):
        for kind in ("text", "finding", "symptom"):
            with self.subTest(kind=kind):
                s = state("DifferentialDiagnosis", True)
                record(s, "exam", OW.ExamX, "finding", field="O.exam")
                s.case.get("exam").acquisition = "EXAM"
                before = s.case.get("exam").model_dump()
                text = "그 소견은 없다고 생각해요"
                forged = fact("S.hpi", kind, OW.ExamX, text, status="absent")
                forged["record_id"] = "exam"
                self.reply(s, text, [forged])
                self.assertEqual(s.case.get("exam").model_dump(), before)
                self.assertTrue(s.interaction.parse_rejections)
                self.consultation.writer.build_soap(s)
                self.assertIn(text, s.interaction.submission_payload["note"]["S"]["hpi"])

    def test_omitted_record_id_cannot_bind_to_a_prior_exam_question(self):
        s = state("DifferentialDiagnosis", True)
        q = question(s, ident="exam", target=OW.ExamX, field="O.exam", kind="EXAM")
        q.observation_id, q.episode_id = "obs1", "episode1"
        record(s, "exam", OW.ExamX, "finding", field="O.exam")
        before = s.case.get("exam").model_dump()
        disputed = {"field": "S.hpi", "quote": "その所見はない", "value": {
            "kind": "text", "text": "その所見はない", "status": "absent", "record_category": "other",
            "concept_ids": [str(OW.ExamX)], "observation_id": "obs1", "episode_id": "episode1"}}
        self.reply(s, disputed["quote"], [disputed])
        self.assertEqual(s.case.get("exam").model_dump(), before)
        self.assertTrue(any(field == "S.hpi" and item.value and item.value.text == disputed["quote"]
                            for field, item in s.case.entries()))

    def test_patient_cannot_replace_initial_vitals(self):
        s = state("ChiefComplaint", True)
        record(s, "initial:vitals", OW.ExamX, "finding", field="O.exam")
        s.case.get("initial:vitals").source_refs = ["initial"]
        before = s.case.get("initial:vitals").model_dump()
        forged = fact("S.hpi", "text", OW.ExamX, "맥박은 정상이 아니에요", status="absent")
        forged["record_id"] = "initial:vitals"
        self.reply(s, forged["quote"], [forged])
        self.assertEqual(before, s.case.get("initial:vitals").model_dump())

    def test_new_exam_can_correct_its_own_acquisition_target(self):
        s = state("DifferentialDiagnosis", True)
        record(s, "exam", OW.ExamX, "finding", field="O.exam")
        s.case.get("exam").acquisition = "EXAM"
        result = fact("S.hpi", "finding", OW.ExamX, "재진찰에서 소견 없음", status="absent")
        result["record_id"] = "exam"
        self.reply(s, result["quote"], [result], kind="EXAM", target=OW.ExamX, field="O.exam")
        self.assertFalse(s.interaction.parse_rejections)
        self.assertEqual(s.case.get("exam").value.status, "absent")
        self.assertEqual(s.case.get("exam").acquisition, "EXAM")
        self.assertFalse(s.interaction.patient_reports)

    def test_exam_cannot_rewrite_initial_acquisition_or_subjective_report(self):
        for field in ("O.exam", "S.cc"):
            with self.subTest(field=field):
                s = state("DifferentialDiagnosis", True)
                record(s, "initial-record", OW.ExamX, "finding", field=field)
                item = s.case.get("initial-record")
                item.source_refs, item.acquisition = ["initial"], "initial"
                original = item.model_dump()
                result = fact(field, "finding", OW.ExamX, "再検査", status="absent")
                result["record_id"] = item.id
                self.reply(s, result["quote"], [result], kind="EXAM", target=OW.ExamX, field="O.exam")
                self.assertEqual(original, s.case.get("initial-record").model_dump())

    def test_idless_opposite_report_is_uncertain_for_every_evidence_consumer(self):
        s = state("DifferentialDiagnosis", True)
        record(s)
        negative = fact("S.hpi", "symptom", OW.Complaint, "その症状はありません", status="absent")
        self.reply(s, negative["quote"], [negative])
        self.assertEqual(s.case.get("chief").value.status, "present")
        self.assertFalse(s.case.chief_complaints(confirmed=True))
        self.assertFalse(InterviewPlanner.has_resolved_evidence(s, str(OW.Complaint), observation="obs1", episode="episode1"))
        self.assertEqual({row[2] for row in self.consultation.planner._occurrences(s, str(OW.Complaint))}, {"uncertain"})
        self.consultation.reasoner.retrieve_candidates(s)
        self.assertFalse(ClinicalReasoner.supported_hypotheses(s))
        self.assertTrue(s.interaction.needs_clarification)
        self.consultation.writer.build_soap(s)
        self.assertIn("Uncertain", s.interaction.submission_payload["note"]["S"]["cc"])
        self.consultation.reasoner.select_diagnosis(s)
        self.assertIsNone(s.case.diagnosis)
        self.assertEqual(s.interaction.reason, "no_supported_diagnosis")

    def test_explicit_idless_retraction_replaces_only_the_matching_occurrence(self):
        s = state("DifferentialDiagnosis", True)
        record(s)
        record(s, "other-episode", episode="episode2")
        original = s.case.get("other-episode").model_dump()
        negative = fact("S.hpi", "symptom", OW.Complaint, "아까 말한 증상은 사실 없어요", status="absent")
        negative["correction"] = True
        parsed = self.parse(s, negative)
        self.assertFalse(parsed.rejected_facts)
        self.assertEqual(parsed.accepted_facts[0].record_id, "chief")
        self.assertEqual(parsed.accepted_facts[0].field, "S.cc")
        self.interpreter._apply_facts(s, parsed, "retraction")
        self.assertEqual(s.case.get("chief").value.status, "absent")
        self.assertEqual(s.case.get("chief").source_refs, ["source", "retraction"])
        self.assertEqual(s.case.get("other-episode").model_dump(), original)
        self.assertEqual([item.id for item in s.case.chief_complaints(confirmed=True)], ["other-episode"])

    def test_correction_with_missing_or_ambiguous_occurrence_is_rejected(self):
        s = state("ChiefComplaint", True)
        record(s)
        negative = fact("S.cc", "symptom", OW.Complaint, "아까 말은 정정해요", status="absent")
        negative["correction"] = True
        negative["value"]["episode_id"] = None
        self.assertTrue(self.parse(s, negative).rejected_facts)
        negative["value"]["episode_id"] = "episode1"
        record(s, "duplicate")
        self.assertTrue(self.parse(s, negative).rejected_facts)
        self.assertEqual(s.case.get("chief").value.status, "present")

    def test_different_episode_subject_and_past_reports_do_not_cancel_current_chief(self):
        for dimension, value in (("episode_id", "episode2"), ("subject", "family"), ("time_context", "past")):
            with self.subTest(dimension=dimension):
                s = state("DifferentialDiagnosis", True)
                record(s)
                negative = fact("S.hpi", "symptom", OW.Complaint, "別の症状はありません", status="absent")
                negative["value"][dimension] = value
                parsed = self.parse(s, negative)
                self.assertFalse(parsed.rejected_facts)
                self.interpreter._apply_facts(s, parsed, "separate-report")
                self.assertEqual([item.id for item in s.case.chief_complaints(confirmed=True)], ["chief"])

    def test_nonexclusive_values_remain_positive_until_explicitly_contradicted(self):
        s = state("DifferentialDiagnosis", True)
        record(s)
        record(s, "here", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Here])
        record(s, "elsewhere", kind="attribute", field="S.hpi", attribute=OW.Location, values=[OW.Elsewhere])
        self.assertTrue(InterviewPlanner.has_resolved_evidence(s, str(OW.Complaint), str(OW.Location), "obs1", "episode1"))
        self.consultation.reasoner.retrieve_candidates(s)
        self.assertEqual({hypothesis.evidence_score for hypothesis in s.differential.hypotheses}, {2})
        s.case.get("elsewhere").value.values = [str(OW.Here)]
        s.case.get("elsewhere").value.status = "absent"
        self.assertFalse(InterviewPlanner.has_resolved_evidence(s, str(OW.Complaint), str(OW.Location), "obs1", "episode1"))
        self.consultation.reasoner.refresh_hypotheses(s)
        self.assertEqual({hypothesis.evidence_score for hypothesis in s.differential.hypotheses}, {1})

    def test_omitted_allergy_is_preserved_and_does_not_create_score_support(self):
        s = state("ChiefComplaint", True)
        first, second = "가상증상이 있어요.", "항생제 알레르기가 있어요."
        accepted = fact("S.cc", "symptom", OW.Complaint, first)
        self.reply(s, first + " " + second, [accepted], field="S.pmh")
        report = s.interaction.patient_reports[0]
        self.assertEqual(report.text, first + " " + second)
        self.assertEqual(report.covered_spans, [(0, len(first))])
        self.assertEqual([report.text[start:end].strip() for start, end in report.uncovered_spans], [second])
        self.assertTrue(s.interaction.needs_clarification)
        self.consultation.reasoner.retrieve_candidates(s)
        self.assertEqual({hypothesis.evidence_score for hypothesis in s.differential.hypotheses}, {1})
        self.consultation.writer.build_soap(s)
        note = s.interaction.submission_payload["note"]
        self.assertIn("Patient report (unstructured): " + second, note["S"]["pmh"])
        self.assertNotIn(second, note["S"]["hpi"])
        self.assertEqual(note["O"]["tests"], "")
        self.assertNotIn(second, note["A"]["evidence"])

    def test_fully_extracted_clauses_keep_english_allergy_without_raw_duplication(self):
        s = state("ChiefComplaint", True)
        first, second = "가상증상이 있어요.", "항생제 알레르기가 있어요."
        allergy = {"field": "S.pmh", "quote": second, "value": {"kind": "text", "text": second,
            "status": "present", "record_category": "allergy", "record_details": [
                {"quote": "항생제 알레르기", "english": "Antibiotic allergy"}]}}
        self.reply(s, first + " " + second, [fact("S.cc", "symptom", OW.Complaint, first), allergy])
        self.assertFalse(s.interaction.patient_reports[0].uncovered_spans)
        self.consultation.writer.build_soap(s)
        note = s.interaction.submission_payload["note"]["S"]
        self.assertIn("Allergy: (+); Antibiotic allergy", note["pmh"])
        self.assertNotIn("Patient report (unstructured)", note["hpi"])

    def test_misclassified_empty_output_cannot_discard_a_patient_report(self):
        s = state("ChiefComplaint", True)
        text = "항생제 알레르기가 있어요."
        self.reply(s, text, [], clinical_content=False)
        self.assertTrue(s.interaction.patient_reports[0].uncovered_spans)
        self.consultation.writer.build_soap(s)
        self.assertIn(text, s.interaction.submission_payload["note"]["S"]["hpi"])

    def test_broad_quote_cannot_claim_coverage_of_unextracted_sentences(self):
        s = state("ChiefComplaint", True)
        text = "가상증상이 있어요. 항생제 알레르기가 있어요."
        self.reply(s, text, [fact("S.cc", "symptom", OW.Complaint, text)])
        self.assertFalse(s.interaction.patient_reports[0].covered_spans)
        self.consultation.writer.build_soap(s)
        self.assertIn(text, s.interaction.submission_payload["note"]["S"]["hpi"])
        self.assertTrue(s.interaction.needs_clarification)

    def test_whitespace_quote_cannot_create_a_positive_observation(self):
        s = state("ChiefComplaint", True)
        forged = fact("S.cc", "symptom", OW.Complaint, " ")
        self.assertTrue(self.parse(s, forged).rejected_facts)

    def test_acknowledgements_and_grounded_empathy_do_not_create_soap_reports(self):
        for text in (*CONFIG.texts.unknown_replies, *CONFIG.texts.education_acknowledgements):
            with self.subTest(text=text):
                s = state("ChiefComplaint", True)
                self.reply(s, text, [])
                self.assertFalse(s.interaction.patient_reports[0].uncovered_spans)
        s = state("ChiefComplaint", True)
        s.session.gateway_successes = 1
        q = question(s, target=None)
        pending(s, q)
        s.interaction.incoming = {"content": "무서워요", "facts": [], "clinical_content": False,
            "empathy": {"quote": "무서워요", "intent": "new_distress"}}
        self.interpreter.process_input(s, self.k, self.client)
        self.assertFalse(s.interaction.patient_reports[0].uncovered_spans)

    def test_report_coverage_survives_state_roundtrip_and_soap_rebuild(self):
        s = state("ChiefComplaint", True)
        self.reply(s, "증상. 알레르기 보고.", [fact("S.cc", "symptom", OW.Complaint, "증상.")])
        restored = WorkflowState.model_validate_json(s.model_dump_json())
        self.consultation.writer.build_soap(restored)
        before = copy.deepcopy(restored.interaction.submission_payload)
        self.consultation.writer.build_soap(restored)
        self.assertEqual(before, restored.interaction.submission_payload)
        self.assertEqual(before["note"]["S"]["hpi"].count("알레르기 보고."), 1)

    def test_final_workflow_submits_remaining_chief_and_preserves_unparsed_allergy(self):
        s = state("DifferentialDiagnosis", True, turns=0)
        record(s)
        record(s, "remaining-chief", OW.Other)
        q = question(s, target=None)
        pending(s, q)
        retract, allergy = "아까 증상은 사실 없어요.", "항생제 알레르기가 있어요."
        correction = fact("S.cc", "symptom", OW.Complaint, retract, status="absent")
        correction["correction"] = True
        s.interaction.incoming = {"content": retract + " " + allergy, "facts": [correction],
            "spans": [{"quote": allergy, "role": "clinical", "field": "S.pmh"}]}
        s.session.gateway_successes = s.session.doctor_successes = 1
        self.interpreter.process_input(s, self.k, self.client)
        self.client.remaining = 0
        result = WorkflowState.model_validate(build_graph(self.consultation, self.k).invoke(s.model_dump(), {"recursion_limit": 1800}))
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.case.diagnosis_kind, "symptom")
        self.assertEqual(result.case.diagnosis_evidence, ["remaining-chief"])
        self.assertEqual(len(self.client.submissions), 1)
        self.assertIn(allergy, self.client.submissions[0]["note"]["S"]["pmh"])
        self.assertNotIn("chief", result.case.diagnosis_evidence)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Verification))
    (HERE / "verification.json").write_text(json.dumps({"tests": result.testsRun,
        "failures": [str(test) for test, _ in result.failures], "errors": [str(test) for test, _ in result.errors],
        "successful": result.wasSuccessful(), "network": "none", "real_model_calls": 0}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
