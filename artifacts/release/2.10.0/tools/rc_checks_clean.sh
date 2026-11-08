#!/usr/bin/env bash
# Release-candidate checks on the clean-built distributions (see build_clean.sh):
# reproducibility, wheel contents, twine check, installed-wheel smoke,
# upgrade rehearsal and adoption snapshots. Run from the repository root.
set -uo pipefail
R=artifacts/release/2.10.0
COMMIT=$(tail -1 "$R/evidence/dist-sha256.txt" | awk '{print $3}')
W="$PWD/$R/dist/palimnex-2.10.0-py3-none-any.whl"; S="$PWD/$R/dist/palimnex-2.10.0.tar.gz"
echo "== candidate commit $COMMIT"; cat "$R/evidence/dist-sha256.txt"
echo "== reproducibility: rebuild into a scratch copy and compare"
cp "$R/evidence/dist-sha256.txt" /tmp/palimnex-rc-sha.first
"$R/tools/build_clean.sh" "$COMMIT" > /tmp/palimnex-rc-rebuild.log 2>&1
diff /tmp/palimnex-rc-sha.first "$R/evidence/dist-sha256.txt" && echo "reproducible=yes" || echo "reproducible=no"
echo "== wheel members under palimnex/tests (expect 0)"
python3 -c "import zipfile,sys;print(sum(x.startswith('palimnex/tests') for x in zipfile.ZipFile(sys.argv[1]).namelist()))" "$W"
echo "== twine check --strict"; /tmp/palimnex-rc-twine/bin/twine check --strict "$W" "$S"; echo "exit=$?"
V=/tmp/palimnex-rc-wheel; rm -rf $V; python3 -m venv $V && $V/bin/pip install --quiet --no-index "$W"
echo "== installed version"; $V/bin/palimnex --version; echo "exit=$?"
echo "== wheel smoke (core only)"; (cd /tmp && $V/bin/python "$OLDPWD/scripts/package_smoke.py" --core-only); echo "exit=$?"
echo "== upgrade rehearsal v2.9.0 -> 2.10.0"; ./.venv/bin/python scripts/upgrade_rehearsal.py --from v2.9.0 > $R/evidence/upgrade-rehearsal.json 2> $R/logs/upgrade-rehearsal.err; echo "exit=$?"
echo "== adoption snapshots (rgbhackathon optional, skipped: no commits)"
"$R/tools/adoption_smoke.sh" "$W" "$PWD/$R/evidence/adoption" \
  /media/kestl/andor/github/waveshares3 /media/kestl/andor/github/ereditas /media/kestl/andor/github/edgelinkd; echo "exit=$?"
echo "== done"
