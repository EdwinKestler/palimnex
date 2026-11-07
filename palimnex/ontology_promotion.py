"""Offline promotion evidence for approved ontology retrieval influence.

The evaluator compares the uninfluenced retrieval path with a directly
constructed measurement-only ``ActiveInfluence``.  It never activates a
repository setting, writes evidence, or touches a real Redis instance.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from . import cache_v3, core
from ._offline_fixtures import write_project
from ._offline_redis import FakeRedis
from .challenge import FIXTURE_SHA256 as V26_FIXTURE_SHA256
from .concepts import (
    ConceptRegistry,
    ConceptRegistryError,
    load_registry,
    normalize_alias,
    verify_source_bindings,
)
from .durable import canonical_json
from .ontology_eval import (
    V26_PATH,
    _CaseOutcome,
    _EvaluationCase,
    _cohort_cases,
    _load_cohort_document,
    _load_v26,
    _load_v27_cases,
    _metric_summary,
    _read_fixture,
    _safe_relative_path,
    _variant_outcome,
)
from .ontology_influence import (
    DEFAULT_REGISTRY_PATH,
    PROMOTION_EVIDENCE_SCHEMA,
    ActiveInfluence,
    InfluenceSetting,
    OntologyInfluenceError,
    influence_implementation_digest,
    validate_promotion_evidence,
)
from .retrieval import retrieve_sources


MAX_REGRESSED_CASE_IDS = 64
MAX_RETRIEVAL_CANDIDATES = 512
MEASUREMENT_EVIDENCE_DIGEST = "0" * 64
VISIBLE_CHANNELS = frozenset({"lexical", "symbol", "graph", "ontology"})


class OntologyPromotionError(ValueError):
    """A non-echoing promotion-evaluation refusal with a stable reason."""

    def __init__(self, reason: str, field: str = "promotion") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"ontology promotion evaluation refused: {reason} at {field}")


@dataclass(frozen=True)
class _MeasuredCase:
    outcome: _CaseOutcome
    off_identical: bool
    deterministic: bool
    channels_visible: bool
    bounded: bool


def _fail(reason: str, field: str) -> NoReturn:
    raise OntologyPromotionError(reason, field)


def _registry_has_ambiguity(registry: ConceptRegistry) -> bool:
    owners: dict[str, str] = {}
    try:
        for concept in registry.active_concepts:
            keys = (normalize_alias(concept.canonical_name), *concept.aliases)
            for key in keys:
                prior = owners.get(key)
                if prior is not None and prior != concept.concept_id:
                    return True
                owners[key] = concept.concept_id
    except ConceptRegistryError as exc:
        raise OntologyPromotionError(exc.reason, exc.field) from exc
    return False


def _measurement_influence(
    registry: ConceptRegistry, registry_path: str, implementation_digest: str
) -> ActiveInfluence:
    setting = InfluenceSetting(
        "enabled",
        registry_path,
        registry.registry_digest,
        None,
        None,
    )
    return ActiveInfluence(
        setting,
        registry,
        MEASUREMENT_EVIDENCE_DIGEST,
        implementation_digest,
    )


def _registry_matches_root(registry: ConceptRegistry, root: Path) -> bool:
    try:
        return (
            registry.project.project_id == cache_v3.project_id(root)
            and registry.project.project_slug == core.project_slug(root)
        )
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyPromotionError("configuration_refused", "project") from exc


def _result_rows(document: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    value = document.get("results")
    if not isinstance(value, list):
        _fail("retrieval_result_invalid", field + ".results")
    rows: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            _fail("retrieval_result_invalid", f"{field}.results[{index}]")
        rows.append(cast(Mapping[str, Any], item))
    return rows


def _paths(rows: Sequence[Mapping[str, Any]], field: str) -> tuple[str, ...]:
    return tuple(
        _safe_relative_path(item.get("path"), f"{field}[{index}].path")
        for index, item in enumerate(rows)
    )


def _ranking(rows: Sequence[Mapping[str, Any]], field: str) -> tuple[str, ...]:
    pointers: list[str] = []
    for index, item in enumerate(rows):
        pointer = item.get("pointer")
        if (
            not isinstance(pointer, str)
            or not pointer
            or len(pointer) > 4096
            or any(ord(character) < 32 or ord(character) == 127 for character in pointer)
        ):
            _fail("retrieval_result_invalid", f"{field}[{index}].pointer")
        pointers.append(pointer)
    return tuple(pointers)


def _channels_are_visible(
    document: Mapping[str, Any], *, influence_expected: bool
) -> bool:
    disclosure = document.get("ontology_influence")
    if influence_expected:
        if not isinstance(disclosure, Mapping) or set(disclosure) != {
            "mode",
            "channel",
            "retrieval_influence",
            "registry_digest",
            "promotion_evidence_digest",
            "implementation_digest",
            "contributing_concept_ids",
        }:
            return False
        contributing = disclosure.get("contributing_concept_ids")
        if (
            disclosure.get("mode") != "enabled"
            or disclosure.get("channel") != "ontology"
            or disclosure.get("retrieval_influence") is not True
            or not isinstance(contributing, list)
            or len(contributing) > MAX_RETRIEVAL_CANDIDATES
            or contributing != sorted(set(contributing))
            or not all(isinstance(item, str) for item in contributing)
        ):
            return False
    elif disclosure is not None:
        return False

    try:
        rows = _result_rows(document, "retrieval")
    except OntologyPromotionError:
        return False
    for row in rows:
        channels = row.get("channels")
        if (
            not isinstance(channels, Mapping)
            or not channels
            or set(channels) - VISIBLE_CHANNELS
            or (not influence_expected and "ontology" in channels)
            or any(
                type(rank) is not int or not 1 <= rank <= MAX_RETRIEVAL_CANDIDATES
                for rank in channels.values()
            )
        ):
            return False
    return True


def _result_is_bounded(document: Mapping[str, Any], *, limit: int) -> bool:
    try:
        rows = _result_rows(document, "retrieval")
    except OntologyPromotionError:
        return False
    candidate_count = document.get("candidate_count")
    omitted_count = document.get("omitted_count")
    byte_budget = document.get("byte_budget")
    items_bytes = document.get("items_bytes")
    if (
        type(candidate_count) is not int
        or not 0 <= candidate_count <= MAX_RETRIEVAL_CANDIDATES
        or type(omitted_count) is not int
        or omitted_count != candidate_count - len(rows)
        or type(byte_budget) is not int
        or not 128 <= byte_budget <= 65536
        or type(items_bytes) is not int
        or not 0 <= items_bytes <= byte_budget
        or len(rows) > limit
        or len(rows) > candidate_count
    ):
        return False
    return all(
        isinstance(row.get("channels"), Mapping)
        and len(cast(Mapping[str, Any], row["channels"])) <= len(VISIBLE_CHANNELS)
        for row in rows
    )


def _retrieve(
    case: _EvaluationCase,
    *,
    root: Path,
    report_limit: int,
    client: Any,
    snapshot: Any,
    influence: str | ActiveInfluence,
) -> dict[str, Any]:
    active_limit = min(report_limit, case.limit)
    result = retrieve_sources(
        case.query,
        root=root,
        limit=active_limit,
        byte_budget=8192,
        include_graph=True,
        client=client,
        snapshot=snapshot,
        influence=cast(Any, influence),
    )
    if not isinstance(result, dict):
        _fail("retrieval_result_invalid", "retrieval")
    return result


def _measure_case(
    case: _EvaluationCase,
    *,
    root: Path,
    report_limit: int,
    client: Any,
    snapshot: Any,
    active: ActiveInfluence | None,
) -> _MeasuredCase:
    baseline = _retrieve(
        case,
        root=root,
        report_limit=report_limit,
        client=client,
        snapshot=snapshot,
        influence="off",
    )
    fresh_baseline = _retrieve(
        case,
        root=root,
        report_limit=report_limit,
        client=client,
        snapshot=snapshot,
        influence="off",
    )
    measurement: str | ActiveInfluence = active if active is not None else "off"
    influenced = _retrieve(
        case,
        root=root,
        report_limit=report_limit,
        client=client,
        snapshot=snapshot,
        influence=measurement,
    )
    repeated = _retrieve(
        case,
        root=root,
        report_limit=report_limit,
        client=client,
        snapshot=snapshot,
        influence=measurement,
    )
    baseline_rows = _result_rows(baseline, "baseline")
    influenced_rows = _result_rows(influenced, "influenced")
    baseline_variant = _variant_outcome(
        _paths(baseline_rows, "baseline.results"),
        case.expected_paths,
        case.forbidden_paths,
    )
    influenced_variant = _variant_outcome(
        _paths(influenced_rows, "influenced.results"),
        case.expected_paths,
        case.forbidden_paths,
    )
    identical_ranking = _ranking(
        baseline_rows, "baseline.results"
    ) == _ranking(influenced_rows, "influenced.results")
    disclosure = influenced.get("ontology_influence")
    contributing = (
        disclosure.get("contributing_concept_ids")
        if isinstance(disclosure, Mapping)
        else None
    )
    active_limit = min(report_limit, case.limit)
    outcome = _CaseOutcome(
        case,
        baseline_variant,
        influenced_variant,
        isinstance(contributing, list) and bool(contributing),
        identical_ranking,
        canonical_json(baseline) == canonical_json(fresh_baseline),
        _channels_are_visible(influenced, influence_expected=active is not None),
        _result_is_bounded(baseline, limit=active_limit)
        and _result_is_bounded(influenced, limit=active_limit),
        (),
    )
    return _MeasuredCase(
        outcome,
        outcome.baseline_identical,
        canonical_json(influenced) == canonical_json(repeated),
        outcome.channels_visible,
        outcome.bounded,
    )


def _measure_suite(
    cases: Sequence[_EvaluationCase],
    *,
    root: Path,
    report_limit: int,
    client: Any,
    snapshot: Any,
    active: ActiveInfluence | None,
) -> tuple[_MeasuredCase, ...]:
    return tuple(
        _measure_case(
            case,
            root=root,
            report_limit=report_limit,
            client=client,
            snapshot=snapshot,
            active=active,
        )
        for case in cases
    )


def _suite_evidence(measured: Sequence[_MeasuredCase]) -> dict[str, Any]:
    outcomes = tuple(item.outcome for item in measured)
    return {
        "baseline": _metric_summary(outcomes, "baseline"),
        "influenced": _metric_summary(outcomes, "shadow"),
        "changed_ranking_count": sum(
            not outcome.identical_ranking for outcome in outcomes
        ),
        "regressed_case_ids": sorted(
            outcome.case.identifier
            for outcome in outcomes
            if outcome.baseline.passed and not outcome.shadow.passed
        )[:MAX_REGRESSED_CASE_IDS],
    }


def _backend_gates(
    measured: Sequence[_MeasuredCase],
    *,
    registry_unambiguous: bool,
    registry_current: bool,
) -> dict[str, bool]:
    outcomes = tuple(item.outcome for item in measured)
    return {
        "off_identical": all(item.off_identical for item in measured),
        "no_critical_regression": all(
            not outcome.baseline.passed or outcome.shadow.passed
            for outcome in outcomes
            if outcome.case.critical
        ),
        "no_case_regression": all(
            not outcome.baseline.passed or outcome.shadow.passed
            for outcome in outcomes
        ),
        "no_new_forbidden": sum(
            len(outcome.shadow.forbidden_hits) for outcome in outcomes
        )
        <= sum(len(outcome.baseline.forbidden_hits) for outcome in outcomes),
        "abstention_not_regressed": all(
            not outcome.baseline.abstained or outcome.shadow.abstained
            for outcome in outcomes
        ),
        "registry_unambiguous": registry_unambiguous,
        "registry_current": registry_current,
        "channels_visible": all(item.channels_visible for item in measured),
        "bounded": all(item.bounded for item in measured),
        "deterministic": all(item.deterministic for item in measured),
    }


def _backend_evidence(
    backend: str,
    *,
    root: Path,
    registry: ConceptRegistry,
    active: ActiveInfluence,
    report_limit: int,
    v27_cases: Sequence[_EvaluationCase],
    v26_documents: dict[str, str],
    v26_cases: Sequence[_EvaluationCase],
    cohort_cases: Sequence[_EvaluationCase],
    root_snapshot: Any,
    registry_unambiguous: bool,
    registry_current: bool,
) -> dict[str, Any]:
    if backend not in {"local", "cache"}:
        _fail("backend_invalid", "backend")
    root_client: Any = None
    if backend == "cache":
        root_client = FakeRedis()
        cache_v3.build_index(root_client, root)

    v27 = _measure_suite(
        v27_cases,
        root=root,
        report_limit=report_limit,
        client=root_client,
        snapshot=root_snapshot,
        active=active,
    )
    cohort = _measure_suite(
        cohort_cases,
        root=root,
        report_limit=report_limit,
        client=root_client,
        snapshot=root_snapshot,
        active=active,
    )
    with tempfile.TemporaryDirectory(prefix="palimnex-ontology-promotion-") as directory:
        challenge_root = Path(directory)
        write_project(challenge_root, v26_documents)
        challenge_snapshot = cache_v3.source_snapshot(challenge_root)
        challenge_client: Any = None
        if backend == "cache":
            challenge_client = FakeRedis()
            cache_v3.build_index(challenge_client, challenge_root)
        challenge_active = active if _registry_matches_root(registry, challenge_root) else None
        challenges = _measure_suite(
            v26_cases,
            root=challenge_root,
            report_limit=report_limit,
            client=challenge_client,
            snapshot=challenge_snapshot,
            active=challenge_active,
        )

    all_measured = v27 + challenges + cohort
    return {
        "suites": {
            "v27": _suite_evidence(v27),
            "challenges_v26": _suite_evidence(challenges),
            "cohort": _suite_evidence(cohort),
        },
        "gates": _backend_gates(
            all_measured,
            registry_unambiguous=registry_unambiguous,
            registry_current=registry_current,
        ),
    }


def _v27_digest(root: Path) -> str:
    try:
        config = core.project_config(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyPromotionError("configuration_refused", "v27") from exc
    relative = _safe_relative_path(config.get("evaluation_fixture"), "v27.path")
    raw, _document = _read_fixture(root, Path(relative), "v27")
    return hashlib.sha256(raw).hexdigest()


def evaluate_ontology_promotion(
    root: Path, *, registry_path: str | None = None, limit: int = 5
) -> dict[str, Any]:
    """Return deterministic local and offline-cache promotion evidence."""
    if not isinstance(root, Path):
        _fail("invalid_type", "root")
    if type(limit) is not int or not 1 <= limit <= 100:
        _fail("invalid_limit", "limit")
    selected_registry_path = (
        DEFAULT_REGISTRY_PATH if registry_path is None else registry_path
    )
    if not isinstance(selected_registry_path, str):
        _fail("invalid_path", "registry_path")

    try:
        registry = load_registry(
            selected_registry_path,
            root=root,
            expected_kind="approved_registry",
        )
        verification = verify_source_bindings(registry, root=root)
    except ConceptRegistryError as exc:
        raise OntologyPromotionError(exc.reason, exc.field) from exc
    registry_unambiguous = not _registry_has_ambiguity(registry)
    registry_current = not verification.stale_concept_ids

    try:
        implementation_digest = influence_implementation_digest()
    except OntologyInfluenceError as exc:
        raise OntologyPromotionError(exc.reason, exc.field) from exc
    active = _measurement_influence(
        registry,
        selected_registry_path,
        implementation_digest,
    )

    cohort_document, cohort_digest = _load_cohort_document(root)
    cohort_cases = _cohort_cases(cohort_document)
    v27_cases = _load_v27_cases(root)
    v26_documents, v26_cases = _load_v26(root)
    v27_digest = _v27_digest(root)
    v26_raw, _v26_document = _read_fixture(root, V26_PATH, "challenges_v26")
    v26_digest = hashlib.sha256(v26_raw).hexdigest()
    if v26_digest != V26_FIXTURE_SHA256:
        _fail("fixture_digest_mismatch", "challenges_v26.digest")

    try:
        root_snapshot = cache_v3.source_snapshot(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyPromotionError("snapshot_refused", "root") from exc
    backends = {
        backend: _backend_evidence(
            backend,
            root=root,
            registry=registry,
            active=active,
            report_limit=limit,
            v27_cases=v27_cases,
            v26_documents=v26_documents,
            v26_cases=v26_cases,
            cohort_cases=cohort_cases,
            root_snapshot=root_snapshot,
            registry_unambiguous=registry_unambiguous,
            registry_current=registry_current,
        )
        for backend in ("local", "cache")
    }
    try:
        final_snapshot = cache_v3.source_snapshot(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyPromotionError("snapshot_refused", "root") from exc
    if final_snapshot.fingerprint != root_snapshot.fingerprint:
        _fail("repository_changed", "root")

    promotable = all(
        all(cast(bool, value) for value in backends[name]["gates"].values())
        for name in ("local", "cache")
    )
    evidence: dict[str, Any] = {
        "schema": PROMOTION_EVIDENCE_SCHEMA,
        "status": "promotable" if promotable else "held",
        "registry": {
            "path": selected_registry_path,
            "digest": registry.registry_digest,
        },
        "implementation_digest": implementation_digest,
        "fixture_digests": {
            "v27": v27_digest,
            "v26": v26_digest,
            "cohort": cohort_digest,
        },
        "limit": limit,
        "backends": backends,
        "activation_authorized": False,
        "authority": "evidence_only",
        "authorizes_actions": False,
    }
    evidence["evidence_digest"] = hashlib.sha256(canonical_json(evidence)).hexdigest()
    try:
        validate_promotion_evidence(evidence)
    except OntologyInfluenceError as exc:
        raise OntologyPromotionError(exc.reason, exc.field) from exc
    return evidence


__all__ = ["OntologyPromotionError", "evaluate_ontology_promotion"]
