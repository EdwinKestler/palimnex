#!/usr/bin/env python3
"""Snapshot file hashes and audit post-run changes against lane ownership.

Usage (repository root):
  ./.venv/bin/python artifacts/ontology/phase-0/tools/ownership_audit.py snapshot
  ./.venv/bin/python artifacts/ontology/phase-0/tools/ownership_audit.py audit [--lanes a,b]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
PHASE0 = "artifacts/ontology/phase-0"
SNAPSHOT = ROOT / PHASE0 / "integration/pre-run-snapshot.json"
SKIP_DIRS = {".git", ".venv", ".palimnex", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache"}
SKIP_PREFIXES = (f"{PHASE0}/logs/", f"{PHASE0}/integration/pre-run-snapshot.json")
log = logging.getLogger("ownership_audit")


def file_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in files:
            path = Path(base, name)
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(SKIP_PREFIXES) or path.is_symlink():
                continue
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def owned_by(rel: str, ownership: dict[str, list[str]]) -> str | None:
    for lane, paths in ownership.items():
        for owned in paths:
            if rel == owned or rel.startswith(owned.rstrip("/") + "/"):
                return lane
    return None


def audit(lanes: list[str] | None) -> int:
    before = json.loads(SNAPSHOT.read_text())["files"]
    after = file_hashes()
    manifest = json.loads((ROOT / PHASE0 / "manifest.json").read_text())
    ownership = manifest["exclusive_file_ownership"]
    if lanes:
        ownership = {k: v for k, v in ownership.items() if k in lanes}
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    by_lane: dict[str, list[str]] = {}
    violations = []
    for rel in changed:
        lane = owned_by(rel, ownership)
        state = "deleted" if rel not in after else ("added" if rel not in before else "modified")
        if lane is None:
            violations.append({"path": rel, "change": state})
        else:
            by_lane.setdefault(lane, []).append(rel)
    report = {"schema": "palimnex:ontology-ownership-audit:v1", "changed_by_lane": by_lane,
              "violations": violations, "status": "clean" if not violations else "violation",
              "authorizes_actions": False}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not violations else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["snapshot", "audit"])
    parser.add_argument("--lanes")
    args = parser.parse_args()
    if args.mode == "snapshot":
        files = file_hashes()
        SNAPSHOT.write_text(json.dumps({"files": files}, indent=1, sort_keys=True) + "\n")
        log.info("snapshot of %d files written to %s", len(files), SNAPSHOT.relative_to(ROOT))
        return 0
    return audit(args.lanes.split(",") if args.lanes else None)


if __name__ == "__main__":
    sys.exit(main())
