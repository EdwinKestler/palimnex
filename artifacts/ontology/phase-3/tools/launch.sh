#!/usr/bin/env bash
# Launch wave-2 (reconciliation) Codex lanes. Usage: launch_wave2.sh [--snapshot] LANE...
set -euo pipefail
P0=artifacts/ontology/phase-3
SNAP=0; if [[ "${1:-}" == "--snapshot" ]]; then SNAP=1; shift; fi
ALL=(ontology-phase-3-channel ontology-phase-3-cohort ontology-phase-3-retrieval ontology-phase-3-evaluation)
for ws in "${ALL[@]}"; do
  cat > "$P0/prompts/$ws.md" <<EOF
You are the bounded implementer for Palimnex ontology workstream \`$ws\`, Phase 3 (approved implementation).
You write product code only inside your owned_paths.

Read, in this order, before writing anything:
1. AGENTS.md
2. .agents/skills/palimnex-ontology-workstream/SKILL.md
3. $P0/tasks/$ws.json (task card; your authority boundary)
4. $P0/briefs/COMMON.md
5. $P0/briefs/SHADOW_SPEC.md
6. $P0/briefs/$ws.md

Other lanes may be running in parallel in this same working tree. Write ONLY inside your task card's owned_paths.
When the deliverables, tests, receipt and acceptance commands all pass, stop and print a short summary
with the public API or contract you added, test counts, and open risks.
EOF
done
# Prompts are deterministic, so regenerating them never changes their hashes.
if [[ $SNAP == 1 ]]; then ./.venv/bin/python $P0/tools/ownership_audit.py snapshot; fi
for ws in "$@"; do
  echo "[launch] $ws"
  nohup codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -c approval_policy="never" -s workspace-write \
    -C "$PWD" -o "$P0/logs/$ws.last-message.md" - < "$P0/prompts/$ws.md" \
    > "$P0/logs/$ws.log" 2>&1 &
  echo "$!" > "$P0/logs/$ws.pid"
done
