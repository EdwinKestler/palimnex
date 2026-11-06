#!/usr/bin/env bash
# Launch wave-2 (reconciliation) Codex lanes. Usage: launch_wave2.sh [--snapshot] LANE...
set -euo pipefail
P0=artifacts/ontology/phase-0
SNAP=0; if [[ "${1:-}" == "--snapshot" ]]; then SNAP=1; shift; fi
ALL=(ontology-phase-0-registry-contract ontology-phase-0-coverage-contract ontology-phase-0-threat-cases)
for ws in "${ALL[@]}"; do
  cat > "$P0/prompts/$ws.md" <<EOF
You are the bounded implementer for Palimnex ontology workstream \`$ws\`, Phase 0 RECONCILIATION WAVE 2.
Your wave-1 drafts already exist in your owned paths; revise them, do not start over.

Read, in this order, before writing anything:
1. AGENTS.md
2. .agents/skills/palimnex-ontology-workstream/SKILL.md
3. $P0/tasks/$ws.json (reissued task card; your authority boundary)
4. $P0/briefs/COMMON.md
5. $P0/integration/reconciliation-decisions.v1.md
6. $P0/briefs/wave-2/$ws.md
7. $P0/wave-1/reviews/$ws.review-receipt.json (independent review of your wave-1 work)

Other lanes may be running in parallel in this same working tree. Write ONLY inside your task card's owned_paths.
When the revised deliverables, check script, receipt and acceptance commands all pass, stop and print a short summary
that maps each decision (R1-R7) and each review finding to what you changed, or to why you did not.
EOF
done
# Prompts are deterministic, so regenerating them never changes their hashes.
if [[ $SNAP == 1 ]]; then ./.venv/bin/python $P0/tools/ownership_audit.py snapshot; fi
for ws in "$@"; do
  echo "[launch] $ws"
  nohup codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s workspace-write \
    -C "$PWD" -o "$P0/logs/$ws.last-message.md" - < "$P0/prompts/$ws.md" \
    > "$P0/logs/$ws.log" 2>&1 &
  echo "$!" > "$P0/logs/$ws.pid"
done
