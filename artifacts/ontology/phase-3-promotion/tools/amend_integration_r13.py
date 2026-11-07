#!/usr/bin/env python3
"""One-shot: give the coordinator-owned integration lane the R11 defect fix paths.

Adds palimnex/concepts.py and palimnex/tests/test_concepts.py to the Phase 2
integration workstream only (manifest and its task card). Other task cards are
untouched, so their digests and receipts stay valid. Re-validates the bundle.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-3-promotion/tools"))
import bootstrap_promotion as b2  # noqa: E402

log = logging.getLogger("amend_integration_r13")
ADDED = ["palimnex/evaluation/ontology-shadow.v1.json"]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p2 = b2.b1.ROOT / b2.PP
    manifest = json.loads((p2 / "manifest.json").read_text())
    card_path = p2 / "tasks" / f"{b2.INTEG}.json"
    card = json.loads(card_path.read_text())
    for path in ADDED:
        if path in card["owned_paths"]:
            raise SystemExit("already amended")
    card["owned_paths"] = sorted(card["owned_paths"] + ADDED)
    card["read_only_paths"] = [p for p in card["read_only_paths"] if p not in ADDED]
    card["objective"] += (" Amended (R11, artifacts/ontology/phase-2/integration/clarification-R11.md): "
                          "rebind cohort line ranges that the retrieval refactor moved; labels unchanged.")
    manifest["exclusive_file_ownership"][b2.INTEG] = card["owned_paths"]
    manifest["status"] = "in_progress"
    tasks = [json.loads((p2 / "tasks" / f"{ws}.json").read_text()) for ws in b2.LANES if ws != b2.INTEG] + [card]
    report = b2.vc.validate_workstream_bundle(manifest, tasks)
    report["approval_evidence_digest"] = b2.vc.digest(card["approval_evidence"])
    report["amendment"] = "R13: integration lane owns palimnex/evaluation/ontology-shadow.v1.json"
    b2.write_json(f"{b2.PP}/manifest.json", manifest)
    b2.write_json(f"{b2.PP}/tasks/{b2.INTEG}.json", card)
    b2.write_json(f"{b2.PP}/integration/bundle-validation.r13.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
