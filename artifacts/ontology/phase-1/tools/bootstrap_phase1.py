#!/usr/bin/env python3
"""One-shot serial bootstrap for ontology Phase 1 (coordinator-owned).

Records the Phase 0 exit gate, updates the approved design for Phase 1, writes
Phase 1 approval evidence, manifest and task cards, and validates the bundle.
No Git, network, Redis or ledger activity.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".agents/skills/palimnex-ontology-coordinator/scripts"))
import validate_contract as vc  # noqa: E402

log = logging.getLogger("bootstrap_phase1")
DESIGN = "docs/ONTOLOGY_ADOPTION.md"
PROPOSAL = "artifacts/design/Ontologyadoptionplan.md"
P0 = "artifacts/ontology/phase-0"
P1 = "artifacts/ontology/phase-1"
DRAFTS = "artifacts/design/ontology-phase-0"
CASES = f"{DRAFTS}/frozen-cases/cases.v0.json"
EXPECTED_CASES_SHA = "a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b"
EXPECTED_DESIGN_SHA = "9bfdb51ddec03aa8976206979fc45df5a1c7668579aa855d1cff6cae690686c2"
ACCEPTED_AT = "2026-11-05T21:32:00-06:00"
EVIDENCE = ("claude.ai conversation with the repository owner, user message sent "
            "2026-11-05 21:32 America/Guatemala: 'accept phase 0 and authorize to proceed to phase 1'")
GRANTOR = "repository owner (Gus, GitHub EdwinKestler)"
VALIDATOR = "./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one match for {old[:70]!r}, found {text.count(old)}")
    return text.replace(old, new)


def write_json(path: str, value: dict) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("wrote %s", path)


OLD_STATUS = """Status: **approved for Phase 0 only (contract freeze and threat model) by the
repository owner on 2026-11-05. Phases 1-5 remain proposals and each requires a
separate named approval.**"""
NEW_STATUS = """Status: **Phase 0 accepted by the repository owner at its exit gate on
2026-11-05. Phase 1 (reviewed concept-registry foundation) approved on
2026-11-05. Phases 2-5 remain proposals and each requires a separate named
approval.**"""
OLD_EVIDENCE = "unchanged. Approval evidence: `artifacts/ontology/phase-0/approval-evidence.json`."
NEW_EVIDENCE = (
    "unchanged. Approval evidence: Phase 0 `artifacts/ontology/phase-0/approval-evidence.json`\n"
    "and exit gate `artifacts/ontology/phase-0/exit-gate.json`; Phase 1\n"
    "`artifacts/ontology/phase-1/approval-evidence.json`."
)
OLD_SCOPE_START = "Phase 0 approval authorizes contract drafting, threat modeling, frozen-case"
OLD_SCOPE_END = "Git writes, publication, deployment, or any other external action."
NEW_SCOPE = """Phase 1 approval authorizes implementing the reviewed concept-registry
foundation (see "Phase 1" below) in `palimnex/`, its tests and `docs/`, within
exact Phase 1 task cards. It does not authorize coverage receipts, retrieval
influence, a default registry location, configuration keys or CLI wiring that
load a registry, model or network calls, changes to live Redis or SQLite state,
ledger migration, retention-policy activation, erasure, pack activation, Git
writes, publication, deployment, or any other external action. Accepted Phase 0
drafts remain under `artifacts/design/ontology-phase-0/` as the promotion source;
coordination records live under `artifacts/ontology/`."""
OLD_DEFAULTS_HEAD = "## Phase 0 working defaults (provisional)"
OLD_OPEN_HEAD = "## Open owner decisions"


def accepted_section(cases_sha: str) -> str:
    return f"""## Accepted Phase 0 decisions (exit gate, 2026-11-05)

