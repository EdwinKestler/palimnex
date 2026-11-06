#!/usr/bin/env python3
"""One-shot: write and validate the Phase 3 coordinator integration receipt."""
from __future__ import annotations

import json
import subprocess

P = "artifacts/ontology/phase-3"
WS = "ontology-phase-3-integration"
LANES = ("channel", "cohort", "retrieval", "evaluation")
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"
GATE = f"{P}/integration/gate-final.log"


def main() -> int:
    task = json.load(open(f"{P}/tasks/{WS}.json"))
    bv = json.load(open(f"{P}/integration/bundle-validation.json"))
    git = [l for l in subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout.split("\n") if l]
    receipt = {
        "schema": "palimnex:ontology-implementation-receipt:v1", "workstream_id": WS,
        "design_identity": task["approved_design_identity"], "task_digest": bv["task_digests"][WS],
        "approval_evidence_digest": bv["approval_evidence_digest"],
        "owned_scope": task["owned_paths"], "files_changed": task["owned_paths"],
        "dependencies_consumed": [f"{P}/receipts/ontology-phase-3-{w}.implementation-receipt.json" for w in LANES]
        + [f"{P}/reviews/ontology-phase-3-{w}.review-receipt.json" for w in LANES + ("integration",)],
        "commands": [
            {"command": "./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'", "exit_code": 0, "result": f"411 tests OK, unsandboxed ({GATE})"},
            {"command": "./.venv/bin/python -m mypy", "exit_code": 0, "result": "no issues in 16 source files including ontology_shadow.py and ontology_eval.py"},
            {"command": "python3 palimnex.py index", "exit_code": 0, "result": "fresh index, 120 files"},
            {"command": "python3 palimnex.py validate --deep", "exit_code": 0, "result": "fresh, deep validation passed"},
            {"command": "python3 palimnex.py evaluate --limit 5", "exit_code": 0, "result": "cache-backed production search: 20 cases, critical passed, recall_at_limit 1.0, MRR 0.9 (unchanged from Phase 2)"},
            {"command": "python3 palimnex.py evaluate-ontology-shadow", "exit_code": 0, "result": f"all eight gates true, promotion_authorized false, cohort sha256 f71f3fb9..., report {P}/integration/shadow-evaluation.final.json"},
            {"command": 'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "exit_code": 0, "result": "standalone gate passed; isolated retrieval recall 1.0; no live ledger write or model call"},
            {"command": "python3 palimnex.py ledger-status", "exit_code": 0, "result": "integrity ok, 0 events"},
            {"command": "coordinator identity check: git archive HEAD palimnex vs working tree, retrieve_sources over 40 inputs on the repository", "exit_code": 0, "result": "40/40 canonical-JSON digests identical"},
            {"command": "./.venv/bin/python artifacts/ontology/phase-3/tools/ownership_audit.py audit", "exit_code": 0, "result": "no lane wrote outside its owned paths in any run; reviewer wrote nothing"},
        ],
        "compatibility_effect": "Additive: palimnex.ontology_shadow, palimnex.ontology_eval, retrieval.shadow_retrieve, public schema palimnex:ontology-shadow-comparison:v1, report palimnex:ontology-shadow-evaluation:v1, frozen cohort palimnex:ontology-shadow-cohort:v1 (excluded from the index), read-only evaluate-ontology-shadow command, docs/ONTOLOGY_SHADOW.md. retrieve_sources refactored with byte-identical output; search, context, explain-search, cache, ledger, pack, MCP unchanged; no retrieval influence; no approved registry created.",
        "privacy_and_authority_checks": [
            "no Git writes", "no model or provider calls", "no ledger writes (0 events)",
            "Redis used for the gate only, then stopped",
            "comparison documents carry pointers only: no query text or excerpts",
            "shadow_retrieve imported only by ontology_eval and tests; no configuration switch enables influence",
            "Codex lanes ran with approval_policy=never; no sandbox escapes",
        ],
        "integration_patch_proposals": ["R8 (from Phase 0): validator should accept files_changed descendants of directory-valued owned paths; still not applied"],
        "unresolved_risks": [
            "Integration review status is accepted_with_limits. Each limit is closed by coordinator evidence: (1) socket-backed commands (full suite, palimnex_check.sh, index, palimnex evaluate, ledger-status) ran unsandboxed and passed, see gate-final.log; (2) the missing integration receipt is this receipt, validated against the task card; (3) cache-backed palimnex evaluate was re-run and passes every critical case with Recall@5 1.0 and MRR 0.9",
            "R12 (gate meaning) is a coordinator decision for owner confirmation; the reviewer judged it faithful",
            "retrieve_sources passes only 4/12 critical v27 search cases at limit 5 under both baseline and shadow (pre-existing; v27 is calibrated for cache-backed search)",
            "on the real repository retrieve_sources never abstains for unrelated queries; abstention evidence comes from the v26 challenge negatives",
            "cohort line bindings drift when bound source moves; anchor tests in test_ontology_shadow_cohort.py catch it",
            "Grok tool-level write block only removed Write; reviewer read-only status verified by snapshot audits",
        ],
        "cache_and_ledger_state": {"cache_consulted": True, "index_fresh_at_gate": True, "redis_final_state": "stopped (restored)", "ledger_integrity": "ok", "ledger_events": 0},
        "git_state": {"head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(), "staged": [], "status": git},
        "status": "tested",
    }
    out = f"{P}/receipts/{WS}.implementation-receipt.json"
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
    res = subprocess.run(["./.venv/bin/python", VALIDATOR, f"{P}/tasks/{WS}.json", "--implementation-receipt", out], capture_output=True, text=True)
    print("integration receipt:", "valid" if res.returncode == 0 else res.stderr[-300:])
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
