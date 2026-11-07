#!/usr/bin/env python3
"""One-shot serial bootstrap: ontology influence promotion and Phase 4 approvals.

Records the owner's 2026-11-06 16:46 approvals and decisions in the approved
design, writes approval evidence for the influence promotion (Phase 3 action)
and for Phase 4, and issues the influence-promotion manifest and task cards.
Phase 4 task cards are issued later by their own bootstrap. No Git, network,
Redis or ledger activity.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-1/tools"))
import bootstrap_phase1 as b1  # noqa: E402

vc, sha, replace_once, write_json = b1.vc, b1.sha, b1.replace_once, b1.write_json
log = logging.getLogger("bootstrap_promotion")
DESIGN, PROPOSAL, GRANTOR = b1.DESIGN, b1.PROPOSAL, b1.GRANTOR
P3, PP, P4 = "artifacts/ontology/phase-3", "artifacts/ontology/phase-3-promotion", "artifacts/ontology/phase-4"
EXPECTED_DESIGN_SHA = "f97c4f426960b1e4011ef825380f1c7cbe87e393e7ab773b408eb65cb3360b65"
RECORDED_AT = "2026-11-06T16:46:00-06:00"
EVIDENCE = ("claude.ai conversation with the repository owner, user message sent 2026-11-06 16:46 "
            "America/Guatemala ('R12 is confirmed and Phase 3 is committed ... Phase 4 and retrieval influence "
            "Approved'), commits ad96d37 and 2b9bebc, plus the owner's detailed answers on influence activation, "
            "influence surfaces, Phase 4 embeddings and Phase 4 thresholds in the same conversation")

STATUS_OLD = """Phase 3 (ontology-aware retrieval in shadow mode)
approved on 2026-11-06. Phases 4-5 remain proposals and each requires a
separate named approval.**"""
STATUS_NEW = """Phase 3 (ontology-aware retrieval in shadow mode)
accepted at its exit gate on 2026-11-06 (commits ad96d37, 2b9bebc). The move
from shadow to ontology retrieval influence and Phase 4 (local semantic
experiment) were approved on 2026-11-06. Phase 5 remains a proposal.**"""
EVIDENCE_OLD = "`artifacts/ontology/phase-3/approval-evidence.json`."
EVIDENCE_NEW = ("`artifacts/ontology/phase-3/approval-evidence.json` and exit gate\n"
                "`artifacts/ontology/phase-3/exit-gate.json`; influence promotion\n"
                "`artifacts/ontology/phase-3-promotion/approval-evidence.json`; Phase 4\n"
                "`artifacts/ontology/phase-4/approval-evidence.json`.")
SCOPE_START = "Phase 3 approval authorizes ontology-aware retrieval in shadow mode"
SCOPE_END = "drafts remain under `artifacts/design/ontology-phase-0/`; coordination records\nlive under `artifacts/ontology/`."
SCOPE_NEW = """The influence-promotion approval authorizes an opt-in ontology retrieval
influence for `retrieve_sources` and its direct consumers (`context`,
`explain-search`, SDK calls), controlled by `.palimnex.json`
`ontology_influence.mode` (`off` | `shadow` | `enabled`; missing means `off`),
disclosed through new versioned results (`project-memory:context:v2`,
`palimnex:explain-search:v2`), an `evaluate-ontology-promotion` command that
writes `palimnex:ontology-promotion-evidence:v1` over the local and cache
backends, and an `ontology-status` command. Activation is the owner's config
edit and must bind the approved registry digest and the promotion evidence.
Phase 4 approval authorizes a deterministic in-process semantic provider (the
existing hashed embedding plus test doubles), a frozen semantic cohort, a
semantic shadow channel and a new versioned evaluation contract with the
owner's thresholds. Neither approval authorizes changes to cache-backed
`search`, `symbols`, `impact` or `palimnex evaluate`; activating influence on
the owner's behalf; creating or populating the approved registry; promoting a
semantic provider (a passing report means only "promotable"); downloading
models, installing packages, network access or a persistent vector store;
changes to `project-memory:semantic-provider:v1` or the existing semantic gate;
changes to live Redis or SQLite state; ledger migration; Git writes;
publication; deployment; or any other external action. Accepted Phase 0 drafts
remain under `artifacts/design/ontology-phase-0/`; coordination records live
under `artifacts/ontology/`."""
ROW_ANCHOR = "| Phase 2 coordinator decisions | R10, R11, the byte-budget attribution fix and independent truncation flags confirmed at the Phase 2 exit gate |"
NEW_ROWS = ROW_ANCHOR + """
| Phase 3 gate meaning (R12) | "Critical cases remain green" means production retrieval stays byte-identical and the shadow causes no critical regression (confirmed 2026-11-06) |
| Influence activation | Opt-in `.palimnex.json` `ontology_influence.mode` (`off`, `shadow`, `enabled`; missing means `off`). `enabled` binds the approved registry digest and the promotion evidence (path and digest). Missing, corrupt, stale, ambiguous or privacy-refused registry data, or mismatched evidence, is an explicit error, never a silent fallback. Rollback is `mode: off`. Registry presence is data, not operational authority (owner decision 2026-11-06) |
| Influence surfaces | Only `retrieve_sources` and its direct consumers (`context`, `explain-search`, SDK calls); cache-backed `search`, `symbols`, `impact` and `palimnex evaluate` unchanged and kept as the compatibility sentinel. Influenced results are disclosed through new versioned contracts; `context:v1` is never silently changed. Promotion testing covers the local and cache backends (owner decision 2026-11-06) |
| Phase 4 provider | Deterministic in-process provider over the existing hashed embedding, with test doubles for malformed dimensions, NaN/Inf, timeouts and failures; a distinct provider ID, revision, dimensions and implementation digest; no model download, package installation, network or persistent vector store. A real local model is a later, separately approved experiment (owner decision 2026-11-06) |
| Phase 4 thresholds | Fixed before testing: no critical or per-case regression; Recall@5 not reduced on any protected suite; at least +0.02 MRR or Recall@5 on the frozen semantic cohort, with at least one more passing cohort case; p95 at most 1.5x the paired baseline under a fixed benchmark protocol; no new forbidden hits; abstention, ambiguity, source-drift and privacy-canary gates; deterministic results; bound provider identity. Requires a new versioned evaluation contract; the semantic v1 helper (+0.05, 2x) is unchanged. A passing report means promotable only (owner decision 2026-11-06) |"""


def build_design() -> str:
    text = (b1.ROOT / DESIGN).read_text(encoding="utf-8")
    text = replace_once(text, STATUS_OLD, STATUS_NEW)
    text = replace_once(text, EVIDENCE_OLD, EVIDENCE_NEW)
    start, end = text.index(SCOPE_START), text.index(SCOPE_END) + len(SCOPE_END)
    text = text[:start] + SCOPE_NEW + text[end:]
    return replace_once(text, ROW_ANCHOR, NEW_ROWS)


def approval(design_sha: str, phase: int) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1", "authority_source": "user_message",
        "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": sha(PROPOSAL)},
        "approved_phases": [phase], "authorized_actions": [vc.PHASE_ACTIONS[phase]],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in range(6) if p != phase],
        "recorded_at": RECORDED_AT, "implementation_authorized": True,
        "network_authorized": False, "git_write_authorized": False, "live_state_authorized": False,
    }


GATE, SCHEMAS, RETRIEVAL, PROMOTION, INTEG = (
    "ontology-influence-gate",
    "ontology-influence-schemas",
    "ontology-influence-retrieval",
    "ontology-influence-promotion",
    "ontology-influence-integration",
)
PY = "./.venv/bin/python"


def mypy(*paths: str) -> str:
    return f"{PY} -m mypy --python-version 3.11 --follow-imports=silent --check-untyped-defs --disallow-untyped-defs " + " ".join(paths)


REGRESSION = f"{PY} -m unittest palimnex.tests.test_ontology_shadow palimnex.tests.test_retrieval_shadow palimnex.tests.test_coverage palimnex.tests.test_explain_search"
LANES: dict[str, dict] = {
    GATE: {
        "owned": ["palimnex/ontology_influence.py", "palimnex/tests/test_ontology_influence.py", "docs/ONTOLOGY_INFLUENCE.md"],
        "objective": "Implement palimnex/ontology_influence.py: the ontology_influence setting parser, activation checks (approved, project-matching, unambiguous, current registry bound by digest; promotion evidence bound by digest, implementation digest and status), the implementation digest, the promotion-evidence validator, the influence disclosure and the context v2 and explain-search v2 wrappers; tests and docs/ONTOLOGY_INFLUENCE.md. Follow INFLUENCE_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_ontology_influence -v", mypy("palimnex/ontology_influence.py"), REGRESSION],
    },
    SCHEMAS: {
        "owned": ["palimnex/schemas/context.v2.schema.json", "palimnex/schemas/explain-search.v2.schema.json",
                  "palimnex/schemas/ontology-promotion-evidence.v1.schema.json", "palimnex/tests/test_influence_schemas.py",
                  "palimnex/tests/fixtures/ontology_influence"],
        "objective": "Define the public schemas project-memory:context:v2, palimnex:explain-search:v2 and palimnex:ontology-promotion-evidence:v1 exactly per INFLUENCE_SPEC.md, with valid and invalid fixtures and schema tests.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_influence_schemas palimnex.tests.test_retrieval_coverage_schema palimnex.tests.test_sdk -v"],
    },
    RETRIEVAL: {
        "owned": ["palimnex/retrieval.py", "palimnex/experience.py", "palimnex/ontology_eval.py",
                  "palimnex/tests/test_retrieval_influence.py", "palimnex/tests/test_ontology_eval.py"],
        "objective": "Make retrieve_sources honor the ontology_influence setting (off and shadow byte-identical to today; enabled fuses the ontology channel and discloses it), make assemble_context emit context v2 only when influenced, and pin Phase 3 shadow evaluation to the uninfluenced baseline. Follow INFLUENCE_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_retrieval_influence palimnex.tests.test_ontology_eval -v", mypy("palimnex/ontology_eval.py"),
                   REGRESSION + " palimnex.tests.test_experience palimnex.tests.test_challenge palimnex.tests.test_ontology_influence"],
    },
    PROMOTION: {
        "owned": ["palimnex/ontology_promotion.py", "palimnex/tests/test_ontology_promotion.py"],
        "objective": "Implement palimnex/ontology_promotion.py: evaluate_ontology_promotion, which measures baseline versus influenced retrieve_sources on the local and cache (offline FakeRedis) backends and returns palimnex:ontology-promotion-evidence:v1 with gates and promotable/held status, never authorizing activation. Follow INFLUENCE_SPEC.md.",
        "checks": [f"{PY} -m unittest palimnex.tests.test_ontology_promotion -v", mypy("palimnex/ontology_promotion.py")],
    },
    INTEG: {
        "owned": ["palimnex/core.py", "palimnex/tests/test_ontology_influence_cli.py", "pyproject.toml", "palimnex/CHANGELOG.md",
                  "docs/COMPATIBILITY.md", "docs/CONCEPT_REGISTRY.md", f"{PP}/integration"],
        "objective": "Coordinator-owned serial integration: explain-search v2 when influenced, the read-only evaluate-ontology-promotion and ontology-status commands with tests, mypy list, CHANGELOG, COMPATIBILITY, the activation note in docs/CONCEPT_REGISTRY.md; ownership audit, reindex and the full gate. Not delegated.",
        "checks": [f"{PY} -m unittest discover -s palimnex/tests -p 'test_*.py'", f"{PY} -m mypy", "python3 palimnex.py index",
                   "python3 palimnex.py validate --deep", "python3 palimnex.py evaluate --limit 5",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "python3 palimnex.py ledger-status",
                   "python3 palimnex.py evaluate-ontology-shadow", "python3 palimnex.py ontology-status"],
    },
}
EDGES = [{"from": GATE, "to": RETRIEVAL}, {"from": RETRIEVAL, "to": PROMOTION}, {"from": SCHEMAS, "to": PROMOTION},
         {"from": GATE, "to": INTEG}, {"from": SCHEMAS, "to": INTEG}, {"from": RETRIEVAL, "to": INTEG},
         {"from": PROMOTION, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "With ontology_influence missing, off or shadow, every existing output (retrieve_sources, context v1, explain-search v1, search) stays byte-identical.",
    "Never enable influence on the owner's behalf: do not edit .palimnex.json or write any promotion evidence into the repository.",
    "Cache-backed search, symbols, impact and palimnex evaluate are unchanged.",
    "Do not create or populate ontology/concept-registry.v1.json or any approved registry.",
    "No silent fallback: an enabled setting that cannot be activated is an explicit typed error.",
    "No change to any existing identifier, schema, frozen fixture or test expectation except where a task card owns the file.",
    "No runtime dependency: runtime modules use only the standard library and palimnex modules.",
    "No Git staging, commits, branches or pushes; no network, installs, model or provider calls.",
    "No palimnex index, remember, session, capture, retention, migration, erasure or pack commands; no Redis or SQLite writes.",
    "Never read or echo credentials; never store literal secret-pattern strings.",
]


def receipt(ws: str) -> str:
    return f"{PP}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{b1.VALIDATOR} {PP}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    base = {DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml", "docs", "palimnex",
            ".agents/skills", "artifacts/design/ontology-phase-0", "artifacts/ontology/phase-0",
            "artifacts/ontology/phase-1", "artifacts/ontology/phase-2", P3, f"{PP}/briefs", f"{PP}/tasks",
            f"{PP}/approval-evidence.json", f"{PP}/manifest.json"}
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 3,
        "action_id": "ontology_phase_3_shadow", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": sorted(base - set(owned(ws))), "forbidden_paths": FORBIDDEN,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 3,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "missing, off or shadow setting: retrieve_sources, context v1, explain-search v1 and search byte-identical to the committed code",
            "enabled setting activates only with an approved, project-matching, unambiguous, current registry and matching promotion evidence; every failure is a typed error, never a fallback",
            "influenced results disclose ontology influence and use context v2 and explain-search v2",
            "promotion evidence covers the local and cache backends; status promotable only when every gate holds on both; activation never authorized by the report",
            "cache-backed search and palimnex evaluate unchanged (production sentinel)",
            "focused tests and strict mypy pass; receipts validate; ownership audit clean; independent review per workstream",
            "full suite (unsandboxed), standard gate, deep validation, evaluations and ledger status pass; no ledger writes",
        ],
        "authority_limits": [
            "influence promotion under the Phase 3 action; no activation on the owner's behalf; Phase 4 runs as a separate program",
            "no network, provider, model, Git-write or live-state authority for any lane",
            "no approved registry created; no change to search, symbols, impact or palimnex evaluate",
            "Codex lanes run with approval_policy=never inside workspace-write; the coordinator runs socket tests unsandboxed",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("design changed since the Phase 3 exit gate; stopping")
    (b1.ROOT / DESIGN).write_text(build_design(), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    log.info("design updated: sha256=%s", design["sha256"])
    promotion_evidence = approval(design["sha256"], 3)
    write_json(f"{PP}/approval-evidence.json", promotion_evidence)
    write_json(f"{P4}/approval-evidence.json", approval(design["sha256"], 4))
    plan = manifest(design)
    write_json(f"{PP}/manifest.json", plan)
    tasks = [task(ws, design, promotion_evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{PP}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(promotion_evidence)
    write_json(f"{PP}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
