import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from Dev.education import prepare as prep


class EducationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / "Tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "data/preparation/education/batch"
        self.output.mkdir(parents=True)
        self.catalog = self.root / "assets/guidelines/catalog.csv"
        self.catalog.parent.mkdir(parents=True)
        self.documents = {
            "Books/alpha.md": ("Alpha", "질환 개요(교과서)",
                "# Alpha\r\n\r\n## Education\r\n\r\n성인에게 적용합니다. Children need a different approach.\r\n"
                "### Warning signs\r\n\r\n| 조건 | 안내 |\r\n|---|---|\r\n| 악화 | 다시 진료 |\r\n\r\n"
                "## Management\r\n\r\nDo not include this separate section.\r\n"),
            "Guides/beta.md": ("Beta", "진료지침",
                "# Beta\n\n## Care\n\nOnly the specified adult population.\n"
                "### Considerations\n\nConditional recommendation and exceptions.\n\n"
                "## Care\n\nDifferent setting.\n### Considerations\n\nKeep this distinct.\n"
                "## Empty\n\n"),
        }
        with self.catalog.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(prep.CATALOG_FIELDS)
            for path, (title, kind, body) in self.documents.items():
                metadata = {"title": title, "organization": "Fixture Society", "year": "2026",
                            "language": "en", "source_url": f"https://example.invalid/{title}", "license": "Fixture only"}
                header = "---\n" + "\n".join(f"{key}: {json.dumps(value)}" for key, value in metadata.items()) + "\n---\n"
                document = self.catalog.parent / path
                document.parent.mkdir(parents=True, exist_ok=True)
                document.write_bytes((header + body).encode())
                writer.writerow([path, title, metadata["organization"], "2026", "영어", kind,
                                 "Markdown", metadata["license"], metadata["source_url"]])
        knowledge = self.root / "submission/knowledge"
        knowledge.mkdir(parents=True)
        assets = {}
        for name, text in {"schema": "@prefix ow: <urn:ontoward:> . ow:Disease a <http://www.w3.org/2000/01/rdf-schema#Class> .",
                           "vocabulary": '@prefix ow: <urn:ontoward:> . @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . ow:Alpha a ow:Disease ; rdfs:label "Alpha"@en, "알파"@ko . ow:Beta a ow:Disease ; rdfs:label "Beta"@en .',
                           "clinical": "@prefix ow: <urn:ontoward:> . ow:Alpha ow:hasAssociation ow:Example ."}.items():
            data = text.encode()
            (knowledge / f"{name}.ttl").write_bytes(data)
            assets[name] = {"path": f"knowledge/{name}.ttl", "sha256": prep.sha256(data)}
        (knowledge / "manifest.json").write_bytes(prep.json_bytes({"preparation_status": "admitted",
            "schema": assets["schema"], "vocabulary": assets["vocabulary"], "bundles": [assets["clinical"]]}))
        self.saved = prep.inventory(self.root)
        self.inventory_file = self.output / "inventory.json"
        self.inventory_file.write_bytes(prep.json_bytes(self.saved))
        self.mappings = {"version": prep.VERSION, "status": prep.STATUS,
                         "inventory_sha256": prep.sha256(self.inventory_file.read_bytes()), "diseases": []}
        for name, path in (("Alpha", "Books/alpha.md"), ("Beta", "Guides/beta.md")):
            self.mappings["diseases"].append({"disease_id": f"urn:ontoward:{name}", "disposition": "mapped_draft",
                "reason": "Direct title and body confirmed for the fixture.", "selections": [self.mapping(path)]})
        self.mappings_file = self.output / "mappings.json"

    def mapping(self, path, index=1):
        source = self.saved["sources"][path]
        _, _, headings = prep.document((self.catalog.parent / path).read_bytes())
        heading = headings[index]
        return {"source": path, "source_sha256": source["sha256"],
                "heading_path": heading["heading_path"], "start_line": heading["start_line"], "end_line": heading["end_line"],
                "selection": "section", "document_role": "clinical_guidance" if source["document_type"] in prep.GUIDANCE else "clinician_textbook",
                "reason": "Education with qualifying context.", "applicability": "The adult population stated in the source.",
                "limitations": "No extension to other populations.", "identity_evidence": "Disease named in the chapter body.",
                "authority_evidence": "Fixture publisher and clinical role checked.", "context_review": "Full section and nested conditions retained."}

    def run_batch(self, verify=False):
        self.mappings_file.write_bytes(prep.json_bytes(self.mappings))
        return prep.batch(self.root, self.inventory_file, self.mappings_file, self.output, verify=verify)

    def test_full_inventory_build_verify_preserves_exact_source(self):
        result = self.run_batch()
        self.assertEqual(result["dispositions"], {"mapped_draft": 2})
        raw = (self.output / "excerpts.jsonl").read_bytes()
        entries = [json.loads(line) for line in raw.splitlines()]
        for entry in entries:
            original = (self.catalog.parent / entry["source"]).read_bytes().splitlines(keepends=True)
            expected = b"".join(original[entry["start_line"] - 1:entry["end_line"]])
            self.assertEqual(entry["text"].encode(), expected)
            self.assertEqual(entry["excerpt_sha256"], prep.sha256(expected))
            self.assertEqual(entry["provenance"]["license"], "Fixture only")
        alpha = next(entry for entry in entries if entry["disease_id"].endswith("Alpha"))
        self.assertIn("\r\n", alpha["text"])
        self.assertIn("악화", alpha["text"])
        self.assertIn("Warning signs", alpha["text"])
        self.assertNotIn("Do not include", alpha["text"])
        self.assertGreater(len(alpha["text"]), 30)
        self.assertEqual(self.run_batch(verify=True)["result"], "pass")
        self.assertEqual((self.output / "excerpts.jsonl").read_bytes(), raw)

    def test_repeated_heading_uses_explicit_position(self):
        mapping = self.mapping("Guides/beta.md", 4)
        entry = prep.extract(self.root, self.saved, mapping)
        self.assertIn("Keep this distinct", entry["text"])
        self.assertNotIn("Conditional recommendation", entry["text"])

    def test_source_mutation_rejects_without_overwriting_previous_output(self):
        self.run_batch()
        before = (self.output / "excerpts.jsonl").read_bytes()
        with (self.catalog.parent / "Books/alpha.md").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "Source digest mismatch"):
            self.run_batch()
        self.assertEqual((self.output / "excerpts.jsonl").read_bytes(), before)

    def test_changed_inventory_or_runtime_rejected(self):
        self.mappings["inventory_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "inventory pin"):
            self.run_batch()
        (self.root / "submission/knowledge/vocabulary.ttl").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Runtime asset digest"):
            self.run_batch()

    def test_catalog_mutation_rejected(self):
        with self.catalog.open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(ValueError, "catalog changed"):
            self.run_batch()

    def test_unknown_duplicate_and_missing_diseases_rejected(self):
        original = copy.deepcopy(self.mappings)
        for mutation in ("urn:ontoward:Unknown", "urn:ontoward:Alpha"):
            self.mappings = copy.deepcopy(original)
            self.mappings["diseases"][1]["disease_id"] = mutation
            with self.assertRaisesRegex(ValueError, "every runtime Disease"):
                self.run_batch()
        self.mappings["diseases"].pop()
        with self.assertRaisesRegex(ValueError, "every runtime Disease"):
            self.run_batch()

    def test_non_catalog_path_and_symlink_escape_rejected(self):
        mapping = self.mapping("Books/alpha.md")
        mapping["source"] = "Books/not-cataloged.md"
        with self.assertRaisesRegex(ValueError, "eligible catalog"):
            prep.extract(self.root, self.saved, mapping)
        for path in ("../outside.md", "/outside.md", "Books\\outside.md"):
            with self.assertRaises(ValueError):
                prep.source_path(self.root, path)
        target = self.root / "outside.md"
        target.write_bytes(b"outside")
        (self.catalog.parent / "Books/link.md").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "leaves its owner"):
            prep.source_path(self.root, "Books/link.md")

    def test_invalid_ranges_and_clipped_sections_rejected(self):
        for start, end in ((0, 2), (True, 3), (3, 2), (1, 1000)):
            mapping = self.mapping("Books/alpha.md")
            mapping.update(start_line=start, end_line=end)
            with self.assertRaises(ValueError):
                prep.extract(self.root, self.saved, mapping)
        mapping = self.mapping("Books/alpha.md")
        mapping["end_line"] -= 1
        with self.assertRaisesRegex(ValueError, "entire section"):
            prep.extract(self.root, self.saved, mapping)

    def test_empty_section_and_wrong_heading_rejected(self):
        with self.assertRaisesRegex(ValueError, "Empty clinical excerpt"):
            prep.extract(self.root, self.saved, self.mapping("Guides/beta.md", 5))
        mapping = self.mapping("Books/alpha.md")
        mapping["heading_path"] = ["Wrong"]
        with self.assertRaisesRegex(ValueError, "heading"):
            prep.extract(self.root, self.saved, mapping)

    def test_explicit_paragraph_range_preserves_qualifier(self):
        mapping = self.mapping("Books/alpha.md")
        mapping.update(selection="lines", start_line=mapping["start_line"] + 2, end_line=mapping["start_line"] + 2)
        self.assertIn("Children need a different approach", prep.extract(self.root, self.saved, mapping)["text"])

    def test_artifact_tampering_rejected(self):
        self.run_batch()
        (self.output / "excerpts.jsonl").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "artifact differs"):
            self.run_batch(verify=True)

    def test_gap_requires_reason_and_has_no_excerpt(self):
        disease = self.mappings["diseases"][1]
        disease.update(disposition="needs_review", selections=[], reason="Only a population-specific source candidate remains.")
        self.assertEqual(self.run_batch()["excerpts"], 1)
        disease["reason"] = ""
        with self.assertRaisesRegex(ValueError, "concrete selection or gap reason"):
            self.run_batch()

    def test_pins_review_role_and_output_boundary(self):
        mapping = self.mapping("Books/alpha.md")
        mapping["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "pin differs"):
            prep.extract(self.root, self.saved, mapping)
        mapping = self.mapping("Books/alpha.md")
        mapping["context_review"] = ""
        with self.assertRaisesRegex(ValueError, "context_review"):
            prep.extract(self.root, self.saved, mapping)
        mapping = self.mapping("Books/alpha.md")
        mapping["document_role"] = "clinical_guidance"
        with self.assertRaisesRegex(ValueError, "role differs"):
            prep.extract(self.root, self.saved, mapping)
        with self.assertRaisesRegex(ValueError, "output must stay"):
            prep.output_path(self.root, "submission/knowledge")

    def test_noneligible_sources_do_not_become_selected_evidence(self):
        for title in ("Alpha (Nursing)", "Alpha (Archived)"):
            self.assertFalse(prep.eligible({"title": title, "document_type": prep.TEXTBOOK}))
        self.assertFalse(prep.eligible({"title": "Alpha", "document_type": "근거 리뷰"}))
        self.mappings["status"] = "admitted"
        with self.assertRaisesRegex(ValueError, "draft inventory pin"):
            self.run_batch()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EducationPreparationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    output = ROOT / "Tmp/education-tests/verification.json"
    prep.write(output, prep.json_bytes({"tests": result.testsRun, "successful": result.wasSuccessful(),
        "failures": [str(test) for test, _ in result.failures], "errors": [str(test) for test, _ in result.errors],
        "clinical_validation": "not_run", "real_model": "not_run", "official_sdk": "not_run"}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
