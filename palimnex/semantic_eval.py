"""Evaluate the local semantic channel without influencing retrieval.

The report produced here is promotion evidence only.  It never enables a
provider, changes configuration, or persists vectors outside the process.
"""
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, NoReturn, cast

from . import cache_v3, core, ontology_eval, retrieval
from ._offline_fixtures import write_project
from .durable import canonical_json
from .security import read_bounded_file, scan_bytes, scan_text
from .semantic_local import (
    HashedEmbeddingProvider,
    SemanticProviderError,
    implementation_digest,
    identity_digest,
    provider_identity,
)
from .semantic_shadow import (
    CHANNELS,
    SEMANTIC_TOP_K,
    EmbeddingMemo,
    SemanticShadowError,
    policy_digest,
    semantic_shadow_retrieve,
    validate_semantic_comparison,
)


EVALUATION_SCHEMA = "palimnex:semantic-shadow-evaluation:v1"
PROMOTION_POLICY: dict[str, Any] = {
    "schema": "palimnex:semantic-promotion-policy:v2",
    "limit": 5,
    "min_mrr_gain": 0.02,
    "min_recall_gain": 0.02,
    "min_additional_passes": 1,
    "max_p95_multiplier": 1.5,
    "gain_rule": "mrr_or_recall",
}
BENCHMARK_PROTOCOL: dict[str, Any] = {
    "schema": "palimnex:semantic-benchmark-protocol:v1",
    "backend": "local",
    "queries": "semantic_cohort_repository_cases_in_file_order",
    "memo": "one_shared_in_process_memo",
    "warmup_passes": 1,
    "measured_repetitions": 3,
    "pair_order": "baseline_first_even_semantic_first_odd",
    "percentile": "nearest_rank_p95",
}
COHORT_PATH = Path("palimnex/evaluation/semantic-shadow.v1.json")
COHORT_SHA256 = "bfaa3998bc8c8ae5d05959f51e71aae08bf14f339a55fc0924d7e0b7b9ef4200"

_COHORT_SCHEMA = "palimnex:semantic-shadow-cohort:v1"
_LIMIT = 5
_BYTE_BUDGET = 8192
_MAX_FIXTURE_BYTES = 1_000_000
_SCORED_CATEGORIES = frozenset({"paraphrase", "synonym", "ambiguity", "control"})
_PROTECTED_SUITES = ("v27", "challenges_v26", "ontology_cohort")


