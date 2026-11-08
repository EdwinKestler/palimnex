#!/usr/bin/env python3
"""One-shot: give the coordinator-owned Phase 5 integration lane palimnex/experience.py (R16).

Feedback events must stay out of context and capsule historical recall. Only the
integration task card and the manifest change; the lane cards, their digests and
receipts stay valid. Re-validates the bundle into bundle-validation.r16.json.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "artifacts/ontology/phase-5/tools"))
import bootstrap_phase5 as b5  # noqa: E402

log = logging.getLogger("amend_integration_r16")
ADDED = ["palimnex/experience.py"]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = b5.b1.ROOT / b5.P5
    manifest = json.loads((root / "manifest.json").read_text())
    card_path = root / "tasks" / f"{b5.INTEG}.json"
    card = json.loads(card_path.read_text())
    if any(path in card["owned_paths"] for path in ADDED):
        raise SystemExit("already amended")
    card["owned_paths"] = sorted(card["owned_paths"] + ADDED)
    card["read_only_paths"] = [p for p in card["read_only_paths"] if p not in ADDED]
    card["objective"] += (" Amended (R16, artifacts/ontology/phase-5/integration/clarification-R16.md): "
                          "exclude feedback payloads from context and capsule historical recall so feedback "
                          "has no effect on any retrieval output.")
    manifest["exclusive_file_ownership"][b5.INTEG] = card["owned_paths"]
    manifest["status"] = "in_progress"
    tasks = [json.loads((root / "tasks" / f"{ws}.json").read_text()) for ws in b5.LANES if ws != b5.INTEG] + [card]
    report = b5.vc.validate_workstream_bundle(manifest, tasks)
    report["approval_evidence_digest"] = b5.vc.digest(card["approval_evidence"])
    report["amendment"] = "R16: integration lane owns palimnex/experience.py"
    b5.write_json(f"{b5.P5}/manifest.json", manifest)
    b5.write_json(f"{b5.P5}/tasks/{b5.INTEG}.json", card)
    b5.write_json(f"{b5.P5}/integration/bundle-validation.r16.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
