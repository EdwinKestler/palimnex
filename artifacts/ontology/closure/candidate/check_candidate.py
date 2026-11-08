#!/usr/bin/env python3
"""Validate the source-derived Palimnex candidate concept registry."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = Path(__file__).with_name("concept-registry.candidate.json")
REGISTRY_RELATIVE = REGISTRY_PATH.relative_to(ROOT)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from palimnex.concepts import (  # noqa: E402
    canonical_registry_digest,
    load_registry,
    normalize_alias,
    verify_source_bindings,
)
from palimnex.security import scan_text  # noqa: E402


EXPECTED_IDS = (
    "concept.source_admission",
    "concept.source_locator",
    "concept.retrieval_fusion",
    "concept.context_assembly",
    "concept.cache_generation",
    "concept.durable_ledger",
    "concept.retention_eligibility",
    "concept.ledger_migration",
    "concept.memory_pack",
    "concept.audit_graph",
    "concept.concept_registry",
    "concept.coverage_receipt",
    "concept.ontology_shadow",
    "concept.ontology_activation",
    "concept.semantic_shadow",
    "concept.retrieval_feedback",
)

FORBIDDEN_STANDALONE_ALIASES = frozenset(
    {
        "memory",
        "search",
        "graph",
        "registry",
        "cache",
        "ledger",
        "index",
        "context",
        "source",
        "feedback",
        "evaluation",
        "shadow",
        "migration",
        "retention",
        "pack",
        "audit",
        "concept",
        "coverage",
        "semantic",
        "ontology",
    }
)


def fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    serialized_document = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if scan_text(serialized_document):
        fail("serialized candidate document has a privacy-scanner finding")
    registry = load_registry(
        REGISTRY_RELATIVE,
        root=ROOT,
        expected_kind="candidate_set",
    )

    if document.get("registry_digest") != canonical_registry_digest(document):
        fail("registry digest does not match canonical content")
    if tuple(item.get("concept_id") for item in document.get("concepts", ())) != EXPECTED_IDS:
        fail("candidate concepts do not match the required ordered 16-concept set")
    if len(registry.concepts) != len(EXPECTED_IDS):
        fail("candidate registry must contain exactly 16 concepts")

    keys: dict[str, str] = {}
    concept_keys_by_id: dict[str, tuple[str, ...]] = {}
    alias_count = 0
    binding_count = 0
    for concept in registry.concepts:
        if concept.status != "candidate":
            fail(f"{concept.concept_id} is not a candidate")
        if concept.provenance.origin != "model_candidate":
            fail(f"{concept.concept_id} has unexpected provenance")
        if not 2 <= len(concept.aliases) <= 5:
            fail(f"{concept.concept_id} must have 2-5 aliases")
        if not 1 <= len(concept.source_bindings) <= 3:
            fail(f"{concept.concept_id} must have 1-3 source bindings")
        if scan_text(concept.canonical_name) or scan_text(concept.definition):
            fail(f"{concept.concept_id} contains privacy-scanner findings")

        concept_keys = (normalize_alias(concept.canonical_name), *concept.aliases)
        concept_keys_by_id[concept.concept_id] = concept_keys
        for key in concept_keys:
            owner = keys.get(key)
            if owner is not None and owner != concept.concept_id:
                fail(f"matching-key collision between {owner} and {concept.concept_id}")
            keys[key] = concept.concept_id

        for alias in concept.aliases:
            if alias in FORBIDDEN_STANDALONE_ALIASES:
                fail(f"{concept.concept_id} uses forbidden standalone alias")
            if len(alias.split()) < 2:
                fail(f"{concept.concept_id} alias is not multi-word")
            if normalize_alias(alias) != alias:
                fail(f"{concept.concept_id} alias is not normalized")
            if scan_text(alias):
                fail(f"{concept.concept_id} alias has a privacy-scanner finding")

        for binding in concept.source_bindings:
            if binding.scheme != "repo":
                fail(f"{concept.concept_id} has a non-repository binding")
        alias_count += len(concept.aliases)
        binding_count += len(concept.source_bindings)

    for concept in registry.concepts:
        for alias in concept.aliases:
            for other_concept_id, other_keys in concept_keys_by_id.items():
                if other_concept_id == concept.concept_id:
                    continue
                if any(other_key in alias for other_key in other_keys):
                    fail(
                        f"{concept.concept_id} alias contains a matching key from "
                        f"{other_concept_id}"
                    )

    approved_view = replace(
        registry,
        registry_kind="approved_registry",
        concepts=tuple(replace(concept, status="approved") for concept in registry.concepts),
    )
    verification = verify_source_bindings(approved_view, root=ROOT)
    if verification.stale_concept_ids:
        fail("one or more candidate source bindings are stale")
    if len(verification.bindings) != binding_count:
        fail("not every candidate source binding was verified")
    if any(not result.verified for result in verification.bindings):
        fail("one or more candidate source bindings failed verification")

    print(
        json.dumps(
            {
                "status": "valid_candidate",
                "registry_kind": registry.registry_kind,
                "registry_digest": registry.registry_digest,
                "concept_count": len(registry.concepts),
                "alias_count": alias_count,
                "binding_count": binding_count,
                "verified_binding_count": len(verification.bindings),
                "concept_ids": list(EXPECTED_IDS),
                "authority": registry.authority,
                "authorizes_actions": registry.authorizes_actions,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
