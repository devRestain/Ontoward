# Ontoward Agent Contract

## Project Philosophy and Anti-Slop

- Treat competition submission as the project endpoint.
- Implement only capabilities required by the selected competition workflow and the documented acceptance slice.
- Reject speculative features, reusable platforms, and extension points for hypothetical future use.
- Curate the final submission artifact to contain only required code, dependencies, and permitted assets.
- Verify the complete final agent workflow in its designated Docker container using representative cases.
- Prioritize evidence retrieval, action execution, response handling, SOAP generation, diagnosis submission, and confirmed termination.
- Exclude structure-only tests, deployment-environment test suites, and compatibility matrices from project acceptance.
- Prefer the smallest readable implementation that satisfies the current contract.
- Add abstractions, helper layers, configuration, and dependencies only for demonstrated needs in the current workflow.
- Reuse existing project patterns before introducing new ones.
- Keep comments and docstrings only for non-obvious constraints, rationale, or required interface documentation.
- Remove code-restating comments, decorative banners, dead code, and unused scaffolding within the changed scope.
- Handle real failures explicitly at the boundary that can act on them.
- Preserve input and output validation required by the competition workflow.

## Project Ownership

- Treat this directory as the Ontoward project boundary.
- Use `PRD.md` for the intended MVP behavior and adopted technology roles.
- Keep root documentation, dependency declarations, Docker configuration, and cross-directory integration in the root scope.
- Keep submission-agent Python and runtime graph readers in `submission/`.
- Keep submission/run.py as the thin NOVA entrypoint exposing prepare and consult from submission/workflow/runtime.py.
- Keep execution classes and shared case models in submission/workflow/ and RDFLib access code in submission/knowledge/ under D13.
- Keep pre-submission extraction, validation, RDF generation, and bundle preparation code and prompts in `Dev/`.
- Keep disposable project scratch in `Tmp/` and durable preparation results in `data/`.
- Keep the D27 local evaluation API, simulator model bridge, and isolated public-sample container harness in `Test/`.
- Keep the D31 local website, shell execution bridge, and read-only workflow observation in Test/; preserve submission/ bytes.
- Keep the D32 static project atlas in Test/atlas.html as a self-contained offline document; preserve runtime files and exclude execution controls and external assets.
- Assign Dev, Test, and Tmp operational progress to root `PROJECT_STATE.md` without adding state scopes.
- Preserve organizer packages in assets/ and permit only the D12 hash-pinned unchanged nova_sdk.py submission copy.
- Keep project-authored directory contracts and human orientation in `assets/` separate from preserved upstream files.
- Keep admitted additional sources, provenance, preparation results, and generated knowledge artifacts in `data/`.
- Assign provenance and preparation evidence for `assets/` inputs to the data scope.
- Assign operational progress to the `PROJECT_STATE.md` in its owning scope.
- Treat root, `submission/`, and `data/` as the three maintained state scopes.
- Keep generated directories and upstream archive internals under their existing owner.
- Apply D17 prepared interviews Pattern-first fit bounded parsing and adaptive budgets while preserving D11 session and submission boundaries.
- Apply D17 prepared Doctor delivery and designated-model Gateway interpretation; keep selection in InterviewPlanner and submission in SubmissionWriter.
- Maintain the implemented Korean workflow white paper in submission/README.md and keep root README as project orientation.
- Do not resume cancelled model jobs or expand the corpus without a new user request.
- Apply D18's source-only reset; exclude source downloads, submission publication, and WSL2 deployment.
- Apply D20's user-accepted competition graph connections and batch approval; leave Korean generation to its separate session.
- Apply D21 patient-action-only Korean generation with independent NFC 1-30 validation; prioritize the explicitly requested NOVA development-key route and retain SNU workspace Codex CLI as the alternative.
- Apply newer D22 NOVA-only continuation and explicitly authorized failure resumption within the frozen same-day ceiling; retain every rejected request and stop on completion or request/service limits.
- Apply D23 competition acceptance to complete source-backed candidates and D22 patient actions without another clinical or user approval gate; preserve technical exclusions and exact runtime pins.
- Apply D26 with Education disabled in the packaged public setting; skip its actions and turn reserve and leave P.education empty while completing diagnosis submission.
- Apply D29 for case-independent chief mapping to one supplied Symptom, source-backed bilingual aliases, and one bounded full-index lookup recovery.
- Apply D30 to fresh guideline-corpus document mappings for every admitted Disease; keep relation scope exact source evidence and bounded NOVA gpt-6-luna provenance outside runtime knowledge and SOAP plan generation.
- Exclude JEV, Laya, HPOA, deployment, and compatibility matrices from this slice; keep maintained workflow tests in Dev/tests/workflow and generated synthetic assets and evidence in Tmp.

