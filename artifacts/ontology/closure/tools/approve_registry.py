#!/usr/bin/env python3
"""Freeze the reviewed candidate and write the approved registry ontology/concept-registry.v1.json.

Only kind and status change (candidate_set -> approved_registry, candidate ->
approved); every concept, alias, definition, binding and provenance is copied
unchanged. The approved file is the reviewed repository change the owner
approves by merging. Activation is not touched. No Git, network, Redis or
ledger activity.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from palimnex.concepts import canonical_registry_digest, load_registry, verify_source_bindings  # noqa: E402

log = logging.getLogger("approve_registry")
PC = "artifacts/ontology/closure"
CANDIDATE = f"{PC}/candidate/concept-registry.candidate.json"
REVIEW = f"{PC}/reviews/ontology-closure-registry.review-receipt.json"
APPROVED = "ontology/concept-registry.v1.json"


def sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    review = json.loads((ROOT / REVIEW).read_text(encoding="utf-8"))
    if review["status"] not in {"accepted", "accepted_with_limits"}:
        raise SystemExit("candidate review is not accepted; refusing to freeze")
    candidate = load_registry(CANDIDATE, root=ROOT, expected_kind="candidate_set")
    import subprocess
    check = subprocess.run([sys.executable, f"{PC}/candidate/check_candidate.py"], capture_output=True, text=True)
    if check.returncode != 0:
        raise SystemExit("candidate checker failed; refusing to freeze")
    document = json.loads((ROOT / CANDIDATE).read_text(encoding="utf-8"))
    document["registry_kind"] = "approved_registry"
    for concept in document["concepts"]:
        if concept["status"] != "candidate":
            raise SystemExit(f"unexpected status in {concept['concept_id']}")
        concept["status"] = "approved"
    document["registry_digest"] = canonical_registry_digest(document)
    target = ROOT / APPROVED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    approved = load_registry(APPROVED, root=ROOT, expected_kind="approved_registry")
    verification = verify_source_bindings(approved, root=ROOT)
    if verification.stale_concept_ids or len(verification.verified_concept_ids) != len(approved.concepts):
        raise SystemExit("approved registry bindings are not all current")
    freeze = {
        "schema": "palimnex:concept-registry-freeze:v1",
        "frozen_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-6))).isoformat(timespec="seconds"),
        "candidate": {"path": CANDIDATE, "sha256": sha(CANDIDATE), "registry_digest": candidate.registry_digest},
        "review_receipt": {"path": REVIEW, "sha256": sha(REVIEW), "status": review["status"]},
        "approved": {"path": APPROVED, "sha256": sha(APPROVED), "registry_digest": approved.registry_digest,
                     "concept_count": len(approved.concepts)},
        "changes_from_candidate": ["registry_kind candidate_set -> approved_registry",
                                   "concept status candidate -> approved", "registry_digest recomputed"],
        "approval": "pending the owner's merge of the reviewed release branch (design row 'Registry approval path')",
        "activation": "off; .palimnex.json not edited",
        "authorizes_actions": False,
    }
    (ROOT / PC / "integration/registry-freeze.json").write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(freeze, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
