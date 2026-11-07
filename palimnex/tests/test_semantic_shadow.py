"""Focused tests for the evidence-only R14 semantic shadow channel."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from palimnex import cache_v3, retrieval
from palimnex._offline_fixtures import write_project
from palimnex.durable import canonical_json
from palimnex.semantic_local import HashedEmbeddingProvider, checked_embed
from palimnex.semantic_shadow import (
    CHANNELS,
    SEMANTIC_TOP_K,
    EmbeddingMemo,
    SemanticShadowError,
    policy_digest,
    semantic_channel,
    semantic_shadow_retrieve,
    validate_semantic_comparison,
)
from palimnex.tests.semantic_doubles import (
    BadIdentityProvider,
    FailingProvider,
    FakeClock,
    NonFiniteProvider,
    NonNumericProvider,
    RecordingProvider,
    SlowProvider,
    WrongCountProvider,
    WrongDimensionProvider,
)


REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "palimnex/schemas/semantic-shadow-comparison.v1.schema.json"


def comparison_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(schema, registry=registry)


class _VectorProvider:
    model_id = "semantic-double-vectors"
    revision = "1"
    dimensions = 8
    artifact_digest = hashlib.sha256(model_id.encode("utf-8")).hexdigest()

    def __init__(self, vectors: dict[str, tuple[float, ...]]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[str, ...]] = []

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        batch = tuple(texts)
        self.calls.append(batch)
        return tuple(self.vectors.get(text, (0.0,) * self.dimensions) for text in batch)


def _chunk(text: str, pointer: str) -> dict[str, object]:
    return {"text": text, "pointer": pointer}


class SemanticChannelUnitTests(unittest.TestCase):
    def assert_reason(self, reason: str, callable_: object) -> SemanticShadowError:
        with self.assertRaises(SemanticShadowError) as caught:
            callable_()  # type: ignore[operator]
        self.assertEqual(caught.exception.reason, reason)
        return caught.exception

    def test_strict_positive_floor_and_zero_norm(self) -> None:
        positive = (1.0,) + (0.0,) * 7
        orthogonal = (0.0, 1.0) + (0.0,) * 6
        negative = (-1.0,) + (0.0,) * 7
        provider = _VectorProvider(
            {"query": positive, "positive": positive, "zero": orthogonal, "negative": negative}
        )
        channel = semantic_channel(
            provider,
            "query",
            (
                _chunk("positive", "docs/a.md:1-1"),
                _chunk("zero", "docs/b.md:1-1"),
                _chunk("negative", "docs/c.md:1-1"),
            ),
            memo=EmbeddingMemo(),
            baseline_candidate_count=1,
        )
        self.assertEqual(channel.ranking, (0,))
        self.assertEqual(channel.candidate_count, 1)
        self.assertFalse(channel.truncated)

    def test_ties_break_by_pointer(self) -> None:
        vector = (1.0,) + (0.0,) * 7
        provider = _VectorProvider({"query": vector, "first": vector, "second": vector})
        channel = semantic_channel(
            provider,
            "query",
            (
                _chunk("first", "docs/z.md:1-1"),
                _chunk("second", "docs/a.md:1-1"),
            ),
            memo=EmbeddingMemo(),
            baseline_candidate_count=1,
        )
        self.assertEqual(channel.ranking, (1, 0))

    def test_ranking_is_capped_and_reports_truncation(self) -> None:
        vector = (1.0,) + (0.0,) * 7
        vectors = {"query": vector, **{f"chunk-{index}": vector for index in range(65)}}
        provider = _VectorProvider(vectors)
        chunks = tuple(
            _chunk(f"chunk-{index}", f"docs/{index:03d}.md:1-1") for index in range(65)
        )
        channel = semantic_channel(
            provider,
            "query",
            chunks,
            memo=EmbeddingMemo(),
            baseline_candidate_count=1,
        )
        self.assertEqual(channel.candidate_count, 65)
        self.assertEqual(len(channel.ranking), SEMANTIC_TOP_K)
        self.assertTrue(channel.truncated)

    def test_chunk_misses_are_embedded_in_bounded_batches(self) -> None:
        vector = (1.0,) + (0.0,) * 7
        vectors = {"query": vector, **{f"chunk-{index}": vector for index in range(1025)}}
        provider = _VectorProvider(vectors)
        semantic_channel(
            provider,
            "query",
            tuple(
                _chunk(f"chunk-{index}", f"docs/{index:04d}.md:1-1")
                for index in range(1025)
            ),
            memo=EmbeddingMemo(),
            baseline_candidate_count=1,
        )
        self.assertEqual([len(batch) for batch in provider.calls], [1, 1024, 1])

    def test_abstention_suppresses_without_embedding(self) -> None:
        provider = _VectorProvider({})
        channel = semantic_channel(
            provider,
            "unmatched",
            (_chunk("content", "docs/a.md:1-1"),),
            memo=EmbeddingMemo(),
            baseline_candidate_count=0,
        )
        self.assertEqual(channel.ranking, ())
        self.assertEqual(channel.suppressed, "baseline_abstained")
        self.assertEqual(provider.calls, [])

    def test_privacy_scan_precedes_provider(self) -> None:
        canary = "".join(("AK", "IA", "ABCDEFGHIJKLMNOP"))
        provider = _VectorProvider({})
        error = self.assert_reason(
            "query_privacy_refused",
            lambda: semantic_channel(
                provider,
                canary,
                (_chunk("content", "docs/a.md:1-1"),),
                memo=EmbeddingMemo(),
                baseline_candidate_count=1,
            ),
        )
        self.assertEqual(error.field, "query")
        self.assertNotIn(canary, str(error))
        self.assertEqual(provider.calls, [])

    def test_capacity_overflow_clears_the_memo(self) -> None:
        vector = (1.0,) + (0.0,) * 7
        provider = _VectorProvider({"query": vector, "one": vector, "two": vector})
        memo = EmbeddingMemo(capacity=1)
        semantic_channel(
            provider,
            "query",
            (_chunk("one", "docs/a.md:1-1"), _chunk("two", "docs/b.md:1-1")),
            memo=memo,
            baseline_candidate_count=1,
        )
        self.assertEqual(len(memo), 1)


class SemanticShadowRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        write_project(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_reason(self, reason: str, callable_: object) -> SemanticShadowError:
        with self.assertRaises(SemanticShadowError) as caught:
            callable_()  # type: ignore[operator]
        self.assertEqual(caught.exception.reason, reason)
        return caught.exception

    def test_baseline_is_byte_identical_for_queries_and_limits(self) -> None:
        provider = HashedEmbeddingProvider()
        for query, limit in (("cobalt orchard recovery", 1), ("amber watcher cursors", 5)):
            with self.subTest(query=query, limit=limit):
                result = semantic_shadow_retrieve(
                    query, provider=provider, root=self.root, limit=limit
                )
                direct = retrieval.retrieve_sources(
                    query, root=self.root, limit=limit, influence="off"
                )
                self.assertEqual(canonical_json(result["baseline"]), canonical_json(direct))

    def test_shadow_is_the_manual_four_channel_fusion(self) -> None:
        query = "cobalt orchard recovery"
        snapshot = cache_v3.source_snapshot(self.root)
        baseline, state = retrieval._retrieve_sources_with_state(
            query,
            root=self.root,
            limit=5,
            byte_budget=8192,
            include_graph=True,
            client=None,
            snapshot=snapshot,
            influence="off",
        )
        channel = semantic_channel(
            HashedEmbeddingProvider(),
            query,
            state.chunks,
            memo=EmbeddingMemo(),
            baseline_candidate_count=baseline["candidate_count"],
        )
        expected = retrieval._fuse_rankings(
            state.chunks,
            state.rankings + (("semantic", channel.ranking),),
            limit=5,
            byte_budget=8192,
        )
        result = semantic_shadow_retrieve(
            query,
            provider=HashedEmbeddingProvider(),
            root=self.root,
            snapshot=snapshot,
        )
        actual_items = result["comparison"]["shadow"]["items"]
        self.assertEqual(
            [item["pointer"] for item in actual_items],
            [item["pointer"] for item in expected.results],
        )
        self.assertEqual(
            [item["channels"] for item in actual_items],
            [item["channels"] for item in expected.results],
        )
        self.assertEqual(result["comparison"]["shadow"]["candidate_count"], expected.candidate_count)
        self.assertEqual(result["comparison"]["shadow"]["items_bytes"], expected.items_bytes)

    def test_retrieval_abstention_records_suppression_and_no_embed_calls(self) -> None:
        provider = RecordingProvider(HashedEmbeddingProvider())
        result = semantic_shadow_retrieve(
            "unrelated quasar nebula", provider=provider, root=self.root
        )
        self.assertEqual(result["baseline"]["candidate_count"], 0)
        self.assertEqual(
            result["comparison"]["semantic_channel"]["suppressed"],
            "baseline_abstained",
        )
        self.assertEqual(provider.calls, [])

    def test_retrieval_privacy_refusal_never_calls_provider(self) -> None:
        canary = "".join(("AK", "IA", "ABCDEFGHIJKLMNOP"))
        provider = RecordingProvider(HashedEmbeddingProvider())
        error = self.assert_reason(
            "query_privacy_refused",
            lambda: semantic_shadow_retrieve(canary, provider=provider, root=self.root),
        )
        self.assertNotIn(canary, str(error))
        self.assertEqual(provider.calls, [])

    def test_provider_failures_are_typed_without_fallback(self) -> None:
        providers = (
            (WrongDimensionProvider(), "dimension_mismatch"),
            (NonFiniteProvider(math.nan), "non_finite"),
            (NonFiniteProvider(math.inf), "non_finite"),
            (FailingProvider(), "provider_failed"),
            (WrongCountProvider(), "count_mismatch"),
            (NonNumericProvider(), "invalid_vector"),
            (BadIdentityProvider("provider_id"), "identity_invalid"),
        )
        for provider, reason in providers:
            with self.subTest(provider=type(provider).__name__, reason=reason):
                self.assert_reason(
                    reason,
                    lambda provider=provider: semantic_shadow_retrieve(
                        "cobalt orchard", provider=provider, root=self.root
                    ),
                )

    def test_provider_timeout_is_typed_without_fallback(self) -> None:
        clock = FakeClock()
        provider = SlowProvider(clock, 2.001)

        def checked_with_fake_clock(
            active_provider: object,
            texts: Sequence[str],
            *,
            expected_dimensions: int,
        ) -> tuple[tuple[float, ...], ...]:
            return checked_embed(
                active_provider,
                texts,
                expected_dimensions=expected_dimensions,
                clock=clock,
            )

        with patch("palimnex.semantic_shadow.checked_embed", side_effect=checked_with_fake_clock):
            self.assert_reason(
                "provider_timeout",
                lambda: semantic_shadow_retrieve(
                    "cobalt orchard", provider=provider, root=self.root
                ),
            )

    def test_memo_reuses_unchanged_chunks_and_reembeds_only_drift(self) -> None:
        provider = RecordingProvider(HashedEmbeddingProvider())
        memo = EmbeddingMemo()
        query = "cobalt orchard"
        semantic_shadow_retrieve(query, provider=provider, root=self.root, memo=memo)
        first_call_count = len(provider.calls)
        self.assertEqual(first_call_count, 2)

        semantic_shadow_retrieve(query, provider=provider, root=self.root, memo=memo)
        self.assertEqual(len(provider.calls), first_call_count + 1)

        (self.root / "docs/alpha.md").write_text(
            "# Alpha\n\nThe cobalt orchard recovery rule changed deterministically.\n",
            encoding="utf-8",
        )
        semantic_shadow_retrieve(query, provider=provider, root=self.root, memo=memo)
        self.assertEqual(len(provider.calls), first_call_count + 3)
        self.assertEqual(len(provider.calls[-1]), 1)

    def test_comparison_validates_with_schema_and_runtime_validator(self) -> None:
        result = semantic_shadow_retrieve(
            "cobalt orchard", provider=HashedEmbeddingProvider(), root=self.root
        )
        comparison = result["comparison"]
        validator = comparison_validator()
        validator.check_schema(validator.schema)
        validator.validate(comparison)
        validate_semantic_comparison(comparison)
        self.assertEqual(comparison["channels"], list(CHANNELS))
        self.assertNotIn("text", comparison["shadow"]["items"][0])

    def test_validator_rejects_tampering(self) -> None:
        comparison = semantic_shadow_retrieve(
            "cobalt orchard", provider=HashedEmbeddingProvider(), root=self.root
        )["comparison"]
        mutations = []
        extra = copy.deepcopy(comparison)
        extra["extra"] = False
        mutations.append(extra)
        authority = copy.deepcopy(comparison)
        authority["promotion_authorized"] = True
        mutations.append(authority)
        ordering = copy.deepcopy(comparison)
        ordering["diff"]["added"] = ["docs/z.md:1-1", "docs/a.md:1-1"]
        mutations.append(ordering)
        digest = copy.deepcopy(comparison)
        digest["provider_identity_digest"] = "0" * 64
        mutations.append(digest)
        for mutation in mutations:
            with self.subTest(keys=tuple(mutation)):
                self.assert_reason(
                    "comparison_invalid",
                    lambda mutation=mutation: validate_semantic_comparison(mutation),
                )

    def test_fresh_memos_are_deterministic(self) -> None:
        first = semantic_shadow_retrieve(
            "cobalt orchard", provider=HashedEmbeddingProvider(), root=self.root
        )["comparison"]
        second = semantic_shadow_retrieve(
            "cobalt orchard", provider=HashedEmbeddingProvider(), root=self.root
        )["comparison"]
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(policy_digest(), policy_digest())


if __name__ == "__main__":
    unittest.main()
