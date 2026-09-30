# Documentation claim check

- Date: 2026-09-30
- Commit: `8193ab6`
- Method: one clean-context verifier per document group extracted and checked every technical claim; an independent skeptic tried to refute each drift finding; every locator and verbatim quote was then checked mechanically against the files.
- Authority: repository source. This report is evidence for a documentation fix, not an authorization.

## Summary

- Claims checked: 727 (contradicted 6, imprecise 38, supported 664, unsupported 2, unverifiable 17)
- Drift findings raised: 46; after skeptic review: confirmed 32, refuted 7, uncertain 7
- Locator checks on non-unverifiable claims: ok 709, out_of_range 1

## Coverage

| Group | Document | Lines | Last reviewed |
|---|---|---:|---:|
| G1 | `docs/DESIGN.md` | 439 | 439 |
| G1 | `docs/COMPATIBILITY.md` | 28 | 28 |
| G1 | `docs/V26.md` | 80 | 80 |
| G2 | `docs/RUNBOOK.md` | 435 | 435 |
| G2 | `README.md` | 81 | 81 |
| G3 | `docs/RETENTION.md` | 323 | 323 |
| G3 | `docs/SDK.md` | 267 | 267 |
| G4 | `palimnex/README.md` | 300 | 300 |
| G4 | `AGENTS.md` | 37 | 37 |
| G4 | `.agents/skills/palimnex/SKILL.md` | 17 | 17 |
| G4 | `docs/PROVENANCE.md` | 27 | 27 |
| G4 | `docs/PAGES.md` | 42 | 42 |
| G5 | `docs/LONGITUDINAL_EVALUATION.md` | 234 | 234 |
| G5 | `palimnex/CHANGELOG.md` | 199 | 199 |
| G6 | `docs/AGENT_INIT_PROMPT.md` | 138 | 138 |
| G6 | `docs/index.html` | 346 | 346 |

## Confirmed drift (32)

### G3-047 · high · `docs/RETENTION.md:137`

- Claim: "Unknown or unverified pack membership conservatively blocks affected deletion"
- Verifier: **contradicted** — Only packs recorded via RetentionLedger.register_pack block (called only in tests; no CLI/SDK path). memory-export/export_pack on a retention ledger registers nothing, so unknown pack copies do not block; they only appear as caveat unregistered_copies_out_of_band. (`palimnex/retention.py:428-430`, check: ok)
- Skeptic: **confirmed** — Pack blocking happens only for event ids in s['packs'] (retention.py:428-430). That state is filled only by RetentionLedger.register_pack, and the only caller in the repository is test_retention.py:58. No CLI command, SDK method, or export path calls it. portable.export_pack (portable.py:517-579), used by the memory-export CLI (core.py:3259-3270) and the SDK (api.py:191-196), writes a pack without registering its membership. Records in unregistered or unverified packs therefore stay eligible for deletion. The plan only carries the generic caveat 'unregistered_copies_out_of_band' (retention.py:453). Deletion is not conservatively blocked, so the doc states an erasure guarantee that does not hold. (`palimnex/retention.py:276-283`, check: ok)
- Suggested fix: Only pack membership recorded with register_pack blocks affected deletion (pack_sealed). Packs exported with memory-export are not registered automatically; their copies are not blocked and appear only as the unregistered_copies_out_of_band caveat.

### G1-118 · medium · `docs/COMPATIBILITY.md:12`

- Claim: "`PROJECT_MEMORY_URL` remains a secondary Redis URL alias"; `PALIMNEX_URL` preferred
- Verifier: **imprecise** — Without a redis_url_envs config entry only PALIMNEX_URL is read; PROJECT_MEMORY_URL works only because this repo's .palimnex.json lists it. (`palimnex/core.py:268-271`, check: ok)
- Skeptic: **confirmed** — redis_url_envs() returns only (PALIMNEX_URL,) when no redis_url_envs config entry exists. The string PROJECT_MEMORY_URL does not appear anywhere in the Python or shell source. It works as an alias only because this repository's .palimnex.json lists it in redis_url_envs. The documented example config (palimnex/README.md:42) and the test support config list only PALIMNEX_URL. In another repository, setting PROJECT_MEMORY_URL would be silently ignored and the tool would fall back to the configured or default URL. (`palimnex/core.py:268-271`, check: ok)
- Suggested fix: `PALIMNEX_URL` is the default Redis URL variable. `PROJECT_MEMORY_URL` is honored only when listed in the repository's `.palimnex.json` `redis_url_envs` (as this repository does) for migrations; it is not a built-in alias.

### G1-011 · medium · `docs/DESIGN.md:46`

