# R17 — release documentation names 2.10.0 before publication (coordinator decision, for owner confirmation)

Review round 1 of the release preparation
(`artifacts/release/2.10.0/reviews/release-prep.round-1.json`) raised two
BLOCKERs: `docs/INSTALL.md` says "Palimnex 2.10.0 is published on PyPI", and
`README.md` pins installs to `palimnex[crypto]==2.10.0` and the tag `v2.10.0`,
neither of which exists yet.

Decision: keep the 2.10.0 install text in the release branch, as the 2.9.0
release did (`git show v2.9.0:docs/INSTALL.md` says "Palimnex 2.9.0 is
published on PyPI"). The publish workflow builds from the tag, so the tagged
commit must already carry the final install instructions. The text becomes
true at publication, and the candidate stays unpublished until the owner
approves it separately.

Condition: the release pull request is merged only together with the tag and
PyPI publication (merge, then tag `v2.10.0`, then publish). Until then the
documentation lives only on the `release/2.10.0` branch, and the pull request
description and the handoff state this.
