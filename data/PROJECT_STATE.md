/state version=1
/project id=ontoward-data
/status value=complete
/checkpoint revision=f06b8cb2360b7edddf87553fe015a003f06bc69d dirty=true updated=2026-10-14T16:58:21+00:00
/goal phase=current id=DATA.V501 state=complete action="Preserve required archival evidence and prepare the bounded real-source v5.0 preview"
/goal phase=next id=DATA.V5REVIEW01 state=blocked action="Review the v5.0 registry source mappings variants and unresolved conditions before runtime admission"
/accept id=DATA.V501.A1 state=pass action="Generate a pinned v5.0 preview from supplied RF2 and BODHI sources for the three selected Targets" evidence=DATA.V501.E1,DATA.V501.E2
/accept id=DATA.V501.A2 state=pass action="Verify real-source score replacement sharing typed values source boundaries and required-condition dispositions" evidence=DATA.V501.E2,DATA.V501.E3
/accept id=DATA.V501.A3 state=pass action="Preserve source and prior preparation identity while clearly deprecating old interfaces" evidence=DATA.V501.E2,DATA.V501.E4,DATA.V501.E5
/accept id=DATA.V501.A4 state=pass action="Reconcile source schema ownership contracts and the separate clinical-admission handoff" evidence=DATA.V501.E6
/evidence id=DATA.V501.E1 class=artifact result=pass source=data/preparation/v5/snomed-bodhi-2026-10-15/manifest.json observed="Pin schema 5.0 registry normalization source Snapshot and file hashes plus public scoring policy v5.0.1 for International 20260501 and Korean 20260615"
/evidence id=DATA.V501.E2 class=runtime result=pass source=data/preparation/v5/snomed-bodhi-2026-10-15/verification.json observed="Pass 59 checks across 19 source files and the real preview with synthetic patient observations including cholecystitis 2 to 1 to 4 and graph immutability"
/evidence id=DATA.V501.E3 class=artifact result=pass source=data/preparation/v5/snomed-bodhi-2026-10-15/report.json observed="Generate 72 shared Patterns 670 Associations and 153 Features from 81 of 93 selected BODHI variants and retain 12 unresolved variants plus 92 unresolved of 95 SNOMED packets"
/evidence id=DATA.V501.E4 class=artifact result=pass source=Tmp/ontology-v5/preservation.json observed="Verify 274 unchanged entries in seven retained preparation manifests plus exact archived v4.2 schema and vocabulary and unchanged starter terminology"
/evidence id=DATA.V501.E5 class=semantic result=pass source=data/ontology/deprecated.json observed="Identify retired extraction code schemas and preparation directories as archival and runtime-ineligible without deleting source originals or approval receipts"
/evidence id=DATA.V501.E6 class=semantic result=pass source=data/ontology/AGENTS.md observed="Align v5.0 shared Pattern and typed value ownership with source review and runtime admission and remove obsolete pending guideline and live SNOMED goals"
/evidence id=DATA.V501.E7 class=artifact result=pass source=data/preparation/v5/snomed-bodhi-2026-10-15/sources.json observed="Retain 27 unknown and 9 inactive Condition identifiers and 189 context or non-disease exclusions with raw values and variant or relationship-group unresolved reasons"
/evidence id=DATA.V501.E8 class=artifact result=pass source=data/ontology/vocabulary-approval.json observed="Preserve the approved 510-term receipt and prior explicit candidate approvals as archival evidence without automatic v5.0 conversion"
/evidence id=DATA.V501.E9 class=semantic result=not_run source=data/preparation/v5/snomed-bodhi-2026-10-15/registry.json observed="Leave candidate mapping clinical correctness unresolved-variant review diagnostic performance and runtime admission unrun"
/evidence id=DATA.V501.E10 class=external_service result=not_run source=Dev/ontology/source_projection.py observed="Make zero real model or API calls and leave official evaluation publication and new source acquisition unrun"
/blocker id=DATA.V5REVIEW01.B1 state=open action="Obtain clinician review of candidate registry mappings complete variant meaning and unresolved source conditions" source=data/preparation/v5/snomed-bodhi-2026-10-15/registry.json
/blocker id=DATA.V5REVIEW01.B2 state=open action="Select separately reviewed execution assets and prepared clinical questions and plans before runtime admission" source=DECISION_STATE.md
/scope id=DATA.V501.S1 state=in action="Own source provenance version pins schema registry mappings variant dispositions derived contributions and durable preview verification"
/scope id=DATA.V501.S2 state=out action="Exclude patient state corpus expansion automatic clinical admission old job resumption and source publication"
/handoff state=blocked action="Keep the three-Target preview candidate-only and await clinician review before handing assets to APP.ASSETS01"
