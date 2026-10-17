from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from Dev.guidelines import map as mapping


DISEASE = {"id": "urn:ontoward:SnomedCT1", "labels": {"en": "Example disease"}, "aliases": ["Example disease"]}
BODY = b'''---
title: "Example disease"
organization: "Example Society"
year: "2025"
language: en
source_url: "https://example.org/guideline"
license: "CC BY"
---
# Example disease

## Introduction
Example disease affects adults and requires assessment.

## Treatment
For adults only, consider the following qualified treatment.
### Exceptions
Do not apply this approach to children.

## Follow-up
Review unresolved symptoms.
'''


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/workspace/Tmp")
        self.root = Path(self.temporary.name)
        self.output = self.root / "data/preparation/guideline-mapping/test"
        self.output.mkdir(parents=True)
        self.source = {"document_id": "G00001", "path": "Group/example.md", "title": "Example disease",
                       "organization": "Example Society", "year": "2025", "language": "영어",
                       "source_url": "https://example.org/guideline", "license": "CC BY",
                       "document_type": "진료지침", "sha256": mapping.sha256(BODY)}
        self.path = self.root / "assets/guidelines/Group/example.md"
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(BODY)
        self.packet = mapping.packet(self.root, DISEASE, [(self.source, 200)])
        self.entry = {"disease_id": DISEASE["id"], "selections": [{"document_id": "G00001", "relation": "exact", "document_role": "clinical_guidance",
                      "identity_quote": "Example disease affects adults", "scope": "Adults; not children.",
                      "rationale": "The document covers the same disease.", "plan_fields": ["treatment", "follow_up"]}],
                      "search_terms": [], "gap_reason": None}
        self.inventory = {"version": mapping.VERSION, "runtime": {"fixture": True}, "diseases": [DISEASE],
                          "sources": [self.source], "protected_submission": {},
                          "catalog": {"path": "assets/guidelines/catalog.csv", "sha256": mapping.sha256(b"catalog")}}
        (self.root / "assets/guidelines/catalog.csv").write_bytes(b"catalog")
        mapping.save(self.output / "inventory.json", self.inventory)
        (self.output / "candidates.jsonl").write_text(json.dumps(self.packet) + "\n")
        mapping.save(self.output / "preparation.json", {"inventory_sha256": mapping.sha256((self.output / "inventory.json").read_bytes()),
                     "candidates_sha256": mapping.sha256((self.output / "candidates.jsonl").read_bytes())})

    def tearDown(self):
        self.temporary.cleanup()

    def encoded(self, entry):
        return json.dumps({"items": [entry]})

    def fake_client(self, entry=None):
        content = self.encoded(entry or self.entry)
        class Client:
            def chat(self, **request):
                return {"model": mapping.MODEL, "choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        return Client()

    def complete(self):
        mapping.run(self.root, self.output, max_calls=2, batch_size=1, client=self.fake_client())
        mapping.export(self.root, self.output)

    def verify(self):
        with patch.object(mapping, "runtime_inputs", return_value=({"fixture": True}, [DISEASE])):
            return mapping.verify(self.root, self.output)

    def test_exact_quotes_and_population(self):
        actual = mapping.validate_response(self.encoded(self.entry), [self.packet])
        self.assertEqual(actual[0]["selections"][0]["scope"], "Adults; not children.")

    def test_fabricated_quote_is_rejected(self):
        entry = copy.deepcopy(self.entry)
        entry["selections"][0]["identity_quote"] = "Example disease always requires antibiotics"
        with self.assertRaisesRegex(ValueError, "Quote"):
            mapping.validate_response(self.encoded(entry), [self.packet])

    def test_evidence_id_copies_exact_provided_text(self):
        packet = mapping.wire_batches([self.packet], 1)[0][0]
        entry = copy.deepcopy(self.entry)
        entry["selections"][0].pop("identity_quote")
        entry["selections"][0]["evidence_id"] = "E1"
        result = mapping.validate_response(self.encoded(entry), [packet])
        self.assertEqual(result[0]["selections"][0]["identity_quote"], packet["candidates"][0]["evidence"][0]["text"])
        entry["selections"][0]["evidence_id"] = "E99"
        with self.assertRaisesRegex(ValueError, "Unprovided body evidence"):
            mapping.validate_response(self.encoded(entry), [packet])

    def test_foreign_and_duplicate_ids_are_rejected(self):
        entry = copy.deepcopy(self.entry)
        entry["selections"].append(entry["selections"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            mapping.validate_response(self.encoded(entry), [self.packet])
        entry["selections"][0]["document_id"] = "unprovided"
        with self.assertRaisesRegex(ValueError, "unprovided"):
            mapping.validate_response(self.encoded(entry), [self.packet])

    def test_documents_are_shared_across_the_supplied_request(self):
        first = copy.deepcopy(self.packet)
        second = copy.deepcopy(self.packet)
        second["disease_id"] = "urn:ontoward:SnomedCT2"
        second["candidates"][0]["document_id"] = "G00002"
        first["candidates"] = []
        left = copy.deepcopy(self.entry)
        left["selections"][0]["document_id"] = "G00002"
        right = copy.deepcopy(left)
        right["disease_id"] = second["disease_id"]
        results = mapping.validate_response(json.dumps({"items": [left, right]}), [first, second])
        self.assertEqual(len(results), 2)

    def test_unsupported_relation_and_plan_field_are_rejected(self):
        for field, value in (("relation", "same"), ("plan_fields", ["made_up"])):
            entry = copy.deepcopy(self.entry)
            entry["selections"][0][field] = value
            with self.assertRaises(ValueError):
                mapping.validate_response(self.encoded(entry), [self.packet])

    def test_background_reference_cannot_supply_plan_fields(self):
        entry = copy.deepcopy(self.entry)
        entry["selections"][0]["evidence_use"] = "background_only"
        with self.assertRaisesRegex(ValueError, "Background-only"):
            mapping.validate_response(self.encoded(entry), [self.packet])
        entry["selections"][0]["plan_fields"] = []
        mapping.validate_response(self.encoded(entry), [self.packet])

    def test_unresolved_is_explicit(self):
        entry = {**self.entry, "selections": []}
        with self.assertRaisesRegex(ValueError, "gap reason"):
            mapping.validate_response(self.encoded(entry), [self.packet])
        entry.update(gap_reason="No relevant candidate", search_terms=["alternate name"])
        self.assertEqual(mapping.validate_response(self.encoded(entry), [self.packet])[0], entry)

    def test_traversal_and_symlink_escape_are_rejected(self):
        with self.assertRaises(ValueError):
            mapping.output_directory(self.root, "submission/mappings.json")
        with self.assertRaises(ValueError):
            mapping.source_path(self.root, "../outside.md")
        (self.path.parent / "escape.md").symlink_to(self.root / "outside.md")
        with self.assertRaises(ValueError):
            mapping.source_path(self.root, "Group/escape.md")

    def test_retrieval_finds_body_mentions_and_excludes_archived(self):
        sources = [dict(self.source, title="Care of adults"), dict(self.source, path="Group/archived.md", title="Example disease (Archived)")]
        self.path.with_name("archived.md").write_bytes(BODY)
        db = sqlite3.connect(":memory:")
        db.execute("CREATE VIRTUAL TABLE search USING fts5(title,body,content='')")
        db.execute("INSERT INTO search(rowid,title,body) VALUES (1,'Care of adults','Example disease is discussed')")
        db.execute("INSERT INTO search(rowid,title,body) VALUES (2,'Example disease Archived','Example disease')")
        result = mapping.retrieve(db, sources, DISEASE)
        self.assertEqual([s["path"] for s, _ in result], [self.source["path"]])
        db.close()

    def test_title_navigation_keeps_laterality_and_excludes_basic_anatomy(self):
        self.assertEqual(mapping.title_key("Metatarsal Fractures"), mapping.title_key("Fracture of metatarsal bone"))
        self.assertNotEqual(mapping.title_key("Disorder of right eye"), mapping.title_key("Disorder of left eye"))
        self.assertTrue(mapping.excluded({**self.source, "title": "Anatomy, Foot"}))
        self.assertFalse(mapping.excluded({**self.source, "title": "Metatarsal Fractures"}))

    def test_prefix_retrieval_finds_plural_condition_with_site(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE VIRTUAL TABLE search USING fts5(title,body,content='')")
        db.execute("INSERT INTO search(rowid,title,body) VALUES (1,'Clinical Reference','Contusions of the elbow are discussed here')")
        db.execute("INSERT INTO search(rowid,title,body) VALUES (2,'Elbow Dislocation','Elbow assessment for dislocation')")
        sources = [dict(self.source, title="Clinical Reference"), dict(self.source, title="Elbow Dislocation", path="Group/other.md")]
        disease = {"aliases": ["Contusion of elbow"]}
        result = mapping.retrieve(db, sources, disease)
        self.assertEqual(result[0][0]["title"], "Clinical Reference")
        db.close()

    def test_full_replay_and_complete_section_subtree(self):
        self.complete()
        result = self.verify()
        self.assertEqual(result["mapped"], 1)
        value = mapping.load(self.output / "mappings.json")
        selection = value["diseases"][0]["selections"][0]
        treatment = next(s for s in selection["plan_sections"] if s["title"] == "Treatment")
        lines = BODY.splitlines(keepends=True)[treatment["start_line"] - 1:treatment["end_line"]]
        self.assertIn(b"Do not apply this approach to children.", b"".join(lines))
        self.assertFalse(selection["unconditional_disease_plan"])

    def test_source_mutation_is_detected(self):
        self.complete()
        self.path.write_bytes(BODY + b"changed\n")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            self.verify()

    def test_mapping_mutation_is_detected(self):
        self.complete()
        value = mapping.load(self.output / "mappings.json")
        value["diseases"][0]["selections"][0]["relation"] = "broader"
        mapping.save(self.output / "mappings.json", value)
        with self.assertRaisesRegex(ValueError, "Artifact differs"):
            self.verify()

    def test_model_response_mutation_is_detected(self):
        self.complete()
        path = next((self.output / "calls").glob("*/response.json"))
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "pin changed"):
            self.verify()

    def test_attempted_stage_is_not_resumed(self):
        self.complete()
        with self.assertRaisesRegex(ValueError, "already attempted"):
            mapping.run(self.root, self.output, max_calls=2, client=self.fake_client())

    def test_rejected_response_is_preserved(self):
        invalid = copy.deepcopy(self.entry)
        invalid["selections"][0]["identity_quote"] = "This quote was never present"
        with self.assertRaisesRegex(ValueError, "Quote"):
            mapping.run(self.root, self.output, max_calls=2, client=self.fake_client(invalid))
        call = next((self.output / "calls").iterdir())
        self.assertTrue((call / "request.json").exists())
        self.assertTrue((call / "response.json").exists())
        self.assertTrue((call / "failure.json").exists())
        self.assertEqual((self.output / "requests.jsonl").read_text().count('"event": "reserved"'), 1)

    def test_transport_failure_stops_without_retry(self):
        class FailedClient:
            def __init__(self):
                self.calls = 0
            def chat(self, **request):
                self.calls += 1
                raise RuntimeError("provider unavailable")
        client = FailedClient()
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            mapping.run(self.root, self.output, max_calls=2, client=client)
        self.assertEqual(client.calls, 1)
        self.assertTrue(next((self.output / "calls").glob("*/failure.json")))

    def test_no_source_is_not_complete_coverage(self):
        entry = {**self.entry, "selections": [], "gap_reason": "No relevant document"}
        mapping.run(self.root, self.output, max_calls=2, client=self.fake_client(entry))
        mapping.export(self.root, self.output)
        with self.assertRaisesRegex(ValueError, "no supported document"):
            self.verify()

    def test_request_ceiling_is_finite(self):
        for ceiling in (0, 201):
            with self.assertRaisesRegex(ValueError, "finite ceiling"):
                mapping.run(self.root, self.output, max_calls=ceiling, client=self.fake_client())

    def test_packet_mutation_before_execution_is_rejected(self):
        (self.output / "candidates.jsonl").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "preparation changed"):
            mapping.run(self.root, self.output, max_calls=2, client=self.fake_client())

    def test_family_path_requires_active_inferred_chain_and_direction(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE rf2_components(kind,id,active,type_id,characteristic,source_id,destination_id)")
        db.executemany("INSERT INTO rf2_components VALUES ('relationship',?,'1','116680003','900000000000011006',?,?)",
                       [("r1", "child", "middle"), ("r2", "middle", "parent")])
        link = {"source_child": "child", "source_parent": "parent", "rf2_relationship_ids": ["r1", "r2"],
                "relation": "narrower", "disease_id": "urn:ontoward:SnomedCTchild"}
        mapping.verify_family_path(db, "parent", link)
        with self.assertRaisesRegex(ValueError, "wrong direction"):
            mapping.verify_family_path(db, "parent", {**link, "relation": "broader"})
        with self.assertRaisesRegex(ValueError, "exact active inferred"):
            mapping.verify_family_path(db, "parent", {**link, "rf2_relationship_ids": ["r2", "r1"]})
        db.execute("UPDATE rf2_components SET active='0' WHERE id='r1'")
        with self.assertRaisesRegex(ValueError, "exact active inferred"):
            mapping.verify_family_path(db, "parent", link)
        db.close()


if __name__ == "__main__":
    unittest.main()
