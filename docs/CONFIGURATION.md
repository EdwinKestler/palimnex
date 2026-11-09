# Palimnex configuration reference

Palimnex reads repository configuration from `.palimnex.json`. Commit that
file when it contains only repository identity and non-secret policy. Never
store Redis passwords, provider credentials, cryptographic keys, memory
payloads, or other secrets in it.

`palimnex init` previews a starter configuration without writing.
`palimnex init --write` creates the file exclusively and adds the required
runtime-state patterns to `.gitignore`; it never overwrites an existing
configuration, creates a ledger, starts Redis, or contacts a network.

## Loading and precedence

The installed CLI uses the current directory as the repository root unless
`PALIMNEX_ROOT` is set before the process starts. SDK clients always receive an
explicit root. Palimnex reads `.palimnex.json`; only when that file is absent
does it accept the deprecated `.project-memory.json` name.

Redis connection selection is, from highest to lowest precedence:

1. CLI `--url`;
2. the first nonempty environment variable named by `redis_url_envs`; and
3. `redis_socket_path`, or the legacy loopback default when no socket is set.

Prefer the guarded owner-only Unix socket. Never put a Redis URL containing a
password in the configuration, logs, command history, or documentation.

Configuration is a JSON object. Consumers validate the fields they use and
fail visibly on malformed values. There is no permissive fallback for an
invalid recognized field.

## Core fields

| Field | Type and default | Meaning and change effect |
| --- | --- | --- |
| `project_id` | Required UUID | Stable project identity and v3 namespace key. Generate one per project and preserve it across authorized clones. Reusing another project's ID or changing it after state exists can select the wrong namespace or make state unreadable. |
| `project_slug` | Nonempty string; directory name when absent | Human-readable project identity. Set it explicitly: the ledger refuses a checkout whose effective slug differs from the stored slug. |
| `cache_mode` | `off`, `shadow`, or `on`; missing means `off` | `off` uses legacy v2, `shadow` builds v2 and v3 while v2 remains authoritative, and `on` uses v3. New repositories should use `on`; existing v2 deployments follow `UPGRADING.md`. |
| `redis_socket_path` | Repository-relative path; otherwise legacy loopback default | Socket managed by `palimnex redis`. `redis start` requires this field so it cannot silently start a socket server while the client targets TCP. Keep the path under ignored `.palimnex/` state. |
| `redis_url_envs` | Nonempty environment-variable-name list; `["PALIMNEX_URL"]` | Ordered names from which the CLI reads an injected Redis URL. `PROJECT_MEMORY_URL` is not automatic; list it explicitly for a legacy deployment. |
| `durable_ledger_path` | Repository-relative path; `.palimnex/memory.sqlite3` | Durable SQLite ledger. Set the final location before the first write, keep it ignored by Git, and preserve it across upgrades. |

## Corpus admission fields

| Field | Type and default | Meaning and safety boundary |
| --- | --- | --- |
| `include_patterns` | String glob list; built-in defaults when absent | Replaces the default corpus patterns. Root `README.md`, `AGENTS.md`, `agent_instructions.md`, `instructions.md`, `pyproject.toml`, `.gitignore`, and `.env.example` are still considered. Inspect `status --verbose` after changes. |
| `exclude_directories` | Directory-name list; empty | Adds directory names to the built-in exclusion set. Entries are names, not paths, and cannot contain `/` or `\`. |
| `exclude_paths` | Repository-relative path list; empty | Excludes exact paths. Absolute paths and traversal are refused. Use this for evaluation fixtures and generated evidence that must not influence retrieval. |
| `include_palimnex` | Boolean; `false` | Includes a copied `palimnex` bundle that is otherwise excluded. Installed-package adoption normally leaves it false. `include_project_memory` is a deprecated fallback read only when `include_palimnex` is absent. |
| `content_scan_allowlist_sha256` | Lowercase SHA-256 list; empty | Exact-content exceptions to index-time privacy admission. This is a security-sensitive, digest-pinned exception—not a rule disable. Review each byte payload, record why it is safe, keep the list minimal, and remove obsolete digests. A content edit invalidates the exception. |

Changing corpus admission fields changes the index-policy identity and requires
`palimnex index --incremental`, `validate --deep`, and retrieval evaluation.
Symlinks, oversized or non-UTF-8 files, sensitive path names, and content that
fails privacy admission remain excluded or refused independently of broad
include patterns.

## Evaluation fields

| Field | Type and default | Meaning |
| --- | --- | --- |
| `evaluation_fixture` | Repository-relative path; absent | Frozen retrieval evaluation written for this repository. Palimnex's bundled fixtures describe Palimnex and should not be copied as another project's labels. |
| `evaluation_fixture_sha256` | Lowercase SHA-256; required with a fixture | Pins the exact fixture bytes. Exclude the fixture from the corpus. Never re-pin or relabel solely to make a changed ranking pass. |

## Semantic provider field

The portable runtime accepts only:

```json
"semantic_provider": {"mode": "disabled"}
```

Unknown fields or any other mode are refused. The Phase 4 local semantic
experiment is evaluation-only and does not add a runtime configuration mode.
A future provider requires a separately reviewed design and promotion.

## Ontology influence field

Missing `ontology_influence`, `{"mode": "off"}`, and
`{"mode": "shadow"}` leave production ranking and v1 result documents
unchanged. `off` and `shadow` accept no additional members.

Enabled influence is fail-closed:

```json
"ontology_influence": {
  "mode": "enabled",
  "registry": "ontology/concept-registry.v1.json",
  "registry_digest": "<canonical registry SHA-256>",
  "promotion_evidence": "artifacts/ontology/activation/promotion-evidence.json",
  "promotion_evidence_digest": "<SHA-256 of the exact evidence file bytes>"
}
```

`registry` is optional only because it defaults to the path shown. Every path
must be repository-relative and free of traversal. Activation requires an
approved, current, unambiguous registry and complete promotable evidence for
the local and cache backends, bound to the current implementation.

Promotion evidence v1 does not contain a corpus fingerprint. Therefore rerun
`evaluate-ontology-promotion` and save/review its complete output immediately
before every activation, and again after **any indexed-corpus change**, not
only after registry-bound or implementation files change. Bind the SHA-256 of
the exact saved bytes, then run `ontology-status`. Rollback is `mode: off`.
See `ONTOLOGY_INFLUENCE.md` for the full procedure and refusal reasons.

## Reviewed example

```json
{
  "project_slug": "my-repository",
  "project_id": "REPLACE-WITH-A-NEW-UUID",
  "cache_mode": "on",
  "redis_socket_path": ".palimnex/redis/redis.sock",
  "durable_ledger_path": ".palimnex/memory.sqlite3",
  "include_patterns": ["docs/**/*.md", "src/**/*.py", "tests/**/*.py"],
  "exclude_paths": ["eval/retrieval.json"],
  "content_scan_allowlist_sha256": [],
  "evaluation_fixture": "eval/retrieval.json",
  "evaluation_fixture_sha256": "REPLACE-WITH-LOWERCASE-SHA256",
  "semantic_provider": {"mode": "disabled"}
}
```

After any configuration edit, run `palimnex doctor`, `status`, and the checks
appropriate to the changed field. Configuration changes never authorize a
ledger migration, retention action, erasure, pack activation, Git operation,
publication, provider call, or other external action.
