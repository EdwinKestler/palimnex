# Palimnex 2.10.1 publication record

Date: 2026-11-08 (America/Guatemala)

The owner authorized the complete reliability-fix and 2.10.1 release sequence.
The transaction completed without a repair commit or history rewrite.

| Step | Result |
| --- | --- |
| Release PR | PR [#27](https://github.com/EdwinKestler/palimnex/pull/27) merged with merge commit `eac999a5520e2c01e6f28b449772b8d0c8889fda` |
| Reviewed content | The merge tree `d68be5fad57b0f71b6abb9c74b71dfb0f806de04` is identical to reviewed PR head `90f6909013ebf2129b07ad417f70dfd999110271` |
| Final PR CI | Run [42562051353](https://github.com/EdwinKestler/palimnex/actions/runs/42562051353): Python 3.11 through 3.14 on Ubuntu, Python 3.11 on macOS, and the upgrade rehearsal passed |
| Tag | Annotated tag `v2.10.1` (tag object `3b4da6f750ad985ad0afe200b998ca2b75b28428`) points to the exact merge commit |
| Publish workflow | Run [42562824603](https://github.com/EdwinKestler/palimnex/actions/runs/42562824603) on `main`: both `build` and trusted `publish` jobs passed |
| PyPI | Version [2.10.1](https://pypi.org/project/palimnex/2.10.1/) published and independently verified |
| GitHub release | [Palimnex 2.10.1](https://github.com/EdwinKestler/palimnex/releases/tag/v2.10.1), latest, not draft or prerelease, with no attached assets |

## Published distributions

PyPI reports `Requires-Python >=3.11`. Files downloaded from PyPI matched the
digests and sizes returned by its version API:

| File | SHA-256 | Size |
| --- | --- | ---: |
| `palimnex-2.10.1-py3-none-any.whl` | `fea6ec4fd7aef6e26e1952adbeeac5de3e0583778bebbf703d6772245cfd0547` | 312,911 bytes |
| `palimnex-2.10.1.tar.gz` | `2228ff4bfeb76f0a4c07455d83e9cd70e5b5ad84e78d65d9d18a06a9696946eb` | 416,937 bytes |

The published wheel and the candidate wheel built from the reviewed source
have the same 80 member names and byte-identical member payloads. Their whole
file hashes differ only because ZIP archive metadata differs.

## Independent installed-package verification

Fresh throwaway environments, outside the checkout and with pip's cache
disabled, installed `palimnex==2.10.1` and `palimnex[crypto]==2.10.1` from the
normal PyPI simple index after propagation completed.

- package metadata, `palimnex.__version__`, and `palimnex --version` all report
  `2.10.1`;
- the core-only resource, CLI, and SDK smoke passed;
- the crypto resource, CLI, SDK, and offline-evaluation smoke passed;
- ChaCha20-Poly1305 construction through the installed portable-pack path
  passed; and
- the removed `index --no-snapshot` option exits with status 2.

Before the simple index propagated, the version API and distribution files
were already live. That transient lag was not treated as installed-package
acceptance; the normal version-based installs above were repeated afterward.

## Post-publication boundaries

- The large-corpus Redis fix is implemented, merged, published, and live in
  the PyPI package.
- Ontology influence remains off and `.palimnex.json` is unchanged.
- The semantic provider remains held; feedback has no ranking influence; the
  offline graph explorer and local-model experiment remain separate work.
- The repository ledger retained integrity with zero events; the release did
  not migrate or write durable history.
- No cache, ledger, credentials, key material, packs, logs, or live database
  was included in either distribution.
