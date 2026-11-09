# Releasing Palimnex

This runbook records the reviewed release transaction established by 2.10.0.
It does not authorize a merge, tag, push, PyPI publication, GitHub release, or
configuration activation. Obtain explicit owner approval for the exact release
and keep implementation, integration, publication, and live verification as
separate states.

## 1. Prepare the candidate

1. Work from a dedicated release branch based on current `main`.
2. Set `palimnex.core.BUNDLE_VERSION`, update the changelog and every current
   install/version reference, and document upgrade and rollback behavior.
3. Keep unrelated and untracked work out of the release. Never package
   `.palimnex/`, ledgers, Redis state, packs, keys, credentials, logs, or
   private evidence.
4. If indexed files change, reindex, deep-validate, and run the frozen
   evaluation. Review ranking movement rather than changing labels to fit it.
5. If registry-bound files change, verify every source binding and update the
   registry only through reviewed maintenance. Documentation-bound test
   fixtures may be re-pinned under R18 only when their selected-range digests
   and intended labels remain unchanged.
6. Build from a clean export of the pinned candidate commit, not from a dirty
   working tree.

Required candidate checks include:

```bash
./scripts/palimnex_check.sh
python3 -m mypy
python3 -m build
python3 -m twine check --strict dist/*
```

Test the installed wheel outside the checkout, with core-only and crypto-extra
smoke runs. Confirm its runtime version, package metadata, included files, and
the release's documented removals and compatibility behavior. Rehearse the
supported upgrade path and any explicitly selected downstream repositories in
isolated copies with separate Redis and ledger state.

## 2. Review the release pull request

Require the complete CI matrix and upgrade rehearsal to pass on the final
code-or-test commit. A later records-only commit must still pass CI and must be
shown not to alter product code, tests, registry-bound files, or workflows.

Before approval, record:

- candidate commit and clean-build provenance;
- wheel and source-distribution SHA-256 values;
- test, type, build, smoke, upgrade, and downstream-adoption results;
- independent-review findings and accepted limits;
- current registry and promotion-evidence state; and
- features that remain off, held, deferred, or separately authorized.

Release documentation may name the new version before publication only when
merge, tag, publication, verification, and GitHub release are treated as one
controlled transaction. If that transaction fails after merge, stop and
repair forward; do not rewrite published or merged history.

## 3. Publish as one controlled transaction

With explicit owner approval:

1. Mark the reviewed release PR ready and merge it with the selected method.
2. Verify the resulting merge commit contains the reviewed candidate content.
3. Create and push an annotated `vX.Y.Z` tag on that exact commit.
4. Manually dispatch `.github/workflows/publish.yml` with `version: X.Y.Z`.
5. Wait for both workflow jobs to pass.
6. Verify the PyPI files and installed package independently.
7. Create the GitHub release from the same tag and mark it latest only when
   appropriate.

The workflow checks out the existing tag, runs the standard gate and strict
typing, builds and checks both distributions, tests the installed wheel, and
publishes through PyPI Trusted Publishing. It does not create the tag or the
GitHub release. Only its publish job receives an OIDC token.

## 4. Verify publication

In a throwaway environment installed from PyPI:

- confirm `palimnex --version` and `palimnex.__version__`;
- run the package smoke test without and with the crypto dependency;
- confirm documented removed options fail with the expected exit status;
- compare downloaded PyPI file hashes with PyPI and the publication record;
- compare the published wheel's member list and payloads with the tested
  candidate, explaining build-tool metadata-only differences; and
- confirm the GitHub release points to the annotated tag and has the intended
  notes and assets.

A successful upload is not enough: the installed PyPI artifact is the live
acceptance target.

## 5. Record and close

Add a post-release record in a separate records-only pull request. It should
name the merge commit, tag, workflow run, PyPI hashes, installed verification,
GitHub release, test state, cache/ledger state, Git state, and every feature
whose activation remains separate. Update the changelog or adoption status
only when those facts are true.

Do not silently turn on an optional feature as part of release closure. In
particular, an approved ontology registry and promotable evidence do not enable
ontology influence; `.palimnex.json` activation remains its own reviewed owner
decision.