- Claim: Durable ledger default location `.palimnex/project-memory/memory-v25.sqlite3`
- Verifier: **contradicted** — Code default (and this repo's .palimnex.json durable_ledger_path) is .palimnex/memory.sqlite3; no memory-v25.sqlite3 path exists anywhere in code. (`palimnex/core.py:294-297`, check: ok)
- Skeptic: **confirmed** — durable_ledger_path() defaults to .palimnex/memory.sqlite3. This repo's .palimnex.json (line 43) and palimnex/README.md (line 44) use the same path. 'memory-v25.sqlite3' appears only as a temp filename in tests/test_redis_launcher.py, never as a default. No code path uses .palimnex/project-memory/memory-v25.sqlite3. (`palimnex/core.py:294-297`, check: ok)
- Suggested fix: Durable ledger default location: `.palimnex/memory.sqlite3` (configurable through `durable_ledger_path` in `.palimnex.json`; must be repository-relative).

### G1-065 · medium · `docs/DESIGN.md:231`

- Claim: Projection "bounds the stream to approximately 10,000 entries"
- Verifier: **contradicted** — Stream is capped exactly (XADD MAXLEN '=') at 4,096 entries, and hot-events reads at most 4,096; not ~10,000. (`palimnex/durable.py:34-34`, check: ok)
- Skeptic: **confirmed** — The one projection XADD (durable.py:2537) uses 'MAXLEN','=' with ARGV HOT_STREAM_MAXLEN, set to 4,096 at line 34 and passed at 2607. hot-events also reads at most HOT_STREAM_MAXLEN (2670-2672), and status reports bounded_stream_maxlen = HOT_STREAM_MAXLEN. The cap is exact, not approximate, and the bound is 4,096 rather than about 10,000. The only 10_000 constants in the code are MAX_RECALL_CANDIDATES and MAX_PIPELINE_COMMANDS, which are unrelated. (`palimnex/durable.py:34-34`, check: ok)
- Suggested fix: Projection is idempotent, caps the stream exactly at 4,096 entries (`XADD MAXLEN =`), and records delivery notification, supersession and contradiction pointers without the payload body.

### G1-113 · medium · `docs/DESIGN.md:414`

- Claim: "`clear` removes only this project's v3 disposable cache. It never opens or alters the SQLite ledger or legacy v2 namespace."
- Verifier: **imprecise** — With cache_mode off (the default when the field is absent) `clear` runs the legacy v2 clear and deletes the v2 namespace; the v3-only behavior holds only for shadow/on. (`palimnex/core.py:3129-3133`, check: ok)
- Skeptic: **confirmed** — configured_cache_mode defaults to 'off' when the field is absent (cache_v3.py:92). In off mode, `clear` calls the legacy core.clear, whose _clear_locked deletes keys in the legacy v2 namespace (registry, active-generation, manifest, chunk keys). The paragraph just before says v2-compatible repositories without cache_mode stay on v2, so for those repositories 'never ... alters the legacy v2 namespace' is false. It holds only for shadow and on (this repo uses on). The SQLite-ledger part of the claim is not contradicted. Rated medium rather than high because what is deleted is a rebuildable cache, not durable records. (`palimnex/core.py:3129-3133`, check: ok)
- Suggested fix: With `cache_mode` shadow or on, `clear` removes only this project's v3 disposable cache; with `cache_mode` off (the default when absent) it clears the legacy v2 cache namespace instead. It never opens or alters the SQLite ledger.

### G5-025 · medium · `docs/LONGITUDINAL_EVALUATION.md:140`

- Claim: Persisted result envelope includes "schema": "project-memory:longitudinal-answer:v1" and usage {input_tokens, output_tokens}
- Verifier: **contradicted** — score_external requires exactly these keys, so a result with a 'schema' field is rejected ('invalid result fields'); usage must have exactly the budget keys incl. context_bytes, so the documented usage is rejected too. (`palimnex/longitudinal.py:163-170`, check: ok)
- Skeptic: **confirmed** — score_external needs the result's keys to be exactly the required set, which has no 'schema' key. A result built from the doc example is therefore rejected with 'invalid result fields'. Line 170 also requires set(usage) to equal the manifest's budget keys, which include context_bytes, so the example's usage {input_tokens, output_tokens} is rejected too. The unit test's valid result includes context_bytes in usage. (`palimnex/longitudinal.py:163-170`, check: ok)
- Suggested fix: Remove "schema" from the result envelope, and give usage one integer per manifest budget key, e.g. {"input_tokens": 100, "output_tokens": 20, "context_bytes": 200}. longitudinal-score rejects any other field set.

### G2-019 · medium · `docs/RUNBOOK.md:59`

- Claim: Exit table: 0 success; 2 cache missing/stale or quality/promotion gate failed; 1 operational, privacy, schema, integrity or input error
- Verifier: **imprecise** — ledger-status exits 2 when the ledger is missing, stale or corrupt, so an integrity failure exits 2, not 1. reverify also exits 2 on evidence drift (core.py:3193). Neither case is described. (`palimnex/core.py:3138-3141`, check: ok)
- Skeptic: **confirmed** — ledger-status returns 0 only when status is ready, otherwise 2 (core.py:3138-3141). A failed PRAGMA integrity_check, a foreign-key error or a semantic error makes the status 'corrupt', so that integrity failure exits 2, not the 1 the table gives for integrity errors. reverify also exits 2 when evidence fails verification (core.py:3190-3193). Exceptions go to the handler at core.py:3321-3326, which returns 1. The table is wrong for ledger integrity. (`palimnex/durable.py:1266-1269`, check: ok)
- Suggested fix: `2`: cache missing/stale, quality/promotion gate not passed, `ledger-status` not `ready` (missing, stale or corrupt), or `reverify` evidence not verified. `1`: operational, privacy, schema or input error raised as an exception.

### G6-084 · medium · `docs/index.html:312`

- Claim: Quick start 'From checkout to verified retrieval': redis start, status, index, validate, evaluate, ledger-status, audit-graph
- Verifier: **imprecise** — All commands exist, but no ledger-init step: on a fresh checkout ledger-status returns status missing with exit 2 (core.py:3138-3141) and audit-graph fails because the ledger is opened with create=False. (`palimnex/durable.py:637-638`, check: ok)
- Skeptic: **confirmed** — The quick start never runs ledger-init. None of the earlier steps (status, index, validate, evaluate) creates the ledger. In core.py the only ledger calls are initialize (line 3136, for ledger-init) and the session and remember write paths. On a fresh checkout, ledger.status() returns status 'missing' (durable.py:1229-1236), and core.py:3141 then exits 2. audit-graph calls build_audit_graph, which opens the ledger with ledger.connection(create=False) (audit.py:77), so it raises 'durable ledger is missing'. RUNBOOK.md:23 does include ledger-init before these steps. The block also ends with a success banner that fresh-checkout users would not reach. (`palimnex/durable.py:635-638`, check: ok)
- Suggested fix: Add `python3 palimnex.py ledger-init` (a one-time, explicitly authorized durable write) before `ledger-status`, or note that ledger-status and audit-graph require an initialized ledger (see RUNBOOK).

### G5-094 · medium · `palimnex/CHANGELOG.md:125`

- Claim: Shadow migration `legacy_comparison`: v3 must return every expected path, and v2 must either do the same or overlap v3
- Verifier: **contradicted** — Only v3 must contain every expected path; v2 need only return a non-empty list of strings. No expected-path or overlap-with-v3 check exists for v2 (test passes legacy ['docs/alpha.md','docs/other.md'] and fails only v3 miss/empty legacy). (`palimnex/cache_v3.py:2100-2109`, check: ok)
- Skeptic: **confirmed** — _legacy_comparison_status is the only producer of legacy_comparison (called at line 2301). Only v3 must contain every expected path. v2 passes with any non-empty list of non-empty strings, with no check for expected paths or for overlap with v3. So a v2 result like ['docs/beta.md'] passes as long as v3 is correct. The function's own docstring at line 2088, 'Require both backends...', is also inaccurate. The test at test_cache_v3.py:717-768 checks only v3 misses and empty legacy results. (`palimnex/cache_v3.py:2100-2110`, check: ok)
- Suggested fix: Shadow migration `legacy_comparison` is an asserted check, not a literal "passed": v3 must return every expected path, and v2 must return a non-empty list of paths (v2 paths are not checked against expected paths or v3).

### G4-037 · medium · `palimnex/README.md:130`

- Claim: "`clear` deletes only this project's v3 cache and reports that both the durable ledger and v2 were untouched"
- Verifier: **imprecise** — Only in shadow/on mode. With cache_mode off (the documented default) the CLI calls legacy clear(), which DELs the v2 namespace keys and reports no ledger/v2-untouched fields. (`palimnex/core.py:3129-3134`, check: ok)
- Skeptic: **confirmed** — The CLI sends `clear` to legacy core.clear() when cache_mode is "off". "off" is the default: configured_cache_mode uses `.get("cache_mode", "off")` (cache_v3.py:92), and README:66 says "Missing means `off`". Legacy _clear_locked DELs the v2 namespace's registry, active-generation, manifest, chunk and graph keys (core.py:2513-2553). It returns only status/namespace/deleted_keys, with no durable_ledger_touched or legacy_namespace_touched fields. Only cache_v3.clear (shadow/on) deletes just v3 and reports `durable_ledger_touched: False` and `legacy_namespace_touched: False` (cache_v3.py:2414-2421). The README sentence has no mode qualifier, so in the default mode an operator would think v2 is kept when it is deleted. Severity is medium, not high: v2 is a rebuildable cache, the ledger really is untouched in both paths, and line 136 does say "v3 `clear`" there. (`palimnex/core.py:3129-3134`, check: ok)
- Suggested fix: With `cache_mode` `shadow` or `on`, `clear` deletes only this project's v3 cache and reports that the durable ledger and v2 were untouched; with `off` (the default) it deletes this project's v2 cache namespace. Neither mode touches the durable ledger.

### G2-104 · low · `README.md:30`

- Claim: Quick start: redis start, status, index, validate, evaluate, `ledger-status`, `audit-graph` (no `ledger-init`)
- Verifier: **imprecise** — On a fresh checkout without ledger-init, ledger-status reports missing and exits 2, and audit-graph fails with exit 1. The RUNBOOK sequence includes ledger-init. (`palimnex/durable.py:636-638`, check: ok)
- Skeptic: **confirmed** — audit-graph builds from ledger.connection(create=False) (audit.py:77). On a fresh checkout with no ledger, _open raises 'durable ledger is missing', which the CLI handler turns into exit 1 (core.py:3321-3326). ledger-status returns status 'missing' and exits 2 (durable.py:1230-1236, core.py:3141). The README quick start omits ledger-init, which the RUNBOOK sequence includes at line 23, so the last two quick-start commands fail on a fresh checkout. (`palimnex/durable.py:636-638`, check: ok)
- Suggested fix: Add `python3 palimnex.py ledger-init` before `ledger-status` in the quick start, or note that `ledger-status`/`audit-graph` require an initialized ledger (missing ledger: exit 2 / exit 1).

### G1-001 · low · `docs/DESIGN.md:3`

- Claim: Title "Palimnex v2.5 design"; "Status: implemented locally; release candidate."
- Verifier: **imprecise** — Bundle is released 2.7.0 (pyproject version 2.7.0, CHANGELOG 2.7.0 dated 2026-09-16) and the doc also describes unreleased 2.7-line additions (section 10.1); the v2.5 title and 'release candidate' status are stale. (`palimnex/core.py:32-32`, check: ok)
- Skeptic: **confirmed** — DESIGN.md opens with '# Palimnex v2.5 design' and 'Status: implemented locally; release candidate.' Current source says 2.7.0: BUNDLE_VERSION in core.py, pyproject version = "2.7.0", and palimnex/CHANGELOG.md has '## 2.7.0 - 2026-09-16' above an Unreleased section. The doc also carries later additions (section 10.1 on the audit graph and Semantica). So the release-candidate status is stale. The v2.5 heading can be read as naming the design's origin, so the only real problem is the status line and the wording. (`palimnex/core.py:32-32`, check: ok)
- Suggested fix: Status: implemented; released in 2.7.0 (this design originated in v2.5; later additive sections, e.g. 10.1, are marked). This is repository-local memory tooling, not application protocol or deployment authorization.

### G1-016 · low · `docs/DESIGN.md:66`

- Claim: v3 chunk record contains path/line bounds, file and content digests, "project-keyed term digests and term count", vector and policy identity
- Verifier: **imprecise** — Chunk payload holds path, file_hash, lines, content_digest, term_count, vector, index_policy_digest; project-keyed term digests live in the separate posting hash, not in the chunk record. (`palimnex/cache_v3.py:332-343`, check: ok)
- Skeptic: **confirmed** — _chunk_payload builds the chunk record from schema, id, path, file_hash, start/end line, content_digest, term_count, vector and index_policy_digest. The project-keyed term digests (_chunk_terms, which uses token_digest with _term_digest_key) are returned separately. They are stored only in the posting hash (_encode_posting, posting_hash_key), not in the chunk record. The doc's list merges the chunk and posting stores. (`palimnex/cache_v3.py:331-343`, check: ok)
- Suggested fix: A chunk record contains: path and line bounds; file and content digests; term count; a packed signed-byte feature vector and its policy identity. Project-keyed term digests are stored in the generation's separate posting hash, not in chunk records.

### G1-024 · low · `docs/DESIGN.md:96`

- Claim: GC retains three complete generations and "does not remove a leased or grace-period generation"
- Verifier: **imprecise** — Leased generations are kept, but only the newest MAX_UNLEASED_GRACE_GENERATIONS (=2) unleased grace-period generations are retained; older grace-period generations can be deleted. (`palimnex/cache_v3.py:1298-1309`, check: ok)
- Skeptic: **confirmed** — _collect_garbage keeps the newest GENERATION_RETENTION (3) complete generations and every leased generation. Unleased complete generations younger than GENERATION_GRACE_MS go into grace_candidates, but only the newest MAX_UNLEASED_GRACE_GENERATIONS (2, line 39) are kept. Any other grace-period generation goes into doomed_entries and is deleted. So 'does not remove a ... grace-period generation' does not hold unconditionally. (`palimnex/cache_v3.py:1300-1313`, check: ok)
- Suggested fix: Garbage collection retains the current three complete generations and any leased generation; of unleased generations still in the 60 s grace period it keeps only the newest two. Older staged or grace-period generations may be removed.

### G1-033 · low · `docs/DESIGN.md:123`

- Claim: migration-shadow "compares 66 samples per backend on the shipped search() path"
- Verifier: **contradicted** — Samples = search cases x MIGRATION_LATENCY_RUNS (3). The pinned fixture has 14 search-mode cases (6 are symbols), so the current code measures 42 samples per backend, not 66. (`palimnex/cache_v3.py:2229-2279`, check: ok)
- Skeptic: **confirmed** — Samples per backend = (number of mode=='search' cases) x MIGRATION_LATENCY_RUNS (3, line 51). The migration reports this count as 'samples_per_backend': len(legacy_samples). The pinned fixture palimnex/evaluation/v25.json (sha256 matches .palimnex.json) has 20 cases: 14 search and 6 symbols. That gives 14 x 3 = 42 samples, not 66. 66 would need 22 search cases. The number also depends on the fixture, so a fixed count is fragile. (`palimnex/cache_v3.py:2229-2269`, check: ok)
- Suggested fix: It also times every frozen search-mode case three times per backend (42 samples with the current 14-case search fixture) on the shipped `search()` path over the same deep-validated corpus...

### G1-054 · low · `docs/DESIGN.md:176`

- Claim: "A repository source locator has the exact form `path:start` or `path:start-end`"
- Verifier: **imprecise** — Since 2.7.0 source evidence also accepts structured `palimnex:source-locator:v1:` locators resolved via registered resolvers; path:start[-end] is only the legacy form. (`palimnex/durable.py:1606-1613`, check: ok)
- Skeptic: **confirmed** — _source_evidence_digest accepts structured 'palimnex:source-locator:v1:' locators (LOCATOR_PREFIX in palimnex/locators.py:14) and resolves them through registered resolvers. Only other locators have to match path:start[-end]. CHANGELOG 2.7.0 and COMPATIBILITY.md also document structured locators. DESIGN's claim that the locator has 'the exact form' path:start[-end] is therefore incomplete. (`palimnex/durable.py:1606-1613`, check: ok)
- Suggested fix: A repository source locator has the legacy form `path:start` or `path:start-end`, or (since 2.7.0) a structured `palimnex:source-locator:v1:` locator resolved by an explicitly registered resolver; the referenced bytes are hashed and verified before the event commits.

### G5-014 · low · `docs/LONGITUDINAL_EVALUATION.md:89`

- Claim: Development reports record scenario/session/query counts, process restart count, fixture digest, code identity, backend configuration, output byte budget, source fingerprints, cleanup ran
- Verifier: **imprecise** — Report has scenario_count, sessions_per_scenario, cohort/generator digests, per-outcome erased_records and worker_pid, but no explicit process-restart count, backend configuration, output byte budget, query count or source fingerprints fields. (`palimnex/longitudinal.py:108-113`, check: ok)
- Skeptic: **confirmed** — Line 89 says as a plain fact that development reports record these things. The report dict and the reference longitudinal.json have these keys: arms, cohort_digest, development_only, family_count, generator_digest, model_calls, outcomes, quality_boundary, scenario_count, schema, sessions_per_scenario, status, supported_answer_accuracy, task_success. Each outcome has worker_pid and erased_records. The report has no process-restart count, no backend configuration, no output byte budget (the worker's byte_budget=8192 is not recorded) and no source fingerprints. Cleanup is shown only as erased_records counts, not as an explicit 'cleanup ran' flag. (`palimnex/longitudinal.py:108-113`, check: ok)
- Suggested fix: Development reports record scenario/family counts, sessions per scenario, per-outcome session/arm/worker PID, cohort and generator digests, and per-outcome erased-record counts. Restart count, backend configuration, byte budget and source fingerprints are not yet recorded.

### G5-015 · low · `docs/LONGITUDINAL_EVALUATION.md:92`

- Claim: Measure evidence hit rate, forbidden/stale exposure, abstention, output bytes, latency separately per arm; report missing or truncated context explicitly
- Verifier: **imprecise** — Per-arm summary has evidence_success, abstention_accuracy, mean_context_bytes, p95 latency, erased_records; forbidden exposure is only a per-outcome flag (folded into evidence_success) and context truncation/omitted_count is not recorded. (`palimnex/longitudinal.py:103-107`, check: ok)
- Skeptic: **confirmed** — Part of the finding is wrong. Forbidden exposure is measured for every observation and tagged with its arm (forbidden_evidence_present), and context bytes and latency are summarized per arm. The truncation part holds. Neither the outcomes nor the summary carry the context's omitted_count or candidate_scan_truncated (experience.py:280-281), so missing or truncated context is not reported explicitly. The per-arm summary (lines 103-107) also has no aggregated forbidden-exposure rate. (`palimnex/longitudinal.py:94-99`, check: ok)
- Suggested fix: Per-arm summaries report evidence success, abstention accuracy, mean context bytes and p95 retrieval latency. Forbidden exposure is a per-outcome flag. Omitted or truncated context (omitted_count, candidate_scan_truncated) is not yet recorded.

### G5-017 · low · `docs/LONGITUDINAL_EVALUATION.md:97`

- Claim: Model and task metrics remain `not_measured` until real external results are supplied
- Verifier: **imprecise** — Unmeasured metrics are JSON null (task_success/supported_answer_accuracy None), not a `not_measured` value; no 'not_measured' string exists in the code. (`palimnex/longitudinal.py:111-111`, check: ok)
- Skeptic: **confirmed** — The string not_measured appears nowhere in the repository except this doc line. Unmeasured model and task metrics are JSON null in the development report, and score_external reports value None with measured=0 (lines 182-183). Line 161 of the same doc already says unmeasured metrics are null. (`palimnex/longitudinal.py:111-111`, check: ok)
- Suggested fix: Model and task metrics remain null (task_success, supported_answer_accuracy; score values with measured=0) until real external results are supplied.

### G5-023 · low · `docs/LONGITUDINAL_EVALUATION.md:133`

- Claim: Each runner request contains only manifest digest, scenario/session/query/arm identity, visible-input digest, question/context, and declared model/budgets
- Verifier: **imprecise** — requests.json entries contain scenario_id, session, query_id, arm, visible_input_digest and input{query,items}; they carry no manifest_digest or model/budgets. Manifest is written after replay, alongside requests. (`palimnex/longitudinal.py:92-93`, check: ok)
- Skeptic: **confirmed** — The requests.json entries that longitudinal-prepare writes have only scenario_id, session, query_id, arm, visible_input_digest and input {query, items} (lines 92-93, written at line 126). They carry no manifest digest and no declared model or budgets, which exist only in manifest.json. The exclusion of gold answers and future actions does hold. (`palimnex/longitudinal.py:92-93`, check: ok)
- Suggested fix: Each prepared request (requests.json) contains scenario/session/query/arm identity, the visible-input digest and the query with retrieved context. The manifest digest, model and budgets are in manifest.json. Requests exclude scoring gold and future actions.

### G5-026 · low · `docs/LONGITUDINAL_EVALUATION.md:157`

- Claim: "These shapes are an integration proposal until implemented"
- Verifier: **imprecise** — Manifest/result scoring is implemented (longitudinal-prepare/score); the proposal wording is stale and the implemented shapes differ from the examples. (`palimnex/core.py:2746-2748`, check: ok)
- Skeptic: **confirmed** — Both shapes are implemented and enforced. seal_manifest and score_external (longitudinal.py:133-187) back the longitudinal-prepare, longitudinal-reserve and longitudinal-score CLI commands, and the doc's own section at line 200 says so. So 'integration proposal until implemented' is stale, and the result example differs from what the code enforces (see G5-025). (`palimnex/core.py:2743-2748`, check: ok)
- Suggested fix: These shapes are enforced by longitudinal-prepare and longitudinal-score (seal_manifest/score_external); field sets must match exactly.

### G3-037 · low · `docs/RETENTION.md:91`

- Claim: First winning exclusion order: unconfigured, hold, session pin/grace, anchor, missing authorization, not expired, dependency guard, then pack/cache
- Verifier: **imprecise** — Code also has already_erased; store_not_adapted/pack_sealed are per-event blockers assigned before dependency_guard, which only labels the other roots; order of the last two is effectively reversed. (`palimnex/retention.py:426-434`, check: ok)
- Skeptic: **confirmed** — The root loop (retention.py:372-388) runs unconfigured, hold, active_session (grace, then pin), already_erased, protected_audit_log, authorization_required, not_expired. The doc omits already_erased, and in code the audit-anchor check comes after pin/grace but also after already_erased. The closure pass gives the blocked event its own store_not_adapted or pack_sealed reason. Only roots with no blocker of their own get dependency_guard (lines 431-434), so a pack or cache constraint beats dependency_guard for the affected record. That is the reverse of the doc's 'dependency guard, then pack/cache' order. The doc is a summary, but its ordering claim is wrong. (`palimnex/retention.py:427-434`, check: ok)
- Suggested fix: Eligibility uses the first winning exclusion: unconfigured policy, hold, session grace/pin, already erased, protected audit anchor, missing explicit authorization for durable/imported content, not expired; closure members blocked by audit/hold/session/unadapted store/registered pack get that reason, other roots get dependency_guard.

### G3-051 · low · `docs/RETENTION.md:154`

- Claim: Gate testing includes "policy monotonicity"
- Verifier: **unsupported** — Guard exists (retention.py:229-230) but no test asserts refusal of a non-increasing policy version; searched tests for 'must increase' / policy version. (`palimnex/tests/test_retention.py:65-71`, check: ok)
- Skeptic: **confirmed** — The monotonicity guard exists in code: 'policy version must increase' at retention.py:229-230. A search of all .py files, including every test module, finds that message only in retention.py. The only test that changes the policy version raises it from 1 to 2 and checks that the old plan goes stale. No test asserts that an equal or lower version is refused, so the Testing column's 'policy monotonicity' has no test behind it. (`palimnex/tests/test_retention.py:65-71`, check: ok)
- Suggested fix: Testing: unconfigured retain-all; changed policy/ledger/hold/pins/pack refusal; tampered plan refusal (policy version monotonicity is enforced in code but has no dedicated test).

### G3-053 · low · `docs/RETENTION.md:155`

- Claim: Gate testing includes "contention behavior"
- Verifier: **unsupported** — No retention test exercises concurrent writers/lock contention; searched tests for lock/contention/concurrency/busy. (`palimnex/tests/test_retention.py:76-84`, check: ok)
- Skeptic: **confirmed** — The retention tests cover transaction rollback, crash/resume via patch, and process-exit crashes via subprocess (test_retention.py:76-84, 245-263). None of them runs concurrent writers or lock contention against retention apply or finalize. The only threading and lock-contention tests are in test_cache_v3.py and test_portable.py (import activation waiting for the live lock), not retention cleanup. (`palimnex/tests/test_retention.py:76-84`, check: ok)
- Suggested fix: Testing: survivor integrity; no dangling references or resurrection; exclusion order; retry/crash (in-process and process-exit) behavior; deletion canaries. Retention contention is not covered by a dedicated test.

### G3-054 · low · `docs/RETENTION.md:156`

- Claim: Longitudinal harness tests restarts, temporal ordering, corrections, expiry, holds, abstention, identical budgets
- Verifier: **imprecise** — Harness families have no preservation-hold scenario; holds are not exercised by the longitudinal replay. (`palimnex/longitudinal.py:18-18`, check: ok)
- Skeptic: **confirmed** — The scenarios in longitudinal.py:22-39 and the worker in :41-77 cover per-session subprocess restarts, temporal ordering, corrections and revocations, TTL-0 expiry cleanup, abstention and fixed budgets. They never place or release a preservation hold. longitudinal.py contains no 'hold', test_longitudinal.py contains no 'hold', and the reference longitudinal.json contains 0 occurrences. (`palimnex/longitudinal.py:18-18`, check: ok)
- Suggested fix: Testing: restarts, temporal ordering, corrections/revocations, expiry, abstention, identical budgets; frozen existing fixtures unchanged. Holds are covered by retention unit tests, not the longitudinal harness.

### G2-001 · low · `docs/RUNBOOK.md:1`

- Claim: Title: "Palimnex v2.5 runbook"
- Verifier: **imprecise** — The bundle is 2.7.0 (pyproject version 2.7.0) and the runbook covers 2.6/2.7 features such as audit-graph and --include-audit-graph. The v2.5 title is stale. (`palimnex/core.py:32-32`, check: ok)
- Skeptic: **confirmed** — The bundle and pyproject version are both 2.7.0 (pyproject.toml:7). The runbook documents later commands such as audit-graph (RUNBOOK lines 25 and 263) and --include-audit-graph, and it cites 2.6.0-rc.1 ranking. Only the title still says v2.5. This is a stale title, not a behavior problem. (`palimnex/core.py:32-32`, check: ok)
- Suggested fix: # Palimnex runbook (2.7.0)

### G2-031 · low · `docs/RUNBOOK.md:103`

- Claim: "Local physical pruning of `volatile` and `session` rows is not implemented in v2.5."
- Verifier: **imprecise** — In the current 2.7.0 code, a migrated retention ledger with an active policy can erase expired volatile/session events through cleanup-plan/apply by TTL rule (tombstone plus VACUUM). The v2.5-scoped statement is stale. (`palimnex/retention.py:386-388`, check: ok)
- Skeptic: **confirmed** — In the current 2.7.0 code, cleanup-plan and cleanup-apply (both in the CLI help) can erase expired volatile/session events by TTL rule once the ledger is retention-migrated and a policy is active. Apply rewrites each event row as a tombstone under PRAGMA secure_delete, deletes dependent rows and runs VACUUM (retention.py:524-599). RETENTION.md calls this physical cleanup. Event rows are tombstoned rather than dropped, and nothing prunes an unmigrated ledger. Still, the version-scoped 'not implemented in v2.5' sentence misstates current capability. (`palimnex/retention.py:386-388`, check: ok)
- Suggested fix: Nothing prunes `volatile` and `session` rows automatically. After an authorized retention migration and policy activation, `cleanup-plan`/`cleanup-apply` can erase expired rows by TTL rule (tombstone plus compaction); see docs/RETENTION.md.

### G2-059 · low · `docs/RUNBOOK.md:257`

- Claim: Example `memory-keygen .palimnex/project-memory/transfer-2026-09.key` in an ignored private directory
- Verifier: **imprecise** — keygen does not create the parent directory, and .palimnex/project-memory does not exist in a fresh checkout. The command fails until the operator creates the directory. (`palimnex/portable.py:76-80`, check: ok)
- Skeptic: **confirmed** — generate_pack_key calls _write_new_private_file, which only opens the existing parent directory and never creates it (portable.py:166-169, 54-80). The ledger code creates only the ledger path's parent, .palimnex/ (durable.py:530), and the Redis launcher creates only .palimnex/redis. Nothing creates .palimnex/project-memory, and in this checkout .palimnex/ is empty. The example command fails with exit 1 until the operator creates the directory. It fails closed, so the severity is low. (`palimnex/portable.py:76-80`, check: ok)
- Suggested fix: Create the private directory first (e.g. `install -d -m 0700 .palimnex/project-memory`), then run `python3 palimnex.py memory-keygen .palimnex/project-memory/transfer-2026-09.key`; keygen does not create parent directories.

### G3-098 · low · `docs/SDK.md:36`

- Claim: Committed `.palimnex.json` containing project UUID, slug and private ledger path is required
- Verifier: **imprecise** — File and UUID are required, but durable_ledger_path defaults to .palimnex/memory.sqlite3 and project_slug falls back to the directory name (core.py:260). (`palimnex/core.py:294-297`, check: ok)
- Skeptic: **confirmed** — The SDK constructor (api.py:56-58) requires .palimnex.json to exist, and cache_v3.project_id (cache_v3.py:80-87) requires a UUID project_id. The ledger path, however, defaults to .palimnex/memory.sqlite3, and project_slug falls back to the directory name (core.py:257-261). The code also checks only that the file exists, not that it is committed. The file and UUID are required; slug and ledger path are optional. (`palimnex/core.py:294-297`, check: ok)
- Suggested fix: A `.palimnex.json` with the project's UUID `project_id` is required; `project_slug` defaults to the directory name and `durable_ledger_path` to `.palimnex/memory.sqlite3`.

### G1-129 · low · `docs/V26.md:3`

- Claim: "Status: release candidate `2.6.0-rc.1`."
- Verifier: **imprecise** — Current bundle is released 2.7.0 and the page also documents 2.7 surfaces; the rc.1 status line is stale. (`palimnex/core.py:32-32`, check: ok)
- Skeptic: **confirmed** — The bundle and pyproject version is 2.7.0, and palimnex/CHANGELOG.md records '## 2.7.0 - 2026-09-16'. V26.md itself has a section '## Additive 2.7 surfaces' (line 70), so its 'Status: release candidate 2.6.0-rc.1' line is stale. This is cosmetic; the capability descriptions are not affected. (`palimnex/core.py:32-32`, check: ok)
- Suggested fix: Status: introduced in 2.6.0 (first as `2.6.0-rc.1`); current bundle 2.7.0 adds the surfaces listed under "Additive 2.7 surfaces".

### G5-106 · low · `palimnex/CHANGELOG.md:163`

- Claim: The legacy `project-memory:v2` namespace is never changed by v3 migration or `clear`
- Verifier: **imprecise** — migration_shadow does refuse v2 changes, but `clear` with cache_mode off (the default when unset) runs the legacy clear on the v2 namespace; only in shadow/on does clear leave v2 untouched. (`palimnex/core.py:3132-3132`, check: ok)
- Skeptic: **confirmed** — cache_mode defaults to 'off' when missing (cache_v3.py:92). In off mode the clear command runs the legacy clear(), and _clear_locked (core.py:2513-2545) deletes the v2 registry, active-generation, chunk and graph keys under the project-memory:v2 namespace. So v2 is left alone only when clear runs in shadow or on mode. This repository's .palimnex.json sets cache_mode 'on', so it is not affected, but the unconditional 'never changed by clear' is inaccurate. (`palimnex/core.py:3129-3133`, check: ok)
- Suggested fix: The legacy `project-memory:v2` namespace is read-only during shadow comparison and is never changed by v3 migration or by `clear` in `shadow`/`on` mode; with `cache_mode=off` (the default), `clear` removes the v2 index.

### G4-057 · low · `palimnex/README.md:218`

- Claim: "an append-only attempt timestamp is the actual check time"
- Verifier: **imprecise** — checked_at is clamped to be >= the previous attempt's checked_at, so it can exceed the actual wall-clock check time when the clock moves backwards. (`palimnex/durable.py:1660-1666`, check: ok)
- Skeptic: **confirmed** — Callers pass now_ms() (durable.py:2180, 357-358). _record_verification_attempt then clamps checked_at so it is never earlier than the previous attempt's checked_at, and returns that clamped value, which becomes verified_at. If the wall clock goes backwards, the stored attempt time is the previous attempt's time and not the actual check time. The doc's main point, that the ledger clock is used and not a caller-supplied time, holds. But "is the actual check time" is not strictly true. DESIGN.md:208 and RUNBOOK.md:126 say the same thing. (`palimnex/durable.py:1660-1666`, check: ok)
- Suggested fix: an append-only attempt timestamp is the ledger-clock check time, clamped so it never precedes the event's previous attempt (attempt_sequence breaks ties).


## Uncertain or evidence not mechanically confirmed (7)

### G5-033 · low · `docs/LONGITUDINAL_EVALUATION.md:180`

- Claim: Tests cover process restarts, independent dirs, no future actions/gold, abstention, correction/revocation, applicability, budget, unsupported-cleanup and unmeasured-model flags
- Verifier: **imprecise** — Unit tests call worker() in-process; subprocess restart and correction/revocation suppression are exercised only by the gate's evaluate-longitudinal replay. No unsupported-cleanup flag exists or is tested. (`palimnex/tests/test_longitudinal.py:20-32`, check: ok)
- Skeptic: **uncertain** — Line 180 is an imperative list of required tests, not a statement that all of them exist. Some are covered. The gate runs evaluate-longitudinal, which uses real subprocess restarts, and asserts status passed; that status needs evidence success 1.0 including the forbidden-value checks for corrections and revocations. Unit tests cover directory isolation, rejection of gold answers in the worker envelope, abstention before ingestion, budget rejection and null task_success. Two items are not covered: checkout applicability, which line 205 already concedes, and an unsupported-cleanup flag, which appears nowhere in longitudinal.py or its tests. Because the sentence is a requirement rather than a claim of completion, this is drift only in part. (`scripts/palimnex_check.sh:20-30`, check: ok)
- Suggested fix: Add: Current coverage exercises restarts and correction/revocation suppression via the gated evaluate-longitudinal replay; checkout applicability and an unsupported-cleanup flag are not yet tested.

### G3-082 · low · `docs/RETENTION.md:285`

- Claim: Policy, contract v2, plan v2, tombstone schemas checked with Draft 2020-12 against runtime policy and unconfigured, configured, event-scoped plans
- Verifier: **imprecise** — Only test validates contract, one event-scoped configured plan, and the receipt against erasure-tombstone; no test validates retention-policy.v1 or unconfigured/unscoped plans. (`palimnex/tests/test_retention.py:177-192`, check: ok)
- Skeptic: **uncertain** — The doc uses the past tense ('were checked'), which may describe a manual one-off check that source cannot confirm or refute. The only reproducible Draft 2020-12 retention validation in the repository covers the deletion contract, one configured event-scoped plan, and the erasure-tombstone receipt. No committed code validates retention-policy.v1.schema.json or any unconfigured or unscoped plan: a grep for retention-policy, Draft202012 and cleanup-plan.v2 finds only this test, and test_sdk.py validates only locator, signature, checkpoint and audit-graph schemas. The claim cannot be backed by current source, but it is not directly contradicted either. (`palimnex/tests/test_retention.py:177-192`, check: ok)
- Suggested fix: The unit suite checks the deletion-contract v2, cleanup-plan v2 (configured, event-scoped plan) and erasure-tombstone schemas with Draft 2020-12 on isolated temporary ledgers; retention-policy and unconfigured-plan schema validation is not automated.

### G2-003 · low · `docs/RUNBOOK.md:8`

- Claim: Pack operations "require the reviewed distribution-provided `python3-cryptography` package and probe ChaCha20-Poly1305 support"
- Verifier: **imprecise** — The code only lazily imports ChaCha20Poly1305 from any installed cryptography and never checks that it came from the distribution. There is no separate probe. CI and README install cryptography with pip (.[test,mcp]). (`palimnex/portable.py:205-213`, check: ok)
- Skeptic: **uncertain** — The doc states an operator requirement, not a code check, and the code's own error text uses the same 'reviewed distribution cryptography package' wording. Importing ChaCha20Poly1305 lazily is the de-facto support probe. However, nothing checks provenance. pyproject declares crypto = ["cryptography>=41"], and CI installs it with pip, so any cryptography>=41 that has ChaCha20Poly1305 works. Whether this counts as drift depends on reading 'require' as policy or as enforced behavior. (`palimnex/portable.py:206-213`, check: ok)
- Suggested fix: Pack operations additionally require a reviewed `cryptography` (>=41) package; Palimnex imports ChaCha20-Poly1305 on first use and fails closed if it is unavailable. It does not verify where the package came from.

### G2-053 · low · `docs/RUNBOOK.md:210`

- Claim: Don't use --rebuild as routine retry "when the normal response already says `projection_pending: 0`"
- Verifier: **imprecise** — The normal project-hot response reports the undelivered count as `remaining`. `projection_pending` appears only in ledger-status as a count, and in event responses as a boolean. (`palimnex/durable.py:2641-2649`, check: ok)
- Skeptic: **uncertain** — project-hot's response (durable.py:2641-2649, printed at core.py:3231-3237) reports undelivered outbox rows as `remaining`, not `projection_pending`. However, `ledger-status` returns an integer `projection_pending` (durable.py:1277), so 'the normal response' may mean ledger-status. The doc does not say which command it means, so this is ambiguous rather than clearly wrong. (`palimnex/durable.py:2641-2649`, check: ok)
- Suggested fix: Do not use it as a routine retry when a normal `project-hot` response already says `remaining: 0` (or `ledger-status` says `projection_pending: 0`).

### G6-065 · low · `docs/index.html:216`

- Claim: Redis store card: "Default transport: Owner-only Unix socket"
- Verifier: **imprecise** — Code default without redis_socket_path is loopback TCP (configured_redis_url returns DEFAULT_URL, core.py:279-282); Unix socket is the launcher/this repo's .palimnex.json setting. Writes still require private socket or auth. (`palimnex/core.py:38-38`, check: ok)
- Skeptic: **uncertain** — When .palimnex.json has no redis_socket_path, the client falls back to DEFAULT_URL, which is loopback TCP (redis://127.0.0.1:6379/0). The socket default comes from elsewhere. The guarded launcher starts Redis with '--port 0 --unixsocket ... --unixsocketperm 600' and no TCP listener. The shipped .palimnex.json and the configuration example in palimnex/README.md both set redis_socket_path. DESIGN.md:143 says 'default local writes use an owner-only Unix socket'. palimnex/README.md:71 hedges: 'The default may be an owner-only redis+unix:// socket'. So the card is right about the packaged setup but not about the code fallback. (`palimnex/core.py:279-291`, check: ok)
- Suggested fix: Default transport: owner-only Unix socket (guarded launcher and shipped config); without redis_socket_path the client falls back to loopback TCP, which cannot be used for writes unless authenticated.

### G6-073 · low · `docs/index.html:265`

- Claim: Redis server + CLI: Disposable; owner-only Unix socket by default
- Verifier: **imprecise** — Without redis_socket_path in .palimnex.json the client defaults to loopback TCP; owner-only socket comes from the launcher/configured path. (`palimnex/core.py:38-38`, check: ok)
- Skeptic: **uncertain** — Same issue as G6-065. The launcher (scripts/palimnex_redis.sh, --port 0 --unixsocket) and the shipped or example .palimnex.json make the owner-only socket the practical default. The code fallback when redis_socket_path is missing is DEFAULT_URL = redis://127.0.0.1:6379/0. palimnex/README.md itself says the default 'may be' a socket. Whether 'by default' is accurate depends on which default the reader means. (`palimnex/core.py:279-291`, check: ok)
- Suggested fix: Disposable; owner-only Unix socket via the guarded launcher and configured redis_socket_path (client falls back to loopback TCP if unset).

### G4-024 · low · `palimnex/README.md:97`

- Claim: Exit 0 success/fresh, 2 missing/stale or failed quality gate, 1 "operational or validation error"
- Verifier: **imprecise** — A failed validate/--deep integrity check yields fresh=False and exits 2, not 1; exit 1 is only for raised RedisError/TypeError/ValueError/OSError. (`palimnex/core.py:3036-3037`, check: ok)
- Skeptic: **uncertain** — The source is clear. When `validate --deep` fails an integrity check, cache_v3.validate (cache_v3.py:941-948) and legacy validate (core.py:1720-1736) return fresh=False with status stale/missing_or_invalid and validation "failed", and the CLI exits 2. Exit 1 comes only from raised RedisError/TypeError/ValueError/OSError (core.py:3321-3326), which includes argument and config ValueErrors such as "--limit must be between 1 and 100". So "validation error" in the doc can fairly mean input/config validation errors, and a failed integrity check can fairly be read as a "failed quality gate" or "missing_or_invalid" (exit 2). But the paragraph is about the `validate` command, so a reader may expect a failed validate to exit 1. The wording is ambiguous; it is not clearly wrong. (`palimnex/core.py:3036-3037`, check: ok)
- Suggested fix: Exit `0` means success/fresh; `2` means missing, stale or invalid cache (including a failed `validate --deep` integrity check) or a failed quality gate; `1` means an operational error or invalid argument/configuration.


## Refuted by skeptic (7)

### G6-005 · none · `docs/AGENT_INIT_PROMPT.md:22`

- Claim: "Additive 2.7 surfaces: palimnex.audit, palimnex:audit-graph:v1, optional palimnex.semantica"
- Verifier: **imprecise** — CHANGELOG lists audit-graph export and Semantica projector/adapter under 'Unreleased', not the 2.7.0 release; COMPATIBILITY.md also calls them 'Unreleased additive schemas on this line'. (`palimnex/CHANGELOG.md:6-10`, check: ok)
- Skeptic: **refuted** — The doc line says 'Additive 2.7 surfaces', meaning surfaces on the 2.7 line. It does not say they shipped in the 2.7.0 release. COMPATIBILITY.md describes them the same way, as additive schemas 'on this line'. pyproject.toml:7 and core.py:32 still report version 2.7.0, and CHANGELOG lists them under Unreleased on that line. A reader could still misread the wording as 'released in 2.7.0', but nothing in the doc contradicts the source. (`docs/COMPATIBILITY.md:24-27`, check: ok)

### G5-022 · none · `docs/LONGITUDINAL_EVALUATION.md:126`

- Claim: Manifest example: "arms": ["source_only", "accepted_memory"], "scoring_protocol": "external-labels-v1"
- Verifier: **imprecise** — Implemented arms are source_only/history/history_cleanup (line 17); there is no accepted_memory arm. Prepared manifests use scoring_protocol 'external-independent-labels:v1' and context_bytes 8192. (`palimnex/longitudinal.py:123-125`, check: ok)
- Skeptic: **refuted** — The example's field set matches exactly what seal_manifest requires, and so do its cohort keys and budget keys. seal_manifest accepts any unique non-empty arm names (line 142), does not check the scoring_protocol value, and accepts any positive integer budgets (line 145). The unit test uses a different protocol string, 'independent-labels:v1'. So ['source_only','accepted_memory'], 'external-labels-v1' and context_bytes 16384 are valid illustrative values for an external manifest, not claims about the manifest that longitudinal-prepare generates. (`palimnex/longitudinal.py:133-145`, check: ok)

### G5-043 · none · `docs/LONGITUDINAL_EVALUATION.md:214`

- Claim: The controller checks obsolete-value absence for correction/revocation cases
- Verifier: **imprecise** — The forbidden (obsolete) value is checked only in session 2; the final session 5 re-query of the same key has no forbidden list, so absence after later restarts is not checked. (`palimnex/longitudinal.py:34-37`, check: ok)
- Skeptic: **refuted** — The doc says only that the controller checks obsolete-value absence for correction and revocation cases. It does: session 2 of those families has forbidden=[a] (line 34), and any exposure makes that observation fail (lines 89-90). Session 2 already runs in a fresh subprocess over the persisted ledger. The doc never claims the check repeats in later sessions, so the finding reads more into it than it says. (`palimnex/longitudinal.py:88-90`, check: ok)

### G4-090 · none · `docs/PAGES.md:21`

- Claim: "Publishing is separate from building the site and requires explicit authority"
- Verifier: **imprecise** — The workflow builds and deploys in one run and triggers automatically on every push to main (plus workflow_dispatch); once Pages is enabled no separate publish step exists. (`.github/workflows/jekyll-gh-pages.yml:3-6`, check: ok)
- Skeptic: **refuted** — In PAGES.md, "building the site" means the authored static page and the local preview (the Local preview section). It does not mean the workflow's build job. Publishing needs repository-settings activation (Settings → Pages) and a push to main. Pushing is a Git write, and AGENTS.md:29 lists Git writes as requiring explicit authority. The push-to-main trigger in jekyll-gh-pages.yml:5-6 is exactly that authority-gated step, so the doc's claim holds. The workflow running build and deploy in one run does not contradict it. (`docs/PAGES.md:26-27`, check: ok)

### G2-084 · none · `docs/RUNBOOK.md:371`

- Claim: "`clear` is intentionally v3-only"
- Verifier: **imprecise** — clear is v3-only only when cache_mode is shadow or on. With cache_mode off it runs the legacy v2 clear. This repo's committed mode is on. (`palimnex/core.py:3132-3132`, check: ok)
- Skeptic: **refuted** — The paragraph concerns a repository that has migrated to v3 and still holds a 'preserved legacy v2 namespace'. Section 11 is titled 'Clear only the disposable v3 cache' and expects legacy_namespace_touched: false. In shadow and on modes, core.py:3132 routes clear to cache_v3.clear, which clears only the v3 namespace (cache_v3.py:2346-2347). This repository commits cache_mode 'on', so the doc is correct here. The legacy path exists only for unmigrated repositories in 'off' mode, which have no v3 cache or preserved-legacy situation. (`.palimnex.json:38-38`, check: ok)

### G3-129 · none · `docs/SDK.md:168`

- Claim: "`verify_checkpoint` additionally compares the current ledger snapshot"
- Verifier: **imprecise** — integrity.verify_checkpoint only checks fields/signature; snapshot comparison is in integrity.verify_current, reached via the SDK method Palimnex.verify_checkpoint (api.py:185-189). (`palimnex/integrity.py:58-78`, check: ok)
- Skeptic: **refuted** — SDK.md documents the SDK, and the public `verify_checkpoint` there is the Palimnex client method, as used in test_sdk.py (self.client.verify_checkpoint). That method calls integrity.verify_current, which checks the signature and expected tip and then compares _snapshot(ledger) to the checkpoint, raising 'ledger changed since checkpoint' on mismatch (integrity.py:113-122). integrity.verify_checkpoint is an internal helper that palimnex/__init__.py does not export, so the doc's claim is correct for the documented API. (`palimnex/api.py:185-189`, check: ok)

### G4-015 · none · `palimnex/README.md:55`

- Claim: "Redis and ledger paths must be repository-relative and ignored by Git"
- Verifier: **imprecise** — Code enforces repository-relative (no absolute, no ..) for socket and ledger paths, but nothing checks the path is Git-ignored (searched check-ignore/gitignore in palimnex/*.py); only the repo .gitignore covers .palimnex/. (`palimnex/core.py:294-305`, check: ok)
- Skeptic: **refuted** — README line 55 sits in configuration guidance aimed at the operator ("Generate a real UUID... never reuse..."). "must be ... ignored by Git" tells the operator what to do. It does not say the code enforces it. The code does enforce the repository-relative part for both the socket path (core.py:283-289) and the ledger path (core.py:298-304). The Git-ignored part is met by the repository's .gitignore, which covers the default paths (.gitignore:11 `.palimnex/`, :14 `*.sqlite3`). The doc never says Palimnex checks Git-ignore status, so it is not wrong. (`palimnex/core.py:294-305`, check: ok)


## Supported claims with unusable locators (1)

These were marked supported but their locator did not resolve; they are counted as checked but their evidence is not confirmed.

- `docs/RUNBOOK.md:215` Example workflow JSON matches `palimnex/schemas/workflow-spec.v1.schema.json` → `palimnex/schemas/workflow-spec.v1.schema.json:1-68` (out_of_range)
