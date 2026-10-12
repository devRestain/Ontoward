# Execution and Submission Contract

Observed **2026-10-12 KST**. Published requirements come from [N02](https://nova.snubhai.org/rules/) and [N03](https://nova.snubhai.org/docs/); execution details are supplemented by [L07 slides 3–12](slides/workflow-2026-10-11.md).

## Runtime lifecycle

| Boundary | Contract |
| --- | --- |
| Build | PyPI wheels and pinned name==version requirements; 20-minute limit |
| prepare() | Up to 10 minutes, no case access |
| ready() | SDK signals readiness before consultation |
| consult(client, prepared) | Up to 30 minutes; 50 interaction turns |
| Termination | Submit through client.diagnose and inspect its response |
| Case isolation | New case container; no cross-case memory, files or statistics |

Preliminary resources: two CPUs, 8 GB RAM, no GPU; designated openai/gpt-oss-20b via client.chat. Finals: eight CPUs, 32 GB RAM, one A6000-class 48 GB GPU; participant model from NOVA_MODEL_DIR, without preliminary client.chat.

The workflow deck describes a read-only filesystem with /tmp (512 MB) and /output writable. Official session reads omit past events; the application must maintain its transcript. A process exit alone does not establish a valid diagnosis submission or score. These are organizer descriptions, not locally reproduced server behavior.

## Environment boundary

| Value | Owner |
| --- | --- |
| NOVA_API_BASE, NOVA_RUN_TOKEN, NOVA_SESSION_ID | Official runner connection and case identity |
| NOVA_GUIDELINES_DIR | Organizer corpus mount, usually /opt/nova/guidelines |
| NOVA_MODEL_DIR, NOVA_OUTPUT_DIR | Runner model/output locations |
| Root .env: NOVA_API_BASE, NOVA_DEV_KEY, local guideline path | Local development only; never packaged |
| submission/.env: ONTOWARD_KNOWLEDGE_MANIFEST | Public application setting; included in code ZIP |

Packaged settings use literal KEY=VALUE, without shell expansion. Runtime environment values take precedence. The application reads its manifest relative to the submission directory and cannot escape into the development workspace. Runner credentials are not stored in the packaged .env.

## Code artifact

ZIP root must contain run.py and requirements.txt. Limits are **50,000,000 compressed bytes**, **500,000,000 expanded bytes**, and **5,000 files**. Encryption, symlinks, traversal and duplicate paths are prohibited. Participant Dockerfiles are not submitted.

Ontoward maintains runtime source in submission/. It includes the unchanged SDK 1.0.1 and public .env. Its AGENTS.md, README.md, PROJECT_STATE.md and caches are development metadata and must be excluded. The project command `docker compose run --rm -T package` creates `Tmp/packaging/ontoward-submission.zip` with root-relative members and checks the archive constraints. D14 uses a dedicated package image with only /submission input and /output mounts and no network; runtime and test assets stay inside the submission knowledge directory.

An archive can satisfy packaging constraints while the clinical workflow remains unimplemented. The packager does not grant clinical knowledge admission or certify working diagnosis. No empty manifest or unapproved extraction preview is packaged.

## Dependencies and later assets

The root Dockerfile installs submission/requirements.txt; extraction and conversion dependencies stay outside it. No lazy network downloads are permitted during evaluation. The organizer already mounts its guideline corpus; do not copy that corpus into the code archive.

Only reviewed, submission-admitted Turtle and required JSON assets belong under submission/knowledge/. Preserve provenance in the data owner. Finals model ZIP (up to 32 GB) and PPT/PPTX are separate artifacts. Model size does not establish fit in GPU memory.

Submission versions may be rebuilt after their cached image is unused for over three days, using the same pinned versions (N03). Uploading code and selecting official evaluation are distinct actions; sample validation is optional (N02).
