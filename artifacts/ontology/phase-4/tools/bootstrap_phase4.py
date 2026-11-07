#!/usr/bin/env python3
"""One-shot Phase 4 bootstrap: manifest and task cards for the semantic shadow experiment.

Reuses the approval evidence written on 2026-11-06 (owner message 16:46) and
checks that the approved design is unchanged since then. No Git, network,
Redis or ledger activity.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-1/tools"))
import bootstrap_phase1 as b1  # noqa: E402

vc, sha, write_json = b1.vc, b1.sha, b1.write_json
log = logging.getLogger("bootstrap_phase4")
DESIGN, PROPOSAL = b1.DESIGN, b1.PROPOSAL
P4 = "artifacts/ontology/phase-4"
EXPECTED_DESIGN_SHA = "bee8ea6dff05ad2dc3371868ec66e9be9aa8218d25c5d758aa0aefdcaf4ec8a3"
PY = "./.venv/bin/python"
PROVIDER, COHORT, CHANNEL, EVAL, INTEG = (
    "ontology-phase-4-provider",
    "ontology-phase-4-cohort",
    "ontology-phase-4-channel",
    "ontology-phase-4-evaluation",
    "ontology-phase-4-integration",
)


def mypy(*paths: str) -> str:
    return (f"{PY} -m mypy --python-version 3.11 --follow-imports=silent --check-untyped-defs "
            "--disallow-untyped-defs " + " ".join(paths))


def unit(*modules: str) -> str:
    return f"{PY} -m unittest " + " ".join(f"palimnex.tests.{m}" for m in modules)


REGRESSION = unit("test_semantic", "test_retrieval_shadow", "test_retrieval_influence", "test_ontology_shadow")
LANES: dict[str, dict] = {
    PROVIDER: {
        "owned": ["palimnex/semantic_local.py", "palimnex/tests/test_semantic_local.py",
                  "palimnex/tests/semantic_doubles.py", "palimnex/schemas/semantic-provider-identity.v1.schema.json"],
        "objective": "Implement palimnex/semantic_local.py: the deterministic in-process HashedEmbeddingProvider over core.embedding with a distinct provider id, revision, dimensions and behavioural implementation digest; provider_identity, identity_digest and checked_embed with typed refusals for invalid input, failures, timeouts, count, vector, dimension and non-finite errors; test doubles in palimnex/tests/semantic_doubles.py; the identity schema; tests. Follow SEMANTIC_SPEC.md section 1.",
        "checks": [unit("test_semantic_local") + " -v", mypy("palimnex/semantic_local.py"), REGRESSION],
    },
    COHORT: {
        "owned": ["palimnex/evaluation/semantic-shadow.v1.json", "palimnex/schemas/semantic-shadow-cohort.v1.schema.json",
                  "palimnex/tests/test_semantic_cohort.py"],
        "objective": "Write the frozen semantic cohort palimnex/evaluation/semantic-shadow.v1.json (paraphrase, synonym, ambiguity, negative and control repository cases; drift and privacy-canary project cases with runtime canary placeholders) blind, without running retrieval or embeddings; its JSON Schema; structural tests. Follow SEMANTIC_SPEC.md section 3.",
        "checks": [unit("test_semantic_cohort") + " -v", unit("test_ontology_shadow_cohort")],
    },
    CHANNEL: {
        "owned": ["palimnex/semantic_shadow.py", "palimnex/tests/test_semantic_shadow.py",
                  "palimnex/schemas/semantic-shadow-comparison.v1.schema.json"],
        "objective": "Implement palimnex/semantic_shadow.py: the R14 semantic channel (cosine over provider vectors, strict positive floor, top 64, abstention suppression, query privacy scan before any provider call, content-keyed in-process memo), semantic_shadow_retrieve returning the byte-identical uninfluenced baseline beside a palimnex:semantic-shadow-comparison:v1 document, its validator and schema; tests. palimnex/retrieval.py is not edited. Follow SEMANTIC_SPEC.md section 2.",
        "checks": [unit("test_semantic_shadow") + " -v", mypy("palimnex/semantic_shadow.py"), REGRESSION + " palimnex.tests.test_semantic_local"],
    },
    EVAL: {
        "owned": ["palimnex/semantic_eval.py", "palimnex/tests/test_semantic_eval.py",
                  "palimnex/schemas/semantic-shadow-evaluation.v1.schema.json", "docs/SEMANTIC_SHADOW.md"],
        "objective": "Implement palimnex/semantic_eval.py: evaluate_semantic_shadow over the protected suites (v27, challenges_v26, Phase 3 cohort), the frozen semantic cohort (pinned digest), drift and privacy-canary project cases, with the owner's Phase 4 gates and thresholds, the R15 benchmark protocol and the palimnex:semantic-shadow-evaluation:v1 report (promotable or held, never promotion); schema, tests and docs/SEMANTIC_SHADOW.md. Follow SEMANTIC_SPEC.md section 4.",
        "checks": [unit("test_semantic_eval") + " -v", mypy("palimnex/semantic_eval.py"),
                   unit("test_semantic_shadow", "test_semantic_cohort", "test_semantic_local", "test_ontology_shadow_cohort")],
    },
    INTEG: {
        "owned": ["palimnex/core.py", "palimnex/tests/test_semantic_cli.py", "pyproject.toml", "palimnex/CHANGELOG.md",
                  "docs/COMPATIBILITY.md", f"{P4}/integration"],
        "objective": "Coordinator-owned serial integration: the read-only evaluate-semantic-shadow command (exit 0 promotable, 2 held, 1 refused) with tests, mypy list, CHANGELOG, COMPATIBILITY; cohort freeze record; ownership audit, reindex, the full unsandboxed gate and the real-repository evaluation run. Not delegated.",
        "checks": [f"{PY} -m unittest discover -s palimnex/tests -p 'test_*.py'", f"{PY} -m mypy", "python3 palimnex.py index",
                   "python3 palimnex.py validate --deep", "python3 palimnex.py evaluate --limit 5",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "python3 palimnex.py ledger-status",
                   "python3 palimnex.py evaluate-ontology-shadow", "python3 palimnex.py ontology-status",
                   "python3 palimnex.py semantic-status", "python3 palimnex.py evaluate-semantic-shadow"],
    },
}
EDGES = [{"from": PROVIDER, "to": CHANNEL}, {"from": CHANNEL, "to": EVAL}, {"from": COHORT, "to": EVAL},
         {"from": PROVIDER, "to": INTEG}, {"from": COHORT, "to": INTEG}, {"from": CHANNEL, "to": INTEG},
         {"from": EVAL, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "palimnex/retrieval.py, palimnex/semantic.py and every existing output (retrieve_sources, context v1/v2, explain-search v1/v2, search, symbols, impact, palimnex evaluate, semantic-status, semantic-gate) stay byte-identical.",
    "Phase 4 is evidence only: no retrieval influence, no promotion, no configuration key, no change to project-memory:semantic-provider:v1 or its +0.05/2x helper.",
    "No model download, package installation, network access, subprocess provider or persistent vector store; the memo is in-process only.",
    "The frozen cohort is written blind and, once frozen, never changed; thresholds and R14/R15 parameters are never tuned.",
    "No silent fallback: provider errors and privacy refusals are typed errors.",
    "No change to any existing identifier, schema, frozen fixture or test expectation except where a task card owns the file.",
    "No runtime dependency: runtime modules use only the standard library and palimnex modules.",
    "No Git staging, commits, branches or pushes; no network, installs, model or provider calls beyond the in-process hashed provider and test doubles.",
    "No palimnex index, remember, session, capture, retention, migration, erasure or pack commands; no Redis or SQLite writes.",
    "Never read or echo credentials; never store literal secret-pattern strings; canaries are built at runtime.",
]


def receipt(ws: str) -> str:
    return f"{P4}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{b1.VALIDATOR} {P4}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    base = {DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml", "docs", "palimnex",
            ".agents/skills", "artifacts/design/ontology-phase-0", "artifacts/ontology/phase-0",
            "artifacts/ontology/phase-1", "artifacts/ontology/phase-2", "artifacts/ontology/phase-3",
            "artifacts/ontology/phase-3-promotion", f"{P4}/briefs", f"{P4}/tasks", f"{P4}/approval-evidence.json",
            f"{P4}/manifest.json"}
    if ws != INTEG:
        base.add(f"{P4}/integration")
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 4,
        "action_id": "ontology_phase_4_semantic", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": sorted(base - set(owned(ws))), "forbidden_paths": FORBIDDEN,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 4,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "retrieval.py, semantic.py and every production output byte-identical; semantic shadow baseline equals retrieve_sources(influence='off')",
            "provider identity (id, revision, dimensions, implementation digest) bound; provider failures, timeouts, malformed dimensions and NaN/Inf refused with typed errors",
            "frozen semantic cohort written blind, reviewed and digest-pinned before any semantic measurement",
            "owner thresholds: no critical or per-case regression; protected Recall@5 not reduced; +0.02 MRR or Recall@5 and at least one more passing case on the cohort; p95 <= 1.5x paired baseline (R15); no new forbidden hits; abstention, ambiguity, drift and privacy-canary gates; deterministic",
            "a promotable report is not promotion; held is a valid outcome and thresholds are never weakened",
            "focused tests and strict mypy pass; receipts validate; ownership audit clean; independent review per workstream",
            "full suite (unsandboxed), standard gate, deep validation, evaluations and ledger status pass; no ledger writes",
        ],
        "authority_limits": [
            "Phase 4 action only; no promotion of the provider, no retrieval influence, no configuration change",
            "no network, model download, install, provider service, Git-write or live-state authority for any lane",
            "no change to search, symbols, impact, palimnex evaluate, retrieve_sources or project-memory:semantic-provider:v1",
            "Codex lanes run with approval_policy=never inside workspace-write; the coordinator runs socket tests unsandboxed",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("design changed since the Phase 4 approval was recorded; stopping")
    evidence = json.loads((b1.ROOT / P4 / "approval-evidence.json").read_text(encoding="utf-8"))
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    if evidence["design_identity"] != design or evidence["approved_phases"] != [4]:
        raise SystemExit("approval evidence does not bind the current design and Phase 4; stopping")
    plan = manifest(design)
    write_json(f"{P4}/manifest.json", plan)
    tasks = [task(ws, design, evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{P4}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{P4}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
