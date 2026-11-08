# Read-only review: CI test fixes for the Palimnex 2.10.0 candidate

You are an independent reviewer. Do not write, edit, create or delete any file,
and do not run Palimnex commands, Redis, the network or the test suite.
Never open `.env*`, `.palimnex/`, `secrets/` or `benchmark/`.

Scope: commits `5edc164` ("Make CI tests platform-independent") and `ce4fde2`
("Pick a wrapper test binary that runs under a copied name") on branch
`release/2.10.0`. Inspect them with `git diff 3364735 ce4fde2 -- palimnex` and
`git show 5edc164`, and read the three
changed test files and the code they exercise
(`palimnex/redis_launcher.py` or wherever the launcher's executable-identity
check lives, and the `checkout_id` computation used by
`palimnex/retrieval_shadow*`/`ontology_influence`/`ontology_shadow` paths;
find it with grep).

Context: CI on PR #24 failed on Ubuntu because the wrapper test copied
coreutils `sleep`, which multicall coreutils rejects when invoked under another
name, and on macOS because golden digests hashed `checkout_id` computed from
`root.resolve()` and `/tmp` resolves to `/private/tmp`. A copied `/bin/sh`
then passed on Ubuntu but failed on macOS (its `/bin/sh` re-executes another
shell), so `ce4fde2` probes `/bin/sleep` first and falls back to `/bin/sh`.

Answer:
1. Does each change keep the test's original guarantee (the launcher still
   proves it accepts a wrapper that execs the real server binary; the golden
   digests still pin every output field, and `checkout_id` is still checked
   rather than ignored)? Name any assertion that became weaker.
2. Is the fix portable to Linux and macOS runners (e.g. `/bin/sh` copied under
   a different name, `-c` loop, process cleanup)?
3. Do the commits touch any non-test file, any file bound by
   `ontology/concept-registry.v1.json`, or any module counted by
   `influence_implementation_digest`?

Output a single JSON object, and nothing after it:
{"status": "accepted" | "accepted_with_limits" | "rejected",
 "findings": [{"severity": "BLOCKER|MAJOR|MINOR|NOTE", "file": "...", "finding": "..."}],
 "limitations": ["..."]}