## Working Order

- Read this contract, root `PROJECT_STATE.md`, and the relevant requirements in `PRD.md` before changing the project.
- Read the owning child contract and state before changing a child scope.
- Read `assets/AGENTS.md` and the relevant nested contract before handling organizer inputs.
- Consult `assets/nova-competition-2026/` for detailed competition information, starting with its `AGENTS.md` and the relevant reference documents.
- Read `DECISION_STATE.md` when an action depends on a user choice.
- Treat recommendations in `DECISION_STATE.md` as proposals until the user selects an option.
- Keep the selected preliminary SDK route for the Doctor; apply D05 and D09's full Snapshot/BODHI-S preparation database and separately approved v5.0 runtime exports.
- Use D07 for preserved preparation evidence, separately admitted submission bundles, and one runtime RDFLib Graph.
- Use D08 and data/ontology/AGENTS.md for shared patterns, typed conditions, disease associations, conditional weights, and SDK text mapping.
- Use specific clinical pain complaints as D08 retrieval targets and preserve finer Location values, raw wording, interpretation uncertainty, and separate episodes.
- Use D17 for the five-session adaptive workflow Python decisions common action budget and reconsideration of undelivered low-priority questions; use D12 for wire format and packaging.
- Apply D15 for information-preserving SOAP and bounded Gateway vocabulary; use D18 for all knowledge and Korean text preparation.
- Apply newer explicit user decisions before stale operational plans or next goals; record implementation and execution only from observed evidence.
- Isolate runtime LLM instructions and editable clinical text in submission/config with public environment-selected paths; keep machine field names and decision codes in Python.
- Package only submission runtime Python, pinned requirements, public .env, config prompts and text, and knowledge assets through the package Compose service under D14.
- Exclude submission guidance, operational state, root .env, caches, preparation files, and organizer originals from the ZIP.
- Keep local development credentials in the root .env and only application-owned public settings in submission/.env.
- Resolve runtime knowledge paths inside submission/ without reading parent workspace data.
- Keep runtime Turtle, required JSON schemas, and their manifest inside submission/knowledge/ for both execution and tests.
- Use package-relative imports within runtime packages and settings.py for file-relative submission data paths.
- Apply D13 responsibility names and keep Consultation as the sole internal-session coordinator.
- Keep pure workflow decisions in workflow/rules and cross-state question interaction and usage operations in their designated workflow/state owners.
- Run maintained offline workflow checks with Dev/tests/workflow/compose.offline.yaml and exclude tests and synthetic assets from the submission.
- Require D08 v5.0 alignment before generating or admitting new clinical artifacts.
- Use Dev/ontology/source_projection.py build/export/admit, database.py, model_normalization.py, admission.py, and v5.py for full source ingestion, candidate projection, and pinned batch admission.
- Delete pre-v5 derived data, authored seed vocabularies, old clinical/text batches, guideline-derived outputs, and their obsolete approvals under D18.
- Preserve supplied assets byte-for-byte and record the hash-verified source custody, deletion receipt, and clean empty v5 base.
- Use source_catalog.py with source_projection.py for every schema class, complete source-edge custody, Korean coverage, and explicit unsupported runtime roles.
- Use source_projection.py connections and connections.py for source-backed ROS, typed Context, prerequisite applicability, and the selected nonduplicate physical finding path.
- Reuse the immutable source-custody database read-only for D20 projection batches; keep approvals pinned to the exact derived graph and transformation policy.
- Treat graph_admitted_text_pending as approved graph data awaiting action text; require completed pinned wording before prepare allows consultation.
- Admit D23 text with a new receipt referencing the D20 graph and D22 provenance; preserve the original graph receipt and admission report.
- Apply D19 with findings.py for source acquisition roles, clinical Observable dimensions, exact grouped values, and specialty gaps; keep its source graph outside executable previews until reviewed.
- Use shared evidence sets and the canonical SQLite audit; archive superseded large JSON losslessly instead of copying global attribute proofs or accumulating interrupted previews.
- Use D22's NOVA-only route for current Korean wording and Docker Codex CLI only for separately authorized normalization or earlier worksets; preserve candidate provenance and never treat model translations as Korean RF2 terms.
- Require new build-pinned admission after D18; do not reuse previous batch or vocabulary approvals.
- Use D10 for the separate extraction image and later WSL2 operating boundary.
- Record decision alternatives, selections, and lifecycle changes only in `DECISION_STATE.md`.
- Reference decision IDs from operational state without copying their alternatives or statuses.
- Reference child state from the root without copying child tasks, completion claims, or evidence.
- Record only cross-directory coordination and root-owned work in root operational state.
- Reserve every project-authored `README.md` for human orientation and inspect it only when the requested work concerns that document or its source contents.
- Use `AGENTS.md` files as agent-consumed contracts for ownership, file meaning, workflow, and input boundaries.
- Treat `assets/Architecture.md` as the human explanation of organizer-package relationships.