class SemanticEvaluationError(ValueError):
    """A non-echoing evaluation refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str = "evaluation") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"semantic shadow evaluation refused: {reason} at {field}")


@dataclass(frozen=True)
class _RunOutcome:
    outcome: ontology_eval._CaseOutcome
    semantic_candidate_count: int
    suppressed: str | None
    comparison_digest: str
    provider_identity_digest: str
    comparison: Mapping[str, Any]


@dataclass(frozen=True)
class _DriftCheck:
    outcome: _RunOutcome
    fingerprint_changed: bool
    content_digests_current: bool
    matches_fresh_memo: bool
    forbidden_absent: bool
    baseline_pass_implies_shadow: bool


def _fail(reason: str, field: str) -> NoReturn:
    raise SemanticEvaluationError(reason, field)


def _provider_identity(provider: object) -> dict[str, Any]:
    try:
        return provider_identity(provider)
    except SemanticProviderError as exc:
        raise SemanticEvaluationError(exc.reason, exc.field) from exc


def _case(
    identifier: object,
    category: object,
    query: object,
    expected: object,
    forbidden: object,
    critical: object = False,
) -> ontology_eval._EvaluationCase:
    if not isinstance(identifier, str) or not identifier:
        _fail("invalid_fixture", "case.id")
    if not isinstance(category, str) or not category:
        _fail("invalid_fixture", f"cases.{identifier}.category")
    if not isinstance(query, str) or not query.strip():
        _fail("invalid_fixture", f"cases.{identifier}.query")
    if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
        _fail("invalid_fixture", f"cases.{identifier}.expected_paths")
    if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
        _fail("invalid_fixture", f"cases.{identifier}.forbidden_paths")
    if type(critical) is not bool:
        _fail("invalid_fixture", f"cases.{identifier}.critical")
    expected_paths = tuple(cast(list[str], expected))
    forbidden_paths = tuple(cast(list[str], forbidden))
    if len(set(expected_paths)) != len(expected_paths) or len(set(forbidden_paths)) != len(forbidden_paths):
        _fail("invalid_fixture", f"cases.{identifier}.paths")
    if set(expected_paths) & set(forbidden_paths):
        _fail("invalid_fixture", f"cases.{identifier}.paths")
    return ontology_eval._EvaluationCase(
        identifier,
        category,
        query,
        _LIMIT,
        expected_paths,
        forbidden_paths,
        cast(bool, critical),
    )


def _load_semantic_cohort(root: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = read_bounded_file(root, COHORT_PATH, max_bytes=_MAX_FIXTURE_BYTES)
    except (OSError, TypeError, ValueError) as exc:
        raise SemanticEvaluationError("fixture_read_refused", "semantic_cohort") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != COHORT_SHA256:
        _fail("fixture_digest_mismatch", "semantic_cohort.digest")
    try:
        if scan_bytes(raw):
            _fail("privacy_refused", "semantic_cohort")
        document = json.loads(raw.decode("utf-8", errors="strict"))
    except SemanticEvaluationError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SemanticEvaluationError("invalid_fixture", "semantic_cohort") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "status", "description", "cases", "projects", "project_cases"}
        or document.get("schema") != _COHORT_SCHEMA
        or document.get("status") != "frozen"
        or not isinstance(document.get("cases"), list)
        or not isinstance(document.get("projects"), dict)
        or not isinstance(document.get("project_cases"), list)
    ):
        _fail("invalid_fixture", "semantic_cohort")
    return cast(dict[str, Any], document), digest


def _repository_cases(document: Mapping[str, Any]) -> tuple[ontology_eval._EvaluationCase, ...]:
    values = document.get("cases")
    if not isinstance(values, list):
        _fail("invalid_fixture", "semantic_cohort.cases")
    result: list[ontology_eval._EvaluationCase] = []
    identifiers: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            _fail("invalid_fixture", "semantic_cohort.cases")
        value = dict(raw)
        parsed = _case(
            value.get("id"),
            value.get("category"),
            value.get("query"),
            value.get("expected_paths"),
            value.get("forbidden_paths"),
            value.get("critical"),
        )
        if parsed.identifier in identifiers:
            _fail("invalid_fixture", "semantic_cohort.cases.id")
        identifiers.add(parsed.identifier)
        result.append(parsed)
    if not result:
        _fail("invalid_fixture", "semantic_cohort.cases")
    return tuple(result)


def _paths_from_baseline(document: Mapping[str, Any]) -> tuple[str, ...]:
    results = document.get("results")
    if not isinstance(results, list):
        _fail("invalid_response", "baseline.results")
    paths: list[str] = []
    for item in results:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            _fail("invalid_response", "baseline.results.path")
        paths.append(cast(str, item["path"]))
    return tuple(paths)


def _paths_from_shadow(comparison: Mapping[str, Any]) -> tuple[str, ...]:
    shadow = comparison.get("shadow")
    if not isinstance(shadow, Mapping) or not isinstance(shadow.get("items"), list):
        _fail("invalid_response", "comparison.shadow")
    paths: list[str] = []
    for item in cast(list[Any], shadow["items"]):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            _fail("invalid_response", "comparison.shadow.items.path")
        paths.append(cast(str, item["path"]))
    return tuple(paths)


def _comparison_bounded(comparison: Mapping[str, Any]) -> bool:
    try:
        validate_semantic_comparison(comparison)
    except SemanticShadowError:
        return False
    shadow = comparison.get("shadow")
    channel = comparison.get("semantic_channel")
    if not isinstance(shadow, Mapping) or not isinstance(channel, Mapping):
        return False
    items = shadow.get("items")
    return (
        isinstance(items, list)
        and len(items) <= _LIMIT
        and type(channel.get("candidate_count")) is int
        and cast(int, channel["candidate_count"]) >= 0
        and type(channel.get("ranked_count")) is int
        and 0 <= cast(int, channel["ranked_count"]) <= SEMANTIC_TOP_K
    )


def _run_case(
    case: ontology_eval._EvaluationCase,
    *,
    provider: object,
    root: Path,
    snapshot: cache_v3.SourceSnapshot,
    memo: EmbeddingMemo,
) -> _RunOutcome:
    try:
        response = semantic_shadow_retrieve(
            case.query,
            provider=provider,
            root=root,
            limit=_LIMIT,
            byte_budget=_BYTE_BUDGET,
            include_graph=True,
            client=None,
            snapshot=snapshot,
            memo=memo,
        )
    except SemanticShadowError as exc:
        raise SemanticEvaluationError(exc.reason, exc.field) from exc
    direct = retrieval.retrieve_sources(
        case.query,
        root=root,
        limit=_LIMIT,
        byte_budget=_BYTE_BUDGET,
        include_graph=True,
        client=None,
        snapshot=snapshot,
        influence="off",
    )
    baseline = response.get("baseline")
    comparison = response.get("comparison")
    if not isinstance(baseline, Mapping) or not isinstance(comparison, Mapping):
        _fail("invalid_response", "semantic_shadow_retrieve")
    baseline_outcome = ontology_eval._variant_outcome(
        _paths_from_baseline(direct), case.expected_paths, case.forbidden_paths
    )
    shadow_outcome = ontology_eval._variant_outcome(
        _paths_from_shadow(comparison), case.expected_paths, case.forbidden_paths
    )
    semantic = comparison.get("semantic_channel")
    diff = comparison.get("diff")
    if not isinstance(semantic, Mapping) or not isinstance(diff, Mapping):
        _fail("invalid_response", "comparison")
    candidate_count = semantic.get("candidate_count")
    suppressed = semantic.get("suppressed")
    if type(candidate_count) is not int or suppressed not in (None, "baseline_abstained"):
        _fail("invalid_response", "comparison.semantic_channel")
    channels_visible = comparison.get("channels") == list(CHANNELS) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("channels"), Mapping)
        and bool(item["channels"])
        and not (set(item["channels"]) - set(CHANNELS))
        for item in cast(Mapping[str, Any], comparison["shadow"])["items"]
    )
    outcome = ontology_eval._CaseOutcome(
        case,
        baseline_outcome,
        shadow_outcome,
        candidate_count > 0,
        bool(diff.get("identical")),
        canonical_json(baseline) == canonical_json(direct),
        channels_visible,
        _comparison_bounded(comparison),
        (),
    )
    return _RunOutcome(
        outcome,
        cast(int, candidate_count),
        cast(str | None, suppressed),
        hashlib.sha256(canonical_json(comparison)).hexdigest(),
        cast(str, comparison.get("provider_identity_digest")),
        comparison,
    )


def _suite_report(outcomes: Sequence[_RunOutcome]) -> dict[str, Any]:
    base = tuple(item.outcome for item in outcomes)
    return {
        "baseline": ontology_eval._metric_summary(base, "baseline"),
        "shadow": ontology_eval._metric_summary(base, "shadow"),
        "cases": [
            {
                "id": item.outcome.case.identifier,
                "category": item.outcome.case.category,
                "critical": item.outcome.case.critical,
                "baseline_pass": item.outcome.baseline.passed,
                "shadow_pass": item.outcome.shadow.passed,
                "baseline_first_relevant_rank": item.outcome.baseline.first_relevant_rank,
                "shadow_first_relevant_rank": item.outcome.shadow.first_relevant_rank,
                "semantic_candidate_count": item.semantic_candidate_count,
                "suppressed": item.suppressed,
            }
            for item in outcomes
        ],
    }


def _run_suite(
    cases: Sequence[ontology_eval._EvaluationCase],
    *,
    provider: object,
    root: Path,
    snapshot: cache_v3.SourceSnapshot,
) -> tuple[_RunOutcome, ...]:
    memo = EmbeddingMemo()
    return tuple(
        _run_case(case, provider=provider, root=root, snapshot=snapshot, memo=memo)
        for case in cases
    )


def _write_synthetic_project(root: Path, documents: Mapping[str, str]) -> None:
    write_project(root, dict(documents))
    config_path = root / core.CONFIG_FILE
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["include_patterns"] = [core.CONFIG_FILE] + sorted(documents)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _project(document: Mapping[str, Any], project_id: object) -> tuple[dict[str, str], dict[str, str | None]]:
    projects = document.get("projects")
    if not isinstance(project_id, str) or not isinstance(projects, Mapping):
        _fail("invalid_fixture", "semantic_cohort.projects")
    raw = projects.get(project_id)
    if not isinstance(raw, Mapping):
        _fail("invalid_fixture", f"semantic_cohort.projects.{project_id}")
    documents = raw.get("documents")
    after = raw.get("after")
    if (
        not isinstance(documents, Mapping)
        or not documents
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in documents.items())
        or not isinstance(after, Mapping)
        or not all(
            isinstance(key, str) and (value is None or isinstance(value, str))
            for key, value in after.items()
        )
    ):
        _fail("invalid_fixture", f"semantic_cohort.projects.{project_id}")
    return dict(cast(Mapping[str, str], documents)), dict(cast(Mapping[str, str | None], after))


def _project_cases(document: Mapping[str, Any], category: str) -> tuple[dict[str, Any], ...]:
    raw_cases = document.get("project_cases")
    if not isinstance(raw_cases, list):
        _fail("invalid_fixture", "semantic_cohort.project_cases")
    return tuple(dict(item) for item in raw_cases if isinstance(item, Mapping) and item.get("category") == category)


def _apply_after(root: Path, changes: Mapping[str, str | None]) -> None:
    for relative, text in changes.items():
        target = root / relative
        if text is None:
            try:
                target.unlink()
            except OSError as exc:
                raise SemanticEvaluationError("drift_apply_failed", "drift.after") from exc
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")


def _current_content_digests(
    query: str,
    *,
    root: Path,
    snapshot: cache_v3.SourceSnapshot,
    comparison: Mapping[str, Any],
) -> bool:
    _baseline, state = retrieval._retrieve_sources_with_state(
        query,
        root=root,
        limit=_LIMIT,
        byte_budget=_BYTE_BUDGET,
        include_graph=True,
        client=None,
        snapshot=snapshot,
        influence="off",
    )
    current = {
        cast(str, chunk["pointer"]): hashlib.sha256(
            cast(str, chunk["text"]).encode("utf-8")
        ).hexdigest()
        for chunk in state.chunks
    }
    shadow = cast(Mapping[str, Any], comparison["shadow"])
    return all(
        isinstance(item, Mapping)
        and current.get(cast(str, item.get("pointer"))) == item.get("content_digest")
        for item in cast(list[Any], shadow["items"])
    )


def _run_drift(
    document: Mapping[str, Any], provider: object
) -> tuple[tuple[_RunOutcome, ...], bool]:
    memo = EmbeddingMemo()
    checks: list[_DriftCheck] = []
    for raw in _project_cases(document, "drift"):
        case = _case(
            raw.get("id"), "drift", raw.get("query"), raw.get("expected_paths"), raw.get("forbidden_paths")
        )
        documents, after = _project(document, raw.get("project"))
        with tempfile.TemporaryDirectory(prefix="palimnex-semantic-drift-") as directory:
            root = Path(directory)
            _write_synthetic_project(root, documents)
            before_snapshot = cache_v3.source_snapshot(root)
            _run_case(case, provider=provider, root=root, snapshot=before_snapshot, memo=memo)
            _apply_after(root, after)
            all_paths = dict(documents)
            for path, text in after.items():
                if text is None:
                    all_paths.pop(path, None)
                else:
                    all_paths[path] = text
            config_path = root / core.CONFIG_FILE
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["include_patterns"] = [core.CONFIG_FILE] + sorted(all_paths)
            config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            after_snapshot = cache_v3.source_snapshot(root)
            outcome = _run_case(case, provider=provider, root=root, snapshot=after_snapshot, memo=memo)
            fresh_outcome = _run_case(
                case,
                provider=provider,
                root=root,
                snapshot=after_snapshot,
                memo=EmbeddingMemo(),
            )
            forbidden_absent = not (
                set(outcome.outcome.shadow.paths) & set(case.forbidden_paths)
            )
            checks.append(
                _DriftCheck(
                    outcome,
                    before_snapshot.fingerprint != after_snapshot.fingerprint,
                    _current_content_digests(
                        case.query,
                        root=root,
                        snapshot=after_snapshot,
                        comparison=outcome.comparison,
                    ),
                    canonical_json(outcome.comparison)
                    == canonical_json(fresh_outcome.comparison),
                    forbidden_absent,
                    not outcome.outcome.baseline.passed or outcome.outcome.shadow.passed,
                )
            )
    return (
        tuple(item.outcome for item in checks),
        bool(checks)
        and all(
            item.fingerprint_changed
            and item.content_digests_current
            and item.matches_fresh_memo
            and item.forbidden_absent
            and item.baseline_pass_implies_shadow
            for item in checks
        ),
    )


def _canary(rule: str) -> str:
    values = {
        "aws-access-key": "".join(("AK", "IA", "0123456789ABCDEF")),
        "github-token": "".join(("gh", "p_", "AbCdEf0123456789GhIjKl")),
        "openai-token": "".join(("sk", "-", "AbCdEf0123456789GhIjKl")),
    }
    value = values.get(rule)
    if value is None or [item.rule for item in scan_text(value)] != [rule]:
        _fail("canary_construction_failed", "privacy.canary")
    return value


class _RecordingProvider:
    def __init__(self, inner: object) -> None:
        self.inner = inner
        self.texts: list[str] = []

    @property
    def model_id(self) -> object:
        return getattr(self.inner, "model_id")

    @property
    def revision(self) -> object:
        return getattr(self.inner, "revision")

    @property
    def dimensions(self) -> object:
        return getattr(self.inner, "dimensions")

    @property
    def artifact_digest(self) -> object:
        return getattr(self.inner, "artifact_digest")

    def embed(self, texts: Sequence[str]) -> object:
        batch = tuple(texts)
        self.texts.extend(batch)
        return getattr(self.inner, "embed")(batch)


def _privacy_outcome(case: ontology_eval._EvaluationCase) -> _RunOutcome:
    variant = ontology_eval._variant_outcome((), (), ())
    outcome = ontology_eval._CaseOutcome(case, variant, variant, False, True, True, True, True, ())
    return _RunOutcome(outcome, 0, "privacy_refused", "0" * 64, "0" * 64, {})


def _run_privacy(
    document: Mapping[str, Any], provider: object
) -> tuple[tuple[_RunOutcome, ...], bool, tuple[str, ...]]:
    outcomes: list[_RunOutcome] = []
    canaries: list[str] = []
    passed = True
    for raw in _project_cases(document, "privacy_canary"):
        identifier = raw.get("id")
        kind = raw.get("canary_kind")
        rule = raw.get("canary_rule")
        if not isinstance(identifier, str) or kind not in {"query", "corpus"} or not isinstance(rule, str):
            _fail("invalid_fixture", "privacy.case")
        canary = _canary(rule)
        canaries.append(canary)
        documents, _after = _project(document, raw.get("project"))
        query_value = raw.get("query")
        if not isinstance(query_value, str):
            _fail("invalid_fixture", f"privacy.{identifier}.query")
        query = query_value.replace("{canary}", canary)
        materialized = {path: text.replace("{canary}", canary) for path, text in documents.items()}
        case = _case(identifier, "privacy_canary", query_value, [], [])
        recording = _RecordingProvider(provider)
        with tempfile.TemporaryDirectory(prefix="palimnex-semantic-privacy-") as directory:
            root = Path(directory)
            _write_synthetic_project(root, materialized)
            if kind == "query":
                try:
                    snapshot = cache_v3.source_snapshot(root)
                    semantic_shadow_retrieve(
                        query,
                        provider=recording,
                        root=root,
                        limit=_LIMIT,
                        byte_budget=_BYTE_BUDGET,
                        include_graph=True,
                        client=None,
                        snapshot=snapshot,
                        memo=EmbeddingMemo(),
                    )
                except SemanticShadowError as exc:
                    case_passed = (
                        exc.reason == "query_privacy_refused"
                        and not recording.texts
                        and canary not in str(exc)
                    )
                else:
                    case_passed = False
            else:
                try:
                    cache_v3.source_snapshot(root)
                except (OSError, TypeError, ValueError) as exc:
                    case_passed = not recording.texts and canary not in str(exc)
                else:
                    case_passed = False
        passed = passed and case_passed
        outcomes.append(_privacy_outcome(case))
    return tuple(outcomes), bool(outcomes) and passed, tuple(canaries)


def _nearest_rank_p95(samples: Sequence[int]) -> float:
    if not samples:
        _fail("benchmark_failed", "benchmark.samples")
    ordered = sorted(samples)
    index = math.ceil(0.95 * len(ordered)) - 1
    return ordered[index] / 1_000_000.0


def _timed(call: Callable[[], object], clock_ns: Callable[[], int]) -> int:
    started = clock_ns()
    call()
    finished = clock_ns()
    if type(started) is not int or type(finished) is not int or finished < started:
        _fail("benchmark_clock_invalid", "clock_ns")
    return finished - started


def _benchmark(
    cases: Sequence[ontology_eval._EvaluationCase],
    *,
    provider: object,
    root: Path,
    snapshot: cache_v3.SourceSnapshot,
    clock_ns: Callable[[], int],
) -> dict[str, Any]:
    memo = EmbeddingMemo()

    def baseline(case: ontology_eval._EvaluationCase) -> object:
        return retrieval.retrieve_sources(
            case.query,
            root=root,
            limit=_LIMIT,
            byte_budget=_BYTE_BUDGET,
            include_graph=True,
            client=None,
            snapshot=snapshot,
            influence="off",
        )

    def semantic(case: ontology_eval._EvaluationCase) -> object:
        return semantic_shadow_retrieve(
            case.query,
            provider=provider,
            root=root,
            limit=_LIMIT,
            byte_budget=_BYTE_BUDGET,
            include_graph=True,
            client=None,
            snapshot=snapshot,
            memo=memo,
        )

    for case in cases:
        baseline(case)
        semantic(case)
    baseline_samples: list[int] = []
    semantic_samples: list[int] = []
    for repetition in range(3):
        for case in cases:
            if repetition % 2 == 0:
                baseline_samples.append(_timed(partial(baseline, case), clock_ns))
                semantic_samples.append(_timed(partial(semantic, case), clock_ns))
            else:
                semantic_samples.append(_timed(partial(semantic, case), clock_ns))
                baseline_samples.append(_timed(partial(baseline, case), clock_ns))
    return {
        "run": True,
        "baseline_p95_ms": _nearest_rank_p95(baseline_samples),
        "semantic_p95_ms": _nearest_rank_p95(semantic_samples),
        "multiplier_limit": PROMOTION_POLICY["max_p95_multiplier"],
        "samples_per_variant": len(baseline_samples),
    }


def _empty_benchmark() -> dict[str, Any]:
    return {
        "run": False,
        "baseline_p95_ms": None,
        "semantic_p95_ms": None,
        "multiplier_limit": PROMOTION_POLICY["max_p95_multiplier"],
        "samples_per_variant": 0,
    }


def _canonical_safe(report: Mapping[str, Any]) -> bytes:
    try:
        return canonical_json(report)
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise SemanticEvaluationError("canonicalization_failed", "report") from exc


def _redact_canaries(value: Any, canaries: Sequence[str]) -> Any:
    if isinstance(value, str):
        redacted = value
        for canary in canaries:
            redacted = redacted.replace(canary, "privacy_canary_redacted")
        return redacted
    if isinstance(value, list):
        return [_redact_canaries(item, canaries) for item in value]
    if isinstance(value, dict):
        return {
            _redact_canaries(key, canaries): _redact_canaries(item, canaries)
            for key, item in value.items()
        }
    return value


def evaluate_semantic_shadow(
    root: Path = core.ROOT,
    *,
    provider: object | None = None,
    benchmark: bool = True,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    """Run every fixed Phase 4 gate and return non-authorizing evidence."""
    if not isinstance(root, Path):
        _fail("invalid_input", "root")
    if type(benchmark) is not bool:
        _fail("invalid_input", "benchmark")
    active_provider = HashedEmbeddingProvider() if provider is None else provider
    identity_before = _provider_identity(active_provider)
    identity_before_digest = identity_digest(identity_before)
    cohort_document, cohort_digest = _load_semantic_cohort(root)
    semantic_cases = _repository_cases(cohort_document)
    try:
        root_snapshot = cache_v3.source_snapshot(root)
        v27_cases = ontology_eval._load_v27_cases(root)
        ontology_document, _ontology_digest = ontology_eval._load_cohort_document(root)
        ontology_cases = ontology_eval._cohort_cases(ontology_document)
        v26_documents, v26_cases = ontology_eval._load_v26(root)
    except ontology_eval.OntologyEvaluationError as exc:
        raise SemanticEvaluationError(exc.reason, exc.field) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise SemanticEvaluationError("snapshot_refused", "root") from exc

    v27 = _run_suite(v27_cases, provider=active_provider, root=root, snapshot=root_snapshot)
    with tempfile.TemporaryDirectory(prefix="palimnex-semantic-challenge-") as directory:
        challenge_root = Path(directory)
        write_project(challenge_root, v26_documents)
        challenge_snapshot = cache_v3.source_snapshot(challenge_root)
        challenges = _run_suite(
            v26_cases,
            provider=active_provider,
            root=challenge_root,
            snapshot=challenge_snapshot,
        )
    ontology = _run_suite(
        ontology_cases,
        provider=active_provider,
        root=root,
        snapshot=root_snapshot,
    )
    semantic = _run_suite(
        semantic_cases,
        provider=active_provider,
        root=root,
        snapshot=root_snapshot,
    )
    semantic_repeat = _run_suite(
        semantic_cases,
        provider=active_provider,
        root=root,
        snapshot=root_snapshot,
    )
    drift, source_drift = _run_drift(cohort_document, active_provider)
    privacy, privacy_canary, privacy_canaries = _run_privacy(
        cohort_document, active_provider
    )
    if cache_v3.source_snapshot(root).fingerprint != root_snapshot.fingerprint:
        _fail("repository_changed", "root")

    named_outcomes = {
        "v27": v27,
        "challenges_v26": challenges,
        "ontology_cohort": ontology,
        "semantic_cohort": semantic,
        "drift": drift,
        "privacy": privacy,
    }
    suites = {name: _suite_report(values) for name, values in named_outcomes.items()}
    all_retrieval = v27 + challenges + ontology + semantic + drift
    scored = tuple(
        item for item in semantic if item.outcome.case.category in _SCORED_CATEGORIES
    )
    scored_base = tuple(item.outcome for item in scored)
    base_metrics = ontology_eval._metric_summary(scored_base, "baseline")
    shadow_metrics = ontology_eval._metric_summary(scored_base, "shadow")
    mrr_gain = cast(float, shadow_metrics["mrr"]) - cast(float, base_metrics["mrr"])
    recall_gain = cast(float, shadow_metrics["recall_at_limit"]) - cast(float, base_metrics["recall_at_limit"])
    additional = sorted(
        item.outcome.case.identifier
        for item in scored
        if not item.outcome.baseline.passed and item.outcome.shadow.passed
    )
    cohort_scored = {
        "baseline_mrr": base_metrics["mrr"],
        "shadow_mrr": shadow_metrics["mrr"],
        "mrr_gain": mrr_gain,
        "baseline_recall": base_metrics["recall_at_limit"],
        "shadow_recall": shadow_metrics["recall_at_limit"],
        "recall_gain": recall_gain,
        "additional_pass_ids": additional,
    }

    benchmark_report = (
        _benchmark(
            semantic_cases,
            provider=active_provider,
            root=root,
            snapshot=root_snapshot,
            clock_ns=clock_ns,
        )
        if benchmark
        else _empty_benchmark()
    )
    identity_after = _provider_identity(active_provider)
    comparison_digests = {item.provider_identity_digest for item in all_retrieval}
    provider_identity_bound = (
        identity_before == identity_after
        and comparison_digests == {identity_before_digest}
        and (
            not isinstance(active_provider, HashedEmbeddingProvider)
            or identity_before.get("implementation_digest") == implementation_digest()
        )
    )
    protected_recall = all(
        cast(float, suites[name]["shadow"]["recall_at_limit"])
        >= cast(float, suites[name]["baseline"]["recall_at_limit"])
        for name in _PROTECTED_SUITES
    )
    cohort_gain = (
        mrr_gain + 1e-12 >= cast(float, PROMOTION_POLICY["min_mrr_gain"])
        or recall_gain + 1e-12 >= cast(float, PROMOTION_POLICY["min_recall_gain"])
    )
    no_new_forbidden = all(
        set(item.outcome.shadow.forbidden_hits).issubset(item.outcome.baseline.forbidden_hits)
        for item in all_retrieval
    )
    abstention = all(
        not item.outcome.baseline.abstained or item.outcome.shadow.abstained
        for item in all_retrieval
    ) and all(
        cast(float, report["shadow"]["negative_abstention"])
        >= cast(float, report["baseline"]["negative_abstention"])
        for report in suites.values()
    )
    latency = benchmark and (
        cast(float, benchmark_report["semantic_p95_ms"])
        <= cast(float, PROMOTION_POLICY["max_p95_multiplier"])
        * cast(float, benchmark_report["baseline_p95_ms"])
    )
    gates = {
        "baseline_identical": all(item.outcome.baseline_identical for item in all_retrieval),
        "no_critical_regression": all(
            not item.outcome.case.critical
            or not item.outcome.baseline.passed
            or item.outcome.shadow.passed
            for item in all_retrieval
        ),
        "no_case_regression": all(
            not item.outcome.baseline.passed or item.outcome.shadow.passed
            for item in all_retrieval
        ),
        "protected_recall_not_reduced": protected_recall,
        "cohort_gain": cohort_gain,
        "cohort_additional_pass": len(additional)
        >= cast(int, PROMOTION_POLICY["min_additional_passes"]),
        "no_new_forbidden": no_new_forbidden,
        "abstention_not_regressed": abstention,
        "ambiguity_not_collapsed": all(
            item.outcome.shadow.found_count >= item.outcome.baseline.found_count
            for item in all_retrieval
            if item.outcome.case.category == "ambiguity"
        ),
        "source_drift": source_drift,
        "privacy_canary": privacy_canary,
        "deterministic": [item.comparison_digest for item in semantic]
        == [item.comparison_digest for item in semantic_repeat],
        "provider_identity_bound": provider_identity_bound,
        "latency_within_bound": latency,
        "channels_visible": all(item.outcome.channels_visible for item in all_retrieval),
        "bounded": all(item.outcome.bounded for item in all_retrieval),
    }
    held_reasons = sorted(name for name, passed in gates.items() if not passed)
    if not benchmark:
        held_reasons = sorted(set(held_reasons) | {"benchmark_not_run"})
    report: dict[str, Any] = {
        "schema": EVALUATION_SCHEMA,
        "cohort_digest": cohort_digest,
        "provider": identity_before,
        "provider_identity_digest": identity_before_digest,
        "policy_digest": policy_digest(),
        "promotion_policy": dict(PROMOTION_POLICY),
        "benchmark_protocol": dict(BENCHMARK_PROTOCOL),
        "benchmark": benchmark_report,
        "suites": suites,
        "cohort_scored": cohort_scored,
        "gates": gates,
        "held_reasons": held_reasons,
        "status": "promotable" if all(gates.values()) else "held",
        "promotion_authorized": False,
        "retrieval_influence": False,
        "authority": "evidence_only",
        "authorizes_actions": False,
    }
    serialized = _canonical_safe(report)
    if any(canary.encode("utf-8") in serialized for canary in privacy_canaries):
        gates["privacy_canary"] = False
        held_reasons = sorted(name for name, passed in gates.items() if not passed)
        if not benchmark:
            held_reasons = sorted(set(held_reasons) | {"benchmark_not_run"})
        report["held_reasons"] = held_reasons
        report["status"] = "promotable" if all(gates.values()) else "held"
        report = cast(dict[str, Any], _redact_canaries(report, privacy_canaries))
        _canonical_safe(report)
    return report
