#!/usr/bin/env python3
"""R18: re-pin the frozen concept-registry test fixtures after 2.10.0 edits to README.md and docs/DESIGN.md.

Only each binding's whole-file `version` and the fixture's `registry_digest`
change. The bound line ranges and their selected-byte digests must be
unchanged; if any range's content changed, the script refuses (that would
change what the fixture binds). Prints a JSON report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from palimnex.concepts import canonical_registry_digest  # noqa: E402
from palimnex.locators import repository_locator  # noqa: E402

FIXTURES = ROOT / "palimnex/tests/fixtures/concept_registry/valid"


def main() -> int:
    report = []
    for path in sorted(FIXTURES.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        changed = False
        for concept in document["concepts"]:
            for binding in concept["source_bindings"]:
                bounds = binding["range"]
                current = repository_locator(ROOT, f"{binding['source_id']}:{bounds['start']}-{bounds['end']}")
                if current.digest != binding["digest"]:
                    raise SystemExit(f"{path.name} {concept['concept_id']}: bound content changed; refusing")
                if current.version != binding["version"]:
                    report.append({"fixture": path.name, "concept": concept["concept_id"],
                                   "source": binding["source_id"], "range": bounds,
                                   "old_version": binding["version"], "new_version": current.version})
                    binding["version"] = current.version
                    changed = True
        if changed:
            old = document["registry_digest"]
            document["registry_digest"] = canonical_registry_digest(document)
            indent = 2 if "\n  " in raw else None
            path.write_text(json.dumps(document, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
            report.append({"fixture": path.name, "old_registry_digest": old, "new_registry_digest": document["registry_digest"]})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
