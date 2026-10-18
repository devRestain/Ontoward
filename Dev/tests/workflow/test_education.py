"""Exercise fixed-diagnosis Education through the real consultation and SOAP consumer."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import unittest
import unicodedata
from unittest.mock import patch

import test_workflow as w
from education_fixtures import education_response, KOREAN, TEXT
from knowledge.guidelines import GuidelineLibrary
from workflow.education import message_bytes
from workflow.rules.limits import LIMITS, PLAN_FIELDS
from workflow.state.models import InteractionEntry, WorkflowState


class EducationSDK(w.FakeSDK):
    def __init__(self):
        super().__init__()
        self.plan_response = None
        self.render_response = None
        self.education_calls = []
        self.late_report = None
        self.verbose_notes = False
        self.late_empathy = False

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        if payload.get("task") not in {"education", "education_doctor"}:
            return super().chat(messages, **kwargs)
        self.calls.append({"messages": messages, **kwargs})
        self.education_calls.append(payload)
        phase = payload.get("repair_phase", payload.get("phase"))
        if payload["task"] == "education_doctor":
            raw = self.render_response(payload) if self.render_response else education_response(payload)
        elif self.plan_response:
            raw = self.plan_response(payload)
        elif phase == "read":
            fragment = payload["documents"][0]
            quote = fragment["text"][:40]
            raw = {"notes": [{"text": "Verified synthetic management evidence. " * (70 if self.verbose_notes else 1),
                              "references": [{"document_id": fragment["document_id"], "quote": quote}]}]}
        elif phase == "combine":
            raw = {"notes": [{"text": "Combined synthetic evidence with the same applicability.",
                              "references": payload["notes"][0]["references"]}]}
        else:
            raw = education_response(payload)
            if payload.get("documents"):
                document = payload["documents"][0]
                refs = [{"document_id": document["document_id"], "quote": document["text"][:40]}]
            elif payload.get("notes"):
                refs = payload["notes"][0]["references"]
            else:
                refs = []
            if refs:
                raw["P"]["tests"][0].update(basis="guideline", references=refs)
        if isinstance(raw, Exception):
            raise raw
        return self.completion(json.dumps(raw, ensure_ascii=False) if not isinstance(raw, str) else raw)

    def _reply(self, text, request_id, exam=False):
        response = super()._reply(text, request_id, exam)
        if self.late_report and text == KOREAN["education"]:
            response.update(content=self.late_report, facts=[w.fact("S.ros", "symptom", w.OW.Other, self.late_report)],
                            clinical_content=True)
            if self.late_empathy:
                response["empathy"] = {"quote": self.late_report, "intent": "new_distress"}
        return response


class EducationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(w.RUN) / self._testMethodName
        self.root.mkdir()
        self.config = w.CONFIG.model_copy(update={"education_enabled": True})
        self.k = w.knowledge()
        self.client = EducationSDK()
        self.s = w.state("Education", False)
        self.s.session.gateway_successes = self.s.session.doctor_successes = 1
        w.record(self.s)
        self.s.interaction.history.append(InteractionEntry(id="initial", kind="initial", response={"opening": "Original patient opening"}))
        for number in range(14):
            self.s.interaction.history.append(InteractionEntry(id=f"old-{number}", kind="SAY", delivered=True,
                request={"content": "Actual delivered question"}, response={"content": f"Original patient reply {number}"}, turn=number + 1))
        self.env = patch.dict(os.environ, {"NOVA_GUIDELINES_DIR": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def sources(self, texts):
        sources = []
        for number, text in enumerate(texts):
            path = self.root / f"source-{number}.md"
            path.write_bytes(text.encode("utf-8"))
            sources.append({"document_id": f"G{number}", "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "title": f"Synthetic source {number}",
                "relation": "narrower" if number else "exact", "scope": "Synthetic adults only; not universal care.",
                "evidence_use": "care_navigation", "document_role": "clinical_guidance"})
        self.k.guidelines = GuidelineLibrary({str(w.OW.Alpha): sources, str(w.OW.Beta): sources})
        return sources

    def enter(self):
        self.agent = w.make_consultation(self.client, w.resources(self.k, self.config))
        self.agent.enter_session(self.s)
        return self.s

    def finish(self):
        self.enter()
        return WorkflowState.model_validate(w.build_graph(self.agent, self.k).invoke(
            self.s.model_dump(), {"recursion_limit": 1500}))

    def test_direct_source_plan_full_dialogue_and_completed_submission(self):
        self.sources(["Synthetic source management evidence for testing only.\n\nComplete source ending."])
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.interaction.education.status, "complete")
        self.assertEqual(result.session.usage["Education"].actions, 5)
        plan = self.client.submissions[0]["note"]["P"]
        self.assertEqual(set(plan), set(PLAN_FIELDS))
        for field, text in TEXT.items():
            self.assertIn(text, plan[field])
        direct = next(p for p in self.client.education_calls if p.get("phase") == "direct")
        self.assertEqual(direct["fixed_diagnosis"]["certainty"], "working")
        self.assertIn("unresolved", direct["fixed_diagnosis"])
        self.assertLessEqual(direct["delivery_turn_budget"], 10)
        self.assertNotIn("dialogue", direct)
        self.assertTrue(direct["patient"]["facts"])
        self.assertNotIn("Original patient opening", json.dumps(direct["patient"]))
        self.assertEqual(direct["documents"][0]["text"].splitlines()[-1], "Complete source ending.")
        self.assertTrue(all(exchange["request"]["reasoning_effort"] == "high"
                            and exchange["request"]["max_tokens"] == 8000
                            for exchange in result.interaction.model_history if exchange["role"] == "education"))
        self.assertTrue(all(exchange["request"]["max_tokens"] == 4000 for exchange in result.interaction.model_history
                            if exchange["role"] == "education_doctor"))
        self.assertEqual(result.interaction.education.sentences[0].basis, "guideline")
        self.assertTrue(result.interaction.education.sentences[0].references)
        self.assertFalse(any(item.value.kind == "education" for _, item in result.case.entries() if item.value))
        self.assertTrue(all(item.status == "delivered" for item in result.questions.education))

    def test_large_documents_read_every_byte_with_full_dialogue_and_combine(self):
        originals = ["Synthetic complete evidence paragraph.\n\n" * 1700 + f"END {number}" for number in range(2)]
        self.sources(originals)
        self.client.verbose_notes = True
        with patch("workflow.education.LIMITS", replace(LIMITS, education_request_bytes=12288)):
            result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.interaction.education.status, "complete")
        self.assertTrue(any(p.get("phase") == "combine" for p in self.client.education_calls))
        self.assertTrue(any(p.get("phase") == "synthesize" for p in self.client.education_calls))
        reads = [p for p in self.client.education_calls if p.get("phase") == "read"]
        for number, original in enumerate(originals):
            chunks = [p["documents"][0] for p in reads if p["documents"][0]["document_id"] == f"G{number}"]
            self.assertEqual("".join(chunk["text"] for chunk in chunks), original)
            offset = 0
            for chunk in chunks:
                self.assertEqual(chunk["start_byte"], offset)
                offset += len(chunk["text"].encode("utf-8"))
                self.assertEqual(chunk["end_byte"], offset)
            self.assertEqual(offset, len(original.encode("utf-8")))
        for call in self.client.calls:
            payload = json.loads(call["messages"][-1]["content"])
            if payload.get("task") == "education":
                self.assertEqual(payload["patient"], reads[0]["patient"])
                self.assertNotIn("dialogue", payload)
                self.assertLessEqual(message_bytes(call["messages"]), 12288)

    def test_missing_and_changed_sources_are_excluded_but_plan_is_generated(self):
        self.sources(["Original first text.", "Original second text."])
        (self.root / "source-0.md").unlink()
        (self.root / "source-1.md").write_text("Changed text must never be transmitted.")
        result = self.finish()
        direct = next(p for p in self.client.education_calls if p.get("phase") == "direct")
        self.assertEqual(direct["documents"], [])
        self.assertEqual(len(result.interaction.education.documents), 2)
        self.assertEqual(result.interaction.education.status, "partial")
        self.assertTrue(all(self.client.submissions[0]["note"]["P"].values()))

    def test_unsafe_source_paths_and_symlinks_cannot_leave_the_corpus(self):
        sources = self.sources(["Inside corpus."])
        for value in ("../outside.md", "/outside.md", "dir\\outside.md", "C:outside.md"):
            with self.subTest(value=value):
                self.k.guidelines.entries[str(w.OW.Alpha)][0] = {**sources[0], "path": value}
                documents, failures = self.k.guidelines.read(str(w.OW.Alpha))
                self.assertEqual(documents, [])
                self.assertEqual(len(failures), 1)
        outside = self.root.parent / "outside.md"
        outside.write_text("Outside corpus.")
        (self.root / "link.md").symlink_to(outside)
        self.k.guidelines.entries[str(w.OW.Alpha)][0] = {**sources[0], "path": "link.md"}
        self.assertEqual(self.k.guidelines.read(str(w.OW.Alpha))[0], [])

    def test_one_plan_repair_retains_partial_sentences_through_finalization(self):
        self.sources([])
        def partial(payload):
            raw = education_response(payload)
            raw["P"]["treatment"] = []
            return raw
        self.client.plan_response = partial
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.interaction.education.repairs, 1)
        self.assertEqual(result.interaction.education.status, "partial")
        self.assertEqual(len(result.interaction.education.sentences), 4)
        self.assertEqual(self.client.submissions[0]["note"]["P"]["treatment"], "")
        self.assertIn(TEXT["tests"], self.client.submissions[0]["note"]["P"]["tests"])
        self.assertEqual(sum(p["task"] == "education" for p in self.client.education_calls), 2)

    def test_fabricated_source_quote_is_rejected_and_repaired(self):
        self.sources(["Only this exact source content was supplied."])
        def reply(payload):
            raw = education_response(payload)
            if payload["phase"] == "direct":
                raw["P"]["tests"][0].update(basis="guideline", references=[{"document_id": "G0", "quote": "Invented quote"}])
            return raw
        self.client.plan_response = reply
        result = self.finish()
        self.assertEqual(result.interaction.education.repairs, 1)
        sentence = next(row for row in result.interaction.education.sentences if row.field == "tests")
        self.assertEqual(sentence.basis, "model_knowledge")
        self.assertEqual(sentence.references, [])

    def test_korean_nfc_and_invalid_ids_repaired_without_truncation(self):
        self.sources([])
        attempted = []
        def render(payload):
            attempted.append([item["id"] for item in payload["sentences"]])
            raw = education_response(payload)
            if len(attempted) == 1:
                raw["items"][0]["utterances"] = ["가" * 31]
                for item in raw["items"][1:]:
                    item["utterances"] = [unicodedata.normalize("NFD", item["utterances"][0])]
            return raw
        self.client.render_response = render
        result = self.finish()
        self.assertEqual([len(ids) for ids in attempted], [5, 1])
        self.assertEqual(result.interaction.education.rendering_errors, {})
        self.assertTrue(all(unicodedata.normalize("NFC", row.question.text) == row.question.text
                            and 1 <= len(row.question.text) <= 30 for row in result.questions.education))
        self.assertFalse(any(action["content"] == "가" * 30 for action in self.client.actions))

    def test_persistently_invalid_render_is_undelivered_without_losing_english(self):
        self.sources([])
        self.client.render_response = lambda payload: {"items": [{"id": row["id"], "utterances": ["가" * 31]}
            for row in payload["sentences"]]}
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(len(result.interaction.education.rendering_errors), 5)
        self.assertEqual(result.session.usage["Education"].actions, 0)
        self.assertTrue(all(self.client.submissions[0]["note"]["P"].values()))

    def test_invalid_condition_withholds_the_whole_treatment_group(self):
        self.sources([])
        conditional = "If the diagnosis and indication are confirmed, discuss the appropriate treatment."
        def plan(payload):
            raw = education_response(payload)
            raw["P"]["treatment"][0]["text"] = conditional
            return raw
        def render(payload):
            raw = education_response(payload)
            for row in raw["items"]:
                if row["id"].startswith("plan:treatment:"):
                    row["utterances"] = ["가" * 31, "확인 후 치료를 상의하겠습니다."]
            return raw
        self.client.plan_response = plan
        self.client.render_response = render
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.session.usage["Education"].actions, 4)
        self.assertIn(conditional, self.client.submissions[0]["note"]["P"]["treatment"])
        self.assertIn("plan:treatment:0", result.interaction.education.rendering_errors)
        self.assertFalse(any(row.question.plan_sentence_id == "plan:treatment:0"
                             for row in result.questions.education))
        self.assertFalse(any(action["content"] == "확인 후 치료를 상의하겠습니다." for action in self.client.actions))
        renders = [p for p in self.client.education_calls if p["task"] == "education_doctor"]
        self.assertEqual([len(p["sentences"]) for p in renders], [5, 1])

    def test_malformed_render_identifier_uses_the_bounded_repair(self):
        self.sources([])
        attempts = []
        def render(payload):
            attempts.append(payload)
            if len(attempts) == 1:
                return {"items": [{"id": [], "utterances": ["잘못된 식별자예요."]}]}
            return education_response(payload)
        self.client.render_response = render
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sum(item.status == "delivered" for item in result.questions.education), 5)

    def test_symptom_diagnosis_skips_disease_retrieval_and_stays_fixed(self):
        self.s.case.remove({"chief"})
        w.record(self.s, target=w.OW.Other)
        result = self.finish()
        self.assertEqual(result.case.fixed_diagnosis.kind, "symptom")
        self.assertIsNone(result.case.fixed_diagnosis.disease_id)
        self.assertEqual(result.interaction.education.documents, [])
        self.assertTrue(all(self.client.submissions[0]["note"]["P"].values()))

    def test_late_patient_facts_do_not_reselect_diagnosis_or_regenerate_plan(self):
        self.sources([])
        self.client.late_report = "A newly reported symptom during education"
        result = self.finish()
        self.assertEqual(result.case.diagnosis, result.case.fixed_diagnosis.name)
        self.assertEqual(sum(p["task"] == "education" for p in self.client.education_calls), 1)
        self.assertFalse(any(item.value and str(w.OW.Other) in item.value.concept_ids for _, item in result.case.entries()))
        self.assertTrue(any(turn.get("patient") == self.client.late_report for turn in result.interaction.dialogue()))

    def test_full_dialogue_overflow_cannot_affect_canonical_education(self):
        self.sources(["Complete document."])
        self.s.interaction.history[0].response["opening"] = "Original speech " * 6000
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertTrue(self.client.education_calls)
        self.assertNotIn("education_context_overflow", result.interaction.education.errors)
        self.assertTrue(all("dialogue" not in p for p in self.client.education_calls))

    def test_education_distress_is_recorded_without_empathy_or_replanning(self):
        self.sources([])
        self.client.late_report = "진단을 듣고 너무 걱정돼요"
        self.client.late_empathy = True
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.session.usage["Education"].empathy_actions, 0)
        self.assertEqual(result.session.usage["Education"].actions, 5)
        self.assertEqual(sum(p["task"] == "education" for p in self.client.education_calls), 1)
        self.assertEqual(result.case.diagnosis, result.case.fixed_diagnosis.name)
        self.assertEqual(sum(item.status == "delivered" for item in result.questions.education), 5)

    def test_response_time_reserve_stops_say_without_erasing_generated_p(self):
        self.sources([])
        self.s.session.deadline = datetime.now(timezone.utc) + timedelta(seconds=200)
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertTrue(all(self.client.submissions[0]["note"]["P"].values()))
        self.assertEqual(self.client.actions, [])
        self.assertTrue(all(item.status == "undelivered" for item in result.questions.education))

    def test_prepared_education_finishes_without_reply_model_allowance(self):
        self.sources([])
        self.s.session.call_limit = 3
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertTrue(all(self.client.submissions[0]["note"]["P"].values()))
        self.assertEqual(sum(item.status == "delivered" for item in result.questions.education), 5)
        self.assertFalse(any(item.status == "undelivered" for item in result.questions.education))

    def test_transient_unknown_stops_before_say_and_diagnose(self):
        self.sources([])
        self.client.plan_response = lambda payload: w.NovaError("API_UNAVAILABLE")
        self.enter()
        self.assertEqual(self.s.interaction.termination, "unknown")
        self.assertEqual(self.client.actions, [])
        self.assertEqual(self.client.submissions, [])
        self.assertEqual(len(self.client.calls), 2)
        self.assertEqual(self.client.calls[0]["request_id"], self.client.calls[1]["request_id"])

    def test_provider_context_rejection_does_not_use_a_format_retry(self):
        self.sources([])
        self.client.plan_response = lambda payload: w.NovaError("CONTEXT_LIMIT_EXCEEDED")
        result = self.finish()
        self.assertEqual(result.interaction.termination, "submitted")
        self.assertEqual(result.interaction.education.repairs, 0)
        self.assertEqual(len(self.client.education_calls), 1)
        self.assertIn("education_model_error:CONTEXT_LIMIT_EXCEEDED", result.interaction.education.errors)
        self.assertEqual(result.interaction.education.status, "failed")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EducationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "result": "pass" if result.wasSuccessful() else "fail", "network": "none", "models": "scripted"}
    (w.HERE / "education-verification.json").write_text(json.dumps(report, indent=2))
    raise SystemExit(not result.wasSuccessful())
