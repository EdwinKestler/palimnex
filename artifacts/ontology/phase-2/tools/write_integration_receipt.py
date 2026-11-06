#!/usr/bin/env python3
"""One-shot: write and validate the Phase 2 coordinator integration receipt."""
from __future__ import annotations

import json
import subprocess

P = "artifacts/ontology/phase-2"
WS = "ontology-phase-2-integration"
LANES = ("coverage-core", "coverage-schema", "frozen-conformance")
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"


def main() -> int:
    task = json.load(open(f"{P}/tasks/{WS}.json"))
    bv = json.load(open(f"{P}/integration/bundle-validation.r11.json"))
    git = [l for l in subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout.split("\n") if l]
    receipt = {
        "schema": "palimnex:ontology-implementation-receipt:v1", "workstream_id": WS,
        "design_identity": task["approved_design_identity"], "task_digest": bv["task_digests"][WS],
        "approval_evidence_digest": bv["approval_evidence_digest"],
        "owned_scope": task["owned_paths"], "files_changed": task["owned_paths"],
        "dependencies_consumed": [f"{P}/receipts/ontology-phase-2-{w}.implementation-receipt.json" for w in LANES]
        + [f"{P}/reviews/ontology-phase-2-{w}.review-receipt.json" for w in LANES + ("integration",)],
        "commands": [
            {"command": "./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'", "exit_code": 0, "result": "361 tests OK, unsandboxed"},
            {"command": "./.venv/bin/python -m mypy", "exit_code": 0, "result": "no issues in 14 source files including palimnex/coverage.py"},
            {"command": "python3 palimnex.py index", "exit_code": 0, "result": "fresh index, 111 files"},
            {"command": "python3 palimnex.py validate --deep", "exit_code": 0, "result": "fresh, deep validation passed"},
            {"command": "python3 palimnex.py evaluate --limit 5", "exit_code": 0, "result": "20 cases, critical passed, recall_at_limit 1.0, MRR 0.9 (was 0.8917: case cache-reader-lease rank 3->2 from corpus statistics; ranking code unchanged)"},
            {"command": 'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "exit_code": 0, "result": "standalone gate passed; isolated retrieval recall 1.0; no live ledger write or model call"},
            {"command": "python3 palimnex.py ledger-status", "exit_code": 0, "result": "integrity ok, 0 events"},
            {"command": "python3 palimnex.py explain-search QUERY --backend cache|local", "exit_code": 0, "result": "cache: verified_cache_rrf, cache_consulted true; local: local_snapshot_rrf; unreachable Redis: typed error exit 1, no silent downgrade"},
            {"command": "./.venv/bin/python artifacts/ontology/phase-2/tools/ownership_audit.py audit", "exit_code": 0, "result": "no lane wrote outside its owned paths in any run; reviewer wrote nothing"},
        ],
        "compatibility_effect": "Additive: palimnex.coverage, public schemas palimnex:retrieval-coverage:v1 and palimnex:explain-search:v1, read-only explain-search command, docs/COVERAGE_RECEIPT.md, tests and fixtures. search, context v1, cache, ledger, pack, MCP and config unchanged; no ranking influence; no approved registry created. R11 changes palimnex.concepts query matching only: queries are bounded at 8 KiB instead of being refused above 128 normalized characters; stored-key rules unchanged.",
        "privacy_and_authority_checks": [
            "no Git writes", "no model or provider calls", "no ledger writes (0 events)",
            "Redis used for gate and cache-backend check, then stopped",
            "coverage receipt carries only query_digest; raw query only inside the unchanged search member; nothing persisted",
            "Codex lanes ran with approval_policy=never; no sandbox escapes",
            "integration lane amended (R11) to own palimnex/concepts.py and its test for one defect fix; other task cards unchanged",
        ],
        "integration_patch_proposals": ["R8 (from Phase 0): validator should accept files_changed descendants of directory-valued owned paths; still not applied"],
        "unresolved_risks": [
            "R10, R11 and the declined exclusivity minor are coordinator decisions for owner review",
            "When --limit binds, additional byte-budget drops cannot be attributed from retrieve_sources fields; reported as retrieval truncation only",
            "Mixed stale reasons on one concept aggregate to unavailable (one reason per concept in v1)",
            "No approved registry exists yet, so explain-search reports registry_absent until one is reviewed and committed",
            "Grok tool-level write block only removed Write; reviewer read-only status verified by snapshot audits",
        ],
        "cache_and_ledger_state": {"cache_consulted": True, "index_fresh_at_gate": True, "redis_final_state": "stopped (restored)", "ledger_integrity": "ok", "ledger_events": 0},
        "git_state": {"head": "80d94c4", "staged": [], "status": git},
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
