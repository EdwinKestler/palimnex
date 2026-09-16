"""Opt-in semantic-provider contract and evidence gate.

Semantic provider: disabled. Promotion requires bounded latency and no critical
regression; until then semantic scores have no retrieval influence.

No network or model provider is registered by the portable bundle.  A caller
must inject a local provider in process and pass the frozen comparison gate
before semantic scores may influence retrieval.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence


SEMANTIC_INTERFACE = "project-memory:semantic-provider:v1"
MIN_RECALL_GAIN = 0.05
MIN_MRR_GAIN = 0.05
MAX_LATENCY_MULTIPLIER = 2.0


class SemanticProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def revision(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def artifact_digest(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True)
class SemanticMetrics:
    recall_at_5: float
    mrr: float
    critical_passed: bool
    p95_ms: float


def semantic_status(config: dict[str, object]) -> dict[str, object]:
    configured = config.get("semantic_provider", {"mode": "disabled"})
    if not isinstance(configured, dict) or set(configured) - {"mode"}:
        raise ValueError("semantic_provider accepts only a mode field")
    mode = configured.get("mode", "disabled")
    if mode != "disabled":
        raise ValueError(
            "portable bundle registers no semantic runtime; inject a reviewed local provider in process"
        )
    return {
        "interface": SEMANTIC_INTERFACE,
        "mode": "disabled",
        "external_network_enabled": False,
        "provider_registered": False,
        "hnsw_enabled": False,
        "retrieval_influence": False,
    }


def promotion_decision(
    baseline: SemanticMetrics,
    candidate: SemanticMetrics,
) -> dict[str, object]:
    values = (
        baseline.recall_at_5,
        baseline.mrr,
        baseline.p95_ms,
        candidate.recall_at_5,
        candidate.mrr,
        candidate.p95_ms,
    )
    if (
        not all(type(value) in {int, float} and math.isfinite(value) for value in values)
        or type(baseline.critical_passed) is not bool
        or type(candidate.critical_passed) is not bool
        or any(value < 0 for value in values)
        or any(
        value > 1 for value in (baseline.recall_at_5, baseline.mrr, candidate.recall_at_5, candidate.mrr)
        )
    ):
        raise ValueError("semantic evaluation metrics are outside their valid ranges")
    recall_gain = candidate.recall_at_5 - baseline.recall_at_5
    mrr_gain = candidate.mrr - baseline.mrr
    latency_limit = baseline.p95_ms * MAX_LATENCY_MULTIPLIER
    passed = bool(
        baseline.critical_passed
        and candidate.critical_passed
        and candidate.recall_at_5 >= baseline.recall_at_5
        and (
            recall_gain + 1e-12 >= MIN_RECALL_GAIN
            or mrr_gain + 1e-12 >= MIN_MRR_GAIN
        )
        and candidate.p95_ms <= latency_limit
    )
    return {
        "status": "promotable" if passed else "held",
        "promotable": passed,
        "recall_gain": recall_gain,
        "mrr_gain": mrr_gain,
        "candidate_p95_ms": candidate.p95_ms,
        "latency_limit_ms": latency_limit,
        "critical_regression": baseline.critical_passed and not candidate.critical_passed,
        "external_network_enabled": False,
        "hnsw_enabled": False,
    }
