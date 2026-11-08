#!/usr/bin/env python3
"""One-shot: write and validate the closure integration receipt from files on disk."""
from __future__ import annotations

import json
import re
import subprocess

P = "artifacts/ontology/closure"
WS = "ontology-closure-integration"
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"
GATE = f"{P}/integration/gate.log"


def gate_steps() -> dict[str, int]:
    text = open(GATE, encoding="utf-8").read()
    return {name: int(code) for name, code in re.findall(r"^== (.+)\n(?:.*\n)*?exit=(\d+)$", text, flags=re.M)}


def fact(pattern: str) -> str:
    match = re.search(pattern, open(GATE, encoding="utf-8").read(), flags=re.M)
    if not match:
        raise SystemExit(f"gate.log lacks {pattern!r}")
    return match.group(0)


def main() -> int:
    steps = gate_steps()
    if any(code != 0 for code in steps.values()):
        raise SystemExit(f"gate steps failed: {steps}")
    task = json.load(open(f"{P}/tasks/{WS}.json"))
    bv = json.load(open(f"{P}/integration/bundle-validation.json"))
    freeze = json.load(open(f"{P}/integration/registry-freeze.json"))
    evidence = json.load(open(f"{P}/integration/promotion-evidence.json"))
    review = json.load(open(f"{P}/reviews/ontology-closure-registry.review-receipt.json"))
    status = json.load(open(f"{P}/integration/ontology-status.json"))
    cohort = evidence["backends"]["local"]["suites"]["cohort"]
    git = [l for l in subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout.split("\n") if l]
    receipt = {
        "schema": "palimnex:ontology-implementation-receipt:v1", "workstream_id": WS,
        "design_identity": task["approved_design_identity"], "task_digest": bv["task_digests"][WS],
        "approval_evidence_digest": bv["approval_evidence_digest"],
        "owned_scope": task["owned_paths"], "files_changed": task["owned_paths"],
        "dependencies_consumed": [f"{P}/receipts/ontology-closure-registry.implementation-receipt.json",
                                  f"{P}/reviews/ontology-closure-registry.review-receipt.json",
                                  f"{P}/integration/registry-freeze.json"],
        "commands": [
            {"command": f"./.venv/bin/python {P}/tools/approve_registry.py", "exit_code": 0,
             "result": f"froze the candidate (review status {review['status']}) and wrote {freeze['approved']['path']} "
                       f"(registry digest {freeze['approved']['registry_digest']}, {freeze['approved']['concept_count']} concepts); "
                       "only registry_kind, concept status and the recomputed registry_digest changed"},
            {"command": "python3 palimnex.py evaluate-ontology-promotion", "exit_code": 0,
             "result": f"status {evidence['status']}; every gate true on the local and cache backends; ontology cohort "
                       f"{cohort['baseline']['cases_passed']} -> {cohort['influenced']['cases_passed']} passing cases, "
                       f"critical {cohort['baseline']['critical_pass_count']} -> {cohort['influenced']['critical_pass_count']}; "
                       f"v27 and challenges_v26 rankings unchanged; activation_authorized {evidence['activation_authorized']} "
                       f"({P}/integration/promotion-evidence.json)"},
            {"command": "python3 palimnex.py ontology-status", "exit_code": 0,
             "result": f"mode {status['mode']}, activation {status['activation']}, retrieval_influence {status['retrieval_influence']}"},
            {"command": "./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'", "exit_code": 0,
             "result": f"{fact(r'^Ran \d+ tests in [0-9.]+s')} {fact(r'^OK \(skipped=\d+\)')}, unsandboxed; the skip is "
                       "test_explain_search.test_cli_on_repository_without_registry, which skips by design now that the "
                       f"repository carries an approved registry ({GATE})"},
            {"command": "./.venv/bin/python -m mypy", "exit_code": 0, "result": fact(r"^Success: no issues found in \d+ source files")},
            {"command": "index, validate --deep, evaluate, ledger-status, evaluate-ontology-shadow, status", "exit_code": 0, "result": "all exit 0 (gate.log)"},
            {"command": 'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "exit_code": 0, "result": "standard gate passed (gate.log)"},
            {"command": 'python3 palimnex.py explain-search "how does reciprocal rank fusion combine retrieval channels" --limit 3', "exit_code": 0,
             "result": "coverage status answerable with the approved registry (gate.log)"},
            {"command": "git diff --exit-code -- palimnex/retrieval.py palimnex/durable.py palimnex/semantic.py palimnex/cache_v3.py palimnex/ontology_influence.py palimnex/ontology_shadow.py palimnex/concepts.py palimnex/experience.py", "exit_code": 0, "result": "unchanged against HEAD"},
            {"command": f"./.venv/bin/python {P}/candidate/check_candidate.py", "exit_code": 0, "result": "45/45 bindings current, 61 aliases, no collisions"},
        ],
        "compatibility_effect": "Adds the reviewed approved registry ontology/concept-registry.v1.json (not indexed). explain-search now reports coverage against it by default. Ontology influence stays off (.palimnex.json unchanged). No runtime module, schema or identifier changes in this workstream. Release-level coordinator changes made alongside (reviewed separately): CHANGELOG registry entry, docs/CONCEPT_REGISTRY.md and docs/ONTOLOGY_ADOPTION.md closure text, R18 re-pin of three frozen registry test fixtures, and palimnex/tests/test_ontology_promotion.py now exercising the real-checkout missing-registry refusal through an explicit absent path.",
        "privacy_and_authority_checks": [
            "no Git writes by lanes; coordinator Git writes only on the release branch after review",
            "registry drafted and reviewed blind to the evaluation sets; the evaluation set was first used after the freeze",
            "activation off: .palimnex.json not edited; promotion evidence is evidence only",
            "no real ledger writes; Redis already running and left as found",
        ],
        "integration_patch_proposals": [],
        "unresolved_risks": [
            "The approved registry becomes approval when the owner merges the reviewed release branch; until then it is a reviewed proposal",
            "Every binding records its whole file's version: any edit to one of the bound runtime files marks that concept stale until re-pinned (documented in docs/CONCEPT_REGISTRY.md); the same holds for the README.md and docs/DESIGN.md test fixtures (R18)",
            "Registry review limit: alias 'candidate approved registry parser' is accurate but awkward (MINOR, accepted)",
            "The promotion evidence binds the current implementation digest; any change to the influence-covered modules invalidates it before activation",
        ],
        "cache_and_ledger_state": {"cache_consulted": True, "index_fresh_at_gate": True, "redis_final_state": "running (as found)", "real_ledger_written": False},
        "git_state": {"head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(), "staged": [], "status": git},
        "status": "tested",
    }
    out = f"{P}/receipts/{WS}.implementation-receipt.json"
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
    res = subprocess.run(["./.venv/bin/python", VALIDATOR, f"{P}/tasks/{WS}.json", "--implementation-receipt", out], capture_output=True, text=True)
    print("integration receipt:", "valid" if res.returncode == 0 else (res.stdout + res.stderr)[-400:])
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
