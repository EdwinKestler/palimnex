#!/usr/bin/env python3
"""One-shot serial bootstrap for ontology Phase 0 (coordinator-owned).

Creates the approved design under docs/, bounded approval evidence, the
workstream manifest and task cards, then validates them as one bundle.
Run from the repository root with ./.venv/bin/python. Writes no Git state,
touches no Redis/SQLite/ledger state, and makes no network calls.
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

log = logging.getLogger("bootstrap_phase0")

PROPOSAL = "artifacts/design/Ontologyadoptionplan.md"
DESIGN = "docs/ONTOLOGY_ADOPTION.md"
PHASE0 = "artifacts/ontology/phase-0"
DRAFTS = "artifacts/design/ontology-phase-0"
EXPECTED_PROPOSAL_SHA = "8fe38bef5f7f25fa8a7d58dad21b89f69c70f4a367d9981c01fdedf6bd165d86"
RECORDED_AT = "2026-11-05T20:06:00-06:00"
VALIDATOR = "./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"


def sha256_file(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match, found {count}: {old[:60]!r}")
    return text.replace(old, new)


STATUS_OLD = "Status: **proposal awaiting owner decision; not indexed (see `AGENTS.md`).**"
SCOPE_OLD = (
    "This document and the accompanying repository-local skills authorize planning,\n"
    "work decomposition, and review only."
)
SCOPE_NEW = (
    "Phase 0 approval authorizes contract drafting, threat modeling, frozen-case\n"
    "design, work decomposition, and review only. Phase 0 drafts live under\n"
    "`artifacts/design/ontology-phase-0/` (unindexed) until the owner accepts them at\n"
    "the Phase 0 exit gate; coordination records live under\n"
    "`artifacts/ontology/phase-0/`. This document and the repository-local skills do\n"
    "not authorize product code under `palimnex/`."
)
GRAPH_ROW = (
    "| Historical audit graph | Sessions, events, evidence, claims, retention actions, "
    "and tombstones | Historical evidence only |"
)
SEMANTICA_NOTE = (
    "\n\nThe existing optional Semantica adapter (`palimnex/semantica.py`) projects the\n"
    "historical audit graph into an external Semantica store as untrusted historical\n"
    "residue. It is unrelated to the proposed concept registry and to the semantic\n"
    "provider (`palimnex/semantic.py`, `project-memory:semantic-provider:v1`).\n"
    "Ontology work must not reuse, extend, or conflate it."
)
LOCATOR_OLD = "- source locators and content digests;"
LOCATOR_NEW = (
    "- source bindings expressed as existing `source-locator.v1` objects\n"
    "  (`palimnex/locators.py`), whose resolver already reopens sources and refuses\n"
    "  digest drift; Phase 0 must not introduce a second locator shape;"
)
DEFAULTS = """## Phase 0 working defaults (provisional)

Phase 0 drafts use the following defaults. They are not owner decisions: the
owner confirms or changes each one at the Phase 0 exit gate, and any change
reissues the affected drafts.

| Decision | Provisional default |
| --- | --- |
| Implementation module | `palimnex/concepts.py` |
| Registry format and location | Canonical JSON; path and whether the registry file is indexed are chosen at the exit gate |
| Read-only CLI spelling | `explain-search` |
| Alias influence in the first release | Shadow-only through Phase 3 |
| Remote semantic providers | Disabled by default; a remote provider needs a separate privacy design and approval |
| Frozen cohort and thresholds | Drafted in Phase 0 as proposals; numbers approved at the exit gate |
| Query-history feedback | Out of scope for the first ontology release |

## Open owner decisions"""


def build_design(proposal_sha: str) -> str:
    text = (ROOT / PROPOSAL).read_text(encoding="utf-8")
    status_new = (
        "Status: **approved for Phase 0 only (contract freeze and threat model) by the\n"
        "repository owner on 2026-11-05. Phases 1-5 remain proposals and each requires a\n"
        "separate named approval.**\n\n"
        f"Source proposal: `{PROPOSAL}` (SHA-256 `{proposal_sha}`), which stays\n"
        f"unchanged. Approval evidence: `{PHASE0}/approval-evidence.json`."
    )
    text = replace_once(text, STATUS_OLD, status_new)
    text = replace_once(text, SCOPE_OLD, SCOPE_NEW)
    text = replace_once(text, GRAPH_ROW, GRAPH_ROW + SEMANTICA_NOTE)
    text = replace_once(text, LOCATOR_OLD, LOCATOR_NEW)
    text = replace_once(text, "## Open owner decisions", DEFAULTS)
    return text


