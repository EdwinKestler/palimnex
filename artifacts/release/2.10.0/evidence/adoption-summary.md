# 2.10.0 candidate — adoption smoke tests on other repositories (2026-11-08)

Wheel: the working-tree build `palimnex-2.10.0-py3-none-any.whl`, installed with
`--no-index` into a throwaway virtual environment `/tmp/palimnex-adoption/venv`.
Each snapshot is `git archive HEAD` of the repository extracted under
`/tmp/palimnex-adoption/<repo>` with its own Redis socket and ledger. The live
checkouts, their `.palimnex/` directories and the global pipx 2.9.0 install
were not touched. Script: `artifacts/release/2.10.0/tools/adoption_smoke.sh`;
per-repository results: `artifacts/release/2.10.0/evidence/adoption/*.json`.

| Repository | Commit (branch) | Config | Files / chunks | Result |
| --- | --- | --- | --- | --- |
| waveshares3 | `dd5bd71` (main) | committed | 53 / 91 | all steps exit 0 except `doctor` 2 and `evaluate` 1 (see notes) |
| ereditas | `b8dcec7` (main) | committed | 52 / 114 | same |
| edgelinkd | `34c626f` (rebrand-n2link) | committed | 326 / 1624 | same; index 5.1 s, validate --deep 4.5 s, search 2.4 s |
| rgbhackathon | none | — | — | **skipped**: not a Git repository with commits and no top-level configuration of its own; the script's snapshot of it is empty and its row in `adoption/rgbhackathon.json` is not a valid test (owner marked it optional) |

Steps run per snapshot: `--version` (2.10.0), `doctor`, `redis start`,
`index`, `validate --deep`, `status`, `search`, `context`
(`project-memory:context:v1`, 5 items), `explain-search`
(`coverage_state: registry_absent`, as expected: the Palimnex registry binds
the Palimnex checkout only), `ontology-status` (off), `semantic-status`
(disabled), `evaluate`, `ledger-init`, `ledger-status`, `feedback-report`
(empty), `redis stop`.

Notes:

- `doctor` exits 2 (`action_needed`) in every snapshot because it runs before
  `redis start` (Redis warning), the snapshot is not a Git work tree (git-ignore
  check skipped), and edgelinkd has code directories outside its configured
  include patterns. None is a 2.10.0 defect.
- `evaluate` exits 1 because none of these repositories configures an
  `evaluation_fixture` ("evaluation_fixture must name a frozen JSON file"),
  which is the documented behaviour.
- The installed-wheel smoke from this working-tree build failed one assertion
  (`palimnex/tests` present in the wheel) because the build reused a stale
  `build/lib` directory; the candidate wheel is therefore rebuilt from a clean
  `git archive` of the release commit and re-checked (see the candidate report).
