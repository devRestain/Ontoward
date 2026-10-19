# Extraction Contract

- Own the independent python -m ontoward_extraction builder, prompts, pinned image, provider adapters, and checkpoint tests. Use root PROJECT_STATE.md for progress and data/ for durable results.
- Apply D49 and read ../data/ontology/AGENTS.md before changing emitted knowledge. Keep one provider per immutable build fingerprint and no automatic provider/model/account fallback.
- Start from supplied RF2 Snapshot/releases, eight BODHI CSVs, DDXPlus evidence/condition metadata, and allowlisted Astra candidate/binding/CPX fields. Exclude patients, old generated bundles/work DBs, and Astra snapshots/policies.
- Index raw inputs in SQLite; select latest RF2 rows before active use and check exact module/release dependencies. Preserve input hashes, phase/chunk cursors, prompts/contracts, requests, responses, accepted rows, usage, retries, and unknown outcomes transactionally.
- Use draft gpt-6-luna medium and final gpt-6.1-sol medium. Use NOVA session-free Client.chat, ChatGPT-authenticated read-only codex exec, or tool-free Responses structured output as explicitly selected.
- Keep NOVA/API output limits at 8000/32000, timeout at 600 seconds, and Codex CLI at 0.162.1. Manage CLI by finite work batches and timeout; do not claim a token cap it cannot enforce.
- Disable Codex shell, web, agents, config inheritance, and API-key authentication for the subscription route. Keep authentication in the new dedicated volume and never inspect or copy the old auth volume.
- Keep only provider-required credentials in each adapter. Never log credentials or run login/model calls as an offline check.
- Freeze finite phase worksets; accept valid sibling rows and repair missing/invalid rows within bounded attempts. Use final model knowledge for general relationships; generate no patient observations.
- Hold a single worker lock. Honor explicit pause, SIGINT, and SIGTERM before new jobs/requests; save the in-flight response and accepted rows before paused exit.
- Recover durable responses locally. Recover NOVA with its same ID/payload; require --retry-unknown for uncertain API/CLI transmissions and retain the superseded attempt. Require --resume for existing checkpoints.
- Compile only in output staging, verify through the production loader, and install build-specific files before atomically replacing the root manifest. Never overwrite an immutable build with different bytes.
- Keep status/pause independent of clients and keys, verify offline/read-only, restart disabled, and Compose stop grace at 660 seconds.
- Run synthetic end-to-end/pause/provider tests in project containers. Keep actual login, model access, generation quality, real DB creation, and real installation unrun in D49 acceptance.
