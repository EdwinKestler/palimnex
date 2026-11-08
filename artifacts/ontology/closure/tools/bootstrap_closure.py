#!/usr/bin/env python3
"""One-shot closure bootstrap: record the owner's 2026-11-08 approval, issue the registry program.

Approval: draft and review the candidate registry, and take the actions needed
to finish and close the ontology adoption and produce the 2.10.0 release
candidate. No Git, network, Redis or ledger activity.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-1/tools"))
import bootstrap_phase1 as b1  # noqa: E402

vc, sha, replace_once, write_json = b1.vc, b1.sha, b1.replace_once, b1.write_json
log = logging.getLogger("bootstrap_closure")
DESIGN, PROPOSAL, GRANTOR = b1.DESIGN, b1.PROPOSAL, b1.GRANTOR
PC = "artifacts/ontology/closure"
EXPECTED_DESIGN_SHA = "2bc034cbb2049d2e4a50c296456041fcd779dbde6107ba98d9875d14716707d8"
RECORDED_AT = "2026-11-08T12:34:00-06:00"
EVIDENCE = ("claude.ai owner message 2026-11-08 12:34 America/Guatemala with attachment: 'Approved to draft "
            "and review the candidate registry. you are approved to take any action needed to finish and close the "
            "nvidia ontology adoption for palimnex ... and produce the new release candidate'; attachment: 14-16 "
            "source-derived concepts, blind evaluation set, Palimnex 2.10.0, activation off, tag and publication "
            "separately approved")

STATUS_OLD = "feedback records, was approved on 2026-11-07.**"
STATUS_NEW = """feedback records, was accepted at its exit gate on 2026-11-07 (commits 6865d40,
79f5a54). On 2026-11-08 the owner approved drafting and review of the first
approved concept registry and the actions needed to close the adoption and
produce the 2.10.0 release candidate; ontology activation stays off.**"""
EVIDENCE_OLD = "`artifacts/ontology/phase-5/approval-evidence.json`."
EVIDENCE_NEW = ("`artifacts/ontology/phase-5/approval-evidence.json` and exit gate\n"
                "`artifacts/ontology/phase-5/exit-gate.json`; registry and closure\n"
                "`artifacts/ontology/closure/approval-evidence.json`.")
ROW_PREFIX = "| Graph exploration format |"
NEW_ROWS = """
| Approved registry v1 scope | 16 source-derived core concepts (source admission and privacy scanning; structured source locators; retrieval-channel fusion; context assembly and byte budgets; cache generations and reader leases; durable historical ledger; retention eligibility and exclusions; ledger migration registry; portable memory packs; audit graph and projections; concept-registry validation; coverage and answerability receipts; ontology shadow ranking; ontology activation gate; semantic shadow evaluation; reviewed retrieval feedback). Conservative multi-word aliases, no standalone generic words. Drafted blind to the Phase 3 evaluation set, which is used only after the candidate is frozen. Bound to the Palimnex checkout only (owner decision 2026-11-08) |
| Registry approval path | A model-drafted candidate (`model_candidate` provenance) is independently reviewed, then committed as `ontology/concept-registry.v1.json` on a release branch; the owner's merge of that reviewed change is the approval. Promotion evidence may be produced and recorded; activation stays off for the release (owner decision 2026-11-08) |
| Release candidate | Palimnex 2.10.0: additive and off by default (API v1, ledger schema v1, existing event kinds and production retrieval unchanged). A candidate is a wheel and sdist built from a pinned commit and tested (CI matrix, installed-wheel smoke, 2.9.0 to 2.10.0 rehearsal, isolated adoption snapshots of other repositories). Tag, GitHub release and PyPI publication need a separate approval (owner decision 2026-11-08) |"""


def build_design() -> str:
    text = (b1.ROOT / DESIGN).read_text(encoding="utf-8")
    text = replace_once(text, STATUS_OLD, STATUS_NEW)
    text = replace_once(text, EVIDENCE_OLD, EVIDENCE_NEW)
    lines = text.split("\n")
    rows = [i for i, line in enumerate(lines) if line.startswith(ROW_PREFIX)]
    if len(rows) != 1:
        raise SystemExit("expected exactly one Graph exploration format row")
    lines[rows[0]] += NEW_ROWS
    return "\n".join(lines)


def approval(design_sha: str) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1", "authority_source": "user_message",
        "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": sha(PROPOSAL)},
        "approved_phases": [1], "authorized_actions": [vc.PHASE_ACTIONS[1]],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in range(6) if p != 1],
        "recorded_at": RECORDED_AT, "implementation_authorized": True,
        "network_authorized": False, "git_write_authorized": False, "live_state_authorized": False,
    }


PY = "./.venv/bin/python"
REG, INTEG = "ontology-closure-registry", "ontology-closure-integration"
BLIND = ["palimnex/evaluation", "palimnex/tests/test_ontology_shadow_cohort.py", "palimnex/tests/test_semantic_cohort.py",
         "artifacts/ontology/phase-3", "artifacts/ontology/phase-3-promotion", "artifacts/ontology/phase-4"]
LANES: dict[str, dict] = {
    REG: {
        "owned": [f"{PC}/candidate"],
        "objective": "Draft the 16-concept candidate concept registry for the Palimnex checkout from source code only (blind to the evaluation sets), with conservative multi-word aliases, current source bindings, NOTES.md rationale and a check_candidate.py validator. Follow briefs/REGISTRY_BRIEF.md.",
        "checks": [f"{PY} {PC}/candidate/check_candidate.py",
                   f"{PY} -m unittest palimnex.tests.test_concepts"],
        "forbidden_extra": BLIND,
    },
    INTEG: {
        "owned": ["ontology", f"{PC}/integration"],
        "objective": "Coordinator-owned: after independent review, write the approved registry ontology/concept-registry.v1.json from the frozen candidate, validate it, record read-only promotion evidence over the local and cache backends, keep activation off, and run the full gate. Not delegated.",
        "checks": [f"{PY} -m unittest discover -s palimnex/tests -p 'test_*.py'", f"{PY} -m mypy",
                   "python3 palimnex.py ontology-status", "python3 palimnex.py evaluate-ontology-promotion",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh'],
        "forbidden_extra": [],
    },
}
EDGES = [{"from": REG, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths.",
    "The candidate is drafted from source code only; the evaluation sets stay unread until the candidate is frozen.",
    "Candidates are never approval: only the reviewed, committed ontology/concept-registry.v1.json merged by the owner is the approved registry.",
    "Ontology activation stays off: .palimnex.json is not edited.",
    "No change to any product module, schema, test expectation or retrieval behaviour.",
    "No Git staging, commits or pushes by lanes; no network, installs, model or provider calls; no Redis or ledger writes.",
    "Never read or echo credentials; never store literal secret-pattern strings.",
]


def receipt(ws: str) -> str:
    return f"{PC}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{b1.VALIDATOR} {PC}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    base = {DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml", "docs", "palimnex",
            ".agents/skills", "artifacts/design/ontology-phase-0", f"{PC}/briefs", f"{PC}/tasks",
            f"{PC}/approval-evidence.json", f"{PC}/manifest.json"}
    if ws != INTEG:
        base.add(f"{PC}/integration")
    forbidden = FORBIDDEN + LANES[ws]["forbidden_extra"]
    read_only = sorted(p for p in base - set(owned(ws)) if p not in forbidden)
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 1,
        "action_id": "ontology_phase_1_registry", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": read_only, "forbidden_paths": forbidden,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 1,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "16 candidate concepts derived from source only, blind to the evaluation sets",
            "conservative multi-word aliases; no collisions or ambiguity; no standalone generic words",
            "every source binding current and digest-verified against the working tree",
            "independent review of every concept, binding and alias before the candidate is frozen",
            "approved registry loads as approved_registry for this project, unambiguous and current",
            "promotion evidence recorded as evidence only; activation off; production retrieval unchanged",
            "full suite (unsandboxed), standard gate and evaluations pass",
        ],
        "authority_limits": [
            "registry drafting and approval path only; activation stays off for the release",
            "no network, provider, Git-write or live-state authority for lanes",
            "the owner's merge of the reviewed registry change is the approval",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("design changed since the Phase 5 exit gate; stopping")
    (b1.ROOT / DESIGN).write_text(build_design(), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    evidence = approval(design["sha256"])
    write_json(f"{PC}/approval-evidence.json", evidence)
    plan = manifest(design)
    write_json(f"{PC}/manifest.json", plan)
    tasks = [task(ws, design, evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{PC}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{PC}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
