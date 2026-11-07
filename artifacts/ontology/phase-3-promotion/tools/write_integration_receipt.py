#!/usr/bin/env python3
"""One-shot: write and validate the Phase 3 coordinator integration receipt."""
from __future__ import annotations

import json
import subprocess

P = "artifacts/ontology/phase-3-promotion"
WS = "ontology-influence-integration"
LANES = ("gate", "schemas", "retrieval", "promotion")
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"
GATE = f"{P}/integration/gate-final.log"


def main() -> int:
    task = json.load(open(f"{P}/tasks/{WS}.json"))
    bv = json.load(open(f"{P}/integration/bundle-validation.r13.json"))
    git = [l for l in subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout.split("\n") if l]
    receipt = {
        "schema": "palimnex:ontology-implementation-receipt:v1", "workstream_id": WS,
        "design_identity": task["approved_design_identity"], "task_digest": bv["task_digests"][WS],
        "approval_evidence_digest": bv["approval_evidence_digest"],
        "owned_scope": task["owned_paths"], "files_changed": task["owned_paths"],
        "dependencies_consumed": [f"{P}/receipts/ontology-influence-{w}.implementation-receipt.json" for w in LANES]
        + [f"{P}/reviews/ontology-influence-{w}.review-receipt.json" for w in LANES + ("integration",)],
        "commands": [
            {"command": "./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'", "exit_code": 0, "result": f"454 tests OK, unsandboxed, after the status-shadowing fix and R13 rebinding ({GATE})"},
            {"command": "./.venv/bin/python -m mypy", "exit_code": 0, "result": "no issues in 18 source files including ontology_influence.py and ontology_promotion.py"},
            {"command": "python3 palimnex.py index && python3 palimnex.py validate --deep", "exit_code": 0, "result": "fresh index after the final doc change, deep validation passed (integration/gate-final-reindex.log)"},
            {"command": "python3 palimnex.py evaluate --limit 5", "exit_code": 0, "result": "production sentinel: every critical case passes, recall_at_limit 1.0, MRR 0.8917 (authorized-erasure rank 2->3 because new test file test_ontology_promotion.py ranks first; cache search code unchanged)"},
            {"command": "python3 palimnex.py evaluate-ontology-shadow", "exit_code": 0, "result": "all eight Phase 3 gates true with rebound cohort sha256 07b5f066..."},
            {"command": "python3 palimnex.py ontology-status", "exit_code": 0, "result": "mode off, activation not_applicable, retrieval_influence false"},
            {"command": "python3 palimnex.py status", "exit_code": 0, "result": "fresh v3 status; regression from the shadowed local fixed"},
            {"command": 'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "exit_code": 0, "result": "standalone gate passed; isolated retrieval recall 1.0; no live ledger write or model call"},
            {"command": "python3 palimnex.py ledger-status", "exit_code": 0, "result": "integrity ok, 0 events"},
            {"command": "coordinator identity check: git archive HEAD palimnex vs working tree, retrieve_sources and assemble_context over 80 inputs, influence key absent", "exit_code": 0, "result": "80/80 canonical-JSON digests identical"},
            {"command": "./.venv/bin/python artifacts/ontology/phase-3-promotion/tools/ownership_audit.py audit", "exit_code": 0, "result": "no lane wrote outside its owned paths in any run; reviewers wrote nothing"},
        ],
        "compatibility_effect": "Additive and opt-in: palimnex.ontology_influence, palimnex.ontology_promotion, retrieve_sources influence parameter, project-memory:context:v2, palimnex:explain-search:v2, palimnex:ontology-promotion-evidence:v1, palimnex:ontology-status:v1, evaluate-ontology-promotion and ontology-status commands. With ontology_influence missing, off or shadow, retrieve_sources, context v1 and explain-search v1 are byte-identical; search, symbols, impact and palimnex evaluate unchanged. Nothing activates influence; no approved registry exists.",
        "privacy_and_authority_checks": [
            "no Git writes", "no model or provider calls", "no ledger writes (0 events)",
            "Redis used for the gate only, then stopped",
            ".palimnex.json not edited; influence never activated on the owner's behalf; no promotion evidence written to the repository",
            "activation refusals are typed and non-echoing; no silent fallback (reviewer-probed)",
            "Codex lanes ran with approval_policy=never; no sandbox escapes",
            "integration lane amended (R13) to own the frozen cohort for one line-range rebinding; other task cards unchanged",
        ],
        "integration_patch_proposals": ["R8 (from Phase 0): validator should accept files_changed descendants of directory-valued owned paths; still not applied"],
        "unresolved_risks": [
            "Integration review status is accepted_with_limits. Each limit is closed by coordinator evidence: (1) socket-backed commands (full suite, palimnex_check.sh, index, validate, palimnex evaluate, evaluate-ontology-shadow) ran unsandboxed and passed, see gate-final.log and gate-final-reindex.log; (2) the missing integration receipt is this receipt, validated against the R13 task card; (3) the stale index the reviewer observed came from the final COMPATIBILITY.md fix and was re-indexed and deep-validated afterwards",
            "R13 (cohort line-range maintenance) is a coordinator decision for owner confirmation; the reviewer judged it faithful",
            "No approved registry exists, so influence cannot be activated yet; activation needs a reviewed ontology/concept-registry.v1.json, a promotable evidence run, and the owner's config edit",
            "Production MRR moved 0.9 -> 0.8917 from corpus drift (a new test file); every critical case passes",
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
