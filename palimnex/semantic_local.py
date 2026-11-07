"""Deterministic local semantic provider and fail-closed validation helpers.

This module is evidence-only.  It wraps the existing in-process hashed
embedding and does not configure retrieval, persist vectors, or use a network.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from numbers import Real
from typing import Any, NoReturn

from . import core
from .durable import canonical_json
from .security import scan_text


PROVIDER_IDENTITY_SCHEMA = "palimnex:semantic-provider-identity:v1"
PROVIDER_ID = "palimnex-hashed-embedding"
PROVIDER_REVISION = "1"
PROVIDER_DIMENSIONS = 384
EMBED_TIMEOUT_MS = 2000
MAX_EMBED_BATCH = 1024
MAX_EMBED_TEXT_BYTES = 65536

_SEMANTIC_INTERFACE = "project-memory:semantic-provider:v1"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_PROBES = (
    "Local evidence stays separate from operational authority.",
    "A changed source document must produce a changed semantic vector.",
    "Deterministic ranking uses stable ordering for equivalent scores.",
    "Repository content is checked before any derived representation.",
)


class SemanticProviderError(ValueError):
    """A non-echoing provider refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str) -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"semantic provider refused: {reason} at {field}")


def _refuse(reason: str, field: str) -> NoReturn:
    raise SemanticProviderError(reason, field)


class HashedEmbeddingProvider:
    """In-process provider over Palimnex's existing hashed embedding."""

    @property
    def model_id(self) -> str:
        return PROVIDER_ID

    @property
    def revision(self) -> str:
        return PROVIDER_REVISION

    @property
    def dimensions(self) -> int:
        return PROVIDER_DIMENSIONS

    @property
    def artifact_digest(self) -> str:
        return implementation_digest()

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(core.embedding(text, PROVIDER_DIMENSIONS) for text in texts)


def implementation_digest() -> str:
    """Return a behavioral digest of tokenization, hashing, and normalization."""
    behavior = {
        "provider_id": PROVIDER_ID,
        "revision": PROVIDER_REVISION,
        "dimensions": PROVIDER_DIMENSIONS,
        "token_pattern": core.TOKEN_RE.pattern,
        "features": "unigram+adjacent-bigram",
        "hash": "sha256-index-mod-dimensions-sign-bit",
        "normalization": "l2",
        "probe_vectors": [
            core.encode_vector(core.embedding(probe, PROVIDER_DIMENSIONS))
            for probe in _PROBES
        ],
    }
    return hashlib.sha256(canonical_json(behavior)).hexdigest()


def _identity_attribute(provider: object, name: str) -> object:
    try:
        return getattr(provider, name)
    except Exception as exc:
        raise SemanticProviderError("identity_invalid", name) from exc


def _identity_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.isprintable()
        or scan_text(value)
    ):
        _refuse("identity_invalid", field)
    return value


def provider_identity(provider: object) -> dict[str, Any]:
    """Read and validate the immutable identity exposed by a provider."""
    provider_id_value = _identity_attribute(provider, "model_id")
    revision_value = _identity_attribute(provider, "revision")
    dimensions_value = _identity_attribute(provider, "dimensions")
    digest_value = _identity_attribute(provider, "artifact_digest")

    provider_id = _identity_text(provider_id_value, "provider_id")
    revision = _identity_text(revision_value, "revision")
    if (
        type(dimensions_value) is not int
        or dimensions_value < 8
        or dimensions_value > 4096
    ):
        _refuse("identity_invalid", "dimensions")
    if not isinstance(digest_value, str) or _DIGEST_RE.fullmatch(digest_value) is None:
        _refuse("identity_invalid", "implementation_digest")

    return {
        "schema": PROVIDER_IDENTITY_SCHEMA,
        "interface": _SEMANTIC_INTERFACE,
        "provider_id": provider_id,
        "revision": revision,
        "dimensions": dimensions_value,
        "implementation_digest": digest_value,
        "execution": "in_process",
        "network": False,
        "model_download": False,
        "persistent_store": False,
        "retrieval_influence": False,
    }


