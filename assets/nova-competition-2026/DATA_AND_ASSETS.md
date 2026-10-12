# Organizer Data and Source Boundaries

Source snapshot: **2026-10-12 KST**. Existing organizer files remain in their sibling directories.

## Asset roles

| Existing location | Engineering purpose | Boundary |
| --- | --- | --- |
| [nova-starter](../nova-starter/README.md) | SDK, baseline, server sample client, build example | Reference implementation; not a performance guarantee |
| [nova-devkit](../nova-devkit/README.md) | Local patient/examiner simulation | Unscored; no server parity claim |
| [nova-samples-2026](../nova-samples-2026/AGENTS.md) | C01, C03, C10 fixtures and reference records | Initial information differs from simulator secrets and review outputs |
| [nova-benchmarks-2026](../nova-benchmarks-2026/AGENTS.md) | AgentClinic-MedQA, DDXPlus, ACI-Bench | Research inputs; not official NOVA cases |
| [guidelines](../guidelines/AGENTS.md) | Source-grouped clinical Markdown and catalog | Catalog-based document selection and per-document license review |

The three public fixtures contain initial information, simulator inputs, and reference records. Patient scripts, examination tables, and model records must not become Doctor-visible initial input. Sources: [preserved sample description](../nova-samples-2026/README.md), [L05: local sample contract](../nova-samples-2026/AGENTS.md).

## Guideline corpus

Local inspection found **15,904** cataloged clinical Markdown documents: **14,398 English** and **1,506 Korean**, across **16** source groups. `catalog.csv` includes paths, title, institution, year, language, type, format, license, and source URL. The workbook supports human browsing. KR/US prefixes describe grouping, not guaranteed language or universal clinical applicability. Source: [L04: catalog](../guidelines/catalog.csv) and [source contracts](../guidelines/AGENTS.md).

The organizer describes a read-only guideline mount at `/opt/nova/guidelines`, exposed as `NOVA_GUIDELINES_DIR`. [L02: Starter README](../nova-starter/README.md)

Project interpretation: use catalog paths as the clinical allowlist. Exclude AGENTS, README, Architecture, and this competition reference package. Preserve source metadata and references through preparation in `data/`; place builders in `Dev/` and runtime readers in `submission/`. Corpus presence does not establish relevance, currency, extraction quality, or license applicability to a derivative.

## Research datasets

| Dataset | Local package description | License evidence |
| --- | --- | --- |
| AgentClinic-MedQA | 215 expanded scenarios; base 107 overlaps | Preserve `LICENSE.txt` and `LICENSE_MedQA.txt` |
| DDXPlus | Approximately 1.29 million synthetic patients, 49 conditions | CC BY 4.0 in supplied license |
| ACI-Bench | 207 encounter dialogue–note pairs | CC BY 4.0 in supplied license |

Sources: [preserved benchmark description](../nova-benchmarks-2026/README.md), local [benchmark contract](../nova-benchmarks-2026/AGENTS.md), and nested contracts linked there. These packages are English text research data; the package describes NOVA evaluation scripts and examination tables as Korean. English technical documentation does not imply English patient interaction. Preserve original partitions; do not count transcript variants or overlapping releases as independent cases. Clinical guideline licenses vary, including noncommercial and no-derivatives conditions; inspect document-specific terms before transformation or redistribution.

## Published archive identifiers

| Organizer archive | Published SHA-256 |
| --- | --- |
| Benchmark ZIP | `a2b4dbc6a2bc177a54cf7c7f1a4e15f94625bfd335738737b575c6832a1060a7` |
| Guideline ZIP | `ef58c2f4369750af382f2706dcc1c9c7a85e3a93c261d880f7470d695eaf30d5` |

Source: [N03: Development documentation](https://nova.snubhai.org/docs/). These identify published ZIP bytes. No fresh archive download or comparison was performed; they do not authenticate the extracted workspace directories or the added project documentation.

## Integrity and permitted use

Research use requires suitable licenses and source attribution; submitted inference cannot use external APIs. [N05: Q&A](https://nova.snubhai.org/qna/)

No held-out-case training, tuning, or answer extraction; no cross-case memory, predictions, or statistics. [N02: Rules](https://nova.snubhai.org/rules/)

Project interpretation: keep public source provenance, simulator inputs, reference answers, and actual case evidence in distinct roles. The presence of a research dataset does not authorize ingestion or fine-tuning in the current project slice.

## Presentation and runtime-copy boundaries

The [opening](slides/opening-2026-10-06.md) and [workflow](slides/workflow-2026-10-11.md) conversions preserve dated competition context. They are excluded from clinical extraction and submission. [D12](../../DECISION_STATE.md#D12) permits only the unchanged SDK runtime copy from the organizer starter; original files remain in place. Source identities are recorded in [SOURCES.md](SOURCES.md).