def receipt_path(ws: str) -> str:
    return f"{PHASE0}/receipts/{ws}.implementation-receipt.json"


def task_path(ws: str) -> str:
    return f"{PHASE0}/tasks/{ws}.json"


LANES = {
    "ontology-phase-0-registry-contract": {
        "objective": (
            "Draft the palimnex:concept-registry:v1 contract: a Draft 2020-12 JSON Schema, "
            "a semantics document (lifecycle, approval, normalization, ambiguity, supersession, "
            "source drift, canonical digest, size and privacy limits), valid and invalid "
            "examples, and an offline check script. Source bindings must reuse "
            "source-locator.v1. Follow the brief at "
            f"{PHASE0}/briefs/ontology-phase-0-registry-contract.md."
        ),
        "owned": [f"{DRAFTS}/registry"],
        "check": f"./.venv/bin/python {DRAFTS}/registry/check_registry_contract.py",
    },
    "ontology-phase-0-coverage-contract": {
        "objective": (
            "Draft the palimnex:retrieval-coverage:v1 receipt contract: a Draft 2020-12 JSON "
            "Schema, a semantics document (status decision table, coverage arithmetic, "
            "ambiguity precedence, truncation and byte-budget separation, identities, digest, "
            "disclosure), valid and invalid examples, and an offline check script. Follow the "
            f"brief at {PHASE0}/briefs/ontology-phase-0-coverage-contract.md."
        ),
        "owned": [f"{DRAFTS}/coverage"],
        "check": f"./.venv/bin/python {DRAFTS}/coverage/check_coverage_contract.py",
    },
    "ontology-phase-0-threat-cases": {
        "objective": (
            "Draft the Phase 0 threat model and the frozen case matrix (positive, partial, "
            "ambiguous, negative, stale-source, secret, truncation, supersession, candidate "
            "non-influence, traversal, cross-project) with an offline check script that also "
            "proves no literal secret material is stored. Follow the brief at "
            f"{PHASE0}/briefs/ontology-phase-0-threat-cases.md."
        ),
        "owned": [f"{DRAFTS}/threat-model", f"{DRAFTS}/frozen-cases"],
        "check": f"./.venv/bin/python {DRAFTS}/frozen-cases/check_cases.py",
    },
    "ontology-phase-0-integration": {
        "objective": (
            "Coordinator-owned serial integration: reconcile the three lane drafts, record the "
            "compatibility and rollback decision and the contract-freeze summary for the owner "
            "exit gate, audit ownership, and run the full gate. Not delegated."
        ),
        "owned": [f"{DRAFTS}/CONTRACT_FREEZE.md", f"{PHASE0}/integration"],
        "check": "./.venv/bin/python -m palimnex validate --deep",
    },
}
INTEGRATION = "ontology-phase-0-integration"

INTEGRATION_COMMANDS = [
    "python3 palimnex.py index",
    "python3 palimnex.py validate --deep",
    "python3 palimnex.py evaluate --limit 5",
    'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh',
    "python3 palimnex.py ledger-status",
    "./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/test_validate_contract.py",
]
COMMON_READ_ONLY = [
    DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "docs",
    "palimnex", ".agents/skills", f"{PHASE0}/briefs", f"{PHASE0}/tasks",
    f"{PHASE0}/approval-evidence.json", f"{PHASE0}/manifest.json",
]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "No product code under palimnex/, no public schema under palimnex/schemas/, no CLI, config or fixture edits.",
    "No Git staging, commits, branches or pushes.",
    "No network access, package installs, model or provider calls from the work itself.",
    "No palimnex index, remember, session, capture, retention, migration, erasure or pack commands; no Redis or SQLite writes.",
    "Never read or echo credentials; never store literal secret-pattern strings.",
]


