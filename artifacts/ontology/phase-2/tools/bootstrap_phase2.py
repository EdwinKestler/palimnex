#!/usr/bin/env python3
"""One-shot serial bootstrap for ontology Phase 2 (coordinator-owned).

Records the Phase 1 exit gate and the owner's Phase 2 decisions in the approved
design, writes Phase 2 approval evidence, manifest and task cards, and validates
the bundle. No Git, network, Redis or ledger activity.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-1/tools"))
import bootstrap_phase1 as b1  # noqa: E402

vc, sha, replace_once, write_json = b1.vc, b1.sha, b1.replace_once, b1.write_json
log = logging.getLogger("bootstrap_phase2")
DESIGN, PROPOSAL, GRANTOR = b1.DESIGN, b1.PROPOSAL, b1.GRANTOR
P1, P2 = "artifacts/ontology/phase-1", "artifacts/ontology/phase-2"
EXPECTED_DESIGN_SHA = "0288521fd44d14333ff059a000596861e2a3babc2ffb0a6c58960ba2a6415856"
PHASE1_COMMIT = "80d94c43a93a33508f2519d5cb44b358c62b35a5"
RECORDED_AT = "2026-11-06T07:45:00-06:00"
EVIDENCE = ("claude.ai conversation with the repository owner, user message sent 2026-11-06 07:45 "
            "America/Guatemala (R9 confirmed, import residual accepted, sandbox escape recorded, commit "
            f"{PHASE1_COMMIT[:7]}, 'Phase 2 approved'), plus the owner's answers to the registry-location and "
            "explain-search output questions in the same conversation")
REGISTRY_PATH = "ontology/concept-registry.v1.json"

STATUS_OLD = """Status: **Phase 0 accepted by the repository owner at its exit gate on
2026-11-05. Phase 1 (reviewed concept-registry foundation) approved on
2026-11-05. Phases 2-5 remain proposals and each requires a separate named
approval.**"""
STATUS_NEW = """Status: **Phase 0 accepted at its exit gate on 2026-11-05. Phase 1
(reviewed concept-registry foundation) accepted and committed on 2026-11-06.
Phase 2 (deterministic coverage receipt) approved on 2026-11-06. Phases 3-5
remain proposals and each requires a separate named approval.**"""
EVIDENCE_OLD = "`artifacts/ontology/phase-1/approval-evidence.json`."
EVIDENCE_NEW = ("`artifacts/ontology/phase-1/approval-evidence.json` and exit gate\n"
                "`artifacts/ontology/phase-1/exit-gate.json`; Phase 2\n"
                "`artifacts/ontology/phase-2/approval-evidence.json`.")
SCOPE_START = "Phase 1 approval authorizes implementing the reviewed concept-registry"
SCOPE_END = "coordination records live under `artifacts/ontology/`."
SCOPE_NEW = f"""Phase 2 approval authorizes the deterministic coverage receipt (see "Phase 2"
below): `palimnex/coverage.py`, the public `palimnex:retrieval-coverage:v1` and
`palimnex:explain-search:v1` schemas, their tests and documentation, and the
read-only `explain-search` command, which loads the approved registry from
`{REGISTRY_PATH}` or `--registry PATH`, within exact Phase 2 task cards. It
does not authorize retrieval or ranking influence (aliases stay shadow-only
through Phase 3), creating or populating the approved registry, changes to the
`search` command output or `project-memory:context:v1`, model or network calls,
changes to live Redis or SQLite state, ledger migration, retention-policy
activation, erasure, pack activation, Git writes, publication, deployment, or
any other external action. Accepted Phase 0 drafts remain under
`artifacts/design/ontology-phase-0/`; coordination records live under
`artifacts/ontology/`."""
LOCATION_OLD = ("| Registry location and indexing | **Open.** Phase 1 loads a registry only from an explicitly "
                "passed path; no default location, configuration key or CLI wiring |")
LOCATION_NEW = (f"| Registry location and indexing | `{REGISTRY_PATH}` (owner decision 2026-11-06), loaded "
                "directly and never admitted to the ordinary source index; `--registry PATH` overrides it; a "
                "missing file means coverage is disabled. Candidate sets live under "
                "`artifacts/ontology/candidates/`, outside both the approved read path and the index |")
R8_ROW = "| Validator patch R8 | Not applied; receipts list owned roots |"
NEW_ROWS = R8_ROW + """
| `explain-search` output | One new `palimnex:explain-search:v1` document holding the unchanged `search` result and the coverage receipt as sibling objects (owner decision 2026-11-06) |
| Query whitespace (R9) | Registry keys refuse every C* code point; in queries, whitespace becomes U+0020 before the same procedure (confirmed 2026-11-06) |
| Import residual | `palimnex.concepts` imports the contract-named `cache_v3.project_id` and `core.project_slug` (accepted 2026-11-06) |"""
HEAD_OLD = "## Original open owner decisions (settled above, except the registry location)"
HEAD_NEW = "## Original open owner decisions (settled above)"


def build_design() -> str:
    text = (b1.ROOT / DESIGN).read_text(encoding="utf-8")
    text = replace_once(text, STATUS_OLD, STATUS_NEW)
    text = replace_once(text, EVIDENCE_OLD, EVIDENCE_NEW)
    start, end = text.index(SCOPE_START), text.index(SCOPE_END) + len(SCOPE_END)
    text = text[:start] + SCOPE_NEW + text[end:]
    text = replace_once(text, LOCATION_OLD, LOCATION_NEW)
    text = replace_once(text, R8_ROW, NEW_ROWS)
    return replace_once(text, HEAD_OLD, HEAD_NEW)


def phase1_exit_gate() -> dict:
    return {
        "schema": "palimnex:ontology-exit-gate:v1", "phase": 1, "decision": "accepted",
        "authority_source": "user_message", "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "recorded_at": RECORDED_AT, "commit": PHASE1_COMMIT,
        "design_identity_at_acceptance": {"path": DESIGN, "sha256": EXPECTED_DESIGN_SHA},
        "handoff": f"{P1}/integration/PHASE1_HANDOFF.md",
        "confirmed": ["R9 query-whitespace clarification", "import residual (cache_v3.project_id, core.project_slug)",
                      "sandbox escape recorded; no detected damage; ownership audits clean"],
        "owner_decisions": {"registry_location": REGISTRY_PATH, "registry_indexed": False,
                            "candidate_location": "artifacts/ontology/candidates/",
                            "explain_search_output": "palimnex:explain-search:v1 with sibling search and coverage objects"},
        "not_decided": ["validator patch R8 (not applied)"],
        "pushed": False, "authorizes_actions": False,
    }


CORE, SCHEMA, FROZEN, INTEG = (
    "ontology-phase-2-coverage-core",
    "ontology-phase-2-coverage-schema",
    "ontology-phase-2-frozen-conformance",
    "ontology-phase-2-integration",
)
PY = "./.venv/bin/python"
MYPY = f"{PY} -m mypy --python-version 3.11 --follow-imports=silent --check-untyped-defs --disallow-untyped-defs palimnex/coverage.py"
LANES: dict[str, dict] = {
    CORE: {
        "owned": ["palimnex/coverage.py", "palimnex/tests/test_coverage.py"],
        "objective": "Implement palimnex/coverage.py: the stdlib-only deterministic coverage engine that builds palimnex:retrieval-coverage:v1 receipts from an approved ConceptRegistry, a query and an unchanged search result, plus a runtime receipt validator (structure and cross-field decision table), the canonical receipt digest, and the palimnex:explain-search:v1 document builder. Unit tests in palimnex/tests/test_coverage.py. Follow the brief.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_coverage -v", MYPY,
                   f"{PY} -m unittest palimnex.tests.test_concepts palimnex.tests.test_concepts_frozen"],
    },
    SCHEMA: {
        "owned": ["palimnex/schemas/retrieval-coverage.v1.schema.json", "palimnex/schemas/explain-search.v1.schema.json",
                  "palimnex/tests/test_retrieval_coverage_schema.py", "palimnex/tests/fixtures/retrieval_coverage",
                  "docs/COVERAGE_RECEIPT.md"],
        "objective": "Promote the accepted Phase 0 coverage contract into the public schema palimnex/schemas/retrieval-coverage.v1.schema.json, define the new palimnex/schemas/explain-search.v1.schema.json wrapper, add valid/invalid fixtures and schema tests with local $ref resolution, and write reader documentation docs/COVERAGE_RECEIPT.md. Follow the brief.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_retrieval_coverage_schema palimnex.tests.test_concept_registry_schema palimnex.tests.test_sdk -v"],
    },
    FROZEN: {
        "owned": ["palimnex/tests/test_coverage_frozen.py"],
        "objective": "Add Phase 2 frozen conformance: every gates_phase 2 case in the committed frozen matrix asserted against palimnex.coverage (status and covered/uncovered/stale/ambiguous sets), plus runtime-validator/JSON-Schema parity over produced receipts and the schema-lane fixtures. Follow the brief.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_coverage_frozen palimnex.tests.test_coverage palimnex.tests.test_concepts_frozen -v"],
    },
    INTEG: {
        "owned": ["palimnex/core.py", "palimnex/tests/test_explain_search.py", "pyproject.toml", "palimnex/CHANGELOG.md",
                  "docs/COMPATIBILITY.md", "docs/CONCEPT_REGISTRY.md", f"{P2}/integration"],
        "objective": "Coordinator-owned serial integration: the read-only explain-search CLI command in palimnex/core.py with its tests, mypy file list, CHANGELOG, COMPATIBILITY and the registry-location section of docs/CONCEPT_REGISTRY.md; ownership audit, reindex and the full gate. Not delegated.",
        "checks": [f"{PY} -m unittest discover -s palimnex/tests -p 'test_*.py'", f"{PY} -m mypy", "python3 palimnex.py index",
                   "python3 palimnex.py validate --deep", "python3 palimnex.py evaluate --limit 5",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "python3 palimnex.py ledger-status"],
    },
}
EDGES = [{"from": CORE, "to": FROZEN}, {"from": SCHEMA, "to": FROZEN},
         {"from": CORE, "to": INTEG}, {"from": SCHEMA, "to": INTEG}, {"from": FROZEN, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "No retrieval or ranking influence; the search result is consumed unchanged and never modified or re-ranked.",
    "No change to the search command output, project-memory:context:v1, cache, ledger, MCP, configuration or any existing identifier, schema or test expectation.",
    "Do not create or populate ontology/concept-registry.v1.json or any approved registry.",
    "No runtime dependency: runtime modules use only the standard library and palimnex modules.",
    "No Git staging, commits, branches or pushes; no network, installs, model or provider calls.",
    "No palimnex index, remember, session, capture, retention, migration, erasure or pack commands; no Redis or SQLite writes.",
    "Never read or echo credentials; never store literal secret-pattern strings.",
]


def receipt(ws: str) -> str:
    return f"{P2}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def approval(design_sha: str) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1", "authority_source": "user_message",
        "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": sha(PROPOSAL)},
        "approved_phases": [2], "authorized_actions": ["ontology_phase_2_coverage"],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in (0, 1, 3, 4, 5)],
        "recorded_at": RECORDED_AT, "implementation_authorized": True,
        "network_authorized": False, "git_write_authorized": False, "live_state_authorized": False,
    }


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{b1.VALIDATOR} {P2}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    others = {p for o in LANES if o != ws for p in owned(o)}
    read_only = sorted(({DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml", "docs",
                         "palimnex", ".agents/skills", "artifacts/design/ontology-phase-0", "artifacts/ontology/phase-0",
                         P1, f"{P2}/briefs", f"{P2}/tasks", f"{P2}/approval-evidence.json", f"{P2}/manifest.json"}
                        | others) - set(owned(ws)))
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 2,
        "action_id": "ontology_phase_2_coverage", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": read_only, "forbidden_paths": FORBIDDEN,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 2,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "focused lane tests pass from the repository root with the repository venv",
            "palimnex/coverage.py passes strict mypy and imports only the standard library and palimnex modules",
            "every gates_phase 2 frozen case passes without label changes; runtime validator and JSON Schema agree",
            "every implementation receipt validates against its task card",
            "ownership audit shows changes only inside owned paths",
            "independent non-implementing review returns a receipt per implementation lane",
            "search output and retrieval unchanged: evaluation Recall@5 1.0 and MRR 0.8917, no critical regression",
            "full suite (unsandboxed), standard gate, deep validation, mypy and ledger status pass; no ledger writes",
        ],
        "authority_limits": [
            "phase 2 coverage receipt only; phases 3-5 excluded",
            "no network, provider, model, Git-write or live-state authority for any lane",
            "no retrieval or ranking influence; no change to search output or context v1",
            "no approved registry is created or populated",
            "Codex lanes run with approval_policy=never inside workspace-write; the coordinator runs socket tests unsandboxed",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("design changed since the Phase 1 commit; stopping")
    if (b1.ROOT / P1 / "exit-gate.json").exists():
        raise SystemExit("Phase 1 exit gate already recorded; refusing to overwrite")
    write_json(f"{P1}/exit-gate.json", phase1_exit_gate())
    (b1.ROOT / DESIGN).write_text(build_design(), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    log.info("design updated for Phase 2: sha256=%s", design["sha256"])
    evidence = approval(design["sha256"])
    write_json(f"{P2}/approval-evidence.json", evidence)
    plan = manifest(design)
    write_json(f"{P2}/manifest.json", plan)
    tasks = [task(ws, design, evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{P2}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{P2}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
