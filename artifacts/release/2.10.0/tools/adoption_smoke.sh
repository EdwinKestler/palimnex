#!/usr/bin/env bash
# Adoption smoke test of the 2.10.0 candidate wheel on isolated snapshots of other repositories.
# Usage: adoption_smoke.sh WHEEL OUT_JSON_DIR REPO_DIR...
# Each snapshot is `git archive HEAD` of the repository (committed files only) plus its .palimnex.json if it is
# untracked; the live checkout, its .palimnex/ (ledger, Redis) and the global pipx install are never touched.
set -uo pipefail
WHEEL="$1"; OUT="$2"; shift 2
BASE=/tmp/palimnex-adoption
rm -rf "$BASE"; mkdir -p "$BASE" "$OUT"
python3 -m venv "$BASE/venv" && "$BASE/venv/bin/pip" install --quiet --no-index "$WHEEL" || { echo "venv install failed"; exit 1; }
PX="$BASE/venv/bin/palimnex"

run() {  # name, command...
  local name="$1"; shift
  local start end code
  start=$(date +%s.%N)
  timeout 900 "$@" > "$SNAP.out/$name.json" 2> "$SNAP.out/$name.err"; code=$?
  end=$(date +%s.%N)
  printf '{"step":"%s","exit":%d,"seconds":%.2f}\n' "$name" "$code" "$(echo "$end - $start" | bc)" >> "$SNAP.steps.jsonl"
}

for SRC in "$@"; do
  NAME=$(basename "$SRC"); SNAP="$BASE/$NAME"; mkdir -p "$SNAP" "$SNAP.out"; : > "$SNAP.steps.jsonl"
  COMMIT=$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo none)
  BRANCH=$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)
  if [[ "$COMMIT" == none ]]; then echo "{\"repo\":\"$NAME\",\"skipped\":\"no committed HEAD\"}" > "$OUT/$NAME.json"; continue; fi
  git -C "$SRC" archive HEAD | tar -x -C "$SNAP"
  CONFIG_SOURCE=committed
  if [[ ! -f "$SNAP/.palimnex.json" && -f "$SRC/.palimnex.json" ]]; then cp "$SRC/.palimnex.json" "$SNAP/"; CONFIG_SOURCE=copied_untracked; fi
  [[ -f "$SNAP/.palimnex.json" ]] || CONFIG_SOURCE=none
  cd "$SNAP"
  run version "$PX" --version
  if [[ "$CONFIG_SOURCE" == none ]]; then run init "$PX" init; fi
  run doctor "$PX" doctor
  run redis_start "$PX" redis start
  run index "$PX" index
  run validate_deep "$PX" validate --deep
  run status "$PX" status
  run search "$PX" search "configuration and installation" --limit 5
  run context "$PX" context "how is the project configured"
  run explain_search "$PX" explain-search "how is the project configured" --limit 3
  run ontology_status "$PX" ontology-status
  run semantic_status "$PX" semantic-status
  run evaluate "$PX" evaluate --limit 5
  run ledger_init "$PX" ledger-init
  run ledger_status "$PX" ledger-status
  run feedback_report "$PX" feedback-report
  run redis_stop "$PX" redis stop
  cd - > /dev/null
  python3 - "$NAME" "$COMMIT" "$BRANCH" "$CONFIG_SOURCE" "$SNAP" "$OUT" <<'PY'
import json, sys
from pathlib import Path
name, commit, branch, config, snap, out = sys.argv[1:]
steps = [json.loads(l) for l in Path(snap + ".steps.jsonl").read_text().splitlines() if l]
def doc(step):
    try:
        return json.loads(Path(f"{snap}.out/{step}.json").read_text() or "null")
    except ValueError:
        return None
index = doc("index") or {}
manifest = index.get("manifest", {}) if isinstance(index, dict) else {}
explain = doc("explain_search") or {}
summary = {"repo": name, "commit": commit, "branch": branch, "config": config, "steps": steps,
           "files": manifest.get("file_count"), "chunks": manifest.get("chunk_count"),
           "version": (Path(f"{snap}.out/version.json").read_text().strip()),
           "coverage_status": (explain.get("coverage") or {}).get("status") if isinstance(explain, dict) else None,
           "errors": {s["step"]: Path(f"{snap}.out/{s['step']}.err").read_text()[-400:] for s in steps if s["exit"] not in (0,)}}
Path(out, f"{name}.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({k: summary[k] for k in ("repo", "commit", "config", "files", "chunks")}),
      [f"{s['step']}={s['exit']}" for s in steps])
PY
done