## Docker Workflow

- Use the root `compose.yaml` project `ontoward` and service `dev` for the declared development environment.
- Use docker compose build package and docker compose run --rm -T package for the isolated submission archive image.
- Mount only submission/ read-only as /submission and Tmp/packaging/ as /output in the package service.
- Use the separate `ontology-extraction` service and image for pre-submission preparation and Codex login.
- Use `docker compose build ontology-extraction` and `docker compose up -d ontology-extraction` for its image and persistent container.
- Enter the extraction environment with `docker compose exec ontology-extraction bash`.
- Use `docker compose build dev` to build the declared environment when image building is in the active scope.
- Use `docker compose run --rm dev` to enter its Python interpreter when container execution is in the active scope.
- Keep submission-agent dependencies in `submission/requirements.txt` and install them through the root Dockerfile.
- Keep the preparation environment in `Dev/codex/Dockerfile` and its setup helper in `Dev/codex/environment.py`; use the existing Pydantic, RDFLib, and standard-library SQLite dependencies.
- Use `/workspace` as the container working directory; mount the project root in dev and only declared input/output paths in ontology-extraction.
- Identify existing Docker resources through the Compose project and service labels plus the workspace mount before using them.
- Keep extraction CLI state and credentials in a dedicated project-owned Docker volume outside disposable scratch and submission artifacts.
- Use Test/compose.yaml for the network-isolated scripted evaluator and its separate compose.nova.yaml overlay for NOVA development chat.
- Use sh Test/web.sh for the loopback-only Test frontend; keep its Docker execution in the host shell bridge and its key outside the web container.
- Keep Test/ patient scripts and the development key outside the agent container and preserve the unchanged submission/run.py entrypoint.
- Record image, package, and RDFLib execution availability only after observing the relevant container behavior.

## Documentation and Handoff

- Write every project-authored `AGENTS.md` as a technical English contract for agent consumption.
- Write operational state in English.
- Write every project-authored `README.md` in Korean for human consumption.
- Write PRD and user decision explanations in Korean.
- Keep stable behavior in the PRD, agent rules in AGENTS, human orientation in README, and mutable progress in scoped state.
- Use the `/state version=1` protocol for each operational `PROJECT_STATE.md`.
- Maintain one current bounded goal and at most one next goal in each operational state file.
- Review document meaning, references, ownership, and observed claims directly.
- Record unperformed execution as `not_run`, `unconfigured`, or `unknown` according to the available evidence.
- Identify all project-maintained operational and decision state documents that could reference, schedule, depend on, or resume a task before declaring completion.
- Verify each identified state document against the completed work and observed evidence.
- Update every affected state document in its owning scope to reflect post-completion goals, blockers, handoffs, and references.
- Declare completion only after all identified state documents are consistent with the post-completion state.
- Delete explicitly withdrawn or rejected decisions and tasks from state documents instead of retaining them as history or evidence.
- Remove references and evidence records used exclusively by deleted decisions or tasks.
- Preserve evidence still required by active work or accepted results.
- Report the completed slice and the next bounded action without promoting scaffold completion to MVP completion.