| Decision | Accepted |
| --- | --- |
| Implementation module | `palimnex/concepts.py` |
| Registry format | Canonical JSON, `palimnex:concept-registry:v1` |
| Registry location and indexing | **Open.** Phase 1 loads a registry only from an explicitly passed path; no default location, configuration key or CLI wiring |
| Read-only CLI spelling | `explain-search` (Phase 2) |
| Alias influence in the first release | Shadow-only through Phase 3 |
| Remote semantic providers | Disabled by default; a remote provider needs a separate privacy design and approval |
| Query-history feedback | Out of scope for the first ontology release |
| Shared definitions (R1-R7) | `artifacts/ontology/phase-0/integration/reconciliation-decisions.v1.md`: concept ID `^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$` (3-128); the registry owns `conceptId`, `alias` and `projectIdentity`; frozen fixtures are full registries; stale is its own collection; ambiguity wins and is disjoint from covered; malformed/traversal paths, symlinks, cross-project bindings and privacy refusals are typed errors, stale source is a receipt state |
| Alias normalization | NFKC, Unicode casefold, punctuation to space, whitespace collapse; aliases are stored normalized |
| Bounds | Registry 1,000,000 bytes and 512 concepts; alias max 128 normalized characters; coverage collections 256 visible and 4,096 total |
| Frozen case matrix | `artifacts/design/ontology-phase-0/frozen-cases/cases.v0.json`, SHA-256 `{cases_sha}`. Labels never change to make an implementation pass. Known: ONT-NORM-001 does not encode a mixed-case query; 8 cases remain `expected_status_disputed` |
| Validator patch R8 | Not applied; receipts list owned roots |

## Original open owner decisions (settled above, except the registry location)"""


def build_design(cases_sha: str) -> str:
    text = (ROOT / DESIGN).read_text(encoding="utf-8")
    text = replace_once(text, OLD_STATUS, NEW_STATUS)
    text = replace_once(text, OLD_EVIDENCE, NEW_EVIDENCE)
    start, end = text.index(OLD_SCOPE_START), text.index(OLD_SCOPE_END) + len(OLD_SCOPE_END)
    text = text[:start] + NEW_SCOPE + text[end:]
    d_start, d_end = text.index(OLD_DEFAULTS_HEAD), text.index(OLD_OPEN_HEAD) + len(OLD_OPEN_HEAD)
    return text[:d_start] + accepted_section(cases_sha) + text[d_end:]


