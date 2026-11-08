#!/usr/bin/env bash
# Coordinator gate for Phase 5 (unsandboxed). Usage: gate.sh LOGFILE
# Leaves Redis in the state it was found.
set -uo pipefail
L="$1"; : > "$L"
step() { local name="$1"; shift; echo "== $name" >> "$L"; "$@" >> "$L" 2>&1; echo "exit=$?" >> "$L"; }
if pgrep -f "redis-server.bin unixsocket:$PWD/.palimnex/redis/redis.sock" > /dev/null; then REDIS_WAS=running; else REDIS_WAS=stopped; fi
echo "redis_initial_state=$REDIS_WAS" >> "$L"
[[ $REDIS_WAS == stopped ]] && ./scripts/palimnex_redis.sh start >> "$L" 2>&1
step "full unittest" ./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'
step "mypy" ./.venv/bin/python -m mypy
step "index" python3 palimnex.py index
step "validate --deep" python3 palimnex.py validate --deep
step "evaluate" python3 palimnex.py evaluate --limit 5
step "ledger-status" python3 palimnex.py ledger-status
step "evaluate-ontology-shadow" python3 palimnex.py evaluate-ontology-shadow
step "ontology-status" python3 palimnex.py ontology-status
step "status" python3 palimnex.py status
step "standard gate" env PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh
step "experience.py diff is R16 only" bash -c "git diff --numstat -- palimnex/experience.py"
step "production files unchanged vs HEAD" git diff --exit-code --stat -- palimnex/retrieval.py palimnex/durable.py palimnex/semantic.py palimnex/cache_v3.py palimnex/ontology_influence.py palimnex/schemas/memory-event.v1.schema.json
[[ $REDIS_WAS == stopped ]] && ./scripts/palimnex_redis.sh stop >> "$L" 2>&1
echo "redis_final_state=$(pgrep -f "redis-server.bin unixsocket:$PWD/.palimnex/redis/redis.sock" > /dev/null && echo running || echo stopped)" >> "$L"
echo "== done" >> "$L"
