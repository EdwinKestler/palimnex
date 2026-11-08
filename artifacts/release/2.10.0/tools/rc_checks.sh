#!/usr/bin/env bash
# Release-candidate checks on the built wheel: installed-wheel smoke, upgrade rehearsal, adoption snapshots.
set -uo pipefail
R=artifacts/release/2.10.0
WHEEL=$(ls $R/dist/palimnex-2.10.0-py3-none-any.whl)
V=/tmp/palimnex-rc-wheel; rm -rf $V; python3 -m venv $V && $V/bin/pip install --quiet --no-index "$WHEEL"
echo "== wheel smoke (core only)"; (cd /tmp && $V/bin/python "$OLDPWD/scripts/package_smoke.py" --core-only); echo "exit=$?"
echo "== upgrade rehearsal v2.9.0 -> working tree"; ./.venv/bin/python scripts/upgrade_rehearsal.py --from v2.9.0 > $R/evidence/upgrade-rehearsal.json 2> $R/logs/upgrade-rehearsal.err; echo "exit=$?"
echo "== adoption snapshots"; $R/tools/adoption_smoke.sh "$PWD/$WHEEL" "$PWD/$R/evidence/adoption" \
  /media/kestl/andor/github/waveshares3 /media/kestl/andor/github/ereditas /media/kestl/andor/github/edgelinkd /media/kestl/andor/github/rgbhackathon; echo "exit=$?"
echo "== done"
