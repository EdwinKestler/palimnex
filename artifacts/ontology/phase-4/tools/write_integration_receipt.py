#!/usr/bin/env python3
"""One-shot: write and validate the Phase 4 coordinator integration receipt."""
from __future__ import annotations

import json
import subprocess

P = "artifacts/ontology/phase-4"
WS = "ontology-phase-4-integration"
LANES = ("provider", "cohort", "channel", "evaluation")
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"
GATE = f"{P}/integration/gate.log"
EVAL = f"{P}/integration/semantic-evaluation.json"


def evaluation_summary() -> str:
    d = json.load(open(EVAL, encoding="utf-8"))
    b, c = d["benchmark"], d["cohort_scored"]
    return (f"exit 2, status {d['status']}; held_reasons {', '.join(d['held_reasons'])}; semantic cohort MRR "
            f"{c['baseline_mrr']:.4f}->{c['shadow_mrr']:.4f}, recall {c['baseline_recall']:.4f}->{c['shadow_recall']:.4f}, "
            f"no additional pass; p95 {b['semantic_p95_ms']:.1f} ms vs {b['baseline_p95_ms']:.1f} ms baseline "
            f"({b['samples_per_variant']} samples each, latency gate passed); privacy, drift, determinism, identity, "
            f"abstention, ambiguity and forbidden-hit gates passed ({EVAL})")


COORDINATOR_RECORDS = (f"{P}/prompts/", f"{P}/reviews/", f"{P}/round-", f"{P}/tools/", f"{P}/integration/")
AUDITS = ("ownership-audit.wave1.json", "ownership-audit.wave23.json", "ownership-audit.review23.json",
          "ownership-audit.evalfix1.json", "ownership-audit.final.json", "ownership-audit.integration-review.json")


def audit_commands() -> list[dict]:
    """Report each saved audit with its true exit code and what its violations were."""
    entries = []
    for name in AUDITS:
        report = json.load(open(f"{P}/integration/{name}", encoding="utf-8"))
        paths = [v["path"] for v in report["violations"]]
        foreign = [p for p in paths if not p.startswith(COORDINATOR_RECORDS)]
        if foreign:
            raise SystemExit(f"{name}: violation outside coordinator records: {foreign}")
        lanes = sorted(report["changed_by_lane"])
        result = (f"status {report['status']}; lane changes stayed inside owned paths ({', '.join(lanes)}); "
                  + (f"{len(paths)} unowned path(s), all coordinator records written by the coordinator after the "
                     f"snapshot (prompts, reviews, round-*, tools): {', '.join(paths)}" if paths else "no unowned path")
                  + "; no reviewer write")
        entries.append({"command": f"./.venv/bin/python {P}/tools/ownership_audit.py audit > {P}/integration/{name}",
                        "exit_code": 1 if paths else 0, "result": result})
    return entries


