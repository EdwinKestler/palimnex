#!/usr/bin/env python3
"""One-shot: write and validate the Phase 5 coordinator integration receipt from files on disk."""
from __future__ import annotations

import json
import re
import subprocess

P = "artifacts/ontology/phase-5"
WS = "ontology-phase-5-integration"
LANES = ("feedback-core", "feedback-schemas")
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"
GATE = f"{P}/integration/gate.log"
COORDINATOR_RECORDS = (f"{P}/prompts/", f"{P}/reviews/", f"{P}/round-", f"{P}/tools/", f"{P}/integration/",
                       f"{P}/briefs/", f"{P}/manifest.json", f"{P}/tasks/ontology-phase-5-integration.json")
AUDITS = ("ownership-audit.lanes.json", "ownership-audit.integration.json")


def gate_steps() -> dict[str, int]:
    text = open(GATE, encoding="utf-8").read()
    steps = re.findall(r"^== (.+)\n(?:.*\n)*?exit=(\d+)$", text, flags=re.M)
    return {name: int(code) for name, code in steps}


def gate_fact(pattern: str) -> str:
    match = re.search(pattern, open(GATE, encoding="utf-8").read(), flags=re.M)
    if not match:
        raise SystemExit(f"gate.log lacks {pattern!r}")
    return match.group(0)


def audit_commands() -> list[dict]:
    entries = []
    for name in AUDITS:
        report = json.load(open(f"{P}/integration/{name}", encoding="utf-8"))
        paths = [v["path"] for v in report["violations"]]
        foreign = [p for p in paths if not p.startswith(COORDINATOR_RECORDS)]
        if foreign:
            raise SystemExit(f"{name}: violation outside coordinator records: {foreign}")
        lanes = sorted(report["changed_by_lane"])
        result = (f"status {report['status']}; changes by {', '.join(lanes)} stayed inside owned paths; "
                  + (f"unowned paths are coordinator records only: {', '.join(paths)}" if paths else "no unowned path"))
        entries.append({"command": f"./.venv/bin/python {P}/tools/ownership_audit.py audit > {P}/integration/{name}",
                        "exit_code": 1 if paths else 0, "result": result})
    return entries


def main() -> int:
    steps = gate_steps()
    failed = {k: v for k, v in steps.items() if v != 0}
    if failed:
        raise SystemExit(f"gate steps failed: {failed}")
    task = json.load(open(f"{P}/tasks/{WS}.json"))
    bv = json.load(open(f"{P}/integration/bundle-validation.r16.json"))
    git = [l for l in subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout.split("\n") if l]
    tests = gate_fact(r"^Ran \d+ tests in [0-9.]+s")
    mypy = gate_fact(r"^Success: no issues found in \d+ source files")
    experience = gate_fact(r"^\d+\t\d+\tpalimnex/experience\.py$")
    receipt = {
        "schema": "palimnex:ontology-implementation-receipt:v1", "workstream_id": WS,
        "design_identity": task["approved_design_identity"], "task_digest": bv["task_digests"][WS],
        "approval_evidence_digest": bv["approval_evidence_digest"],
        "owned_scope": task["owned_paths"], "files_changed": task["owned_paths"],
        "dependencies_consumed": [f"{P}/receipts/ontology-phase-5-{w}.implementation-receipt.json" for w in LANES]
        + [f"{P}/reviews/ontology-phase-5-feedback-schemas.review-receipt.json",
           f"{P}/round-1/ontology-phase-5-feedback-core.review-receipt.json",
           f"{P}/integration/clarification-R16.md"],
        "commands": [
            {"command": "./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'", "exit_code": 0,
             "result": f"{tests} OK, unsandboxed ({GATE})"},
            {"command": "./.venv/bin/python -m mypy", "exit_code": 0, "result": f"{mypy} (feedback.py added to the strict list)"},
            {"command": "python3 palimnex.py index && python3 palimnex.py validate --deep", "exit_code": 0, "result": "fresh index, deep validation passed"},
            {"command": "python3 palimnex.py evaluate --limit 5", "exit_code": 0, "result": "production sentinel passed (gate.log)"},
            {"command": "python3 palimnex.py evaluate-ontology-shadow && python3 palimnex.py ontology-status", "exit_code": 0, "result": "Phase 3 gates and influence status unchanged (gate.log)"},
            {"command": 'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "exit_code": 0, "result": "standard gate passed (gate.log)"},
            {"command": "python3 palimnex.py ledger-status", "exit_code": 0, "result": "read-only ledger status; the real ledger was not written (gate.log)"},
            {"command": "git diff --numstat -- palimnex/experience.py", "exit_code": 0, "result": f"{experience.replace(chr(9), ' ')} (R16 only)"},
            {"command": "git diff --exit-code -- palimnex/retrieval.py palimnex/durable.py palimnex/semantic.py palimnex/cache_v3.py palimnex/ontology_influence.py palimnex/schemas/memory-event.v1.schema.json", "exit_code": 0, "result": "unchanged against HEAD"},
            {"command": "./.venv/bin/python -m unittest palimnex.tests.test_feedback_cli", "exit_code": 0, "result": "6 tests OK, temporary project and ledger only; the context and capsule isolation test fails when R16 is disabled (FEEDBACK_PAYLOAD_SCHEMAS patched empty), confirming it detects the round-1 blocker (integration/r16-negative-control.log)"},
            *audit_commands(),
        ],
        "compatibility_effect": "Additive: palimnex.feedback, palimnex:retrieval-feedback:v1, palimnex:retrieval-feedback-withdrawal:v1, palimnex:retrieval-feedback-report:v1, and the feedback-record, feedback-correct, feedback-withdraw (ledger writes, owner-run) and feedback-report (read-only) commands. Feedback rides on existing fact, correction and revocation events; ledger schema, event kinds, memory-event.v1, exports and packs unchanged. R16: context and capsule exclude feedback payloads from historical recall, so with or without feedback their output is unchanged; retrieve_sources, explain-search, search, symbols, impact and palimnex evaluate unchanged.",
        "privacy_and_authority_checks": [
            "no Git writes", "no network, installs or model calls",
            "the repository's real ledger was not written; feedback tests and CLI tests use temporary projects and ledgers",
            "query, note, reason and reviewer privacy-scanned; refusals never echo them (CLI test with a runtime canary)",
            "feedback payloads are historical_only with authorizes_actions and retrieval_influence false",
            "Redis was already running when the gate started and was left as found",
            "Codex lanes ran with approval_policy=never; no sandbox escapes",
        ],
        "integration_patch_proposals": ["R8 (from Phase 0): validator should accept files_changed descendants of directory-valued owned paths; still not applied"],
        "unresolved_risks": [
            "R16 (feedback excluded from context and capsule recall; integration lane owns palimnex/experience.py for that change) is a coordinator decision for owner confirmation",
            "palimnex recall and the hot-event projection still list feedback events as ordinary historical_only ledger history",
            "Round-1 review limits: feedback-core BLOCKER fixed by R16 in the integration lane (pending re-review); feedback-core MINOR (its test reads the schema lane's files without a declared DAG edge) left as a residual, the schemas having been accepted first; feedback-schemas MINORs (end_line >= start_line and the colon/backslash path rule are enforced by palimnex.feedback, not expressible or not mirrored in JSON Schema) accepted, runtime remaining the closed gate",
            "Concurrent feedback commands targeting the same event could each append a successor (reported by the core lane); sequential repeats are refused",
            "Grok ran with --disallowed-tools Write, which leaves shell access; reviewer read-only status is verified by the ownership snapshot audits",
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
