#!/usr/bin/env python3
"""One-shot: archive Phase 0 wave 1 and reissue reconciliation (wave 2) task cards.

Same approval evidence and design identity; new objectives and dependency DAG
(registry first, then coverage and threat-cases). Validates the new bundle.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap_phase0 as b  # noqa: E402

log = logging.getLogger("reissue_wave2")
ROOT = b.ROOT
P0 = ROOT / b.PHASE0
WAVE1 = P0 / "wave-1"
DECISIONS = f"{b.PHASE0}/integration/reconciliation-decisions.v1.md"
REG, COV, CASES = (
    "ontology-phase-0-registry-contract",
    "ontology-phase-0-coverage-contract",
    "ontology-phase-0-threat-cases",
)


def archive_wave1() -> None:
    if WAVE1.exists():
        raise SystemExit("wave-1 archive already exists; refusing to overwrite")
    WAVE1.mkdir()
    for name in ("tasks", "receipts", "reviews", "logs", "prompts"):
        shutil.move(str(P0 / name), str(WAVE1 / name))
        (P0 / name).mkdir()
    shutil.move(str(P0 / "manifest.json"), str(WAVE1 / "manifest.json"))
    shutil.copytree(ROOT / b.DRAFTS, WAVE1 / "drafts")
    log.info("archived wave 1 to %s", WAVE1.relative_to(ROOT))


def wave2_objective(ws: str) -> str:
    return (
        f"Reconciliation wave 2 for {ws}: revise your Phase 0 drafts so they conform to "
        f"{DECISIONS} and resolve every MAJOR and MINOR finding addressed to your lane in "
        f"{b.PHASE0}/wave-1/reviews/{ws}.review-receipt.json. Follow "
        f"{b.PHASE0}/briefs/wave-2/{ws}.md. Keep everything else in your drafts unchanged."
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    archive_wave1()
    evidence = json.loads((P0 / "approval-evidence.json").read_text())
    design = evidence["design_identity"]
    if b.sha256_file(design["path"]) != design["sha256"]:
        raise SystemExit("approved design digest drifted; stopping")
    for ws in (REG, COV, CASES):
        b.LANES[ws]["objective"] = wave2_objective(ws)
    edges = [
        {"from": REG, "to": COV},
        {"from": REG, "to": CASES},
        {"from": REG, "to": b.INTEGRATION},
        {"from": COV, "to": b.INTEGRATION},
        {"from": CASES, "to": b.INTEGRATION},
    ]
    plan = b.manifest(design, edges)
    plan["status"] = "in_progress"
    b.write_json(f"{b.PHASE0}/manifest.json", plan)
    tasks = []
    for ws in b.LANES:
        deps = [e["from"] for e in edges if e["to"] == ws]
        card = b.task(ws, design, evidence, deps)
        extra = {f"{b.PHASE0}/wave-1"} | ({DECISIONS} if ws != b.INTEGRATION else set())
        card["read_only_paths"] = sorted(set(card["read_only_paths"]) | extra)
        b.write_json(b.task_path(ws), card)
        tasks.append(card)
    report = b.vc.validate_workstream_bundle(plan, tasks)
    report["approval_evidence_digest"] = b.vc.digest(evidence)
    report["wave"] = 2
    b.write_json(f"{b.PHASE0}/integration/bundle-validation.wave-2.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
