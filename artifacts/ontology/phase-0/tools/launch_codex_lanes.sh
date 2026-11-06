#!/usr/bin/env bash
# Launch the three Phase 0 implementation lanes as parallel Codex agents.
# Sandbox: workspace-write (no network for commands). Run from the repo root.
set -euo pipefail
P0=artifacts/ontology/phase-0
LANES=(ontology-phase-0-registry-contract ontology-phase-0-coverage-contract ontology-phase-0-threat-cases)

for ws in "${LANES[@]}"; do
  cat > "$P0/prompts/$ws.md" <<EOF
You are the bounded implementer for Palimnex ontology workstream \`$ws\` (Phase 0, contract drafting).

Read, in this order, before writing anything:
1. AGENTS.md
2. .agents/skills/palimnex-ontology-workstream/SKILL.md
3. docs/ONTOLOGY_ADOPTION.md (approved design; do not edit it)
4. $P0/tasks/$ws.json (your task card; it is your authority boundary)
5. $P0/briefs/COMMON.md
6. $P0/briefs/$ws.md

Two other lanes are running in parallel in this same working tree. Write ONLY inside your task card's owned_paths.
If you need a change anywhere else, describe it in your receipt's integration_patch_proposals instead of editing.
When the deliverables, check script, receipt and acceptance commands are all done and passing, stop and print a short summary.
EOF
done

./.venv/bin/python $P0/tools/ownership_audit.py snapshot

for ws in "${LANES[@]}"; do
  echo "[launch] $ws"
  nohup codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s workspace-write \
    -C "$PWD" -o "$P0/logs/$ws.last-message.md" - < "$P0/prompts/$ws.md" \
    > "$P0/logs/$ws.log" 2>&1 &
  echo "$!" > "$P0/logs/$ws.pid"
done
echo "[launch] pids: $(cat $P0/logs/*.pid | tr '\n' ' ')"
