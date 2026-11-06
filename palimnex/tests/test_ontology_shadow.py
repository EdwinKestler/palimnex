from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from palimnex.concepts import (
    ConceptRegistry,
    ConceptRegistryError,
    canonical_registry_digest,
    parse_registry,
)
from palimnex.durable import canonical_json
from palimnex.locators import ResolvedSource, SourceRange, select_range
from palimnex.ontology_shadow import (
    MAX_ONTOLOGY_CANDIDATES,
    OntologyChannel,
    ShadowComparisonError,
    build_shadow_comparison,
    ontology_channel,
    validate_shadow_comparison,
)


PROJECT_ID = "11111111-1111-4111-8111-111111111111"


class StaticResolver:
    api_version = 1

    def __init__(self, content: bytes, version: str = "v1") -> None:
        self.content = content
        self.version = version

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        return ResolvedSource(self.content, self.version)


class OntologyShadowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / ".palimnex.json").write_text(
            json.dumps({"project_slug": "fixture", "project_id": PROJECT_ID}),
            encoding="utf-8",
        )
        (self.root / "docs").mkdir()
        self.source = self.root / "docs/source.md"
        self.source.write_bytes(b"one\ntwo\nthree\nfour\nfive\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def binding(
        self,
        *,
        path: str = "docs/source.md",
        unit: str = "lines",
        start: int = 1,
        end: int | None = None,
        digest: str | None = None,
    ) -> dict[str, Any]:
        raw = (self.root / path).read_bytes()
        last = start if end is None else end
        bounds = SourceRange(unit, start, last)
        selected = select_range(raw, bounds)
        return {
            "scheme": "repo",
            "source_id": path,
            "version": hashlib.sha256(raw).hexdigest(),
            "range": {"unit": unit, "start": start, "end": last},
            "digest": digest or hashlib.sha256(selected).hexdigest(),
        }

    def external_binding(self, content: bytes = b"external") -> dict[str, Any]:
        return {
            "scheme": "fixture",
            "source_id": "record-1",
            "version": "v1",
            "range": {"unit": "bytes", "start": 0, "end": len(content)},
            "digest": hashlib.sha256(content).hexdigest(),
        }

    def concept(
        self,
        concept_id: str,
        alias: str,
        binding: dict[str, Any],
        *,
        status: str = "approved",
    ) -> dict[str, Any]:
        return {
            "concept_id": concept_id,
            "canonical_name": concept_id.replace(".", " "),
            "aliases": [alias],
            "definition": "Fixture definition.",
            "source_bindings": [binding] if status == "approved" else [],
            "status": status,
            "provenance": {"origin": "manual"},
        }

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

    def chunk(
        self,
        start: int,
        end: int | None = None,
        *,
        path: str = "docs/source.md",
        pointer: str | None = None,
    ) -> dict[str, Any]:
        last = start if end is None else end
        return {
            "path": path,
            "start_line": start,
            "end_line": last,
            "pointer": pointer or f"{path}:{start}-{last}",
        }

    def empty_comparison_channel(self) -> OntologyChannel:
        return OntologyChannel((), (), (), (), (), (), (), 0, False)

    def baseline(self, pointers: list[str]) -> dict[str, Any]:
        return {
            "query": "ordinary question",
            "results": [{"pointer": pointer} for pointer in pointers],
            "candidate_count": len(pointers),
            "byte_budget": 8192,
        }

    def comparison(
        self,
        baseline_pointers: list[str],
        shadow_pointers: list[str] | None = None,
    ) -> dict[str, Any]:
        shadow = baseline_pointers if shadow_pointers is None else shadow_pointers
        return build_shadow_comparison(
            query="ordinary question",
            registry=None,
            channel=self.empty_comparison_channel(),
            baseline=self.baseline(baseline_pointers),
            shadow_results=[
                {"pointer": pointer, "channels": {"lexical": rank}}
                for rank, pointer in enumerate(shadow, 1)
            ],
            shadow_candidate_count=len(shadow),
            shadow_items_bytes=2,
            limit=5,
        )

    def comparison_with_concept_id(self, concept_id: str) -> dict[str, Any]:
        document = self.comparison([])
        ontology = document["ontology_channel"]
        ontology["recognized_concept_ids"] = [concept_id]
        ontology["excluded_uncovered"] = [concept_id]
        digest_input = dict(document)
        digest_input.pop("comparison_digest")
        document["comparison_digest"] = hashlib.sha256(
            canonical_json(digest_input)
        ).hexdigest()
        return document

    def test_no_registry_returns_empty_channel(self) -> None:
        self.assertEqual(
            ontology_channel(None, "anything", [self.chunk(1)], root=self.root),
            self.empty_comparison_channel(),
        )

    def test_candidate_registry_is_refused(self) -> None:
        candidate = self.registry(
            [self.concept("concept.alpha", "alpha", self.binding(), status="candidate")],
            kind="candidate_set",
        )
        with self.assertRaises(ShadowComparisonError) as raised:
            ontology_channel(candidate, "alpha", [self.chunk(1)], root=self.root)
        self.assertEqual(raised.exception.reason, "registry_kind_mismatch")

    def test_contributing_concept_ranks_overlapping_chunk(self) -> None:
        registry = self.registry(
            [self.concept("concept.alpha", "alpha", self.binding(start=2, end=2))]
        )
        result = ontology_channel(
            registry,
            "alpha",
            [self.chunk(1), self.chunk(2), self.chunk(3)],
            root=self.root,
        )
        self.assertEqual(result.ranking, (1,))
        self.assertEqual(result.contributing_concept_ids, ("concept.alpha",))
        self.assertEqual(result.candidate_count, 1)
        self.assertFalse(result.truncated)

    def test_ambiguous_stale_and_uncovered_concepts_are_excluded(self) -> None:
        concepts = [
            self.concept("concept.first", "shared", self.binding(start=1)),
            self.concept("concept.second", "shared", self.binding(start=2)),
            self.concept("concept.stale", "drifted", self.binding(start=3, digest="f" * 64)),
            self.concept("concept.uncovered", "detached", self.external_binding()),
        ]
        result = ontology_channel(
            self.registry(concepts),
            "shared drifted detached",
            [self.chunk(1), self.chunk(2), self.chunk(3)],
            root=self.root,
        )
        self.assertEqual(result.ambiguous_concept_ids, ("concept.first", "concept.second"))
        self.assertEqual(result.excluded_ambiguous, result.ambiguous_concept_ids)
        self.assertEqual(result.excluded_stale, ("concept.stale",))
        self.assertEqual(result.excluded_uncovered, ("concept.uncovered",))
        self.assertEqual(result.contributing_concept_ids, ())
        self.assertEqual(result.ranking, ())

    def test_line_and_byte_overlap_edges_and_non_repo_mapping(self) -> None:
        raw = self.source.read_bytes()
        line_four_start = raw.index(b"four")
        concepts = [
            self.concept("concept.lines", "line span", self.binding(start=2, end=3)),
            self.concept(
                "concept.bytes",
                "byte span",
                self.binding(unit="bytes", start=line_four_start, end=line_four_start + 4),
            ),
            self.concept("concept.external", "outside", self.external_binding()),
        ]
        result = ontology_channel(
            self.registry(concepts),
            "line span byte span outside",
            [self.chunk(1), self.chunk(2), self.chunk(3), self.chunk(4), self.chunk(5)],
            root=self.root,
            resolvers={"fixture": StaticResolver(b"external")},
        )
        self.assertEqual(result.ranking, (1, 2, 3))
        self.assertEqual(
            result.contributing_concept_ids,
            ("concept.bytes", "concept.external", "concept.lines"),
        )
        self.assertNotIn(0, result.ranking)
        self.assertNotIn(4, result.ranking)

    def test_two_concepts_on_one_chunk_rank_it_first(self) -> None:
        registry = self.registry(
            [
                self.concept("concept.alpha", "alpha", self.binding(start=1, end=2)),
                self.concept("concept.beta", "beta", self.binding(start=2, end=2)),
            ]
        )
        result = ontology_channel(
            registry,
            "alpha beta",
            [self.chunk(1), self.chunk(2)],
            root=self.root,
        )
        self.assertEqual(result.ranking, (1, 0))

    def test_one_verified_binding_is_contributing_despite_other_drift(self) -> None:
        concept = self.concept(
            "concept.alpha", "alpha", self.binding(start=2, end=2)
        )
        concept["source_bindings"].append(self.binding(start=3, digest="e" * 64))
        result = ontology_channel(
            self.registry([concept]),
            "alpha",
            [self.chunk(2), self.chunk(3)],
            root=self.root,
        )
        self.assertEqual(result.contributing_concept_ids, ("concept.alpha",))
        self.assertEqual(result.excluded_stale, ())
        self.assertEqual(result.ranking, (0,))

    def test_pointer_breaks_equal_score_ties_deterministically(self) -> None:
        registry = self.registry(
            [self.concept("concept.alpha", "alpha", self.binding(start=1, end=2))]
        )
        chunks = [
            self.chunk(1, pointer="z.md:1-1"),
            self.chunk(2, pointer="a.md:2-2"),
        ]
        first = ontology_channel(registry, "alpha", chunks, root=self.root)
        second = ontology_channel(registry, "alpha", chunks, root=self.root)
        self.assertEqual(first.ranking, (1, 0))
        self.assertEqual(first, second)

    def test_candidate_cap_sets_truncated(self) -> None:
        line_count = MAX_ONTOLOGY_CANDIDATES + 1
        self.source.write_bytes(b"x\n" * line_count)
        registry = self.registry(
            [self.concept("concept.alpha", "alpha", self.binding(start=1, end=line_count))]
        )
        chunks = [self.chunk(index) for index in range(1, line_count + 1)]
        result = ontology_channel(registry, "alpha", chunks, root=self.root)
        self.assertEqual(result.candidate_count, line_count)
        self.assertEqual(len(result.ranking), MAX_ONTOLOGY_CANDIDATES)
        self.assertTrue(result.truncated)

    def test_r7_symlink_refusal_propagates_without_path_echo(self) -> None:
        link = self.root / "docs/link.md"
        link.symlink_to(self.source)
        raw = self.source.read_bytes()
        binding = {
            "scheme": "repo",
            "source_id": "docs/link.md",
            "version": hashlib.sha256(raw).hexdigest(),
            "range": {"unit": "bytes", "start": 0, "end": 3},
            "digest": hashlib.sha256(raw[:3]).hexdigest(),
        }
        registry = self.registry([self.concept("concept.alpha", "alpha", binding)])
        with self.assertRaises(ConceptRegistryError) as raised:
            ontology_channel(registry, "alpha", [self.chunk(1)], root=self.root)
        self.assertEqual(raised.exception.reason, "source_symlink_refused")
        self.assertNotIn("link.md", str(raised.exception))

    def test_secret_query_is_refused_without_echo(self) -> None:
        registry = self.registry(
            [self.concept("concept.alpha", "alpha", self.binding(start=1))]
        )
        canary = "".join(("sk-", "proj-", "A" * 24))
        with self.assertRaises(ConceptRegistryError) as raised:
            ontology_channel(registry, canary, [self.chunk(1)], root=self.root)
        self.assertEqual(raised.exception.reason, "query_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))

    def test_identical_comparison_is_pointer_only(self) -> None:
        document = self.comparison(["docs/a.md:1-2", "docs/b.md:3-4"])
        self.assertTrue(document["diff"]["identical"])
        self.assertEqual(document["diff"]["overlap_count"], 2)
        self.assertEqual(document["diff"]["rank_changes"], [])
        self.assertFalse(document["retrieval_influence"])
        self.assertFalse(document["returned_ranking_changed"])
        self.assertNotIn("ordinary question", json.dumps(document, sort_keys=True))
        validate_shadow_comparison(document)

    def test_comparison_reports_entered_left_and_rank_changes(self) -> None:
        document = self.comparison(
            ["docs/a.md:1-2", "docs/b.md:3-4"],
            ["docs/b.md:3-4", "docs/c.md:5-6"],
        )
        diff = document["diff"]
        self.assertFalse(diff["identical"])
        self.assertEqual(diff["overlap_count"], 1)
        self.assertEqual(diff["entered"], ["docs/c.md:5-6"])
        self.assertEqual(diff["left"], ["docs/a.md:1-2"])
        self.assertEqual(
            diff["rank_changes"],
            [
                {"pointer": "docs/a.md:1-2", "baseline_rank": 1, "shadow_rank": None},
                {"pointer": "docs/b.md:3-4", "baseline_rank": 2, "shadow_rank": 1},
                {"pointer": "docs/c.md:5-6", "baseline_rank": None, "shadow_rank": 2},
            ],
        )

    def test_digest_tamper_is_caught(self) -> None:
        document = self.comparison(["docs/a.md:1-2"])
        document["comparison_digest"] = "0" * 64
        with self.assertRaises(ShadowComparisonError) as raised:
            validate_shadow_comparison(document)
        self.assertEqual(raised.exception.reason, "comparison_digest_mismatch")

    def test_cross_field_tamper_is_caught_before_digest(self) -> None:
        document = self.comparison(["docs/a.md:1-2"])
        document["diff"]["overlap_count"] = 0
        with self.assertRaises(ShadowComparisonError) as raised:
            validate_shadow_comparison(document)
        self.assertEqual(raised.exception.reason, "overlap_mismatch")

    def test_runtime_and_public_schema_accept_and_reject_same_shapes(self) -> None:
        schema_path = (
            Path(__file__).parents[1]
            / "schemas/ontology-shadow-comparison.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema)
        registry = Registry().with_resource(schema["$id"], resource)
        validator = Draft202012Validator(schema, registry=registry)

        valid = self.comparison(["docs/a.md:1-2"])
        self.assertEqual(list(validator.iter_errors(valid)), [])
        validate_shadow_comparison(valid)

        invalid = copy.deepcopy(valid)
        invalid["unexpected"] = False
        self.assertNotEqual(list(validator.iter_errors(invalid)), [])
        with self.assertRaises(ShadowComparisonError) as raised:
            validate_shadow_comparison(invalid)
        self.assertEqual(raised.exception.reason, "invalid_fields")

    def test_concept_id_length_runtime_and_schema_parity(self) -> None:
        schema_path = (
            Path(__file__).parents[1]
            / "schemas/ontology-shadow-comparison.v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema)
        registry = Registry().with_resource(schema["$id"], resource)
        validator = Draft202012Validator(schema, registry=registry)

        for concept_id in ("abc", "a" * 128):
            with self.subTest(length=len(concept_id), expected="accepted"):
                document = self.comparison_with_concept_id(concept_id)
                self.assertEqual(list(validator.iter_errors(document)), [])
                validate_shadow_comparison(document)

        for concept_id in ("ab", "a" * 129):
            with self.subTest(length=len(concept_id), expected="rejected"):
                document = self.comparison_with_concept_id(concept_id)
                self.assertNotEqual(list(validator.iter_errors(document)), [])
                with self.assertRaises(ShadowComparisonError) as raised:
                    validate_shadow_comparison(document)
                self.assertEqual(raised.exception.reason, "invalid_concept_id")

    def test_builder_refuses_secret_query_without_echo(self) -> None:
        canary = "".join(("gh", "p_", "B" * 24))
        baseline = self.baseline([])
        baseline["query"] = canary
        with self.assertRaises(ShadowComparisonError) as raised:
            build_shadow_comparison(
                query=canary,
                registry=None,
                channel=self.empty_comparison_channel(),
                baseline=baseline,
                shadow_results=[],
                shadow_candidate_count=0,
                shadow_items_bytes=2,
                limit=5,
            )
        self.assertEqual(raised.exception.reason, "query_privacy_refused")
        self.assertNotIn(canary, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
