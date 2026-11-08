#!/usr/bin/env bash
# Launch Phase 4 Codex lanes. Usage: launch.sh [--snapshot] LANE...
set -euo pipefail
P=artifacts/ontology/phase-5
SNAP=0; if [[ "${1:-}" == "--snapshot" ]]; then SNAP=1; shift; fi
ALL=(ontology-phase-5-feedback-core ontology-phase-5-feedback-schemas)
for ws in "${ALL[@]}"; do
  cat > "$P/prompts/$ws.md" <<EOF
You are the bounded implementer for Palimnex ontology workstream \`$ws\`, Phase 5 reviewed retrieval feedback records (approved implementation).
You write product code only inside your owned_paths.

Read, in this order, before writing anything:
1. AGENTS.md
2. .agents/skills/palimnex-ontology-workstream/SKILL.md
3. $P/tasks/$ws.json (task card; your authority boundary)
4. $P/briefs/COMMON.md
5. $P/briefs/FEEDBACK_SPEC.md
6. $P/briefs/$ws.md

Another lane may be running in parallel in this same working tree. Write ONLY inside your task card's owned_paths.
When the deliverables, tests, receipt and acceptance commands all pass, stop and print a short summary
with the public API or contract you added, test counts, and open risks.
EOF
done
# Prompts are deterministic, so regenerating them never changes their hashes.
if [[ $SNAP == 1 ]]; then ./.venv/bin/python $P/tools/ownership_audit.py snapshot; fi
for ws in "$@"; do
  echo "[launch] $ws"
  nohup codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -c approval_policy="never" -s workspace-write \
    -C "$PWD" -o "$P/logs/$ws.last-message.md" - < "$P/prompts/$ws.md" \
    > "$P/logs/$ws.log" 2>&1 &
  echo "$!" > "$P/logs/$ws.pid"
done
