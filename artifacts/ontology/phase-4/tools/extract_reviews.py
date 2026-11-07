#!/usr/bin/env python3
"""Extract review receipts from a Grok log and validate each against its task card.

Usage: extract_reviews.py LOG OUT_DIR [BUNDLE_VALIDATION]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

P = "artifacts/ontology/phase-4"
VALIDATOR = ".agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py"


def main() -> int:
    log, out = Path(sys.argv[1]), Path(sys.argv[2])
    blocks = re.findall(r"```json\s*(\[.*?\])\s*```", log.read_text(encoding="utf-8"), flags=re.S)
    if not blocks:
        raise SystemExit("no json receipt block found")
    receipts = json.loads(blocks[-1])
    out.mkdir(parents=True, exist_ok=True)
    for receipt in receipts:
        ws = receipt["workstream_id"]
        path = out / f"{ws}.review-receipt.json"
        path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result = subprocess.run([sys.executable, VALIDATOR, f"{P}/tasks/{ws}.json", "--review-receipt", str(path)],
                                capture_output=True, text=True)
        verdict = "valid" if result.returncode == 0 else "INVALID: " + (result.stdout + result.stderr).strip()[-300:]
        print(f"{ws}: status={receipt['status']} receipt={verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
