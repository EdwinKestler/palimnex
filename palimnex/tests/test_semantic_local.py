"""Focused contract tests for the deterministic local semantic provider."""
from __future__ import annotations

import json
import math
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from palimnex import cache_v3, core
from palimnex.semantic import SemanticProvider, semantic_status
from palimnex.semantic_local import (
    MAX_EMBED_BATCH,
    MAX_EMBED_TEXT_BYTES,
    PROVIDER_DIMENSIONS,
    PROVIDER_ID,
    HashedEmbeddingProvider,
    SemanticProviderError,
    checked_embed,
    identity_digest,
    implementation_digest,
    provider_identity,
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
SCHEMA_PATH = REPO / "palimnex/schemas/semantic-provider-identity.v1.schema.json"


def identity_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(schema, registry=registry)


class _BoolVectorProvider:
    def embed(self, texts: Sequence[str]) -> tuple[tuple[bool, ...], ...]:
        return tuple((False,) * PROVIDER_DIMENSIONS for _ in texts)


class _RaisingIdentityProvider:
    @property
    def model_id(self) -> str:
        raise RuntimeError("private identity marker")


class _CanaryIdentityProvider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.revision = "1"
        self.dimensions = PROVIDER_DIMENSIONS
        self.artifact_digest = "a" * 64


class _CountingIdentityProvider:
    def __init__(self) -> None:
        self.reads = {name: 0 for name in ("model_id", "revision", "dimensions", "artifact_digest")}

    def _read(self, name: str, value: object) -> object:
        self.reads[name] += 1
        return value

    @property
    def model_id(self) -> object:
        return self._read("model_id", "semantic-double-counting")

    @property
    def revision(self) -> object:
        return self._read("revision", "1")

    @property
    def dimensions(self) -> object:
        return self._read("dimensions", PROVIDER_DIMENSIONS)

    @property
    def artifact_digest(self) -> object:
        return self._read("artifact_digest", "b" * 64)


class SemanticLocalProviderTests(unittest.TestCase):
    def assert_reason(self, reason: str, callable_: object) -> SemanticProviderError:
        with self.assertRaises(SemanticProviderError) as caught:
            callable_()  # type: ignore[operator]
        self.assertEqual(caught.exception.reason, reason)
        return caught.exception

    def test_hashed_provider_wraps_core_embedding_and_is_structural_provider(self) -> None:
        provider: SemanticProvider = HashedEmbeddingProvider()
        texts = ("local semantic evidence", "", "stable source binding")
        self.assertEqual(
            provider.embed(texts),
            tuple(core.embedding(text, PROVIDER_DIMENSIONS) for text in texts),
        )
        self.assertEqual(PROVIDER_DIMENSIONS, core.DIMENSIONS)
        self.assertIsInstance(provider.model_id, str)
        self.assertIsInstance(provider.revision, str)
        self.assertIsInstance(provider.dimensions, int)
        self.assertRegex(provider.artifact_digest, r"^[0-9a-f]{64}$")
        self.assertNotEqual(PROVIDER_ID, core.EMBEDDING_ID)
        self.assertNotEqual(PROVIDER_ID, cache_v3.EMBEDDING_ID)

    def test_implementation_digest_is_stable_and_behavioral(self) -> None:
        first = implementation_digest()
        self.assertEqual(first, implementation_digest())
        original = core.embedding

        def changed_embedding(text: str, dimensions: int = core.DIMENSIONS) -> tuple[float, ...]:
            vector = list(original(text, dimensions))
            vector[0] += 0.25
            return tuple(vector)

        with patch.object(core, "embedding", changed_embedding):
            self.assertNotEqual(implementation_digest(), first)

    def test_identity_validates_locally_and_digest_is_stable(self) -> None:
        identity = provider_identity(HashedEmbeddingProvider())
        validator = identity_validator()
        validator.check_schema(validator.schema)
        validator.validate(identity)
        self.assertEqual(identity["implementation_digest"], implementation_digest())
        self.assertEqual(identity_digest(identity), identity_digest(dict(identity)))

    def test_identity_properties_are_read_once(self) -> None:
        provider = _CountingIdentityProvider()
        provider_identity(provider)
        self.assertEqual(set(provider.reads.values()), {1})

    def test_identity_invalid_fields_are_typed(self) -> None:
        for field in ("provider_id", "revision", "dimensions", "implementation_digest"):
            with self.subTest(field=field):
                error = self.assert_reason(
                    "identity_invalid", lambda field=field: provider_identity(BadIdentityProvider(field))
                )
                self.assertEqual(error.field, field)

    def test_identity_property_failure_is_chained_and_not_echoed(self) -> None:
        error = self.assert_reason(
            "identity_invalid", lambda: provider_identity(_RaisingIdentityProvider())
        )
        self.assertIsNotNone(error.__cause__)
        self.assertNotIn("private identity marker", str(error))

    def test_identity_privacy_refusal_does_not_echo_canary(self) -> None:
        canary = "".join(("AK", "IA", "ABCDEFGHIJKLMNOP"))
        error = self.assert_reason(
            "identity_invalid", lambda: provider_identity(_CanaryIdentityProvider(canary))
        )
        self.assertNotIn(canary, str(error))

    def test_checked_embed_accepts_sequences_and_returns_float_tuples(self) -> None:
        result = checked_embed(
            HashedEmbeddingProvider(),
            ("one", "two"),
            expected_dimensions=PROVIDER_DIMENSIONS,
        )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(isinstance(vector, tuple) for vector in result))
        self.assertTrue(all(type(value) is float for vector in result for value in vector))

    def test_invalid_input_refusals_precede_provider_calls(self) -> None:
        provider = RecordingProvider(HashedEmbeddingProvider())
        invalid_batches = (
            object(),
            "one text is not a batch",
            (),
            ("valid", 1),
            ("x",) * (MAX_EMBED_BATCH + 1),
            ("é" * (MAX_EMBED_TEXT_BYTES // 2 + 1),),
        )
        for texts in invalid_batches:
            with self.subTest(kind=type(texts).__name__):
                self.assert_reason(
                    "invalid_input",
                    lambda texts=texts: checked_embed(
                        provider, texts, expected_dimensions=PROVIDER_DIMENSIONS  # type: ignore[arg-type]
                    ),
                )
        self.assertEqual(provider.calls, [])

    def test_invalid_dimension_and_timeout_inputs_are_typed(self) -> None:
        provider = RecordingProvider(HashedEmbeddingProvider())
        self.assert_reason(
            "invalid_input", lambda: checked_embed(provider, ("x",), expected_dimensions=0)
        )
        self.assert_reason(
            "invalid_input",
            lambda: checked_embed(
                provider, ("x",), expected_dimensions=PROVIDER_DIMENSIONS, timeout_ms=-1
            ),
        )
        self.assertEqual(provider.calls, [])

    def test_provider_failure_is_chained_without_echoing_exception(self) -> None:
        error = self.assert_reason(
            "provider_failed",
            lambda: checked_embed(
                FailingProvider(), ("x",), expected_dimensions=PROVIDER_DIMENSIONS
            ),
        )
        self.assertIsNotNone(error.__cause__)
        self.assertNotIn("distinctive provider failure marker", str(error))

    def test_timeout_discards_output_and_does_not_retry(self) -> None:
        clock = FakeClock()
        provider = RecordingProvider(SlowProvider(clock, 2.001))
        self.assert_reason(
            "provider_timeout",
            lambda: checked_embed(
                provider,
                ("x",),
                expected_dimensions=PROVIDER_DIMENSIONS,
                clock=clock,
            ),
        )
        self.assertEqual(provider.calls, [("x",)])

    def test_timeout_boundary_is_strictly_greater_than_limit(self) -> None:
        clock = FakeClock()
        result = checked_embed(
            SlowProvider(clock, 2.0),
            ("x",),
            expected_dimensions=PROVIDER_DIMENSIONS,
            clock=clock,
        )
        self.assertEqual(len(result), 1)

    def test_count_mismatch_is_typed(self) -> None:
        self.assert_reason(
            "count_mismatch",
            lambda: checked_embed(
                WrongCountProvider(), ("x",), expected_dimensions=PROVIDER_DIMENSIONS
            ),
        )

    def test_non_numeric_and_boolean_vectors_are_invalid(self) -> None:
        for provider in (NonNumericProvider(), _BoolVectorProvider()):
            with self.subTest(provider=type(provider).__name__):
                self.assert_reason(
                    "invalid_vector",
                    lambda provider=provider: checked_embed(
                        provider, ("x",), expected_dimensions=PROVIDER_DIMENSIONS
                    ),
                )

    def test_dimension_mismatch_is_typed(self) -> None:
        self.assert_reason(
            "dimension_mismatch",
            lambda: checked_embed(
                WrongDimensionProvider(), ("x",), expected_dimensions=PROVIDER_DIMENSIONS
            ),
        )

    def test_every_non_finite_value_is_refused(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assert_reason(
                    "non_finite",
                    lambda value=value: checked_embed(
                        NonFiniteProvider(value),
                        ("x",),
                        expected_dimensions=PROVIDER_DIMENSIONS,
                    ),
                )

    def test_existing_semantic_status_remains_disabled(self) -> None:
        self.assertEqual(
            semantic_status({}),
            {
                "interface": "project-memory:semantic-provider:v1",
                "mode": "disabled",
                "external_network_enabled": False,
                "provider_registered": False,
                "hnsw_enabled": False,
                "retrieval_influence": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
