# Copied-bundle mode: deprecate or verify

Status: decided. The owner chose option A, deprecation (see "Owner
decisions"). It is implemented in 2.9.0: `doctor` reports the
install mode, and the documentation deprecates the copied bundle.

## Problem

The copied-bundle install puts `palimnex.py` and the `palimnex/` directory
into another repository and runs `python3 palimnex.py COMMAND`. The wrapper
sets `PALIMNEX_ROOT` to its own directory with `os.environ.setdefault`
(`palimnex.py`), and `palimnex.core.ROOT` reads `PALIMNEX_ROOT` or the
working directory (`palimnex/core.py:65`). That works, but:

- **Nothing checks the copy.** A partial copy, or a copy made on top of an
  older `palimnex/`, mixes modules from different versions without warning.
  Files removed in a newer version stay behind. `docs/UPGRADING.md` tells
  operators to delete before copying, but nothing verifies that they did.
- **The code is outside the index by default.** `include_palimnex` defaults to
  `false` and `palimnex/` is not matched by `DEFAULT_PATTERNS`, so `status`
  and `validate` never see the copied code.
- **`doctor` cannot tell the install mode.** It reports
  `Palimnex <BUNDLE_VERSION>` from `core.py` alone
  (`palimnex/onboarding.py`, `_environment_checks`), which is wrong for a
  mixed copy.
- **Two copies can run against one ledger.** When a repository holds a copied
  `palimnex/` and the package is also installed, the `palimnex` console
  script imports the installed package (its `sys.path[0]` is the scripts
  directory), while `python3 palimnex.py` and `python3 -m palimnex` from the
  repository root import the copy. Two versions then share one ledger. That is
  the downgrade hazard `docs/UPGRADING.md` describes for `adapter_receipt`
  under 2.7.0.
- **The launcher can drift.** Before 2.8.0, copied repositories also copied
  `scripts/palimnex_redis.sh`. Since 2.8.0, `palimnex/redis_launcher.sh`
  ships inside the package directory and `palimnex redis` runs it; a test
  keeps it byte-identical to `scripts/palimnex_redis.sh` in this repository.
  A copy of `scripts/palimnex_redis.sh` in another repository has no such
  check.

Since 2.8.0, Palimnex is on PyPI through Trusted Publishing with PEP 740
attestations, and `pipx`, `uv tool` and `pip` pins are documented. That
weakens the case for keeping a second, unverified distribution channel.

## Install-mode detection (needed by both options)

Both options need `doctor` to know how it is running. `doctor` uses this
read-only classification (`onboarding.installation`), with only the standard
library and no network:

| Mode | Rule |
|---|---|
| `installed` | `importlib.metadata.distribution("palimnex")` exists and `locate_file("palimnex/__init__.py")` resolves to the imported `palimnex/__init__.py` |
| `editable` | the distribution's `direct_url.json` has `dir_info.editable: true` and the imported package is the project source directory |
| `source_checkout` | no matching distribution, and the imported package's parent has a `pyproject.toml` declaring `name = "palimnex"` (this repository) |
| `copied_bundle` | anything else |

Reliability:

- Distribution metadata is the strong signal. Wheel installs through `pip`,
  `pipx` and `uv tool` all write it.
- `PALIMNEX_ROOT` is not a signal. The wrapper sets it, but operators also set
  it for installed commands (`docs/INSTALL.md` says so).
- The presence of `palimnex.py` in the root is not a signal either, because
  this repository has one.
- Unusual layouts (`PYTHONPATH` tricks, zip imports, vendoring) fall through
  to `copied_bundle`, which is the conservative answer.

Two further read-only checks cover the two-copies case:

- **Shadowing.** A distribution is installed, but the imported package is not
  that distribution's files. Report both paths and both versions.
- **Second copy in the root.** `ROOT/palimnex/core.py` exists beside an
  installed distribution and is not the imported file. Read its
  `BUNDLE_VERSION` with a bounded text match (no import) and compare.

Cost: a metadata lookup and at most one bounded file read. No hashing.

## Option A: deprecate the copied bundle

**Documentation.** `docs/INSTALL.md` marks copying as deprecated and keeps the
PyPI pins as the only install path for adopting repositories.
`docs/UPGRADING.md` gains a "Copied bundle to package" section:

1. Stop agents. Run `ledger-status` and `ledger-backup` with the copied
   version.
2. Install the same or a newer version from PyPI with `pipx`, `uv tool` or
   `pip`, keeping the extras.
3. In one commit, remove `palimnex.py`, `palimnex/` and any copied
   `scripts/palimnex_redis.sh` from the adopting repository.
4. Change agent instructions from `python3 palimnex.py` to `palimnex`, and the
   MCP configuration to `palimnex-mcp`.
5. Run installed commands from the repository root, or set `PALIMNEX_ROOT`.
6. Run `palimnex doctor` and `palimnex index --incremental`.

`.palimnex.json`, `.palimnex/`, the ledger path and the ledger itself do not
change: the root and every configured path stay the same.

**`doctor`.** An `install_mode` check: `info` for `installed`, `editable` and
`source_checkout`; `warn` for `copied_bundle`, naming the migration section.
The shadowing and second-copy checks are `fail` when the versions differ and
`warn` when they are equal.

**Timeline.**

- 2.9.0: deprecation in documentation and the `doctor` warning.
- Through 2.x: copied bundles keep working and stay covered by upgrade notes.
- 3.0.0: the copy instructions leave `docs/INSTALL.md`, and `doctor` escalates
  `copied_bundle` to `fail`.

The runtime never refuses to run in a copied bundle, because that would strand
existing ledgers. This repository keeps `palimnex.py` as its source-checkout
entry point (AGENTS.md and the gate use it).

**Redis launcher.** Adopting repositories use `palimnex redis`.
`scripts/palimnex_redis.sh` stays canonical in this repository: the
`redis-owner-socket` critical evaluation case and the byte-identity test
depend on it.

**Offline installs.** The core wheel has no dependencies, so
`pip install palimnex-X.Y.Z-py3-none-any.whl` works without a network. The
optional GitHub Releases step (prompt 3.8b) could attach the wheel for
operators who cannot reach PyPI.

## Option B: an integrity manifest

**Generation.** A release step (`scripts/bundle_manifest.py`) writes
`palimnex/BUNDLE_MANIFEST.json` with:

- a new identifier, `palimnex:bundle-manifest:v1`;
- `BUNDLE_VERSION`;
- the sorted `path`, `bytes` and `sha256` of every tracked file in
  `palimnex.py`, `palimnex/` and `scripts/palimnex_redis.sh` at the release
  commit (`git ls-files`), excluding the manifest itself and `__pycache__`.

**Verification.** In `copied_bundle` mode, `doctor` hashes the listed files
(about 1.3 MB across 71 tracked files today) and reports missing, changed and
extra files under `palimnex/`.

**Where the manifest lives** is the hard part:

- **B1, committed.** Every pull request that touches `palimnex/` must
  regenerate it, or a CI check fails. Most changes touch `palimnex/`, so this
  means churn on nearly every pull request. Committing it only in release
  commits instead leaves `main` with a stale manifest that `doctor` would
  report, unless it gains a development exemption.
- **B2, release asset only.** The publish workflow builds and attests a
  `palimnex-bundle-X.Y.Z.tar.gz` that contains the manifest. A copy taken
  from a Git tag has no manifest, so the documented "copy from the tag" path
  stays unverified.

**What it proves.** A manifest that travels with the files detects accidental
partial or mixed copies. It does not detect tampering, because whoever edits
the files can edit the manifest. Tamper evidence needs a signature, and the
signed path already exists: the attested PyPI distribution.

**Upgrades.** Delete the old `palimnex/` and `palimnex.py`, copy the new ones
from the tag or the release asset, run `doctor` to verify, then reindex. This
stays manual; the manifest only catches mistakes.

## Evaluation fixtures

Neither option changes `palimnex/evaluation/v25.json`, `v26.json` or the
active `v27.json`, or their pinned digests.

- Option B's manifest records their digests without changing them. In this
  repository, `palimnex/BUNDLE_MANIFEST.json` would not match the
  `.palimnex.json` include patterns (`palimnex/**/*.py`, `palimnex/**/*.md`,
  `palimnex/schemas/**/*.json`), so it would stay out of the index.
- Under either option, the implementing pull request edits indexed
  documentation (`docs/INSTALL.md`, `docs/UPGRADING.md`, the READMEs). It must
  run incremental indexing, deep validation and the frozen evaluation, and
  keep `critical_margin_warnings` empty. `docs/DESIGN.md` section 10 forbids
  rewording documentation to dodge query vocabulary.

## CI cost

| | Option A | Option B |
|---|---|---|
| New tests | install-mode classification with fake distribution metadata; the shadowing and second-copy checks | the same, plus manifest generation and verification |
| New CI work | none | B1: a regenerate-and-compare check on every pull request; B2: a build-and-attest step in the publish workflow |
| Ongoing maintenance | documentation only | manifest churn (B1) or a second release artifact (B2) |

## Comparison

| | Option A: deprecate | Option B: manifest |
|---|---|---|
| Detects a partial or mixed copy | indirectly: `doctor` steers operators to the package, where `pip` replaces whole distributions | yes |
| Detects two copies against one ledger | yes (shadowing and second-copy checks) | only with the same checks |
| Tamper evidence | yes, through PEP 740 attestations on PyPI | no, unless the manifest is signed |
| Upgrade path | `pipx upgrade`, `uv tool upgrade` or `pip install -U` | manual delete, copy, verify |
| Release machinery | none | a generator plus B1 churn or a B2 asset |
| Risk to existing copies | none: copies keep working through 2.x | none |

## Recommendation: option A

The package already provides what the copied bundle lacks: one version per
install, whole-distribution replacement on upgrade, and attested provenance.
Option B would keep a second distribution channel alive to prove only
self-consistency, at a recurring CI or release cost. The install-mode,
shadowing and second-copy checks address the most dangerous case (two
versions writing one ledger), and option A needs them anyway.

The implementing change:

1. Add the install-mode classification and the shadowing and second-copy
   checks to `palimnex/onboarding.py`, with tests.
2. Add the deprecation and the "Copied bundle to package" steps to
   `docs/INSTALL.md` and `docs/UPGRADING.md`, adjust both READMEs, and record
   the change in `palimnex/CHANGELOG.md`.
3. Pass the standard gate, `mypy`, the installed-wheel smoke test, and the
   frozen evaluation with no fixture change and empty
   `critical_margin_warnings`.

## Owner decisions

1. **Option A, deprecation.** Option B is not implemented.
2. **Timeline as proposed.** The copied bundle is deprecated in 2.9.0. The
   copy instructions leave `docs/INSTALL.md`, and `doctor` escalates
   `copied_bundle` to `fail` in 3.0.0. The runtime never refuses a copied
   bundle.
3. **Severity as proposed.** `install_shadowing` and `second_copy` fail when
   the versions differ and warn when they match. A version that cannot be
   read counts as different.
4. **Wheel on GitHub Releases** (prompt 3.8b) remains a separate, optional
   release step and is not part of this change.
