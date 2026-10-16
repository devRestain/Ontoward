# NOVA review adoption under D15

These are dated D15 dispositions. D17 now adopts prepared utterances, fact-level validation, bounded context, Pattern-first fit, dynamic replanning, shared turns, and correction obligations. Use [D17_REVIEW_ADOPTION.md](D17_REVIEW_ADOPTION.md) and the current decisions/contracts for implementation; keep D16 education draft review independent.

Source: the body of [온워드 공모전 분석 보고서](chatgpt-conversation://6acfbec4-f800-8340-af7f-82c1ea6a4c31), retrieved in this Codex conversation. The report described repository commit ba824e46be7e20a8ac42853635513de5b4096681. Its sandbox-linked Markdown, HTML, ZIP, and reproduction files were not retrieved. Treat the report as review evidence; D15 and the explicit implementation request select the adopted behavior.

The local review reproduced unresolved values being considered known, identical left/right and current/past rendering, and a selected primary disease reappearing in the differential list. The pre-change 52-case synthetic workflow suite passed; that baseline did not cover these conditions. Operational execution evidence belongs in the three PROJECT_STATE.md scopes.

| Report recommendation | D15 disposition and implementation | Acceptance or later decision condition |
|---|---|---|
| Distinguish asked questions from resolved information | Adopt was_asked from delivered actions and has_resolved_evidence from sourced clinical values; retain the existing two-clarification limit | Test unknown, uncertain, empty attributes, valid later clarification, and no ordinary repeated question |
| Preserve structured meaning in SOAP | Adopt deterministic subject, time, episode, categorical and numeric rendering; keep exact source wording | Test laterality, family versus patient, past versus current, repeated occurrences, mixed units and calendar units |
| Keep primary and differential selection consistent | Adopt shared evidence_score > 0 eligibility, explicit selected-ID exclusion and a five-alternative cap | Test context-only ranking above a supported disease and an empty eligible alternative set |
| Preserve valid facts from mixed parser responses | Defer general fact-level partial validation; preserve first-pass valid facts specifically during vocabulary expansion | Next bounded design covers fact dependencies, corrections, error categories and purpose-specific recovery |
| Restrict vocabulary and cache graph access | Adopt cached labels/types/aliases and target values, bounded prioritized vocabulary, and one broader parse for valid unlinked facts | Test count and UTF-8 byte caps, mandatory question values, new symptom recall, invalid expansion and budget exhaustion |
| Prefer prepared Doctor wording | Defer a Doctor framing policy change; supply reviewed prepared questions for the existing policy and fallback | Compare actual Luna semantic fidelity, cost and latency against the current policy under an explicit call budget |
| Replan after new information and redistribute turns | Defer; preserve D11 fixed HPI/ROS, scope caps and one coordinator | Select event triggers, repetition/discard rules and a case comparison before implementation |
| Track conflicts, uncertainty and alternative scoring | Defer a scoring redesign; preserve D08 v5.0 replacement, deduplication, valid zero and fractional weights | Compare policies on held-out cases without treating scores as calibrated probabilities |
| Track explanation obligations and apply plans to the case | Defer disease plans and new obligation state; preserve actual delivery records and explicit missing plans | Prepare separately reviewed clinical plans and select safety/correction obligations before implementation |
| Establish actual-model and sample performance | Keep offline scripted evidence distinct from real Luna, official SDK transport and evaluation | Require exact service targets, call/quota budgets and version-pinned experiments in a later request |

## Knowledge and wording boundary

D15 accepts the full pinned candidate batch: 9,400 associations, 1,701 registry entries, 842 diseases, 490 symptoms, 1,796 patterns and 3,282 features. The original SQLite source custody and preview remain preparation evidence. The separate approved receipt records user candidate acceptance and does not assert independent clinical validation.

Minimal interview assets provide 490 presence questions, 16 attribute templates, Korean wording for the 241 missing symptom labels and 16 attribute names, and two reviewed long-label question overrides. Causal, temporal and laterality qualifiers in source labels remain explicit. These are display and interview assets rather than additional disease relations, thresholds or treatment advice.

The batch has no admitted ExamFinding or ContextFactor concepts. Some source targets are diagnostic composites or reported findings rather than simple complaints; the parser must not infer a composite's causal qualifier from an unqualified symptom. Translations and scripted responses do not establish actual Luna interpretation or clinical accuracy. Missing disease-specific treatment, disposition, follow-up and education plans remain visible as unavailable assets.

The independent archive consumes only its manifest-declared assets under submission/knowledge. The preparation database, source files, approval records, tests, synthetic observations and this review document stay outside the ZIP.
