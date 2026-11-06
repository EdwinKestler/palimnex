#!/usr/bin/env python3
"""One-shot serial bootstrap for ontology Phase 3 (coordinator-owned).

Records the owner's Phase 3 decisions in the approved design, writes Phase 3
approval evidence, manifest and task cards, and validates the bundle. No Git,
network, Redis or ledger activity.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-1/tools"))
import bootstrap_phase1 as b1  # noqa: E402

vc, sha, replace_once, write_json = b1.vc, b1.sha, b1.replace_once, b1.write_json
log = logging.getLogger("bootstrap_phase3")
DESIGN, PROPOSAL, GRANTOR = b1.DESIGN, b1.PROPOSAL, b1.GRANTOR
P2, P3 = "artifacts/ontology/phase-2", "artifacts/ontology/phase-3"
EXPECTED_DESIGN_SHA = "e04a0f878539eb8670e15155ca505497c08284d2e0b39e78c82872ab5badb8a6"
RECORDED_AT = "2026-11-06T11:20:00-06:00"
COHORT = "palimnex/evaluation/ontology-shadow.v1.json"
EVIDENCE = ("claude.ai conversation with the repository owner, user message sent 2026-11-06 11:20 "
            "America/Guatemala ('ok phase 3 is approved'), plus the owner's answers to the shadow-visibility "
            "and evaluation-registry questions in the same conversation; Phase 2 exit gate commit 2558092")

STATUS_OLD = """Phase 2 (deterministic coverage receipt) approved on 2026-11-06. Phases 3-5
remain proposals and each requires a separate named approval.**"""
STATUS_NEW = """Phase 2 (deterministic coverage receipt) accepted at its exit gate on
2026-11-06 (commit 2558092). Phase 3 (ontology-aware retrieval in shadow mode)
approved on 2026-11-06. Phases 4-5 remain proposals and each requires a
separate named approval.**"""
EVIDENCE_OLD = "`artifacts/ontology/phase-2/approval-evidence.json`."
EVIDENCE_NEW = ("`artifacts/ontology/phase-2/approval-evidence.json` and exit gate\n"
                "`artifacts/ontology/phase-2/exit-gate.json`; Phase 3\n"
                "`artifacts/ontology/phase-3/approval-evidence.json`.")
SCOPE_START = "Phase 2 approval authorizes the deterministic coverage receipt"
SCOPE_END = "coordination records live under\n`artifacts/ontology/`."
SCOPE_NEW = f"""Phase 3 approval authorizes ontology-aware retrieval in shadow mode (see
"Phase 3" below): a concept/alias channel computed beside the lexical, symbol and
graph channels of `retrieve_sources`, a shadow fusion and the
`palimnex:ontology-shadow-comparison:v1` report, a frozen evaluation-only
cohort and test registry (`{COHORT}`), and the read-only
`evaluate-ontology-shadow` command, within exact Phase 3 task cards. Shadow
output is visible only through that evaluation command (owner decision
2026-11-06). It does not authorize any change to returned rankings, `search`,
`context`, `explain-search` or their formats, creating or populating the
approved registry, retrieval influence or promotion (a separate owner
approval), model or network calls, changes to live Redis or SQLite state,
ledger migration, retention-policy activation, erasure, pack activation, Git
writes, publication, deployment, or any other external action. Accepted Phase 0
drafts remain under `artifacts/design/ontology-phase-0/`; coordination records
live under `artifacts/ontology/`."""
ROW_ANCHOR = "| Import residual | `palimnex.concepts` imports the contract-named `cache_v3.project_id` and `core.project_slug` (accepted 2026-11-06) |"
NEW_ROWS = ROW_ANCHOR + f"""
| Shadow visibility (Phase 3) | Evaluation command only: `palimnex evaluate-ontology-shadow` compares baseline and shadow rankings; no user-facing retrieval output changes (owner decision 2026-11-06) |
| Phase 3 evaluation concepts | A hand-written, frozen, evaluation-only test registry and ontology cohort in `{COHORT}`; never loaded by `explain-search` and never an approved registry (owner decision 2026-11-06) |
| Phase 2 coordinator decisions | R10, R11, the byte-budget attribution fix and independent truncation flags confirmed at the Phase 2 exit gate |"""


def build_design() -> str:
    text = (b1.ROOT / DESIGN).read_text(encoding="utf-8")
    text = replace_once(text, STATUS_OLD, STATUS_NEW)
    text = replace_once(text, EVIDENCE_OLD, EVIDENCE_NEW)
    start, end = text.index(SCOPE_START), text.index(SCOPE_END) + len(SCOPE_END)
    text = text[:start] + SCOPE_NEW + text[end:]
    return replace_once(text, ROW_ANCHOR, NEW_ROWS)


CHANNEL, COHORT_LANE, RETRIEVAL, EVAL, INTEG = (
    "ontology-phase-3-channel",
    "ontology-phase-3-cohort",
    "ontology-phase-3-retrieval",
    "ontology-phase-3-evaluation",
    "ontology-phase-3-integration",
)
PY = "./.venv/bin/python"


def mypy(path: str) -> str:
    return f"{PY} -m mypy --python-version 3.11 --follow-imports=silent --check-untyped-defs --disallow-untyped-defs {path}"


LANES: dict[str, dict] = {
    CHANNEL: {
        "owned": ["palimnex/ontology_shadow.py", "palimnex/tests/test_ontology_shadow.py",
                  "palimnex/schemas/ontology-shadow-comparison.v1.schema.json", "docs/ONTOLOGY_SHADOW.md"],
        "objective": "Implement palimnex/ontology_shadow.py: the stdlib-only ontology channel ranking over retrieval chunks, the palimnex:ontology-shadow-comparison:v1 builder and runtime validator, the public schema and reader documentation. Follow the brief and SHADOW_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_ontology_shadow -v", mypy("palimnex/ontology_shadow.py"),
                   f"{PY} -m unittest palimnex.tests.test_concepts palimnex.tests.test_coverage"],
    },
    COHORT_LANE: {
        "owned": [COHORT, "palimnex/tests/test_ontology_shadow_cohort.py"],
        "objective": "Author the frozen evaluation-only ontology shadow cohort with its embedded test registry (placeholder digests, materialized at evaluation time) and a structural test. Follow the brief and SHADOW_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_ontology_shadow_cohort -v"],
    },
    RETRIEVAL: {
        "owned": ["palimnex/retrieval.py", "palimnex/tests/test_retrieval_shadow.py"],
        "objective": "Refactor palimnex/retrieval.py so the baseline retrieve_sources output stays byte-identical while shadow_retrieve computes the ontology channel and a shadow fusion beside it and returns the baseline plus a comparison document; tests include baseline identity and the gates_phase 3 frozen cases. Follow the brief and SHADOW_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_retrieval_shadow -v",
                   f"{PY} -m unittest palimnex.tests.test_ontology_shadow palimnex.tests.test_coverage palimnex.tests.test_explain_search palimnex.tests.test_coverage_frozen"],
    },
    EVAL: {
        "owned": ["palimnex/ontology_eval.py", "palimnex/tests/test_ontology_eval.py"],
        "objective": "Implement palimnex/ontology_eval.py: evaluate_ontology_shadow, which measures baseline and shadow rankings over the frozen v27 cases, the v26 challenge negatives and the ontology cohort, and reports the Phase 3 exit-gate measures without ever authorizing promotion. Follow the brief and SHADOW_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_ontology_eval -v", mypy("palimnex/ontology_eval.py")],
    },
    INTEG: {
        "owned": ["palimnex/core.py", "palimnex/tests/test_evaluate_ontology_shadow_cli.py", ".palimnex.json",
                  "pyproject.toml", "palimnex/CHANGELOG.md", "docs/COMPATIBILITY.md", f"{P3}/integration"],
        "objective": "Coordinator-owned serial integration: the read-only evaluate-ontology-shadow CLI command in palimnex/core.py with its tests, excluding the cohort from the source index in .palimnex.json, mypy file list, CHANGELOG and COMPATIBILITY; ownership audit, reindex and the full gate. Not delegated.",
        "checks": [f"{PY} -m unittest discover -s palimnex/tests -p 'test_*.py'", f"{PY} -m mypy", "python3 palimnex.py index",
                   "python3 palimnex.py validate --deep", "python3 palimnex.py evaluate --limit 5",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "python3 palimnex.py ledger-status",
                   "python3 palimnex.py evaluate-ontology-shadow"],
    },
}
EDGES = [{"from": CHANNEL, "to": RETRIEVAL}, {"from": RETRIEVAL, "to": EVAL}, {"from": COHORT_LANE, "to": EVAL},
         {"from": CHANNEL, "to": INTEG}, {"from": COHORT_LANE, "to": INTEG}, {"from": RETRIEVAL, "to": INTEG},
         {"from": EVAL, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "Shadow never alters returned results: retrieve_sources, search, context, explain-search and every existing output stay byte-identical.",
    "No promotion, retrieval influence or configuration switch that would enable either.",
    "Do not create or populate ontology/concept-registry.v1.json or any approved registry; the cohort registry is evaluation-only test data.",
    "No change to any existing identifier, schema, frozen fixture or test expectation; v25-v27 and cases.v0.json are read-only.",
    "No runtime dependency: runtime modules use only the standard library and palimnex modules.",
    "No Git staging, commits, branches or pushes; no network, installs, model or provider calls.",
    "No palimnex index, remember, session, capture, retention, migration, erasure or pack commands; no Redis or SQLite writes.",
    "Never read or echo credentials; never store literal secret-pattern strings.",
]


def receipt(ws: str) -> str:
    return f"{P3}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def approval(design_sha: str) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1", "authority_source": "user_message",
        "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": sha(PROPOSAL)},
        "approved_phases": [3], "authorized_actions": ["ontology_phase_3_shadow"],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in (0, 1, 2, 4, 5)],
        "recorded_at": RECORDED_AT, "implementation_authorized": True,
        "network_authorized": False, "git_write_authorized": False, "live_state_authorized": False,
    }


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{b1.VALIDATOR} {P3}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    base = {DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml", "docs", "palimnex",
            ".agents/skills", "artifacts/design/ontology-phase-0", "artifacts/ontology/phase-0",
            "artifacts/ontology/phase-1", P2, f"{P3}/briefs", f"{P3}/tasks", f"{P3}/approval-evidence.json",
            f"{P3}/manifest.json"}
    read_only = sorted(base - set(owned(ws)))
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 3,
        "action_id": "ontology_phase_3_shadow", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": read_only, "forbidden_paths": FORBIDDEN,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 3,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "baseline identity: retrieve_sources, search, context and explain-search outputs are byte-identical with and without shadow",
            "all current critical retrieval cases remain green; no new forbidden-path hits",
            "negative-query abstention does not regress under the shadow ranking",
            "ambiguous, stale, uncovered and candidate concepts never contribute to the ontology channel",
            "lexical, symbol, graph and ontology channel ranks stay separately visible in the comparison",
            "candidate caps, byte budgets and deterministic tie-breaking stay bounded",
            "evaluation reports promotion_authorized false; promotion needs separate owner approval",
            "focused tests and strict mypy pass; receipts validate; ownership audit clean; independent review per lane",
            "full suite (unsandboxed), standard gate, deep validation, evaluation and ledger status pass; no ledger writes",
        ],
        "authority_limits": [
            "phase 3 shadow only; phases 4-5 excluded; no retrieval influence or promotion",
            "no network, provider, model, Git-write or live-state authority for any lane",
            "shadow visible only through evaluate-ontology-shadow; no approved registry created",
            "Codex lanes run with approval_policy=never inside workspace-write; the coordinator runs socket tests unsandboxed",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("design changed since the Phase 2 exit gate; stopping")
    (b1.ROOT / DESIGN).write_text(build_design(), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    log.info("design updated for Phase 3: sha256=%s", design["sha256"])
    evidence = approval(design["sha256"])
    write_json(f"{P3}/approval-evidence.json", evidence)
    plan = manifest(design)
    write_json(f"{P3}/manifest.json", plan)
    tasks = [task(ws, design, evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{P3}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{P3}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
