"""Deterministic test doubles for the local semantic-provider contract."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from palimnex import core
from palimnex.semantic_local import PROVIDER_DIMENSIONS


def _digest(model_id: str) -> str:
    return hashlib.sha256(model_id.encode("utf-8")).hexdigest()


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _ValidIdentity:
    model_id = "semantic-double-base"
    revision = "1"
    dimensions = PROVIDER_DIMENSIONS

    @property
    def artifact_digest(self) -> str:
        return _digest(self.model_id)


class WrongDimensionProvider(_ValidIdentity):
    model_id = "semantic-double-wrong-dimension"

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple((0.0,) * (PROVIDER_DIMENSIONS - 1) for _ in texts)


class NonFiniteProvider(_ValidIdentity):
    model_id = "semantic-double-non-finite"

    def __init__(self, value: float) -> None:
        self.value = value

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        vector = (self.value,) + (0.0,) * (PROVIDER_DIMENSIONS - 1)
        return tuple(vector for _ in texts)


class FailingProvider(_ValidIdentity):
    model_id = "semantic-double-failing"

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        del texts
        raise RuntimeError("distinctive provider failure marker")


class SlowProvider(_ValidIdentity):
    model_id = "semantic-double-slow"

    def __init__(self, clock: FakeClock, advance_seconds: float) -> None:
        self.clock = clock
        self.advance_seconds = advance_seconds

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.clock.advance(self.advance_seconds)
        return tuple(core.embedding(text, PROVIDER_DIMENSIONS) for text in texts)


class WrongCountProvider(_ValidIdentity):
    model_id = "semantic-double-wrong-count"

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        del texts
        return ()


class NonNumericProvider(_ValidIdentity):
    model_id = "semantic-double-non-numeric"

    def embed(self, texts: Sequence[str]) -> tuple[tuple[object, ...], ...]:
        vector: tuple[object, ...] = ("not numeric",) + (0.0,) * (
            PROVIDER_DIMENSIONS - 1
        )
        return tuple(vector for _ in texts)


class BadIdentityProvider(_ValidIdentity):
    """Expose one invalid identity field selected by its public document name."""

    def __init__(self, field: str) -> None:
        self.field = field

    @property
    def model_id(self) -> str:
        if self.field in {"provider_id", "model_id"}:
            return ""
        return "semantic-double-bad-identity"

    @property
    def revision(self) -> str:
        if self.field == "revision":
            return ""
        return "1"

    @property
    def dimensions(self) -> int | bool:
        if self.field == "dimensions":
            return True
        return PROVIDER_DIMENSIONS

    @property
    def artifact_digest(self) -> str:
        if self.field in {"artifact_digest", "implementation_digest"}:
            return "invalid"
        return _digest(self.model_id)

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(core.embedding(text, PROVIDER_DIMENSIONS) for text in texts)


class RecordingProvider:
    """Proxy a provider while retaining every batch and text passed to embed."""

    def __init__(self, inner: object) -> None:
        self.inner = inner
        self.calls: list[tuple[str, ...]] = []
        self.texts: list[str] = []

    @property
    def recorded_texts(self) -> tuple[str, ...]:
        return tuple(self.texts)

    @property
    def model_id(self) -> str:
        return "semantic-double-recording"

    @property
    def revision(self) -> str:
        return "1"

    @property
    def dimensions(self) -> int:
        value = getattr(self.inner, "dimensions")
        if type(value) is not int:
            raise TypeError("inner dimensions are invalid")
        return value

    @property
    def artifact_digest(self) -> str:
        return _digest(self.model_id)

    def embed(self, texts: Sequence[str]) -> Any:
        batch = tuple(texts)
        self.calls.append(batch)
        self.texts.extend(batch)
        return getattr(self.inner, "embed")(batch)