def main() -> int:
    task = json.load(open(f"{P}/tasks/{WS}.json"))
    bv = json.load(open(f"{P}/integration/bundle-validation.json"))
    git = [l for l in subprocess.run(["git", "status", "--short"], capture_output=True, text=True).stdout.split("\n") if l]
    receipt = {
        "schema": "palimnex:ontology-implementation-receipt:v1", "workstream_id": WS,
        "design_identity": task["approved_design_identity"], "task_digest": bv["task_digests"][WS],
        "approval_evidence_digest": bv["approval_evidence_digest"],
        "owned_scope": task["owned_paths"], "files_changed": task["owned_paths"],
        "dependencies_consumed": [f"{P}/receipts/ontology-phase-4-{w}.implementation-receipt.json" for w in LANES]
        + [f"{P}/reviews/ontology-phase-4-{w}.review-receipt.json" for w in LANES]
        + [f"{P}/integration/cohort-freeze.json", f"{P}/integration/reviewer-launch.md",
                                    f"{P}/integration/ownership-audit.wave1-review.recovered.json"],
        "commands": [
            {"command": "./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'", "exit_code": 0, "result": f"523 tests OK, unsandboxed ({GATE})"},
            {"command": "./.venv/bin/python -m mypy", "exit_code": 0, "result": "no issues in 21 source files including semantic_local.py, semantic_shadow.py and semantic_eval.py"},
            {"command": "python3 palimnex.py index && python3 palimnex.py validate --deep", "exit_code": 0, "result": "fresh index (810 chunks), deep validation passed"},
            {"command": "python3 palimnex.py evaluate --limit 5", "exit_code": 0, "result": "production sentinel: every critical case passes, recall_at_limit 1.0, MRR 0.8917, unchanged from the influence exit gate"},
            {"command": "python3 palimnex.py evaluate-ontology-shadow", "exit_code": 0, "result": "all eight Phase 3 gates true"},
            {"command": "python3 palimnex.py ontology-status && python3 palimnex.py semantic-status", "exit_code": 0, "result": "ontology influence off; semantic provider v1 disabled, retrieval_influence false"},
            {"command": 'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "exit_code": 0, "result": "standalone gate passed; isolated retrieval recall 1.0; no live ledger write or model call"},
            {"command": "python3 palimnex.py ledger-status", "exit_code": 0, "result": "integrity ok, 0 events"},
            {"command": "git diff --exit-code -- palimnex/retrieval.py palimnex/semantic.py palimnex/cache_v3.py palimnex/experience.py palimnex/ontology_influence.py", "exit_code": 0, "result": "production retrieval, semantic v1, cache, context and influence modules byte-identical to HEAD"},
            {"command": "sha256sum palimnex/evaluation/semantic-shadow.v1.json vs integration/cohort-freeze.json", "exit_code": 0, "result": "cohort still pinned at bfaa3998... after every lane and review"},
            {"command": "python3 palimnex.py evaluate-semantic-shadow", "exit_code": 2, "result": evaluation_summary()},
            *audit_commands(),
        ],
        "compatibility_effect": "Additive, evidence only: palimnex.semantic_local, palimnex.semantic_shadow, palimnex.semantic_eval, the evaluate-semantic-shadow command, palimnex:semantic-provider-identity:v1, palimnex:semantic-shadow-comparison:v1, palimnex:semantic-shadow-evaluation:v1 and the frozen palimnex:semantic-shadow-cohort:v1 fixture. retrieve_sources, context, explain-search, search, symbols, impact, palimnex evaluate, semantic-status, semantic-gate and project-memory:semantic-provider:v1 (+0.05/2x) unchanged. No configuration key, no retrieval influence, no promotion.",
        "privacy_and_authority_checks": [
            "no Git writes", "no network, installs or model downloads; only the in-process hashed provider and test doubles",
            "no ledger writes (0 events)",
            "Redis was already running when the gate started and was left running as found",
            "cohort written blind (lane logs checked by the reviewer), reviewed, fixed and frozen by digest before any semantic measurement",
            "R14 and R15 fixed in SEMANTIC_SPEC.md before measurement; no threshold, label or parameter changed after the freeze",
            "canaries built at runtime only; no secret-shaped literal in any owned file; the whole report is scanned for canaries",
            "Codex lanes ran with approval_policy=never; no sandbox escapes",
        ],
        "integration_patch_proposals": ["R8 (from Phase 0): validator should accept files_changed descendants of directory-valued owned paths; still not applied"],
        "unresolved_risks": [
            "Phase 4 result is HELD under the owner's thresholds: zero gain on the frozen semantic cohort, no additional passing cohort case, and two critical Phase 3 cohort cases (alias-retention-ledger, alias-rrf-fusion) regress, reducing that protected suite's recall. Thresholds were not weakened.",
            "The semantic channel improved the v27 suite on local retrieval (5 -> 9 passing cases, recall 0.385 -> 0.692), which is reported but cannot promote the provider.",
            "Review limits closed: provider limit (generator, nested-vector and ragged-vector refusals are probed under /tmp by the reviewer, not asserted in test_semantic_local) accepted as a recorded limit, the behaviour having been verified by those probes; channel MINOR (tests do not assert retrieval.py unchanged) closed by the coordinator git-diff gate step; evaluation round-1 MINORs 1 and 2 RESOLVED in fix round 1 and re-review; evaluation MINOR 3 (gate-failure unit tests mock _run_suite) accepted as a limit, covered by the reviewer's live /tmp probes and two real-repository evaluation runs (reviewer copy and the official run)",
            "Spec v1.1 amendments A1 (canary rule names) and A2 (testable paraphrase isolation) were made before the freeze; R14 and R15 are coordinator decisions for owner confirmation",
            "Audit coverage: the window of the wave-1 Grok review was audited but its output was printed, not saved; the printout is recovered from the device's tool history in integration/ownership-audit.wave1-review.recovered.json. It printed only the violations list: five paths, all coordinator records (the provider review receipt copy, round-1 log and review copies, and tools/extract_reviews.py). changed_by_lane was not printed for that window. Every other window is saved under integration/ownership-audit.*.json",
            "Reviewer write restriction: Grok ran with --disallowed-tools Write, which removes only the file-writing tool while shell access remains (exact launch commands in integration/reviewer-launch.md); reviewer read-only status is therefore verified by the snapshot audits, which show no reviewer write",
        ],
        "cache_and_ledger_state": {"cache_consulted": True, "index_fresh_at_gate": True, "redis_final_state": "running (as found)", "ledger_integrity": "ok", "ledger_events": 0},
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
