from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from palimnex.concepts import (
    MAX_ALIAS_CHARS,
    MAX_REGISTRY_BYTES,
    ConceptRegistryError,
    canonical_registry_digest,
    load_registry,
    match_aliases,
    normalize_alias,
    parse_registry,
    verify_source_bindings,
)
from palimnex.locators import ResolvedSource


PROJECT_ID = "7d96bcda-e4bc-4aa4-be3e-24f761bacbd8"


class ConceptRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".palimnex.json").write_text(
            json.dumps({"project_slug": "palimnex", "project_id": PROJECT_ID}),
            encoding="utf-8",
        )
        (self.root / "docs").mkdir()
        self.source = self.root / "docs/source.md"
        self.source.write_bytes(b"current source\n")

    def locator(self, source_id: str = "docs/source.md") -> dict[str, object]:
        raw = self.source.read_bytes()
        return {
            "scheme": "repo",
            "source_id": source_id,
            "version": hashlib.sha256(raw).hexdigest(),
            "range": {"unit": "bytes", "start": 0, "end": len(raw)},
            "digest": hashlib.sha256(raw).hexdigest(),
        }

    def concept(
        self,
        concept_id: str = "concept.alpha",
        *,
        alias: str = "alpha concept",
        status: str = "approved",
        source_bindings: list[dict[str, object]] | None = None,
        predecessor: str | None = None,
    ) -> dict[str, object]:
        bindings = [self.locator()] if source_bindings is None and status == "approved" else source_bindings or []
        result: dict[str, object] = {
            "concept_id": concept_id,
            "canonical_name": concept_id.replace(".", " "),
            "aliases": [alias],
            "definition": "A bounded registry test concept.",
            "source_bindings": bindings,
            "status": status,
            "provenance": {"origin": "manual"},
        }
        if predecessor is not None:
            result["predecessor_concept_id"] = predecessor
        return result

    def document(
        self,
        concepts: list[dict[str, object]] | None = None,
        *,
        kind: str = "approved_registry",
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": "palimnex:concept-registry:v1",
            "project": {"project_slug": "palimnex", "project_id": PROJECT_ID},
            "registry_version": 1,
            "registry_kind": kind,
            "concepts": concepts or [self.concept()],
            "registry_digest": "",
            "authority": "historical_only",
            "authorizes_actions": False,
        }
        value["registry_digest"] = canonical_registry_digest(value)
        return value

    def rewrite_digest(self, document: dict[str, object]) -> dict[str, object]:
        document["registry_digest"] = canonical_registry_digest(document)
        return document

    def write_registry(self, document: dict[str, object], name: str = "registry.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def test_alias_normalization_unicode_case_punctuation_and_whitespace(self) -> None:
        self.assertEqual(normalize_alias("  CAFÉ—Source Binding  "), "café source binding")
        self.assertEqual(normalize_alias("cafe\u0301 source"), "café source")
        with self.assertRaises(ConceptRegistryError) as raised:
            normalize_alias("safe\ue000value")
        self.assertEqual(raised.exception.reason, "forbidden_unicode")
        for control in ("\t", "\n", "\r"):
            with self.subTest(control=repr(control)):
                with self.assertRaises(ConceptRegistryError) as raised:
                    normalize_alias(f"alpha{control}concept")
                self.assertEqual(raised.exception.reason, "forbidden_unicode")
                self.assertEqual(raised.exception.field, "alias")

    def test_canonical_digest_is_format_independent_and_binds_content(self) -> None:
        document = self.document()
        parsed_again = json.loads(json.dumps(document, indent=4, ensure_ascii=False))
        self.assertEqual(canonical_registry_digest(document), canonical_registry_digest(parsed_again))
        changed = copy.deepcopy(document)
        changed["authority"] = "changed"
        self.assertNotEqual(canonical_registry_digest(document), canonical_registry_digest(changed))

    def test_valid_registry_is_frozen_sorted_and_non_authorizing(self) -> None:
        concepts = [
            self.concept("concept.zulu", alias="zulu"),
            self.concept("concept.alpha", alias="alpha"),
        ]
        registry = parse_registry(self.document(concepts), root=self.root)
        self.assertEqual([item.concept_id for item in registry.concepts], ["concept.alpha", "concept.zulu"])
        self.assertEqual(registry.authority, "historical_only")
        self.assertFalse(registry.authorizes_actions)
        with self.assertRaises(FrozenInstanceError):
            registry.authority = "changed"  # type: ignore[misc]

    def test_exact_fields_types_and_bounds_are_enforced(self) -> None:
        cases: list[tuple[dict[str, object], str]] = []
        extra = self.document()
        extra["extra"] = True
        cases.append((extra, "invalid_fields"))
        boolean_version = self.document()
        boolean_version["registry_version"] = True
        cases.append((boolean_version, "version_mismatch"))
        long_alias = self.document()
        concept = copy.deepcopy(long_alias["concepts"])[0]  # type: ignore[index]
        concept["aliases"] = ["a" * (MAX_ALIAS_CHARS + 1)]
        long_alias["concepts"] = [concept]
        self.rewrite_digest(long_alias)
        cases.append((long_alias, "field_bound"))
        for document, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(ConceptRegistryError) as raised:
                    parse_registry(document, root=self.root)
                self.assertEqual(raised.exception.reason, reason)

    def test_project_identity_is_bound_to_explicit_root(self) -> None:
        document = self.document()
        document["project"] = {"project_slug": "other", "project_id": PROJECT_ID}
        self.rewrite_digest(document)
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(document, root=self.root)
        self.assertEqual(raised.exception.reason, "project_mismatch")

    def test_stored_alias_must_already_be_normalized_and_unique(self) -> None:
        for aliases, reason in ((["Alpha Concept"], "alias_not_normalized"), (["concept alpha"], "duplicate_matching_key")):
            with self.subTest(reason=reason):
                concept = self.concept(alias="unused")
                concept["aliases"] = aliases
                document = self.document([concept])
                with self.assertRaises(ConceptRegistryError) as raised:
                    parse_registry(document, root=self.root)
                self.assertEqual(raised.exception.reason, reason)

    def test_candidate_and_approved_paths_remain_separate(self) -> None:
        candidate = self.concept(status="candidate", source_bindings=[])
        registry = parse_registry(self.document([candidate], kind="candidate_set"), root=self.root)
        self.assertEqual(match_aliases(registry, "alpha concept").recognized_concept_ids, ())
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(
                self.document([candidate], kind="candidate_set"),
                root=self.root,
                expected_kind="approved_registry",
            )
        self.assertEqual(raised.exception.reason, "registry_kind_mismatch")
        document = self.document([candidate], kind="approved_registry")
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(document, root=self.root)
        self.assertEqual(raised.exception.reason, "registry_kind_status")

    def test_matching_reports_collisions_as_explicit_ambiguity(self) -> None:
        concepts = [
            self.concept("concept.beta", alias="memory graph"),
            self.concept("concept.alpha", alias="memory graph"),
            self.concept("concept.audit", alias="audit trail"),
        ]
        result = match_aliases(
            parse_registry(self.document(concepts), root=self.root),
            "What authority does the MEMORY-GRAPH and audit trail have?",
        )
        self.assertEqual(
            result.recognized_concept_ids,
            ("concept.alpha", "concept.audit", "concept.beta"),
        )
        self.assertEqual(result.ambiguous_concept_ids, ("concept.alpha", "concept.beta"))
        self.assertEqual(result.ambiguities[0].matched_alias, "memory graph")

    def test_matching_order_is_deterministic_across_input_order(self) -> None:
        concepts = [
            self.concept("concept.zulu", alias="zulu term"),
            self.concept("concept.alpha", alias="alpha term"),
        ]
        forward = parse_registry(self.document(concepts), root=self.root)
        reverse = parse_registry(self.document(list(reversed(concepts))), root=self.root)
        query = "zulu term then alpha term"
        self.assertEqual(match_aliases(forward, query), match_aliases(reverse, query))

    def test_superseded_and_withdrawn_concepts_do_not_match(self) -> None:
        old = self.concept(
            "concept.old", alias="retired name", status="superseded", source_bindings=[]
        )
        current = self.concept(
            "concept.current", alias="current name", predecessor="concept.old"
        )
        withdrawn = self.concept(
            "concept.withdrawn", alias="withdrawn name", status="withdrawn", source_bindings=[]
        )
        registry = parse_registry(self.document([withdrawn, current, old]), root=self.root)
        result = match_aliases(registry, "retired name withdrawn name current name")
        self.assertEqual(result.recognized_concept_ids, ("concept.current",))

    def test_supersession_forks_cycles_and_missing_relations_are_rejected(self) -> None:
        old = self.concept("concept.old", alias="old", status="superseded", source_bindings=[])
        first = self.concept("concept.first", alias="first", predecessor="concept.old")
        second = self.concept("concept.second", alias="second", predecessor="concept.old")
        fork = self.document([old, first, second])
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(fork, root=self.root)
        self.assertEqual(raised.exception.reason, "supersession_fork")

        cycle = self.document(
            [
                self.concept(
                    "concept.first",
                    alias="first",
                    status="superseded",
                    source_bindings=[],
                    predecessor="concept.second",
                ),
                self.concept(
                    "concept.second",
                    alias="second",
                    status="superseded",
                    source_bindings=[],
                    predecessor="concept.first",
                ),
            ]
        )
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(cycle, root=self.root)
        self.assertEqual(raised.exception.reason, "supersession_cycle")

        relation = self.concept()
        relation["relations"] = [{"relation_type": "related_to", "target_concept_id": "concept.missing"}]
        missing = self.document([relation])
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(missing, root=self.root)
        self.assertEqual(raised.exception.reason, "missing_relation_target")

    def test_placeholder_binding_digest_requires_explicit_fixture_flag(self) -> None:
        binding = self.locator()
        binding["digest"] = "0" * 64
        document = self.document([self.concept(source_bindings=[binding])])
        with self.assertRaises(ConceptRegistryError) as raised:
            parse_registry(document, root=self.root)
        self.assertEqual(raised.exception.reason, "placeholder_digest")
        registry = parse_registry(document, root=self.root, allow_placeholder_digests=True)
        self.assertEqual(registry.concepts[0].source_bindings[0].digest, "0" * 64)

    def test_load_rejects_duplicate_keys_and_tampering(self) -> None:
        document = self.document()
        path = self.write_registry(document)
        registry = load_registry(path.relative_to(self.root), root=self.root)
        self.assertEqual(registry.registry_digest, document["registry_digest"])

        path.write_text(
            json.dumps(document).replace(
                '"schema": "palimnex:concept-registry:v1",',
                '"schema": "palimnex:concept-registry:v1", "schema": "palimnex:concept-registry:v1",',
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ConceptRegistryError) as raised:
            load_registry(path.relative_to(self.root), root=self.root)
        self.assertEqual(raised.exception.reason, "duplicate_key")

        tampered = self.document()
        tampered["authority"] = "changed"
        self.write_registry(tampered)
        with self.assertRaises(ConceptRegistryError) as raised:
            load_registry("registry.json", root=self.root)
        self.assertEqual(raised.exception.reason, "registry_digest_mismatch")

    def test_load_refuses_secret_before_parsing_without_echo(self) -> None:
        canary = "".join(("sk", "-", "A1b2C3d4E5f6G7h8I9j0K1l2"))
        document = self.document()
        concept = copy.deepcopy(document["concepts"])[0]  # type: ignore[index]
        concept["definition"] = canary
        document["concepts"] = [concept]
        self.rewrite_digest(document)
        self.write_registry(document)
        with self.assertRaises(ConceptRegistryError) as raised:
            load_registry("registry.json", root=self.root)
        self.assertEqual(raised.exception.reason, "registry_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))

    def test_parse_refuses_secret_before_derivation_without_echo(self) -> None:
        for field in ("definition", "aliases"):
            with self.subTest(field=field):
                canary = "".join(("sk", "-", "ParseCanary", field, "9876543210"))
                document = self.document()
                concept = copy.deepcopy(document["concepts"])[0]  # type: ignore[index]
                concept[field] = canary if field == "definition" else [canary]
                document["concepts"] = [concept]
                self.rewrite_digest(document)
                with self.assertRaises(ConceptRegistryError) as raised:
                    parse_registry(document, root=self.root)
                self.assertEqual(raised.exception.reason, "registry_privacy_refused")
                self.assertNotIn(canary, str(raised.exception))
                self.assertNotIn(canary, repr(raised.exception))

    def test_load_refuses_oversize_traversal_and_symlink_inputs(self) -> None:
        oversize = self.root / "oversize.json"
        oversize.write_bytes(b"x" * (MAX_REGISTRY_BYTES + 1))
        for path in ("oversize.json", "../outside.json"):
            with self.subTest(path=path):
                with self.assertRaises(ConceptRegistryError) as raised:
                    load_registry(path, root=self.root)
                self.assertEqual(raised.exception.reason, "registry_read_refused")
        target = self.write_registry(self.document(), "target.json")
        (self.root / "link.json").symlink_to(target)
        with self.assertRaises(ConceptRegistryError) as raised:
            load_registry("link.json", root=self.root)
        self.assertEqual(raised.exception.reason, "registry_read_refused")

    def test_query_secret_is_refused_before_alias_derivation_without_echo(self) -> None:
        canary = "".join(("sk", "-", "AlphaNumericSegment", "9876543210"))
        registry = parse_registry(self.document(), root=self.root)
        with self.assertRaises(ConceptRegistryError) as raised:
            match_aliases(registry, canary)
        self.assertEqual(raised.exception.reason, "query_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))

    def test_query_whitespace_is_admitted_but_other_controls_are_refused(self) -> None:
        registry = parse_registry(self.document(), root=self.root)
        for control in ("\t", "\n", "\r"):
            with self.subTest(control=repr(control)):
                result = match_aliases(registry, f"alpha{control}concept")
                self.assertEqual(result.recognized_concept_ids, ("concept.alpha",))

                concept = self.concept(alias=f"alpha{control}concept")
                with self.assertRaises(ConceptRegistryError):
                    parse_registry(self.document([concept]), root=self.root)

        with self.assertRaises(ConceptRegistryError) as raised:
            match_aliases(registry, "alpha\u0007concept")
        self.assertEqual(raised.exception.reason, "forbidden_unicode")
        self.assertEqual(raised.exception.field, "query")

    def test_current_source_verifies_and_changed_or_missing_source_is_stale(self) -> None:
        registry = parse_registry(self.document(), root=self.root)
        current = verify_source_bindings(registry, root=self.root)
        self.assertEqual(current.verified_concept_ids, ("concept.alpha",))
        self.assertEqual(current.stale_concept_ids, ())

        self.source.write_bytes(b"changed source\n")
        changed = verify_source_bindings(registry, root=self.root)
        self.assertEqual(changed.stale_concept_ids, ("concept.alpha",))
        self.source.unlink()
        missing = verify_source_bindings(registry, root=self.root)
        self.assertEqual(missing.stale_concept_ids, ("concept.alpha",))

    def test_source_traversal_and_symlink_are_typed_refusals(self) -> None:
        traversal = self.locator()
        traversal["source_id"] = "../outside.md"
        registry = parse_registry(
            self.document([self.concept(source_bindings=[traversal])]), root=self.root
        )
        with self.assertRaises(ConceptRegistryError) as raised:
            verify_source_bindings(registry, root=self.root)
        self.assertEqual(raised.exception.reason, "source_path_refused")

        link = self.root / "docs/link.md"
        link.symlink_to(self.source)
        binding = self.locator("docs/link.md")
        registry = parse_registry(
            self.document([self.concept(source_bindings=[binding])]), root=self.root
        )
        with self.assertRaises(ConceptRegistryError) as raised:
            verify_source_bindings(registry, root=self.root)
        self.assertEqual(raised.exception.reason, "source_symlink_refused")

    def test_source_privacy_refusal_is_typed_and_does_not_echo(self) -> None:
        canary = "".join(("gh", "p_", "Ab9Cd8Ef7Gh6", "Jk5Lm4No3Pq2"))
        self.source.write_text(canary, encoding="utf-8")
        registry = parse_registry(self.document(), root=self.root)
        with self.assertRaises(ConceptRegistryError) as raised:
            verify_source_bindings(registry, root=self.root)
        self.assertEqual(raised.exception.reason, "source_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))

    def test_second_read_change_is_reported_as_stale(self) -> None:
        first = b"external source"
        second = b"changed source!"

        class ChangingResolver:
            api_version = 1

            def __init__(self) -> None:
                self.calls = 0

            def resolve(self, source_id: str, version: str) -> ResolvedSource:
                self.calls += 1
                return ResolvedSource(first if self.calls == 1 else second, "v1")

        binding = {
            "scheme": "external",
            "source_id": "record-1",
            "version": "v1",
            "range": {"unit": "bytes", "start": 0, "end": len(first)},
            "digest": hashlib.sha256(first).hexdigest(),
        }
        registry = parse_registry(
            self.document([self.concept(source_bindings=[binding])]), root=self.root
        )
        result = verify_source_bindings(
            registry, root=self.root, resolvers={"external": ChangingResolver()}
        )
        self.assertEqual(result.stale_concept_ids, ("concept.alpha",))
        self.assertEqual(result.bindings[0].reason, "source_drift")

    def test_external_resolver_foreign_project_claim_is_typed_refusal(self) -> None:
        raw = b"external source"

        class ForeignResolver:
            api_version = 1
            project_id = "00000000-0000-4000-8000-000000000002"

            def resolve(self, source_id: str, version: str) -> ResolvedSource:
                return ResolvedSource(raw, "v1")

        binding = {
            "scheme": "external",
            "source_id": "record-1",
            "version": "v1",
            "range": {"unit": "bytes", "start": 0, "end": len(raw)},
            "digest": hashlib.sha256(raw).hexdigest(),
        }
        registry = parse_registry(
            self.document([self.concept(source_bindings=[binding])]), root=self.root
        )
        with self.assertRaises(ConceptRegistryError) as raised:
            verify_source_bindings(
                registry, root=self.root, resolvers={"external": ForeignResolver()}
            )
        self.assertEqual(raised.exception.reason, "source_project_mismatch")

    def test_verification_rechecks_project_identity(self) -> None:
        registry = parse_registry(self.document(), root=self.root)
        (self.root / ".palimnex.json").write_text(
            json.dumps({"project_slug": "other", "project_id": PROJECT_ID}),
            encoding="utf-8",
        )
        with self.assertRaises(ConceptRegistryError) as raised:
            verify_source_bindings(registry, root=self.root)
        self.assertEqual(raised.exception.reason, "project_mismatch")


if __name__ == "__main__":
    unittest.main()
