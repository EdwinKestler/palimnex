# R12: what "critical cases remain green" means for the shadow (coordinator correction, Phase 3)

**Finding.** The first full `evaluate-ontology-shadow` run exited 2 because
`critical_green` was false. Under `retrieve_sources` (the bounded context
retrieval that shadow mode extends, per R10), even the *baseline* passes only
4 of the 12 critical `v27` search cases at limit 5. The shadow passes 5. `v27`
is calibrated for the cache-backed `search` command, whose evaluation (`palimnex
evaluate`) passes every critical case and is unchanged. No case regressed: every
case that passes under the baseline also passes under the shadow, and
first-relevant ranks only improved or stayed equal.

**Cause.** SHADOW_SPEC section 5 defined `critical_green` as "every critical
case passes under the shadow". That is an absolute bar the baseline itself does
not meet, so it measures `retrieve_sources` versus the `v27` calibration, not
whether shadow mode is safe. The error was the coordinator's.

**Correction (meaning of the design's exit gate).** "All current critical
retrieval cases remain green" is satisfied when:
1. **Production retrieval is untouched.** `retrieve_sources`, `search`,
   `context` and `explain-search` output is byte-identical (verified separately
   by golden tests and by comparison against the committed code), and
   `palimnex evaluate` still passes every critical case.
2. **The shadow causes no critical regression.** Every critical case that
   passes under the baseline also passes under the shadow.

The evaluation gates therefore become:
- `baseline_identical`: for every evaluated case, the `shadow_retrieve`
  baseline equals a direct `retrieve_sources` call;
- `no_critical_regression`: replaces `critical_green`;
- `no_case_regression`: no case of any kind that passes under the baseline fails
  under the shadow;
- the others are unchanged: `no_new_forbidden`, `abstention_not_regressed`,
  `ambiguity_never_contributes`, `channels_visible`, `bounded`.

Absolute critical counts stay in the report for transparency.
`promotion_authorized` stays false.

**Observation recorded for the owner.** On the real repository,
`retrieve_sources` never abstains, even for unrelated queries ("bread",
"weather"), under both baseline and shadow. Abstention evidence therefore comes
from the v26 challenge negatives, where both abstain. The shadow channel adds
nothing to unrelated queries (no concept recognized).

## Owner confirmation

The repository owner confirmed R12 on 2026-11-06 and instructed the coordinator
to commit Phase 3. This confirmation accepts the paired safety interpretation
above for the Phase 3 exit gate only. It does not authorize returned-ranking
influence, promotion, Phase 4, a model/provider call, a push, publication, or
deployment.
