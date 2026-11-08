#!/usr/bin/env python3
"""One-shot Phase 5 bootstrap: record the owner's approval and decisions, issue manifest and task cards.

No Git, network, Redis or ledger activity.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-1/tools"))
import bootstrap_phase1 as b1  # noqa: E402

vc, sha, replace_once, write_json = b1.vc, b1.sha, b1.replace_once, b1.write_json
log = logging.getLogger("bootstrap_phase5")
DESIGN, PROPOSAL, GRANTOR = b1.DESIGN, b1.PROPOSAL, b1.GRANTOR
P5 = "artifacts/ontology/phase-5"
EXPECTED_DESIGN_SHA = "bee8ea6dff05ad2dc3371868ec66e9be9aa8218d25c5d758aa0aefdcaf4ec8a3"
RECORDED_AT = "2026-11-07T15:02:00-06:00"
EVIDENCE = ("claude.ai conversation with the repository owner, user message sent 2026-11-07 15:02 "
            "America/Guatemala ('if phase 4 is closed then phase 5 is approved'), after the Phase 4 exit gate "
            "commit 56db9e5 was pushed, plus the owner's scope answers in the same conversation: feedback records "
            "only; ledger storage written by the owner; shadow and evaluation only in a later round; offline "
            "HTML + JSON for the deferred graph explorer; semantic cache skipped")

STATUS_OLD = "experiment) were approved on 2026-11-06. Phase 5 remains a proposal.**"
STATUS_NEW = """experiment) were approved on 2026-11-06; the influence exit gate was recorded
(commit bbf4b8b) and Phase 4 was accepted as held at its exit gate on
2026-11-07 (commits 0bee7f9, 56db9e5). Phase 5, limited to reviewed retrieval
feedback records, was approved on 2026-11-07.**"""
EVIDENCE_OLD = "`artifacts/ontology/phase-4/approval-evidence.json`."
EVIDENCE_NEW = ("`artifacts/ontology/phase-4/approval-evidence.json` and exit gate\n"
                "`artifacts/ontology/phase-4/exit-gate.json`; Phase 5\n"
                "`artifacts/ontology/phase-5/approval-evidence.json`.")
SCOPE_ANCHOR = """remain under `artifacts/design/ontology-phase-0/`; coordination records live
under `artifacts/ontology/`."""
SCOPE_ADD = SCOPE_ANCHOR + """