def exit_gate(cases_sha: str) -> dict:
    drafts = sorted(p for p in (ROOT / DRAFTS).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return {
        "schema": "palimnex:ontology-exit-gate:v1",
        "phase": 0,
        "decision": "accepted",
        "authority_source": "user_message",
        "evidence_locator": EVIDENCE,
        "grantor_claim": GRANTOR,
        "recorded_at": ACCEPTED_AT,
        "design_identity_at_acceptance": {"path": DESIGN, "sha256": EXPECTED_DESIGN_SHA},
        "contract_freeze": f"{DRAFTS}/CONTRACT_FREEZE.md",
        "accepted_decisions": f"{P0}/integration/reconciliation-decisions.v1.md (R1-R7)",
        "frozen_case_matrix": {"path": CASES, "sha256": cases_sha},
        "accepted_artifacts": {p.relative_to(ROOT).as_posix(): sha(p.relative_to(ROOT).as_posix()) for p in drafts},
        "not_decided": ["registry location and indexing", "validator patch R8 (not applied)"],
        "authorizes_actions": False,
    }


CORE, SCHEMA, FROZEN, INTEG = (
    "ontology-phase-1-registry-core",
    "ontology-phase-1-registry-schema",
    "ontology-phase-1-frozen-conformance",
    "ontology-phase-1-integration",
)
PY = "./.venv/bin/python"
MYPY = f"{PY} -m mypy --python-version 3.11 --follow-imports=silent --check-untyped-defs --disallow-untyped-defs palimnex/concepts.py"
LANES: dict[str, dict] = {
    CORE: {
        "owned": ["palimnex/concepts.py", "palimnex/tests/test_concepts.py"],
        "objective": "Implement palimnex/concepts.py: the stdlib-only, bounded concept-registry loader, structural validation mirroring the accepted v1 contract, canonical registry digest, deterministic alias normalization, exact-alias matching with explicit ambiguity, candidate/approved separation, supersession and withdrawal exclusion, and source-binding verification through palimnex.locators with drift reported as stale. Unit tests in palimnex/tests/test_concepts.py. Follow the brief.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_concepts -v", MYPY],
    },
    SCHEMA: {
        "owned": ["palimnex/schemas/concept-registry.v1.schema.json", "palimnex/tests/test_concept_registry_schema.py",
                  "palimnex/tests/fixtures/concept_registry", "docs/CONCEPT_REGISTRY.md"],
        "objective": "Promote the accepted Phase 0 registry contract into the public schema palimnex/schemas/concept-registry.v1.schema.json, public reader documentation docs/CONCEPT_REGISTRY.md, valid/invalid fixtures, and schema tests that resolve source-locator.v1 locally. Follow the brief.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_concept_registry_schema palimnex.tests.test_sdk -v"],
    },
    FROZEN: {
        "owned": ["palimnex/tests/test_concepts_frozen.py", "palimnex/tests/fixtures/ontology"],
        "objective": "Add the byte-exact frozen Phase 0 case matrix as a single-owner test fixture and Phase 1 conformance tests: every gates_phase 1 case against palimnex.concepts, plus runtime-validator/JSON-Schema parity over every frozen registry fixture and the schema-lane fixtures. Follow the brief.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_concepts_frozen palimnex.tests.test_concepts -v"],
    },
    INTEG: {
        "owned": ["pyproject.toml", "palimnex/CHANGELOG.md", "docs/COMPATIBILITY.md", f"{P1}/integration"],
        "objective": "Coordinator-owned serial integration: add palimnex/concepts.py to the mypy file list, record the change in CHANGELOG and COMPATIBILITY, audit ownership, reindex, and run the full gate. Not delegated.",
        "checks": ["python3 palimnex.py index", "python3 palimnex.py validate --deep", "python3 palimnex.py evaluate --limit 5",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', f"{PY} -m mypy", "python3 palimnex.py ledger-status"],
    },
}
EDGES = [{"from": CORE, "to": FROZEN}, {"from": SCHEMA, "to": FROZEN},
         {"from": CORE, "to": INTEG}, {"from": SCHEMA, "to": INTEG}, {"from": FROZEN, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "No retrieval, ranking, context, cache, ledger, CLI dispatch, MCP, configuration or default-registry-location changes.",
    "No runtime dependency: palimnex/concepts.py uses only the standard library and palimnex modules.",
    "No change to any existing project-memory:* identifier, existing schema or existing test expectation.",
    "No Git staging, commits, branches or pushes; no network, installs, model or provider calls.",
    "No palimnex index, remember, session, capture, retention, migration, erasure or pack commands; no Redis or SQLite writes.",
    "Never read or echo credentials; never store literal secret-pattern strings.",
]


def receipt(ws: str) -> str:
    return f"{P1}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def approval(design_sha: str, proposal_sha: str) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1", "authority_source": "user_message",
        "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": proposal_sha},
        "approved_phases": [1], "authorized_actions": ["ontology_phase_1_registry"],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in range(2, 6)],
        "recorded_at": ACCEPTED_AT, "implementation_authorized": True,
        "network_authorized": False, "git_write_authorized": False, "live_state_authorized": False,
    }


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{VALIDATOR} {P1}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    others = sorted(p for o in LANES if o != ws for p in owned(o))
    read_only = sorted({DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml",
                        "docs", "palimnex", ".agents/skills", DRAFTS, P0, f"{P1}/briefs", f"{P1}/tasks",
                        f"{P1}/approval-evidence.json", f"{P1}/manifest.json"} | set(others))
    read_only = [p for p in read_only if p not in owned(ws)]
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 1,
        "action_id": "ontology_phase_1_registry", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": read_only, "forbidden_paths": FORBIDDEN,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 1,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "focused lane tests pass from the repository root with the repository venv",
            "palimnex/concepts.py passes strict mypy and imports only the standard library and palimnex modules",
            "every implementation receipt validates against its task card",
            "ownership audit shows changes only inside owned paths",
            "independent non-implementing review returns a receipt per implementation lane",
            "existing retrieval output unchanged: evaluation Recall@5 1.0 and MRR 0.8917 with no critical regression",
            "standard gate, deep validation, mypy and ledger status pass; no ledger writes",
        ],
        "authority_limits": [
            "phase 1 registry foundation only; phases 2-5 excluded",
            "no network, provider, model, Git-write or live-state authority for any lane",
            "no default registry location, configuration key, CLI or retrieval wiring",
            "Redis activity limited to the coordinator's AGENTS.md-required reindex and gate; no ledger writes",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("approved Phase 0 design changed since the exit gate; stopping")
    cases_sha = sha(CASES)
    if cases_sha != EXPECTED_CASES_SHA:
        raise SystemExit("frozen case matrix changed since the exit gate; stopping")
    write_json(f"{P0}/exit-gate.json", exit_gate(cases_sha))
    (ROOT / DESIGN).write_text(build_design(cases_sha), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    log.info("design updated for Phase 1: sha256=%s", design["sha256"])
    evidence = approval(design["sha256"], sha(PROPOSAL))
    write_json(f"{P1}/approval-evidence.json", evidence)
    plan = manifest(design)
    write_json(f"{P1}/manifest.json", plan)
    tasks = [task(ws, design, evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{P1}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{P1}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
