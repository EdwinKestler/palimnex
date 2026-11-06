from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import unicodedata
from pathlib import Path
from typing import Any

from palimnex.concepts import (
    Concept,
    ConceptProvenance,
    ConceptRegistry,
    ProjectIdentity,
    canonical_registry_digest,
    parse_registry,
)
from palimnex.coverage import (
    MAX_COVERAGE_COLLECTION_ITEMS,
    MAX_NESTED_DETAIL_ITEMS,
    CoverageError,
    build_coverage_receipt,
    build_explain_search,
    canonical_receipt_digest,
    query_digest,
    validate_receipt,
)
from palimnex.locators import ResolvedSource, SourceLocator, SourceRange
from palimnex.retrieval import retrieve_sources


PROJECT_ID = "11111111-1111-4111-8111-111111111111"


class StaticResolver:
    api_version = 1

    def __init__(self, content: bytes, version: str = "v1") -> None:
        self.content = content
        self.version = version

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        return ResolvedSource(self.content, self.version)


class MissingResolver:
    api_version = 1

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        raise FileNotFoundError


class FailingResolver:
    api_version = 1

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        raise RuntimeError("provider detail must be suppressed")


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".palimnex.json").write_text(
            json.dumps({"project_slug": "fixture", "project_id": PROJECT_ID}),
            encoding="utf-8",
        )
        (self.root / "docs").mkdir()
        self.current = self.root / "docs/current.md"
        self.current.write_bytes(b"current source\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def repo_binding(self, path: str = "docs/current.md", *, digest: str | None = None) -> dict[str, Any]:
        target = self.root / path
        raw = target.read_bytes() if target.exists() else b"missing"
        return {
            "scheme": "repo",
            "source_id": path,
            "version": hashlib.sha256(raw).hexdigest(),
            "range": {"unit": "bytes", "start": 0, "end": len(raw)},
            "digest": digest or hashlib.sha256(raw).hexdigest(),
        }

    def external_binding(
        self,
        *,
        source_id: str = "record-1",
        version: str = "v1",
        content: bytes = b"external",
        digest: str | None = None,
    ) -> dict[str, Any]:
        return {
            "scheme": "fixture",
            "source_id": source_id,
            "version": version,
            "range": {"unit": "bytes", "start": 0, "end": len(content)},
            "digest": digest or hashlib.sha256(content).hexdigest(),
        }

    def concept(
        self,
        concept_id: str,
        alias: str,
        *,
        bindings: list[dict[str, Any]] | None = None,
        status: str = "approved",
    ) -> dict[str, Any]:
        return {
            "concept_id": concept_id,
            "canonical_name": concept_id.replace(".", " "),
            "aliases": [alias],
            "definition": "Fixture definition.",
            "source_bindings": self._default_bindings(bindings, status),
            "status": status,
            "provenance": {"origin": "manual"},
        }

    def _default_bindings(
        self,
        bindings: list[dict[str, Any]] | None,
        status: str,
    ) -> list[dict[str, Any]]:
        if bindings is not None:
            return bindings
        return [self.repo_binding()] if status == "approved" else []

    def registry(
        self,
        concepts: list[dict[str, Any]],
        *,
        kind: str = "approved_registry",
    ) -> ConceptRegistry:
        document: dict[str, Any] = {
            "schema": "palimnex:concept-registry:v1",
            "project": {"project_slug": "fixture", "project_id": PROJECT_ID},
            "registry_version": 1,
            "registry_kind": kind,
            "concepts": concepts,
            "registry_digest": "0" * 64,
            "authority": "historical_only",
            "authorizes_actions": False,
        }
        document["registry_digest"] = canonical_registry_digest(document)
        return parse_registry(document, root=self.root)

    def search(
        self,
        query: str,
        *,
        results: list[dict[str, Any]] | None = None,
        omitted: int = 0,
        byte_budget: int = 8192,
        items_bytes: int = 2,
    ) -> dict[str, Any]:
        selected = [] if results is None else results
        return {
            "query": query,
            "results": selected,
            "candidate_count": len(selected) + omitted,
            "omitted_count": omitted,
            "byte_budget": byte_budget,
            "items_bytes": items_bytes,
            "budget_unit": "serialized_utf8_bytes",
            "cache_consulted": False,
            "retrieval_mode": "local_snapshot_rrf",
            "scan_scope": "full_admitted_corpus",
            "corpus_fingerprint": "c" * 64,
            "checkout_id": hashlib.sha256(str(self.root.resolve()).encode()).hexdigest(),
            "semantic_influence": False,
            "authorizes_actions": False,
        }

    def build(
        self,
        registry: ConceptRegistry,
        query: str,
        *,
        search: dict[str, Any] | None = None,
        resolvers: dict[str, Any] | None = None,
        retrieval_limit: int | None = None,
    ) -> dict[str, Any]:
        return build_coverage_receipt(
            registry,
            query,
            self.search(query) if search is None else search,
            root=self.root,
            resolvers=resolvers,
            retrieval_limit=retrieval_limit,
        )

    def test_query_digest_vectors_preserve_case_and_whitespace(self) -> None:
        self.assertEqual(query_digest("A\r\n B\rC"), query_digest("A\n B\nC"))
        self.assertNotEqual(query_digest("Alpha"), query_digest("alpha"))
        self.assertNotEqual(query_digest("Alpha"), query_digest(" Alpha "))
        decomposed = "Cafe\u0301"
        self.assertEqual(query_digest(decomposed), query_digest(unicodedata.normalize("NFC", decomposed)))
        with self.assertRaises(CoverageError) as empty:
            query_digest(" \t\n")
        self.assertEqual(empty.exception.reason, "empty_query")
        with self.assertRaises(CoverageError) as oversized:
            query_digest("x" * (8192 + 1))
        self.assertEqual(oversized.exception.reason, "query_byte_bound")

    def test_status_rows_and_integer_zero_over_zero(self) -> None:
        answerable = self.build(self.registry([self.concept("concept.alpha", "alpha")]), "alpha")
        self.assertEqual(answerable["status"], "answerable")

        no_match = self.build(self.registry([self.concept("concept.alpha", "alpha")]), "weather")
        self.assertEqual(no_match["status"], "unanswerable")
        self.assertIs(type(no_match["coverage"]["numerator"]), int)
        self.assertIs(type(no_match["coverage"]["denominator"]), int)
        self.assertEqual(no_match["coverage"], {"numerator": 0, "denominator": 0})

        partial_registry = self.registry(
            [
                self.concept("concept.alpha", "alpha"),
                self.concept("concept.beta", "beta", bindings=[self.external_binding()]),
            ]
        )
        partial = self.build(partial_registry, "alpha beta")
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["uncovered_concepts"]["items"], ["concept.beta"])

    def test_stale_only_is_unanswerable_and_verified_plus_stale_is_partial(self) -> None:
        stale_binding = self.external_binding(digest="f" * 64)
        stale_registry = self.registry(
            [self.concept("concept.stale", "stale", bindings=[stale_binding])]
        )
        stale = self.build(
            stale_registry,
            "stale",
            resolvers={"fixture": StaticResolver(b"external")},
        )
        self.assertEqual(stale["status"], "unanswerable")
        self.assertEqual(stale["stale_concepts"]["items"][0]["reason"], "digest_changed")

        mixed = self.registry(
            [
                self.concept("concept.alpha", "alpha"),
                self.concept("concept.stale", "stale", bindings=[stale_binding]),
            ]
        )
        receipt = self.build(
            mixed,
            "alpha stale",
            resolvers={"fixture": StaticResolver(b"external")},
        )
        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["coverage"], {"numerator": 1, "denominator": 2})

    def test_ambiguity_precedes_other_covered_concepts(self) -> None:
        registry = self.registry(
            [
                self.concept("concept.cache", "generation"),
                self.concept("concept.ledger", "generation"),
                self.concept("concept.source", "source binding"),
            ]
        )
        receipt = self.build(registry, "generation and source binding")
        self.assertEqual(receipt["status"], "ambiguous")
        self.assertEqual(
            [item["concept_id"] for item in receipt["covered_concepts"]["items"]],
            ["concept.source"],
        )
        candidates = receipt["ambiguous_concepts"]["items"][0]["candidate_concept_ids"]
        self.assertEqual(candidates, ["concept.cache", "concept.ledger"])

    def test_each_stale_reason_mapping(self) -> None:
        missing = self.registry(
            [
                self.concept(
                    "concept.missing",
                    "missing",
                    bindings=[self.repo_binding("docs/missing.md")],
                )
            ]
        )
        version = self.registry(
            [self.concept("concept.version", "version", bindings=[self.external_binding()])]
        )
        digest = self.registry(
            [
                self.concept(
                    "concept.digest",
                    "digest",
                    bindings=[self.external_binding(digest="f" * 64)],
                )
            ]
        )
        unavailable = self.registry(
            [self.concept("concept.unavailable", "unavailable", bindings=[self.external_binding()])]
        )
        cases = (
            (missing, "missing", None, "missing"),
            (version, "version", {"fixture": StaticResolver(b"external", "v2")}, "version_changed"),
            (digest, "digest", {"fixture": StaticResolver(b"external")}, "digest_changed"),
            (unavailable, "unavailable", {"fixture": FailingResolver()}, "unavailable"),
        )
        for registry, query, resolvers, expected in cases:
            with self.subTest(reason=expected):
                receipt = self.build(registry, query, resolvers=resolvers)
                self.assertEqual(receipt["stale_concepts"]["items"][0]["reason"], expected)

    def test_unregistered_external_binding_is_uncovered(self) -> None:
        registry = self.registry(
            [self.concept("concept.unbound", "unbound", bindings=[self.external_binding()])]
        )
        receipt = self.build(registry, "unbound")
        self.assertEqual(receipt["uncovered_concepts"]["items"], ["concept.unbound"])
        self.assertEqual(receipt["stale_concepts"]["total_count"], 0)

    def test_candidate_and_cross_project_registries_are_refused(self) -> None:
        candidate = self.registry(
            [self.concept("concept.alpha", "alpha", status="candidate")],
            kind="candidate_set",
        )
        with self.assertRaises(CoverageError) as candidate_error:
            self.build(candidate, "alpha")
        self.assertEqual(candidate_error.exception.reason, "registry_kind_mismatch")

        approved = self.registry([self.concept("concept.alpha", "alpha")])
        foreign = ConceptRegistry(
            approved.schema,
            ProjectIdentity("fixture", "22222222-2222-4222-8222-222222222222"),
            approved.registry_version,
            approved.registry_kind,
            approved.concepts,
            approved.registry_digest,
            approved.authority,
            approved.authorizes_actions,
        )
        with self.assertRaises(CoverageError) as cross_project:
            self.build(foreign, "alpha")
        self.assertEqual(cross_project.exception.reason, "project_mismatch")

    def test_r7_path_symlink_and_privacy_refusals_do_not_echo(self) -> None:
        traversal = self.registry(
            [
                self.concept(
                    "concept.path",
                    "path",
                    bindings=[
                        {
                            "scheme": "repo",
                            "source_id": "../outside.md",
                            "version": "current",
                            "range": {"unit": "bytes", "start": 0, "end": 1},
                            "digest": "f" * 64,
                        }
                    ],
                )
            ]
        )
        with self.assertRaises(CoverageError) as path_error:
            self.build(traversal, "path")
        self.assertEqual(path_error.exception.reason, "source_path_refused")

        link = self.root / "docs/link.md"
        link.symlink_to(self.current)
        symlink = self.registry(
            [self.concept("concept.link", "link", bindings=[self.repo_binding("docs/link.md")])]
        )
        with self.assertRaises(CoverageError) as symlink_error:
            self.build(symlink, "link")
        self.assertEqual(symlink_error.exception.reason, "source_symlink_refused")

        canary = "".join(("gh", "p_", "Ab9Cd8Ef7Gh6", "Jk5Lm4No3Pq2"))
        self.current.write_text(canary, encoding="utf-8")
        private = self.registry(
            [self.concept("concept.private", "private", bindings=[self.repo_binding()])]
        )
        with self.assertRaises(CoverageError) as privacy_error:
            self.build(private, "private")
        self.assertEqual(privacy_error.exception.reason, "source_privacy_refused")
        self.assertNotIn(canary, str(privacy_error.exception))

    def test_query_privacy_refusal_does_not_echo(self) -> None:
        canary = "".join(("sk", "-", "AlphaNumericSegment", "9876543210"))
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        with self.assertRaises(CoverageError) as raised:
            self.build(registry, canary)
        self.assertEqual(raised.exception.reason, "query_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))

    def test_checkout_and_search_query_mismatches_are_refused(self) -> None:
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        wrong_query = self.search("other")
        with self.assertRaises(CoverageError) as query_error:
            self.build(registry, "alpha", search=wrong_query)
        self.assertEqual(query_error.exception.reason, "query_mismatch")
        wrong_checkout = self.search("alpha")
        wrong_checkout["checkout_id"] = "0" * 64
        with self.assertRaises(CoverageError) as checkout_error:
            self.build(registry, "alpha", search=wrong_checkout)
        self.assertEqual(checkout_error.exception.reason, "checkout_mismatch")

    def test_real_retrieval_attributes_byte_budget_omission(self) -> None:
        self.current.write_text("alpha source\n", encoding="utf-8")
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        search = retrieve_sources(
            "alpha",
            root=self.root,
            limit=5,
            byte_budget=128,
            include_graph=False,
        )
        self.assertEqual(search["results"], [])
        self.assertEqual(search["omitted_count"], 1)
        receipt = self.build(
            registry,
            "alpha",
            search=search,
            retrieval_limit=5,
        )
        state = receipt["retrieval_state"]
        self.assertFalse(state["retrieval_truncated"])
        self.assertTrue(state["byte_budget_omission"]["omitted"])
        self.assertEqual(state["byte_budget_omission"]["omitted_item_count"], 1)
        self.assertEqual(state["byte_budget_omission"]["byte_budget"], 128)
        self.assertEqual(state["byte_budget_omission"]["used_bytes"], 2)

    def test_retrieval_limit_attribution_does_not_change_status(self) -> None:
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        truncated_search = self.search(
            "alpha",
            results=[{}],
            omitted=2,
            byte_budget=8192,
            items_bytes=100,
        )
        truncated = self.build(
            registry,
            "alpha",
            search=truncated_search,
            retrieval_limit=1,
        )
        self.assertEqual(truncated["status"], "answerable")
        self.assertTrue(truncated["retrieval_state"]["retrieval_truncated"])
        self.assertFalse(truncated["retrieval_state"]["byte_budget_omission"]["omitted"])

        complete = self.build(
            registry,
            "alpha",
            search=self.search("alpha"),
            retrieval_limit=5,
        )
        self.assertFalse(complete["retrieval_state"]["retrieval_truncated"])
        self.assertFalse(complete["retrieval_state"]["byte_budget_omission"]["omitted"])

        unknown = self.build(
            registry,
            "alpha",
            search=self.search("alpha", omitted=1),
        )
        self.assertTrue(unknown["retrieval_state"]["retrieval_truncated"])
        self.assertFalse(unknown["retrieval_state"]["byte_budget_omission"]["omitted"])

    def test_invalid_or_inconsistent_retrieval_limit_is_refused(self) -> None:
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        with self.assertRaises(CoverageError) as invalid:
            self.build(registry, "alpha", retrieval_limit=0)
        self.assertEqual(invalid.exception.reason, "invalid_retrieval_limit")

        search = self.search("alpha", results=[{}, {}])
        with self.assertRaises(CoverageError) as inconsistent:
            self.build(registry, "alpha", search=search, retrieval_limit=1)
        self.assertEqual(inconsistent.exception.reason, "retrieval_limit_mismatch")

    def test_top_level_and_nested_collection_truncation(self) -> None:
        tokens = tuple(f"t{i:02d}" for i in range(24))
        aliases = tuple(
            " ".join(tokens[start:end])
            for start in range(len(tokens))
            for end in range(start + 1, len(tokens) + 1)
        )[: MAX_COVERAGE_COLLECTION_ITEMS + 1]
        concepts = tuple(
            Concept(
                f"concept.term{i:03d}",
                f"not queried {i:03d}",
                (alias,),
                "definition",
                (),
                (),
                "approved",
                None,
                ConceptProvenance("manual"),
            )
            for i, alias in enumerate(aliases)
        )
        registry = ConceptRegistry(
            "palimnex:concept-registry:v1",
            ProjectIdentity("fixture", PROJECT_ID),
            1,
            "approved_registry",
            concepts,
            "d" * 64,
            "historical_only",
            False,
        )
        query = " ".join(tokens)
        receipt = self.build(registry, query)
        self.assertEqual(receipt["recognized_concepts"]["total_count"], len(concepts))
        self.assertEqual(len(receipt["recognized_concepts"]["items"]), MAX_COVERAGE_COLLECTION_ITEMS)
        self.assertTrue(receipt["recognized_concepts"]["truncated"])
        self.assertTrue(receipt["retrieval_state"]["coverage_output_truncated"])

        aliases = tuple(f"a{i:02d}" for i in range(MAX_NESTED_DETAIL_ITEMS + 1))
        nested_concept = Concept(
            "concept.nested",
            "not queried",
            aliases,
            "definition",
            (),
            (),
            "approved",
            None,
            ConceptProvenance("manual"),
        )
        nested_registry = ConceptRegistry(
            registry.schema,
            registry.project,
            1,
            "approved_registry",
            (nested_concept,),
            "e" * 64,
            "historical_only",
            False,
        )
        nested = self.build(nested_registry, " ".join(aliases))
        recognized = nested["recognized_concepts"]["items"][0]
        self.assertEqual(recognized["matched_alias_count"], len(aliases))
        self.assertEqual(len(recognized["matched_aliases"]), MAX_NESTED_DETAIL_ITEMS)
        self.assertTrue(recognized["matched_aliases_truncated"])

    def test_deterministic_ordering_digest_stability_and_tamper_detection(self) -> None:
        registry = self.registry(
            [
                self.concept("concept.zeta", "zeta"),
                self.concept("concept.alpha", "alpha"),
            ]
        )
        first = self.build(registry, "zeta alpha")
        second = self.build(registry, "zeta alpha")
        self.assertEqual(first, second)
        self.assertEqual(
            [item["concept_id"] for item in first["recognized_concepts"]["items"]],
            ["concept.alpha", "concept.zeta"],
        )
        self.assertEqual(first["receipt_digest"], canonical_receipt_digest(first))
        tampered = copy.deepcopy(first)
        tampered["status"] = "partial"
        with self.assertRaises(CoverageError):
            validate_receipt(tampered)
        tampered = copy.deepcopy(first)
        tampered["receipt_digest"] = "0" * 64
        with self.assertRaises(CoverageError) as digest_error:
            validate_receipt(tampered)
        self.assertEqual(digest_error.exception.reason, "receipt_digest_mismatch")

    def test_validate_receipt_rejects_overlap_arithmetic_and_ordering(self) -> None:
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        receipt = self.build(registry, "alpha")
        overlap = copy.deepcopy(receipt)
        overlap["uncovered_concepts"] = {
            "items": ["concept.alpha"],
            "total_count": 1,
            "truncated": False,
        }
        overlap["receipt_digest"] = canonical_receipt_digest(overlap)
        with self.assertRaises(CoverageError) as overlap_error:
            validate_receipt(overlap)
        self.assertEqual(overlap_error.exception.reason, "classification_overlap")

        ordered_registry = self.registry(
            [self.concept("concept.alpha", "alpha"), self.concept("concept.beta", "beta")]
        )
        unordered = self.build(ordered_registry, "alpha beta")
        unordered["recognized_concepts"]["items"].reverse()
        unordered["receipt_digest"] = canonical_receipt_digest(unordered)
        with self.assertRaises(CoverageError) as ordering_error:
            validate_receipt(unordered)
        self.assertEqual(ordering_error.exception.reason, "ordering_or_duplicate")

    def test_valid_accepted_examples_pass_runtime_validation(self) -> None:
        fixtures = (
            Path(__file__).parents[2]
            / "artifacts/design/ontology-phase-0/coverage/examples/valid"
        )
        for path in sorted(fixtures.glob("*.json")):
            with self.subTest(path=path.name):
                validate_receipt(json.loads(path.read_text(encoding="utf-8")))

    def test_explain_search_enabled_and_absent_deep_copy_inputs(self) -> None:
        registry = self.registry([self.concept("concept.alpha", "alpha")])
        search = self.search("alpha")
        receipt = self.build(registry, "alpha", search=search)
        original_search = copy.deepcopy(search)
        original_receipt = copy.deepcopy(receipt)
        enabled = build_explain_search(
            search,
            receipt,
            registry_path="ontology/concept-registry.v1.json",
            registry_source="default",
        )
        enabled["search"]["new"] = True
        enabled["coverage"]["new"] = True
        self.assertEqual(search, original_search)
        self.assertEqual(receipt, original_receipt)
        self.assertEqual(enabled["coverage_state"], "enabled")
        self.assertEqual(set(enabled), {
            "schema", "search", "coverage_state", "coverage", "registry", "authority", "authorizes_actions"
        })

        absent = build_explain_search(
            search,
            None,
            registry_path="ontology/concept-registry.v1.json",
            registry_source="default",
        )
        self.assertEqual(absent["coverage_state"], "registry_absent")
        self.assertIsNone(absent["coverage"])
        with self.assertRaises(CoverageError) as traversal:
            build_explain_search(
                search,
                None,
                registry_path="../registry.json",
                registry_source="argument",
            )
        self.assertEqual(traversal.exception.reason, "registry_path_refused")


if __name__ == "__main__":
    unittest.main()