def identity_digest(identity: Mapping[str, Any]) -> str:
    """Bind a provider identity document using Palimnex canonical JSON."""
    return hashlib.sha256(canonical_json(identity)).hexdigest()


def _input_batch(texts: Sequence[str]) -> tuple[str, ...]:
    if isinstance(texts, (str, bytes, bytearray)) or not isinstance(texts, Sequence):
        _refuse("invalid_input", "texts")
    try:
        count = len(texts)
    except Exception as exc:
        raise SemanticProviderError("invalid_input", "texts") from exc
    if count == 0 or count > MAX_EMBED_BATCH:
        _refuse("invalid_input", "texts")
    try:
        batch = tuple(texts)
    except Exception as exc:
        raise SemanticProviderError("invalid_input", "texts") from exc
    if len(batch) != count or any(not isinstance(text, str) for text in batch):
        _refuse("invalid_input", "texts")
    for index, text in enumerate(batch):
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise SemanticProviderError("invalid_input", f"texts[{index}]") from exc
        if size > MAX_EMBED_TEXT_BYTES:
            _refuse("invalid_input", f"texts[{index}]")
    return batch


def _clock_value(clock: Callable[[], float]) -> float:
    try:
        value = clock()
    except Exception as exc:
        raise SemanticProviderError("invalid_input", "clock") from exc
    if isinstance(value, bool) or not isinstance(value, Real):
        _refuse("invalid_input", "clock")
    converted = float(value)
    if not math.isfinite(converted):
        _refuse("invalid_input", "clock")
    return converted


def checked_embed(
    provider: object,
    texts: Sequence[str],
    *,
    expected_dimensions: int,
    timeout_ms: int = EMBED_TIMEOUT_MS,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[tuple[float, ...], ...]:
    """Embed one bounded batch and validate the complete provider response."""
    batch = _input_batch(texts)
    if type(expected_dimensions) is not int or expected_dimensions < 1:
        _refuse("invalid_input", "expected_dimensions")
    if type(timeout_ms) is not int or timeout_ms < 0:
        _refuse("invalid_input", "timeout_ms")

    started = _clock_value(clock)
    try:
        embed = getattr(provider, "embed")
        output = embed(batch)
    except Exception as exc:
        raise SemanticProviderError("provider_failed", "embed") from exc
    finished = _clock_value(clock)
    if finished - started > timeout_ms / 1000:
        _refuse("provider_timeout", "embed")

    if isinstance(output, (str, bytes, bytearray)) or not isinstance(output, Sequence):
        _refuse("count_mismatch", "vectors")
    try:
        if len(output) != len(batch):
            _refuse("count_mismatch", "vectors")
        vectors = tuple(output)
    except SemanticProviderError:
        raise
    except Exception as exc:
        raise SemanticProviderError("count_mismatch", "vectors") from exc

    numeric_vectors: list[tuple[Real, ...]] = []
    for index, vector in enumerate(vectors):
        if isinstance(vector, (str, bytes, bytearray)) or not isinstance(vector, Sequence):
            _refuse("invalid_vector", f"vectors[{index}]")
        try:
            values = tuple(vector)
        except Exception as exc:
            raise SemanticProviderError("invalid_vector", f"vectors[{index}]") from exc
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
            _refuse("invalid_vector", f"vectors[{index}]")
        numeric_vectors.append(values)

    for index, vector in enumerate(numeric_vectors):
        if len(vector) != expected_dimensions:
            _refuse("dimension_mismatch", f"vectors[{index}]")

    result: list[tuple[float, ...]] = []
    for index, vector in enumerate(numeric_vectors):
        try:
            converted = tuple(float(value) for value in vector)
        except (OverflowError, TypeError, ValueError) as exc:
            raise SemanticProviderError("invalid_vector", f"vectors[{index}]") from exc
        if any(not math.isfinite(value) for value in converted):
            _refuse("non_finite", f"vectors[{index}]")
        result.append(converted)
    return tuple(result)
