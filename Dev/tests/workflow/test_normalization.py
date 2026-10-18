import copy
import json
import unittest
from unittest.mock import Mock

from test_workflow import CONFIG, FakeSDK, OW, add_v5_pattern, knowledge, make_consultation, pending, question, record, resources, state
from workflow.rules.normalization import strict_json, validate_mapping
from workflow.state.canonical import CanonicalSnapshot
from workflow.state.models import ContextStatement, PatientReport, RecordDetail
from normalization_fixtures import mapping_from_contracts


def statement(text, *, target=OW.Complaint, **changes):
    return {"quote": text, "role": "clinical", "assertion": "present", "time_context": "current",
            "target_terms": [str(target)], **changes}


class Verification(unittest.TestCase):
    def setUp(self):
        self.k, self.client = knowledge(), FakeSDK()
        self.c = make_consultation(self.client, resources(self.k, CONFIG))
        self.payloads = []

    def reply(self, s, contexts, wires=None):
        values = iter(wires or [])
        def chat(messages, **kwargs):
            p = json.loads(messages[1]["content"])
            self.payloads.append(p)
            if p["task"] == "input_context":
                raw = contexts if isinstance(contexts, str) else {"statements": contexts}
            else:
                raw = next(values, mapping_from_contracts(p))
            return self.client.completion(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False))
        self.client.chat = Mock(side_effect=chat)
        self.c.interpreter.process_input(s, self.k, self.client)

    def initial(self, text):
        s = state()
        s.interaction.incoming = {"initial": {"opening": text}}
        return s

    def test_initial_and_injected_facts_always_call_context_and_mapping(self):
        s = self.initial("가상증상")
        s.interaction.incoming["initial"]["facts"] = [{"fake": "ignored"}]
        self.reply(s, [statement("가상증상")])
        self.assertEqual([p["task"] for p in self.payloads], ["input_context", "input_mapping"])
        self.assertEqual(len(s.case.chief_complaints()), 1)
        self.assertEqual(s.case.chief().value.text, "")

    def test_unknown_and_empty_replies_still_call_the_model(self):
        for text in ("모르겠어요", ""):
            with self.subTest(text=text):
                self.setUp()
                s = self.initial(text)
                self.reply(s, [statement(text)] if text else [])
                self.assertEqual(len(self.payloads), 1)
                self.assertFalse(s.case.chief_complaints())

    def test_acknowledgement_and_disease_question_do_not_create_symptoms(self):
        for text, role in (("감사합니다", "nonclinical"), ("암일까요?", "question")):
            with self.subTest(text=text):
                self.setUp()
                s = self.initial(text)
                self.reply(s, [statement(text, role=role)])
                self.assertFalse(CanonicalSnapshot.from_case(s.case).entries)
                self.assertEqual(s.case.outcomes[0].state, "nonclinical")

    def test_compound_reply_preserves_independent_facts_and_negation(self):
        s = self.initial("가상증상 있고 별도증상은 없어요")
        self.reply(s, [statement("가상증상 있고"), statement("별도증상은 없어요", target=OW.Other, assertion="absent")])
        facts = CanonicalSnapshot.from_case(s.case).entries
        self.assertEqual(len(facts), 2)
        self.assertEqual({i.value.status for _, i in facts}, {"present", "absent"})
        self.assertEqual(sum(len(o.fact_ids) for o in s.case.outcomes), 2)

    def test_target_hints_do_not_turn_the_chief_into_a_required_attribute(self):
        s = self.initial("가상증상이 작아 보여요")
        self.reply(s, [statement("가상증상이 작아 보여요", record_category="presentation", primary_concern=True,
            attribute_terms=["relative appearance"], value_terms=["seems small"])], [[{str(OW.Complaint): "(+)"}]])
        self.assertEqual(s.case.chief(confirmed=True).value.concept_ids, [str(OW.Complaint)])
        self.assertEqual([p["task"] for p in self.payloads], ["input_context", "input_mapping"])

    def test_invalid_context_sibling_does_not_erase_valid_clinical_statements(self):
        s = self.initial("가상증상 있고 별도증상은 3일째")
        contexts = [statement("가상증상 있고"), statement("별도증상은 3일째", target=OW.Other,
            measurement={"kind":"quantity","value":"not a number","unit":"day","operator":"eq"})]
        self.reply(s, contexts)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual([o.state for o in s.case.outcomes], ["mapped", "unknown"])
        repair = next(p for p in self.payloads if p["phase"] == "context_repair")
        self.assertEqual(repair["statement_indices"], [1])
        self.assertEqual(repair["frozen_statements"][0]["quote"], "가상증상 있고")

    def test_context_repair_replaces_only_the_invalid_original_index(self):
        s = self.initial("가상증상과 별도증상")
        def chat(messages, **kwargs):
            p = json.loads(messages[1]["content"])
            self.payloads.append(p)
            if p["phase"] == "context":
                raw = {"statements": [statement("가상증상"), statement("별도증상", target=OW.Other,
                    observation_id="not_supplied")]}
            elif p["phase"] == "context_repair":
                self.assertEqual(p["statement_indices"], [1])
                raw = {"statements": [statement("별도증상", target=OW.Other)]}
            else:
                raw = mapping_from_contracts(p)
            return self.client.completion(json.dumps(raw, ensure_ascii=False))
        self.client.chat = Mock(side_effect=chat)
        self.c.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(len(CanonicalSnapshot.from_case(s.case).entries), 2)
        self.assertEqual([o.state for o in s.case.outcomes], ["mapped", "mapped"])

    def test_turn_zero_records_chief_and_incidental_negative_before_first_say(self):
        from workflow.graph import build_graph
        s = self.initial("가상증상이 있어요 별도증상은 없어요")
        delegate = self.client.chat
        def chat(messages, **kwargs):
            p = json.loads(messages[1]["content"])
            if p["task"] == "input_context" and p["question"] is None:
                return self.client.completion(json.dumps({"statements": [
                    statement("가상증상이 있어요", record_category="presentation", primary_concern=True),
                    statement("별도증상은 없어요", target=OW.Other, assertion="absent")]}, ensure_ascii=False))
            if p["task"] == "input_mapping":
                return self.client.completion(json.dumps(mapping_from_contracts(p)))
            return delegate(messages, **kwargs)
        self.client.chat = Mock(side_effect=chat)
        stream = build_graph(self.c, self.k).stream(s.model_dump())
        first = next(stream)
        self.assertEqual(set(first), {"process_initial_input"})
        case = first["process_initial_input"]["case"]
        self.assertTrue(case["S"]["cc"])
        self.assertTrue(case["S"]["ros"])
        self.assertEqual(self.client.actions, [])
        for update in stream:
            if "execute_action" in update:
                self.assertEqual(self.client.actions[0]["content"], CONFIG.texts.greeting)
                break
        stream.close()

    def test_initial_uncertain_presenting_report_has_one_focused_context_review(self):
        s = self.initial("가상증상이 있어 보여 걱정돼요")
        def chat(messages, **kwargs):
            p = json.loads(messages[1]["content"])
            self.payloads.append(p)
            if p["phase"] == "context":
                raw = {"statements": [statement("가상증상이 있어 보여", role="uncertain", assertion="uncertain", primary_concern=True)]}
            elif p["phase"] == "initial_chief_repair":
                self.assertEqual(p["statement_indices"], [0])
                raw = {"statements": [statement("가상증상이 있어 보여", primary_concern=True)]}
            else:
                raw = mapping_from_contracts(p)
            return self.client.completion(json.dumps(raw, ensure_ascii=False))
        self.client.chat = Mock(side_effect=chat)
        self.c.interpreter.process_input(s, self.k, self.client)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual([p["phase"] for p in self.payloads], ["context", "initial_chief_repair", "mapping"])

    def test_focused_initial_review_does_not_force_genuine_unknown_presence(self):
        s = self.initial("가상증상인지는 모르겠어요")
        self.reply(s, [statement("가상증상인지는 모르겠어요", role="uncertain", assertion="uncertain", primary_concern=True)])
        self.assertFalse(s.case.chief(confirmed=True))
        self.assertEqual(s.case.outcomes[0].state, "unknown")

    def test_same_question_two_values_have_independent_fact_ids(self):
        s = state("ChiefComplaint", True)
        record(s)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.Location, field="S.hpi")
        q.observation_id, q.episode_id = "obs1", "episode1"
        pending(s, q)
        s.interaction.incoming = {"content": "가상부위와 다른부위"}
        self.reply(s, [statement("가상부위", attribute_terms=[str(OW.Location)], value_terms=[str(OW.Here)]),
                       statement("다른부위", attribute_terms=[str(OW.Location)], value_terms=[str(OW.Elsewhere)])])
        ids = s.questions.answered_fact_ids[q.item_id]
        self.assertEqual(len(ids), 2)
        self.assertEqual({v for ident in ids for v in s.case.get(ident).value.values}, {str(OW.Here), str(OW.Elsewhere)})
        self.assertNotIn(q.item_id, ids)

    def test_forced_model_mapping_is_used_in_reasoning_and_soap(self):
        s = self.initial("가상증상")
        self.reply(s, [statement("가상증상")], [[{}], [{}], [{str(OW.Complaint): "(+)"}]])
        chief = s.case.chief()
        self.assertEqual(chief.value.forced_by, "model")
        self.c.reasoner.select_diagnosis(s)
        self.c.writer.build_soap(s)
        self.assertTrue(s.case.diagnosis)
        self.assertIn(self.k.label(str(OW.Complaint), language="en"), s.interaction.submission_payload["note"]["S"]["cc"])

    def test_invalid_json_closes_deterministically_with_valid_database_dictionary(self):
        s = self.initial("가상증상")
        self.reply(s, [statement("가상증상")], ["invalid"] * 4)
        self.assertIsNone(s.interaction.termination)
        self.assertEqual(s.case.chief().value.forced_by, "deterministic")
        self.assertEqual(len(self.payloads), 5)
        result = s.interaction.interpretations[-1]["result"]
        self.assertEqual(strict_json(json.dumps(result["mappings"])), [{str(OW.Complaint): "(+)"}])

    def test_repair_freezes_successful_independent_mapping(self):
        s = self.initial("가상증상과 별도증상")
        self.reply(s, [statement("가상증상"), statement("별도증상", target=OW.Other)],
                   [[{str(OW.Complaint): "(+)"}, {}], [{str(OW.Other): "(+)"}]])
        repair = self.payloads[-1]
        self.assertEqual(repair["statement_indices"], [1])
        self.assertEqual(len(CanonicalSnapshot.from_case(s.case).entries), 2)

    def test_unrepresentable_measurement_is_audited_without_fake_evidence(self):
        s = self.initial("키 100cm")
        self.reply(s, [statement("키 100cm", target="Height", measurement={"kind": "quantity", "value": 100,
                    "unit": "cm", "operator": "eq"})])
        self.assertFalse(CanonicalSnapshot.from_case(s.case).entries)
        self.assertEqual(s.case.outcomes[0].state, "unsupported")
        self.assertIsNone(s.interaction.termination)

    def test_duplicate_keys_and_nonfinite_numbers_are_invalid(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(raw)

    def test_family_and_patient_remain_separate(self):
        s = self.initial("저는 가상증상 어머니는 가상증상")
        self.reply(s, [statement("저는 가상증상"), statement("어머니는 가상증상", subject="family", subject_member="mother")])
        self.assertEqual({i.value.subject for _, i in CanonicalSnapshot.from_case(s.case).entries}, {"patient", "family"})

    def test_raw_changes_cannot_change_snapshot_reasoning_or_soap(self):
        s = self.initial("가상증상")
        self.reply(s, [statement("가상증상")])
        self.c.reasoner.select_diagnosis(s)
        self.c.writer.build_soap(s)
        before = copy.deepcopy(s.interaction.submission_payload)
        payload = CanonicalSnapshot.from_case(s.case).payload()
        for field, item in s.case.entries():
            if field.startswith(("S.", "O.")) and item.value:
                item.value.text = "raw poison"
                item.value.record_details = [RecordDetail(quote="poison", english="raw poison")]
        s.interaction.patient_reports.append(PatientReport(source_id="poison", text="raw poison", clinical_spans=[(0, 10, "S.hpi")]))
        s.interaction.history[0].response = {"opening": "raw poison"}
        self.c.reasoner.select_diagnosis(s)
        self.c.writer.build_soap(s)
        self.assertEqual(s.interaction.submission_payload, before)
        self.assertEqual(CanonicalSnapshot.from_case(s.case).payload(), payload)

    def test_negated_feature_is_not_a_negative_target(self):
        s = state("ChiefComplaint", True)
        record(s)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.Quality, field="S.hpi")
        q.observation_id, q.episode_id = "obs1", "episode1"
        pending(s, q)
        s.interaction.incoming = {"content": "둔하지 않아요"}
        self.reply(s, [statement("둔하지 않아요", assertion="absent", attribute_terms=[str(OW.Quality)], value_terms=[str(OW.Dull)])])
        self.assertEqual(s.case.get("chief").value.status, "present")
        value = s.case.get(s.questions.answered_fact_ids[q.item_id][0]).value
        self.assertEqual((value.status, value.values), ("absent", [str(OW.Dull)]))

    def test_qualified_negative_never_cancels_general_positive_evidence(self):
        from workflow.state.evidence import EvidenceIndex
        s = state("ChiefComplaint", True)
        record(s)
        q = question(s, purpose="ros", target=OW.Complaint)
        q.observation_id, q.episode_id = "obs1", "episode1"
        pending(s, q)
        s.interaction.incoming = {"content": "그 조건에서는 없어요"}
        self.reply(s, [statement("그 조건에서는 없어요", assertion="absent", polarity_scope="qualified")])
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual([i.id for _, i in EvidenceIndex.from_case(s.case).entries], ["chief"])
        self.c.writer.build_soap(s)
        self.assertIn("qualified scope", s.interaction.submission_payload["note"]["S"]["ros"])
        self.assertNotIn("그 조건에서는", s.interaction.submission_payload["note"]["S"]["ros"])

    def numeric_reply(self, measured, wires=None):
        add_v5_pattern(self.k, "d41Numeric", OW.Complaint, [(OW.TimeSinceOnset,
            {"kind": "quantity", "value": 1, "unit": "day", "operator": "ge"})])
        s = state("ChiefComplaint", True)
        record(s)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.TimeSinceOnset, field="S.hpi")
        q.observation_id, q.episode_id = "obs1", "episode1"
        pending(s, q)
        s.interaction.incoming = {"content": "3 days"}
        self.reply(s, [statement("3 days", attribute_terms=[str(OW.TimeSinceOnset)], measurement=measured)], wires)
        return s, q

    def test_registered_number_reaches_soap_without_original_wording(self):
        s, q = self.numeric_reply({"kind": "quantity", "value": 3, "unit": "day", "operator": "eq"})
        value = s.case.get(s.questions.answered_fact_ids[q.item_id][0]).value
        self.assertEqual((value.measurement.value, value.measurement.unit), (3, "day"))
        self.c.writer.build_soap(s)
        self.assertIn("Onset: 3 days before presentation", s.interaction.submission_payload["note"]["S"]["hpi"])

    def test_verbose_numeric_context_defaults_do_not_discard_the_measurement(self):
        s, q = self.numeric_reply({"kind":"quantity","value":3,"unit":"day","operator":"eq",
            "concept":None,"concepts":[],"selection":"all_of","match":"subsumption",
            "lower":None,"upper":None,"lower_inclusive":False,"upper_inclusive":False,"upper_unit":None})
        value = s.case.get(s.questions.answered_fact_ids[q.item_id][0]).value
        self.assertEqual(value.measurement.value, 3)
        self.assertEqual([p["phase"] for p in self.payloads], ["context", "mapping"])
        sent = self.payloads[-1]["statements"][0]["measurement"]
        self.assertNotIn("concepts", sent)
        self.assertNotIn("lower_inclusive", sent)

    def test_registered_orphan_number_is_recorded_without_inventing_a_symptom(self):
        from workflow.state.evidence import EvidenceIndex
        add_v5_pattern(self.k, "orphanNumeric", OW.Complaint, [(OW.TimeSinceOnset,
            {"kind":"quantity","value":1,"unit":"day","operator":"ge"})])
        s = self.initial("가상증상의 기간 3일")
        self.reply(s, [statement("가상증상의 기간 3일", focus="attribute", attribute_terms=[str(OW.TimeSinceOnset)],
            measurement={"kind":"quantity","value":3,"unit":"day","operator":"eq"})])
        entries = CanonicalSnapshot.from_case(s.case).entries
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1].value.evidence_use, "record_only")
        payload = CanonicalSnapshot.from_case(s.case).payload()["facts"][0]
        self.assertEqual((payload["kind"], payload["evidence_use"]), ("attribute", "record_only"))
        self.assertFalse(EvidenceIndex.from_case(s.case).entries)
        self.assertFalse(s.case.chief(confirmed=True))
        self.c.writer.build_soap(s)
        self.assertIn("3 days", s.interaction.submission_payload["note"]["S"]["hpi"])

    def test_unregistered_numeric_course_cannot_become_an_absolute_measurement(self):
        add_v5_pattern(self.k, "numericCourse", OW.Complaint, [(OW.TimeSinceOnset,
            {"kind":"quantity","value":1,"unit":"day","operator":"ge"})])
        s = self.initial("3일간 변했어요")
        self.reply(s, [statement("3일간 변했어요", focus="attribute", record_category="course",
            attribute_terms=["change over time"], measurement={"kind":"quantity","value":3,"unit":"day","operator":"eq"})])
        self.assertFalse(CanonicalSnapshot.from_case(s.case).entries)
        self.assertEqual(s.case.outcomes[0].state, "unsupported")

    def test_prior_care_denial_never_negates_the_bound_chief(self):
        s = state("Initiation", True)
        record(s)
        q = question(s, purpose="intake", target=OW.Complaint, field="S.hpi")
        q.record_category = "previous_care"
        pending(s, q)
        s.interaction.incoming = {"content":"치료받은 적은 없어요"}
        self.reply(s, [statement("치료받은 적은 없어요", assertion="absent", target="previous treatment",
            record_category="previous_care")])
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual(s.case.outcomes[0].state, "unsupported")
        self.assertEqual(len(CanonicalSnapshot.from_case(s.case).entries), 1)

    def test_source_offsets_point_only_to_the_reported_current_input(self):
        s = self.initial("가상증상 있고 별도증상은 없어요")
        self.reply(s, [statement("가상증상 있고"), statement("별도증상은 없어요", target=OW.Other, assertion="absent")])
        audit = s.interaction.interpretations[-1]
        self.assertEqual(audit["source_ref"], "initial")
        for span in audit["source_spans"]:
            quote = audit["context"]["statements"][span["statement_index"]]["quote"]
            self.assertTrue(span["positions"])
            for start, end in span["positions"]:
                self.assertEqual(audit["input"][start:end], quote)

    def test_unreported_numeric_value_is_rejected_then_repaired(self):
        wrong = [{str(OW.Complaint): {str(OW.TimeSinceOnset): {"kind":"quantity","value":7,"unit":"day","operator":"eq"}}}]
        s, q = self.numeric_reply({"kind":"quantity","value":3,"unit":"day","operator":"eq"}, [wrong])
        self.assertEqual(s.case.get(s.questions.answered_fact_ids[q.item_id][0]).value.measurement.value, 3)
        self.assertTrue(any("unreported" in r["reason"] for r in s.interaction.parse_rejections))

    def test_approximate_number_survives_normalization_and_soap(self):
        s, q = self.numeric_reply({"kind":"quantity","value":3,"unit":"day","operator":"eq","approximate":True})
        item = s.case.get(s.questions.answered_fact_ids[q.item_id][0])
        self.assertTrue(item.mapping[str(OW.Complaint)][str(OW.TimeSinceOnset)]["approximate"])
        self.c.writer.build_soap(s)
        self.assertIn("approximately 3 days", s.interaction.submission_payload["note"]["S"]["hpi"])

    def test_normalizer_cannot_remove_reported_approximation(self):
        wrong = [{str(OW.Complaint): {str(OW.TimeSinceOnset): {"kind":"quantity","value":3,"unit":"day","operator":"eq"}}}]
        s, q = self.numeric_reply({"kind":"quantity","value":3,"unit":"day","operator":"eq","approximate":True}, [wrong])
        self.assertTrue(s.case.get(s.questions.answered_fact_ids[q.item_id][0]).value.measurement.approximate)
        self.assertTrue(any("unreported" in r["reason"] for r in s.interaction.parse_rejections))

    def test_unknown_attribute_value_cannot_enter_canonical_state(self):
        s = state("ChiefComplaint", True)
        record(s)
        q = question(s, purpose="hpi", target=OW.Complaint, attribute=OW.Location, field="S.hpi")
        q.observation_id, q.episode_id = "obs1", "episode1"
        pending(s, q)
        s.interaction.incoming = {"content": "가상부위"}
        self.reply(s, [statement("가상부위", attribute_terms=[str(OW.Location)], value_terms=[str(OW.Here)])],
                   [[{str(OW.Complaint): {str(OW.Location): str(OW.Dull)}}]])
        self.assertEqual(s.case.get(s.questions.answered_fact_ids[q.item_id][0]).value.values, [str(OW.Here)])
        self.assertTrue(s.interaction.parse_rejections)

    def test_unknown_observation_reference_is_not_admitted(self):
        s = self.initial("가상증상")
        self.reply(s, [statement("가상증상", observation_id="never_transmitted")])
        self.assertFalse(CanonicalSnapshot.from_case(s.case).entries)
        self.assertEqual(len(self.payloads), 2)
        self.assertTrue(any("observation_outside" in r["reason"] for r in s.interaction.parse_rejections))

    def test_duplicate_keys_trigger_one_format_repair(self):
        s = self.initial("가상증상")
        duplicate = '[{"urn:ontoward:Complaint":"(+)","urn:ontoward:Complaint":"(-)"}]'
        self.reply(s, [statement("가상증상")], [duplicate])
        self.assertEqual([p["phase"] for p in self.payloads], ["context", "mapping", "format_repair"])
        self.assertTrue(s.case.chief(confirmed=True))

    def test_truncation_uses_one_larger_context_recovery(self):
        from normalization_fixtures import fixture_chat
        s = self.initial("가상증상")
        delegate = fixture_chat(self.client, [{"quote":"가상증상", "value":{"concept_ids":[str(OW.Complaint)],
            "status":"present", "time_context":"current"}}])
        calls = []
        def chat(messages, **kwargs):
            calls.append(kwargs["max_tokens"])
            if len(calls) == 1:
                result = self.client.completion("truncated")
                result["choices"][0]["finish_reason"] = "length"
                return result
            return delegate(messages, **kwargs)
        self.client.chat = Mock(side_effect=chat)
        self.c.interpreter.process_input(s, self.k, self.client)
        self.assertEqual(calls, [4096, 8000, 4096])
        self.assertTrue(s.case.chief(confirmed=True))

    def test_context_limit_recovery_transmits_a_smaller_request(self):
        from nova_sdk import NovaError
        from normalization_fixtures import fixture_chat
        s = self.initial("가상증상")
        delegate = fixture_chat(self.client, [{"quote":"가상증상", "value":{"concept_ids":[str(OW.Complaint)],
            "status":"present", "time_context":"current"}}])
        calls = []
        def chat(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                raise NovaError("CONTEXT_LIMIT_EXCEEDED")
            return delegate(messages, **kwargs)
        self.client.chat = Mock(side_effect=chat)
        self.c.interpreter.process_input(s, self.k, self.client)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertLessEqual(s.interaction.model_history[1]["parser_payload"]["request_bytes"], 8192)

    def test_long_quote_does_not_hit_the_removed_record_detail_limit(self):
        text = "가상증상 " * 50
        s = self.initial(text)
        self.reply(s, [statement(text)])
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertEqual(s.case.chief().value.record_details, [])

    def test_patient_demographics_stay_in_interpretation_context_only(self):
        text = "6 years 가상증상"
        s = self.initial(text)
        context = json.dumps({"statements":[statement("가상증상")],
            "patient_context":[{"key":"age","value":"6 years","quote":"6 years"}]})
        self.reply(s, context)
        self.assertEqual(s.case.patient_context["age"].value, "6 years")
        self.c.writer.build_soap(s)
        self.assertNotIn("6 years", json.dumps(s.interaction.submission_payload))
        self.assertNotIn("6 years", json.dumps(CanonicalSnapshot.from_case(s.case).payload()))

    def test_oversized_input_is_audited_without_an_invalid_transmission(self):
        text = "long input " * 2000
        s = self.initial(text)
        self.reply(s, [])
        self.assertEqual(self.client.chat.call_count, 0)
        self.assertEqual(s.interaction.patient_reports[0].text, text)
        self.assertEqual(s.case.outcomes[0].state, "unknown")
        self.assertIsNone(s.interaction.termination)

    def test_general_history_denial_never_creates_individual_negatives(self):
        s = self.initial("과거 병력은 없어요")
        self.reply(s, [statement("과거 병력은 없어요", assertion="absent", assertion_scope="domain",
                               record_category="medical_history", target_terms=["medical history"])])
        self.assertFalse(CanonicalSnapshot.from_case(s.case).entries)
        self.assertEqual(s.case.outcomes[0].state, "unsupported")

    def test_invalid_empathy_metadata_does_not_erase_a_clinical_mapping(self):
        s = self.initial("가상증상")
        context = json.dumps({"statements":[statement("가상증상")],
                              "empathy":{"quote":"not reported","intent":"new_distress"}})
        self.reply(s, context)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertFalse(s.interaction.empathy_events)
        self.assertIn("invalid_empathy_signal", s.interaction.issues)

    def test_conflicting_demographics_never_replace_patient_age(self):
        s = self.initial("6 years 37 years 가상증상")
        context = json.dumps({"statements":[statement("가상증상")], "patient_context":[
            {"key":"age","value":"6 years","quote":"6 years"},
            {"key":"age","value":"37 years","quote":"37 years"}]})
        self.reply(s, context)
        self.assertTrue(s.case.chief(confirmed=True))
        self.assertNotIn("age", s.case.patient_context)
        self.assertIn("conflicting_patient_context", s.interaction.issues)

    def test_raw_changes_do_not_change_next_question_targets_or_order(self):
        s = self.initial("가상증상")
        self.reply(s, [statement("가상증상")])
        s.session.current, s.session.initialized = "DifferentialDiagnosis", True
        before, after = s.model_copy(deep=True), s.model_copy(deep=True)
        for _, item in after.case.entries():
            if item.value:
                item.value.text = "arbitrary raw speech"
        after.interaction.history[0].response = {"opening":"arbitrary raw speech"}
        signatures = []
        for sample in (before, after):
            self.c.planner.replan(sample, force=True)
            signatures.append([(q.target_id,q.attribute_id,q.order,q.kind) for q in sample.pending_questions()])
        self.assertTrue(signatures[0])
        self.assertEqual(signatures[0], signatures[1])

    def test_education_patient_payload_is_invariant_to_raw_changes(self):
        from workflow.education import generate_plan
        from workflow.state.models import FixedDiagnosis
        s = self.initial("가상증상")
        self.reply(s, [statement("가상증상")])
        s.case.fixed_diagnosis = FixedDiagnosis(kind="symptom", name="known source label", evidence_ids=[s.case.chief().id])
        before, after = s.model_copy(deep=True), s.model_copy(deep=True)
        for _, item in after.case.entries():
            if item.value:
                item.value.text = "SECRET original wording"
                item.value.record_details = [RecordDetail(quote="SECRET",english="SECRET English summary")]
        after.interaction.history[0].response = {"opening":"SECRET original wording"}
        from education_fixtures import education_response
        requests = []
        def chat(messages, **kwargs):
            p = json.loads(messages[-1]["content"])
            requests.append(p)
            return self.client.completion(json.dumps(education_response(p)))
        self.client.chat = Mock(side_effect=chat)
        for sample in (before, after):
            generate_plan(sample, self.client, self.k, CONFIG, self.c.interpreter.model)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["patient"], requests[1]["patient"])
        self.assertNotIn("SECRET", json.dumps(requests))


if __name__ == "__main__":
    unittest.main()
