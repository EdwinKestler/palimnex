You are the bounded implementer for Palimnex ontology workstream `ontology-closure-registry`, fix round 1.
Write only inside your task card's owned_paths (artifacts/ontology/closure/candidate/ and your receipt). Re-read
AGENTS.md, .agents/skills/palimnex-ontology-workstream/SKILL.md, artifacts/ontology/closure/tasks/ontology-closure-registry.json
and artifacts/ontology/closure/briefs/REGISTRY_BRIEF.md. The blind rule still applies: never open the forbidden
evaluation paths and never run evaluate-*, retrieval or explain-search.

The independent review (artifacts/ontology/closure/round-1/ontology-closure-registry.review-receipt.json) rejected the
candidate. Fix exactly these:
1. MAJOR concept.retention_eligibility: palimnex/retention.py changed for the 2.10.0 release (a deprecation message near
   line 648; the coordinator's release lane removed the `--no-snapshot` CLI option). Re-pin every retention.py binding
   to the current working tree: recompute version and digest, and confirm each bound range still covers the same
   symbol (adjust line numbers only if the symbol moved). Then re-verify ALL 45 bindings against the current tree;
   re-pin any other stale one the same way. Never change which symbol a binding names.
2. MAJOR concept.source_locator: alias "source binding verification" also describes concepts.verify_source_bindings
   (concept.concept_registry). Replace it with a locator-specific phrase.
3. MAJOR concept.ontology_activation: alias "enabled ontology channel" names the ontology retrieval channel
   (concept.ontology_shadow). Replace it with an activation-gate-specific phrase.
4. MINORs, replace or drop (keep 2-5 aliases each): concept.ontology_shadow "shadow rank diff"; concept.retrieval_fusion
   "retrieval channel ranking"; concept.audit_graph "signed audit graph export" (signing is optional);
   concept.concept_registry "candidate registry parser" (it parses both kinds); concept.coverage_receipt
   "covered uncovered concepts".
5. MINOR check_candidate.py: also run security.scan_text over the full serialized candidate document, and add a check
   that no alias of one concept contains the canonical name or another alias of a different concept as a substring
   (catching cross-concept descriptions the exact-key check misses).
Re-check every remaining alias for cross-concept ambiguity by reading the code, and record the changes in NOTES.md
(old alias -> new alias, reason). Recompute the registry digest. Rerun your acceptance commands, update and validate
your receipt, run git status, and print a summary with every changed alias and every re-pinned binding.