def approval(design_sha: str, proposal_sha: str) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1",
        "authority_source": "user_message",
        "evidence_locator": (
            "claude.ai conversation with the repository owner, user message sent "
            "2026-11-05 20:06 America/Guatemala: 'i approve phase 0'"
        ),
        "grantor_claim": "repository owner (Gus, GitHub EdwinKestler)",
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": proposal_sha},
        "approved_phases": [0],
        "authorized_actions": ["ontology_phase_0_contract"],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in range(1, 6)],
        "recorded_at": RECORDED_AT,
        "implementation_authorized": True,
        "network_authorized": False,
        "git_write_authorized": False,
        "live_state_authorized": False,
    }


def lane_owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt_path(ws)]


def task(ws: str, design: dict, evidence: dict, deps: list[str]) -> dict:
    if ws == INTEGRATION:
        commands = INTEGRATION_COMMANDS
    else:
        commands = [
            LANES[ws]["check"],
            f"{VALIDATOR} {task_path(ws)} --implementation-receipt {receipt_path(ws)}",
            "git status --short --untracked-files=all",
        ]
    others = [p for o in LANES if o != ws for p in lane_owned(o)]
    return {
        "schema": "palimnex:ontology-workstream-task:v1",
        "workstream_id": ws,
        "phase": 0,
        "action_id": "ontology_phase_0_contract",
        "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS,
        "approved_design_identity": design,
        "approval_evidence": evidence,
        "owned_paths": lane_owned(ws),
        "read_only_paths": COMMON_READ_ONLY + others,
        "forbidden_paths": FORBIDDEN,
        "dependencies": deps,
        "acceptance_commands": commands,
        "required_output": "ImplementationReceipt",
        "network_authority": False,
        "git_write_authority": False,
        "live_state_authority": False,
    }


def manifest(design: dict, edges: list[dict]) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1",
        "approved_phase": 0,
        "design_identity": design,
        "workstreams": list(LANES),
        "dependency_dag": edges,
        "exclusive_file_ownership": {ws: lane_owned(ws) for ws in LANES},
        "shared_file_owner": INTEGRATION,
        "acceptance_gates": [
            "every lane check script passes offline from the repository root",
            "every implementation receipt validates against its task card",
            "post-run file audit shows changes only inside each lane's owned paths",
            "an independent non-implementing reviewer returns a receipt per implementation lane",
            "standard gate, deep validation, retrieval evaluation and contract regressions pass",
            "owner accepts the contract freeze at the Phase 0 exit gate",
        ],
        "authority_limits": [
            "phase 0 contract work only; phases 1-5 excluded",
            "no network, provider, model, Git-write or live-state authority for any lane",
            "agent runtimes (Codex, Grok) were launched at the owner's request; that does not extend any lane's authority",
            "the only Redis activity is the AGENTS.md-required index rebuild by the coordinator; no ledger writes",
        ],
        "status": "ready",
    }


def write_json(path: str, value: dict) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("wrote %s", path)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    proposal_sha = sha256_file(PROPOSAL)
    if proposal_sha != EXPECTED_PROPOSAL_SHA:
        raise SystemExit("source proposal changed since owner review; stopping")
    if (ROOT / DESIGN).exists():
        raise SystemExit(f"{DESIGN} already exists; refusing to overwrite")
    (ROOT / DESIGN).write_text(build_design(proposal_sha), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha256_file(DESIGN)}
    log.info("approved design %s sha256=%s", DESIGN, design["sha256"])

    evidence = approval(design["sha256"], proposal_sha)
    write_json(f"{PHASE0}/approval-evidence.json", evidence)
    edges = [{"from": ws, "to": INTEGRATION} for ws in LANES if ws != INTEGRATION]
    plan = manifest(design, edges)
    write_json(f"{PHASE0}/manifest.json", plan)
    tasks = []
    for ws in LANES:
        deps = [e["from"] for e in edges if e["to"] == ws]
        card = task(ws, design, evidence, deps)
        write_json(task_path(ws), card)
        tasks.append(card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{PHASE0}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