Phase 5 approval authorizes reviewed retrieval feedback records only: a
versioned, source-verified, review-attributed and non-authorizing
`palimnex:retrieval-feedback:v1` payload (with a withdrawal payload and a
read-only report) stored as existing ledger event kinds (`fact`, `correction`,
`revocation`), the `palimnex.feedback` module, and owner-run commands to record,
correct, withdraw and report feedback. Agents implement and test against
temporary ledgers only; writing the repository's real ledger is the owner's
action. It does not authorize retrieval influence from feedback, a feedback
shadow channel or evaluation (a later round), static graph exploration
(deferred), a semantic cache (skipped), new event kinds, ledger schema or
migration changes, automatic query-history learning, or any change to
`retrieve_sources`, `context`, `explain-search`, `search`, `symbols`, `impact`
or `palimnex evaluate`."""
ROW_PREFIX = "| Phase 4 thresholds |"
NEW_ROWS = """
| Phase 5 scope | This round builds reviewed retrieval feedback records only; feedback shadow and evaluation come in a later round once enough reviewed records exist; the semantic cache is skipped; static graph exploration is deferred at lower priority (owner decision 2026-11-07) |
| Feedback storage | Existing ledger event kinds with a new versioned payload that is source-bound, review-attributed and non-authorizing. The owner records feedback in the real ledger; agents implement and test against temporary ledgers only (owner decision 2026-11-07) |
| Feedback influence | None in Phase 5. A later round may add a feedback shadow channel with a frozen cohort, privacy, source-drift and regression gates and measured benefit; any opt-in influence then needs a separate approval and a new versioned behaviour contract (owner decision 2026-11-07) |
| Graph exploration format | When built: one self-contained, read-only, network-free offline HTML file plus a deterministic JSON graph, generated explicitly into an output directory the owner chooses, excluded from indexing and commits by default (owner decision 2026-11-07) |"""


def build_design() -> str:
    text = (b1.ROOT / DESIGN).read_text(encoding="utf-8")
    text = replace_once(text, STATUS_OLD, STATUS_NEW)
    text = replace_once(text, EVIDENCE_OLD, EVIDENCE_NEW)
    text = replace_once(text, SCOPE_ANCHOR, SCOPE_ADD)
    lines = text.split("\n")
    rows = [i for i, line in enumerate(lines) if line.startswith(ROW_PREFIX)]
    if len(rows) != 1:
        raise SystemExit("expected exactly one Phase 4 thresholds row")
    lines[rows[0]] += NEW_ROWS
    return "\n".join(lines)


def approval(design_sha: str) -> dict:
    return {
        "schema": "palimnex:ontology-approval-evidence:v1", "authority_source": "user_message",
        "evidence_locator": EVIDENCE, "grantor_claim": GRANTOR,
        "design_identity": {"path": DESIGN, "sha256": design_sha},
        "source_proposal_identity": {"path": PROPOSAL, "sha256": sha(PROPOSAL)},
        "approved_phases": [5], "authorized_actions": [vc.PHASE_ACTIONS[5]],
        "excluded_actions": [vc.PHASE_ACTIONS[p] for p in range(5)],
        "recorded_at": RECORDED_AT, "implementation_authorized": True,
        "network_authorized": False, "git_write_authorized": False, "live_state_authorized": False,
    }


PY = "./.venv/bin/python"
CORE, SCHEMAS, INTEG = ("ontology-phase-5-feedback-core", "ontology-phase-5-feedback-schemas",
                        "ontology-phase-5-integration")


def mypy(*paths: str) -> str:
    return (f"{PY} -m mypy --python-version 3.11 --follow-imports=silent --check-untyped-defs "
            "--disallow-untyped-defs " + " ".join(paths))


def unit(*modules: str) -> str:
    return f"{PY} -m unittest " + " ".join(f"palimnex.tests.{m}" for m in modules)


LANES: dict[str, dict] = {
    CORE: {
        "owned": ["palimnex/feedback.py", "palimnex/tests/test_feedback.py", "docs/RETRIEVAL_FEEDBACK.md"],
        "objective": "Implement palimnex/feedback.py: the palimnex:retrieval-feedback:v1 and withdrawal payload builders and validators, record, correct and withdraw through MemoryLedger.append_event with existing event kinds (fact, correction, revocation), and the read-only palimnex:retrieval-feedback-report:v1 with current, stale, superseded, withdrawn and invalid states; tests against temporary ledgers only; docs/RETRIEVAL_FEEDBACK.md. Follow FEEDBACK_SPEC.md sections 1 and 2.",
        "checks": [unit("test_feedback") + " -v", mypy("palimnex/feedback.py"),
                   unit("test_durable", "test_experience", "test_retrieval_influence")],
    },
    SCHEMAS: {
        "owned": ["palimnex/schemas/retrieval-feedback.v1.schema.json",
                  "palimnex/schemas/retrieval-feedback-withdrawal.v1.schema.json",
                  "palimnex/schemas/retrieval-feedback-report.v1.schema.json",
                  "palimnex/tests/fixtures/retrieval_feedback", "palimnex/tests/test_feedback_schemas.py"],
        "objective": "Define the public JSON Schemas palimnex:retrieval-feedback:v1, palimnex:retrieval-feedback-withdrawal:v1 and palimnex:retrieval-feedback-report:v1 exactly per FEEDBACK_SPEC.md, with valid and invalid fixtures and schema tests.",
        "checks": [unit("test_feedback_schemas") + " -v", unit("test_sdk", "test_influence_schemas")],
    },
    INTEG: {
        "owned": ["palimnex/core.py", "palimnex/tests/test_feedback_cli.py", "pyproject.toml", "palimnex/CHANGELOG.md",
                  "docs/COMPATIBILITY.md", f"{P5}/integration"],
        "objective": "Coordinator-owned serial integration: owner-run feedback-record, feedback-correct and feedback-withdraw ledger commands and the read-only feedback-report command with tests against temporary ledgers, mypy list, CHANGELOG, COMPATIBILITY; ownership audit and the full unsandboxed gate. Not delegated; never writes the repository's real ledger.",
        "checks": [f"{PY} -m unittest discover -s palimnex/tests -p 'test_*.py'", f"{PY} -m mypy", "python3 palimnex.py index",
                   "python3 palimnex.py validate --deep", "python3 palimnex.py evaluate --limit 5",
                   'PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh', "python3 palimnex.py ledger-status",
                   "python3 palimnex.py evaluate-ontology-shadow", "python3 palimnex.py ontology-status"],
    },
}
EDGES = [{"from": CORE, "to": INTEG}, {"from": SCHEMAS, "to": INTEG}]
FORBIDDEN = [".palimnex", ".env", ".env.example", "benchmark", "secrets", ".git"]
EXCLUSIONS = [
    "No edits outside owned_paths; foreign changes are returned as integration patch proposals.",
    "Feedback has no retrieval influence: retrieve_sources, context, explain-search, search, symbols, impact and palimnex evaluate stay byte-identical and never read feedback.",
    "Existing ledger event kinds only (fact, correction, revocation); no new event kind, ledger schema change, migration or change to palimnex/durable.py.",
    "Never write the repository's real ledger; tests use temporary repositories and temporary ledgers only.",
    "Feedback is non-authorizing: authority historical_only, authorizes_actions false, retrieval_influence false.",
    "No automatic query-history learning; every record is an explicit reviewed judgement.",
    "No feedback shadow channel, evaluation, graph exploration or semantic cache in this phase.",
    "No change to any existing identifier, schema, frozen fixture or test expectation except where a task card owns the file.",
    "No runtime dependency: runtime modules use only the standard library and palimnex modules.",
    "No Git staging, commits, branches or pushes; no network, installs, model or provider calls.",
    "Never read or echo credentials; never store literal secret-pattern strings; refusals never echo query, note or reason text.",
]


def receipt(ws: str) -> str:
    return f"{P5}/receipts/{ws}.implementation-receipt.json"


def owned(ws: str) -> list[str]:
    return LANES[ws]["owned"] + [receipt(ws)]


def task(ws: str, design: dict, evidence: dict) -> dict:
    deps = [e["from"] for e in EDGES if e["to"] == ws]
    commands = list(LANES[ws]["checks"])
    if ws != INTEG:
        commands += [f"{b1.VALIDATOR} {P5}/tasks/{ws}.json --implementation-receipt {receipt(ws)}",
                     "git status --short --untracked-files=all"]
    base = {DESIGN, PROPOSAL, "AGENTS.md", ".palimnex.json", "README.md", "pyproject.toml", "docs", "palimnex",
            ".agents/skills", "artifacts/design/ontology-phase-0", "artifacts/ontology/phase-0",
            "artifacts/ontology/phase-1", "artifacts/ontology/phase-2", "artifacts/ontology/phase-3",
            "artifacts/ontology/phase-3-promotion", "artifacts/ontology/phase-4", f"{P5}/briefs", f"{P5}/tasks",
            f"{P5}/approval-evidence.json", f"{P5}/manifest.json"}
    if ws != INTEG:
        base.add(f"{P5}/integration")
    return {
        "schema": "palimnex:ontology-workstream-task:v1", "workstream_id": ws, "phase": 5,
        "action_id": "ontology_phase_5_extensions", "objective": LANES[ws]["objective"],
        "exclusions": EXCLUSIONS, "approved_design_identity": design, "approval_evidence": evidence,
        "owned_paths": owned(ws), "read_only_paths": sorted(base - set(owned(ws))), "forbidden_paths": FORBIDDEN,
        "dependencies": deps, "acceptance_commands": commands, "required_output": "ImplementationReceipt",
        "network_authority": False, "git_write_authority": False, "live_state_authority": False,
    }


def manifest(design: dict) -> dict:
    return {
        "schema": "palimnex:ontology-workstream-manifest:v1", "approved_phase": 5,
        "design_identity": design, "workstreams": list(LANES), "dependency_dag": EDGES,
        "exclusive_file_ownership": {ws: owned(ws) for ws in LANES}, "shared_file_owner": INTEG,
        "acceptance_gates": [
            "feedback payloads are versioned, source-verified against current admitted bytes, review-attributed and non-authorizing",
            "records use existing event kinds through MemoryLedger.append_event; correction and withdrawal supersede, never delete",
            "the report states current, stale (source drift), superseded, withdrawn and invalid records deterministically",
            "privacy: query, note, reason and reviewer are scanned and never echoed in refusals",
            "no retrieval influence: retrieve_sources and every production output byte-identical with feedback present",
            "logical export and restore preserve feedback events",
            "focused tests and strict mypy pass; receipts validate; ownership audit clean; independent review per workstream",
            "full suite (unsandboxed), standard gate, deep validation, evaluations and ledger status pass; the real ledger is not written",
        ],
        "authority_limits": [
            "Phase 5 action, feedback records only; no influence, shadow, evaluation, graph explorer or semantic cache",
            "no network, provider, Git-write or live-state authority for any lane; the real ledger is written only by the owner",
            "no change to search, symbols, impact, palimnex evaluate, retrieve_sources, context, explain-search or the ledger schema",
            "Codex lanes run with approval_policy=never inside workspace-write; the coordinator runs socket tests unsandboxed",
        ],
        "status": "ready",
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if sha(DESIGN) != EXPECTED_DESIGN_SHA:
        raise SystemExit("design changed since the Phase 4 exit gate; stopping")
    (b1.ROOT / DESIGN).write_text(build_design(), encoding="utf-8")
    design = {"path": DESIGN, "sha256": sha(DESIGN)}
    log.info("design updated: sha256=%s", design["sha256"])
    evidence = approval(design["sha256"])
    write_json(f"{P5}/approval-evidence.json", evidence)
    plan = manifest(design)
    write_json(f"{P5}/manifest.json", plan)
    tasks = [task(ws, design, evidence) for ws in LANES]
    for card in tasks:
        write_json(f"{P5}/tasks/{card['workstream_id']}.json", card)
    report = vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = vc.digest(evidence)
    write_json(f"{P5}/integration/bundle-validation.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
