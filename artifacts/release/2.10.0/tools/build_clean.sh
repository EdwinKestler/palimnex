#!/usr/bin/env bash
# Build the 2.10.0 candidate wheel and sdist from a git archive of one commit,
# so no stale build/ or untracked file can enter the distribution.
# Usage: build_clean.sh <commit>   (run from the repository root)
set -euo pipefail
COMMIT=$(git rev-parse "${1:?commit required}")
R=artifacts/release/2.10.0
SRC=/tmp/palimnex-rc-src
rm -rf "$SRC" && mkdir -p "$SRC"
git archive "$COMMIT" | tar -x -C "$SRC"
rm -rf "$R/dist" && mkdir -p "$R/dist"
OUT="$PWD/$R/dist"
export SOURCE_DATE_EPOCH=$(git show -s --format=%ct "$COMMIT")
(cd "$SRC" && python3 -c "
import sys; out = sys.argv[1]  # build_meta rewrites sys.argv
import setuptools.build_meta as b
print(b.build_sdist(out)); print(b.build_wheel(out))" "$OUT")
{ (cd "$R/dist" && sha256sum palimnex-2.10.0-py3-none-any.whl palimnex-2.10.0.tar.gz); echo "built from $COMMIT"; } > "$R/evidence/dist-sha256.txt"
cat "$R/evidence/dist-sha256.txt"
