#!/usr/bin/env bash
# Standalone Palimnex gate. Uses only temporary Redis/state and no model calls.
set -euo pipefail
cd "$(dirname "$0")/.."

PALIMNEX_CHECK_TMP="$(mktemp -d /tmp/palimnex-check.XXXXXX)"
export PYTHONPYCACHEPREFIX="$PALIMNEX_CHECK_TMP/pycache"

cleanup() {
  if [ -S "$PALIMNEX_CHECK_TMP/redis.sock" ] && command -v redis-cli >/dev/null 2>&1; then
    redis-cli -s "$PALIMNEX_CHECK_TMP/redis.sock" shutdown nosave >/dev/null 2>&1 || true
  fi
  rm -rf -- "$PALIMNEX_CHECK_TMP"
}
trap cleanup EXIT

python3 palimnex.py --version
python3 -m unittest discover -s palimnex/tests -p 'test_*.py'
python3 palimnex.py evaluate-challenges > "$PALIMNEX_CHECK_TMP/challenges.json"
python3 palimnex.py evaluate-longitudinal > "$PALIMNEX_CHECK_TMP/longitudinal.json"

python3 - "$PALIMNEX_CHECK_TMP/challenges.json" "$PALIMNEX_CHECK_TMP/longitudinal.json" <<'PY'
import json
import sys

challenge = json.load(open(sys.argv[1], encoding="utf-8"))
longitudinal = json.load(open(sys.argv[2], encoding="utf-8"))
assert challenge["status"] == "passed"
assert longitudinal["status"] == "passed"
assert longitudinal["model_calls"] == 0
print("offline gates: challenges and longitudinal replay passed")
PY

command -v redis-server >/dev/null 2>&1
command -v redis-cli >/dev/null 2>&1
redis-server --port 0 --unixsocket "$PALIMNEX_CHECK_TMP/redis.sock" \
  --unixsocketperm 600 --daemonize yes --pidfile "$PALIMNEX_CHECK_TMP/redis.pid" \
  --dir "$PALIMNEX_CHECK_TMP" --save '' --appendonly no \
  --logfile "$PALIMNEX_CHECK_TMP/redis.log"

python3 - "$PALIMNEX_CHECK_TMP/redis.sock" <<'PY'
import sys
from pathlib import Path
from palimnex import cache_v3, core

root = Path.cwd()
client = core.RedisClient("redis+unix://" + sys.argv[1] + "?db=0")
cache_v3.build_index(client, root)
_, valid = cache_v3.validate(client, root, deep=True)
assert valid
report = cache_v3.evaluate(client, 5, root)
assert report["status"] == "passed"
assert report["critical_passed"]
assert report["forbidden_clear"]
print(
    "isolated retrieval:",
    report["cases"],
    "cases, recall",
    report["recall_at_limit"],
)
PY

printf '%s\n' 'Palimnex standalone gate passed; no live ledger write or model call.'
