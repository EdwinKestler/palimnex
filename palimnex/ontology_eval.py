"""Deterministic, local-only evaluation for the Phase 3 ontology shadow."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

from . import cache_v3, core
from ._offline_fixtures import write_project
from .challenge import FIXTURE_SHA256 as V26_FIXTURE_SHA256
from .concepts import (
    ConceptRegistry,
    ConceptRegistryError,
    canonical_registry_digest,
    parse_registry,
)
from .durable import canonical_json
from .locators import RepositoryResolver, SourceRange, select_range
from .retrieval import retrieve_sources, shadow_retrieve
from .security import read_bounded_file, scan_bytes


EVALUATION_SCHEMA = "palimnex:ontology-shadow-evaluation:v1"
COHORT_SCHEMA = "palimnex:ontology-shadow-cohort:v1"
COHORT_PATH = Path("palimnex/evaluation/ontology-shadow.v1.json")
V26_PATH = Path("palimnex/evaluation/v26.json")
MAX_FIXTURE_BYTES = 1_000_000
MAX_CASES = 100
ZERO_DIGEST = "0" * 64
CHANNELS = ("lexical", "symbol", "graph", "ontology")


class OntologyEvaluationError(ValueError):
    """A non-echoing evaluation refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str = "evaluation") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"ontology shadow evaluation refused: {reason} at {field}")


@dataclass(frozen=True)
class _EvaluationCase:
    identifier: str
    category: str
    query: str
    limit: int
    expected_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    critical: bool
    expect_ontology_contribution: bool | None = None


@dataclass(frozen=True)
class _VariantOutcome:
    paths: tuple[str, ...]
    found_count: int
    expected_count: int
    first_relevant_rank: int | None
    forbidden_hits: tuple[str, ...]
    passed: bool
    abstained: bool


@dataclass(frozen=True)
class _CaseOutcome:
    case: _EvaluationCase
    baseline: _VariantOutcome
    shadow: _VariantOutcome
    ontology_contributed: bool
    identical_ranking: bool
    baseline_identical: bool
    channels_visible: bool
    bounded: bool
    stale_concept_ids: tuple[str, ...]


def _fail(reason: str, field: str) -> NoReturn:
    raise OntologyEvaluationError(reason, field)


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key", "fixture")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    _fail("non_finite_number", "fixture")


def _decode_document(raw: bytes, field: str) -> dict[str, Any]:
    try:
        findings = scan_bytes(raw)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise OntologyEvaluationError("invalid_utf8", field) from exc
    if findings:
        _fail("privacy_refused", field)
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except OntologyEvaluationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OntologyEvaluationError("invalid_json", field) from exc
    if not isinstance(value, dict):
        _fail("invalid_type", field)
    return cast(dict[str, Any], value)


def _read_fixture(root: Path, relative: Path, field: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = read_bounded_file(root, relative, max_bytes=MAX_FIXTURE_BYTES)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyEvaluationError("fixture_read_refused", field) from exc
    return raw, _decode_document(raw, field)


def _safe_relative_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096:
        _fail("invalid_path", field)
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _fail("invalid_path", field)
    return value


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_CASES:
        _fail("invalid_list", field)
    items = tuple(_safe_relative_path(item, field) for item in value)
    if len(items) != len(set(items)):
        _fail("duplicate_path", field)
    return items


def _case_identifier(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 256
        or any(ord(character) < 32 for character in value)
    ):
        _fail("invalid_identifier", field)
    return value


def _query(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_query", field)
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise OntologyEvaluationError("invalid_utf8", field) from exc
    if len(raw) > 8192 or scan_bytes(raw):
        _fail("query_privacy_refused", field)
    return value


def _case_limit(value: object, field: str) -> int:
    if type(value) is not int or not 1 <= value <= 100:
        _fail("invalid_limit", field)
    return cast(int, value)


def _validate_case_paths(expected: tuple[str, ...], forbidden: tuple[str, ...], field: str) -> None:
    if set(expected) & set(forbidden):
        _fail("path_classification_overlap", field)


def _load_cohort_document(root: Path) -> tuple[dict[str, Any], str]:
    raw, document = _read_fixture(root, COHORT_PATH, "cohort")
    if set(document) != {
        "schema", "status", "binding_digests_are_placeholders", "registry", "cases"
    }:
        _fail("invalid_fields", "cohort")
    if document["schema"] != COHORT_SCHEMA:
        _fail("schema_mismatch", "cohort.schema")
    if document["status"] != "frozen":
        _fail("status_mismatch", "cohort.status")
    if document["binding_digests_are_placeholders"] is not True:
        _fail("placeholder_policy_mismatch", "cohort.binding_digests_are_placeholders")
    if not isinstance(document["registry"], dict):
        _fail("invalid_type", "cohort.registry")
    cases = document["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        _fail("invalid_cases", "cohort.cases")
    return document, hashlib.sha256(raw).hexdigest()


def _cohort_cases(document: Mapping[str, Any]) -> tuple[_EvaluationCase, ...]:
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list):
        _fail("invalid_cases", "cohort.cases")
    cases: list[_EvaluationCase] = []
    identifiers: set[str] = set()
    allowed_categories = {"alias", "paraphrase", "ambiguity", "negative", "control"}
    required = {
        "id", "category", "query", "limit", "expected_paths", "forbidden_paths",
        "critical", "expect_ontology_contribution", "note",
    }
    for index, value in enumerate(raw_cases):
        field = f"cohort.cases[{index}]"
        if not isinstance(value, dict) or set(value) != required:
            _fail("invalid_fields", field)
        identifier = _case_identifier(value["id"], field + ".id")
        if identifier in identifiers:
            _fail("duplicate_identifier", field + ".id")
        identifiers.add(identifier)
        category = value["category"]
        if not isinstance(category, str) or category not in allowed_categories:
            _fail("invalid_category", field + ".category")
        expected = _string_list(value["expected_paths"], field + ".expected_paths")
        forbidden = _string_list(value["forbidden_paths"], field + ".forbidden_paths")
        _validate_case_paths(expected, forbidden, field)
        if category == "negative" and expected:
            _fail("negative_has_expected_paths", field + ".expected_paths")
        if type(value["critical"]) is not bool:
            _fail("invalid_boolean", field + ".critical")
        if type(value["expect_ontology_contribution"]) is not bool:
            _fail("invalid_boolean", field + ".expect_ontology_contribution")
        if not isinstance(value["note"], str) or not value["note"].strip():
            _fail("invalid_note", field + ".note")
        cases.append(
            _EvaluationCase(
                identifier,
                category,
                _query(value["query"], field + ".query"),
                _case_limit(value["limit"], field + ".limit"),
                expected,
                forbidden,
                cast(bool, value["critical"]),
                cast(bool, value["expect_ontology_contribution"]),
            )
        )
    return tuple(cases)


def _validate_placeholder_registry(document: Mapping[str, Any], root: Path) -> None:
    if document.get("registry_digest") != ZERO_DIGEST:
        _fail("placeholder_digest_mismatch", "cohort.registry.registry_digest")
    concepts = document.get("concepts")
    if not isinstance(concepts, list):
        _fail("invalid_type", "cohort.registry.concepts")
    for concept_index, concept in enumerate(concepts):
        field = f"cohort.registry.concepts[{concept_index}]"
        if not isinstance(concept, dict):
            _fail("invalid_type", field)
        bindings = concept.get("source_bindings")
        if not isinstance(bindings, list) or not bindings:
            _fail("invalid_type", field + ".source_bindings")
        for binding_index, binding in enumerate(bindings):
            binding_field = field + f".source_bindings[{binding_index}]"
            if not isinstance(binding, dict):
                _fail("invalid_type", binding_field)
            if binding.get("scheme") != "repo":
                _fail("unsupported_scheme", binding_field + ".scheme")
            _safe_relative_path(binding.get("source_id"), binding_field + ".source_id")
            if binding.get("version") != ZERO_DIGEST or binding.get("digest") != ZERO_DIGEST:
                _fail("placeholder_digest_mismatch", binding_field)
    placeholder = copy.deepcopy(dict(document))
    placeholder["registry_digest"] = canonical_registry_digest(placeholder)
    try:
        parse_registry(
            placeholder,
            root=root,
            expected_kind="approved_registry",
            allow_placeholder_digests=True,
        )
    except ConceptRegistryError as exc:
        raise OntologyEvaluationError("registry_refused", "cohort.registry") from exc


def _materialize_registry(
    document: Mapping[str, Any], root: Path
) -> tuple[ConceptRegistry, tuple[str, ...]]:
    """Replace current bindings and leave missing/range-drift bindings stale."""
    _validate_placeholder_registry(document, root)
    materialized = copy.deepcopy(dict(document))
    concepts = cast(list[dict[str, Any]], materialized["concepts"])
    stale: set[str] = set()
    resolver = RepositoryResolver(root)
    for concept_index, concept in enumerate(concepts):
        concept_id = cast(str, concept["concept_id"])
        bindings = cast(list[dict[str, Any]], concept["source_bindings"])
        for binding_index, binding in enumerate(bindings):
            field = (
                f"cohort.registry.concepts[{concept_index}]"
                f".source_bindings[{binding_index}]"
            )
            source_id = _safe_relative_path(binding["source_id"], field + ".source_id")
            target = root / source_id
            if target.is_symlink():
                _fail("source_symlink_refused", field + ".source_id")
            if not target.is_file():
                stale.add(concept_id)
                continue
            try:
                source = resolver.resolve(source_id, ZERO_DIGEST)
            except (OSError, TypeError, ValueError):
                stale.add(concept_id)
                continue
            try:
                findings = scan_bytes(source.content)
            except (TypeError, UnicodeError, ValueError) as exc:
                raise OntologyEvaluationError("source_privacy_refused", field) from exc
            if findings:
                _fail("source_privacy_refused", field)
            bounds_value = binding.get("range")
            if not isinstance(bounds_value, dict):
                _fail("invalid_range", field + ".range")
            try:
                bounds = SourceRange(
                    cast(str, bounds_value.get("unit")),
                    cast(int, bounds_value.get("start")),
                    cast(int, bounds_value.get("end")),
                )
                selected = select_range(source.content, bounds)
            except (TypeError, UnicodeError) as exc:
                raise OntologyEvaluationError("invalid_source", field) from exc
            except ValueError:
                stale.add(concept_id)
                continue
            binding["version"] = source.version
            binding["digest"] = hashlib.sha256(selected).hexdigest()
    materialized["registry_digest"] = canonical_registry_digest(materialized)
    try:
        registry = parse_registry(
            materialized,
            root=root,
            expected_kind="approved_registry",
            allow_placeholder_digests=True,
        )
    except ConceptRegistryError as exc:
        raise OntologyEvaluationError("registry_refused", "cohort.registry") from exc
    return registry, tuple(sorted(stale))


def _load_v27_cases(root: Path) -> tuple[_EvaluationCase, ...]:
    try:
        config = core.project_config(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyEvaluationError("configuration_refused", "v27") from exc
    relative_value = config.get("evaluation_fixture")
    digest = config.get("evaluation_fixture_sha256")
    relative_text = _safe_relative_path(relative_value, "v27.path")
    if not isinstance(digest, str) or len(digest) != 64:
        _fail("invalid_fixture_digest", "v27.digest")
    raw, _document = _read_fixture(root, Path(relative_text), "v27")
    if hashlib.sha256(raw).hexdigest() != digest:
        _fail("fixture_digest_mismatch", "v27.digest")
    try:
        loaded = cache_v3._evaluation_cases(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyEvaluationError("fixture_refused", "v27") from exc
    cases: list[_EvaluationCase] = []
    for index, value in enumerate(loaded):
        if value.get("mode") != "search":
            continue
        field = f"v27.cases[{index}]"
        expected = _string_list(value.get("expected_paths"), field + ".expected_paths")
        forbidden = _string_list(value.get("forbidden_paths"), field + ".forbidden_paths")
        _validate_case_paths(expected, forbidden, field)
        critical = value.get("critical")
        if type(critical) is not bool:
            _fail("invalid_boolean", field + ".critical")
        cases.append(
            _EvaluationCase(
                _case_identifier(value.get("id"), field + ".id"),
                "v27",
                _query(value.get("query"), field + ".query"),
                _case_limit(value.get("limit"), field + ".limit"),
                expected,
                forbidden,
                cast(bool, critical),
            )
        )
    if not cases:
        _fail("missing_search_cases", "v27.cases")
    return tuple(cases)


def _load_v26(root: Path) -> tuple[dict[str, str], tuple[_EvaluationCase, ...]]:
    raw, document = _read_fixture(root, V26_PATH, "challenges_v26")
    if hashlib.sha256(raw).hexdigest() != V26_FIXTURE_SHA256:
        _fail("fixture_digest_mismatch", "challenges_v26.digest")
    if set(document) != {"schema", "description", "documents", "cases"}:
        _fail("invalid_fields", "challenges_v26")
    if document["schema"] != "project-memory:challenge:v1":
        _fail("schema_mismatch", "challenges_v26.schema")
    documents_value = document["documents"]
    if not isinstance(documents_value, dict) or not documents_value:
        _fail("invalid_documents", "challenges_v26.documents")
    documents: dict[str, str] = {}
    for raw_path, raw_text in documents_value.items():
        path = _safe_relative_path(raw_path, "challenges_v26.documents")
        if not isinstance(raw_text, str):
            _fail("invalid_document", "challenges_v26.documents")
        encoded = raw_text.encode("utf-8", errors="strict")
        if scan_bytes(encoded):
            _fail("source_privacy_refused", "challenges_v26.documents")
        documents[path] = raw_text
    raw_cases = document["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= MAX_CASES:
        _fail("invalid_cases", "challenges_v26.cases")
    cases: list[_EvaluationCase] = []
    identifiers: set[str] = set()
    for index, value in enumerate(raw_cases):
        field = f"challenges_v26.cases[{index}]"
        if not isinstance(value, dict) or set(value) != {"id", "query", "expected_paths"}:
            _fail("invalid_fields", field)
        identifier = _case_identifier(value["id"], field + ".id")
        if identifier in identifiers:
            _fail("duplicate_identifier", field + ".id")
        identifiers.add(identifier)
        expected = _string_list(value["expected_paths"], field + ".expected_paths")
        cases.append(
            _EvaluationCase(
                identifier,
                "negative" if not expected else "challenge",
                _query(value["query"], field + ".query"),
                100,
                expected,
                (),
                False,
            )
        )
    return documents, tuple(cases)


def _pointer_path(pointer: object) -> str:
    if not isinstance(pointer, str) or ":" not in pointer:
        _fail("invalid_pointer", "comparison.shadow.items.pointer")
    path, suffix = pointer.rsplit(":", 1)
    if not path or "-" not in suffix:
        _fail("invalid_pointer", "comparison.shadow.items.pointer")
    return _safe_relative_path(path, "comparison.shadow.items.pointer")


def _variant_outcome(
    paths: Sequence[str], expected: tuple[str, ...], forbidden: tuple[str, ...]
) -> _VariantOutcome:
    returned = tuple(paths)
    returned_set = set(returned)
    expected_set = set(expected)
    ranks = [returned.index(path) + 1 for path in expected if path in returned_set]
    forbidden_hits = tuple(sorted(set(forbidden) & returned_set))
    abstained = not returned
    found = len(expected_set & returned_set)
    passed = found == len(expected) and not forbidden_hits and (bool(expected) or abstained)
    return _VariantOutcome(
        returned,
        found,
        len(expected),
        min(ranks) if ranks else None,
        forbidden_hits,
        passed,
        abstained,
    )


def _comparison_is_bounded(
    baseline: Mapping[str, Any], comparison: Mapping[str, Any], case_limit: int
) -> bool:
    shadow = comparison.get("shadow")
    ontology = comparison.get("ontology_channel")
    if not isinstance(shadow, Mapping) or not isinstance(ontology, Mapping):
        return False
    baseline_results = baseline.get("results")
    items = shadow.get("items")
    byte_budget = comparison.get("byte_budget")
    candidate_count = ontology.get("candidate_count")
    truncated = ontology.get("truncated")
    if (
        not isinstance(baseline_results, list)
        or not isinstance(items, list)
        or len(baseline_results) > case_limit
        or len(items) > case_limit
        or comparison.get("limit") != case_limit
        or type(byte_budget) is not int
        or type(shadow.get("items_bytes")) is not int
        or not 0 <= shadow["items_bytes"] <= byte_budget
        or type(shadow.get("candidate_count")) is not int
        or not 0 <= shadow["candidate_count"] <= 512
        or type(baseline.get("candidate_count")) is not int
        or not 0 <= baseline["candidate_count"] <= 512
        or type(candidate_count) is not int
        or candidate_count < 0
        or type(truncated) is not bool
        or truncated is not (candidate_count > 512)
    ):
        return False
    for item in items:
        if not isinstance(item, Mapping) or not isinstance(item.get("channels"), Mapping):
            return False
        if any(
            type(rank) is not int or not 1 <= rank <= 512
            for rank in item["channels"].values()
        ):
            return False
    return True


def _run_case(
    case: _EvaluationCase,
    *,
    root: Path,
    registry: ConceptRegistry | None,
    report_limit: int,
    snapshot: Any,
) -> _CaseOutcome:
    active_limit = min(report_limit, case.limit)
    byte_budget = 8192
    include_graph = True
    response = shadow_retrieve(
        case.query,
        registry=registry,
        root=root,
        limit=active_limit,
        byte_budget=byte_budget,
        include_graph=include_graph,
        client=None,
        snapshot=snapshot,
    )
    direct_baseline = retrieve_sources(
        case.query,
        root=root,
        limit=active_limit,
        byte_budget=byte_budget,
        include_graph=include_graph,
        client=None,
        snapshot=snapshot,
    )
    baseline_value = response.get("baseline")
    comparison_value = response.get("comparison")
    if not isinstance(baseline_value, Mapping) or not isinstance(comparison_value, Mapping):
        _fail("invalid_shadow_response", "shadow_retrieve")
    baseline_identical = canonical_json(baseline_value) == canonical_json(direct_baseline)
    baseline_results = direct_baseline.get("results")
    if not isinstance(baseline_results, list):
        _fail("invalid_shadow_response", "baseline.results")
    baseline_paths: list[str] = []
    for item in baseline_results:
        if not isinstance(item, Mapping):
            _fail("invalid_shadow_response", "baseline.results")
        baseline_paths.append(_safe_relative_path(item.get("path"), "baseline.results.path"))
    shadow_value = comparison_value.get("shadow")
    if not isinstance(shadow_value, Mapping) or not isinstance(shadow_value.get("items"), list):
        _fail("invalid_shadow_response", "comparison.shadow")
    shadow_items = cast(list[Any], shadow_value["items"])
    shadow_paths = [
        _pointer_path(item.get("pointer") if isinstance(item, Mapping) else None)
        for item in shadow_items
    ]
    ontology = comparison_value.get("ontology_channel")
    if not isinstance(ontology, Mapping):
        _fail("invalid_shadow_response", "comparison.ontology_channel")
    contributing = ontology.get("contributing_concept_ids")
    candidate_count = ontology.get("candidate_count")
    stale = ontology.get("excluded_stale")
    if not isinstance(contributing, list) or type(candidate_count) is not int:
        _fail("invalid_shadow_response", "comparison.ontology_channel")
    if not isinstance(stale, list) or not all(isinstance(item, str) for item in stale):
        _fail("invalid_shadow_response", "comparison.ontology_channel.excluded_stale")
    channels_visible = comparison_value.get("channels") == list(CHANNELS) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("channels"), Mapping)
        and bool(item["channels"])
        and not (set(item["channels"]) - set(CHANNELS))
        for item in shadow_items
    )
    diff = comparison_value.get("diff")
    if not isinstance(diff, Mapping) or type(diff.get("identical")) is not bool:
        _fail("invalid_shadow_response", "comparison.diff")
    return _CaseOutcome(
        case,
        _variant_outcome(baseline_paths, case.expected_paths, case.forbidden_paths),
        _variant_outcome(shadow_paths, case.expected_paths, case.forbidden_paths),
        bool(contributing) and candidate_count > 0,
        cast(bool, diff["identical"]),
        baseline_identical,
        channels_visible,
        _comparison_is_bounded(baseline_value, comparison_value, active_limit),
        tuple(sorted(cast(list[str], stale))),
    )


def _metric_summary(
    outcomes: Sequence[_CaseOutcome], variant: Literal["baseline", "shadow"]
) -> dict[str, Any]:
    selected = [
        outcome.baseline if variant == "baseline" else outcome.shadow
        for outcome in outcomes
    ]
    expected_total = sum(item.expected_count for item in selected)
    found_total = sum(item.found_count for item in selected)
    reciprocal_total = sum(
        0.0 if item.first_relevant_rank is None else 1.0 / item.first_relevant_rank
        for item in selected
    )
    negative = [item for item in selected if item.expected_count == 0]
    critical = [
        item
        for item, outcome in zip(selected, outcomes, strict=True)
        if outcome.case.critical
    ]
    return {
        "case_count": len(selected),
        "cases_passed": sum(item.passed for item in selected),
        "critical_case_count": len(critical),
        "critical_pass_count": sum(item.passed for item in critical),
        "forbidden_path_hits": sum(len(item.forbidden_hits) for item in selected),
        "recall_at_limit": found_total / expected_total if expected_total else 0.0,
        "mrr": reciprocal_total / len(selected) if selected else 0.0,
        "negative_case_count": len(negative),
        "negative_abstention": (
            sum(item.abstained for item in negative) / len(negative) if negative else 1.0
        ),
    }


def _suite_report(outcomes: Sequence[_CaseOutcome]) -> dict[str, Any]:
    rows = [
        {
            "id": outcome.case.identifier,
            "category": outcome.case.category,
            "critical": outcome.case.critical,
            "baseline_pass": outcome.baseline.passed,
            "shadow_pass": outcome.shadow.passed,
            "baseline_first_relevant_rank": outcome.baseline.first_relevant_rank,
            "shadow_first_relevant_rank": outcome.shadow.first_relevant_rank,
            "ontology_contributed": outcome.ontology_contributed,
        }
        for outcome in outcomes
    ]
    identical = sum(outcome.identical_ranking for outcome in outcomes)
    return {
        "baseline": _metric_summary(outcomes, "baseline"),
        "shadow": _metric_summary(outcomes, "shadow"),
        "identical_ranking_count": identical,
        "changed_ranking_count": len(outcomes) - identical,
        "regressed_case_ids": sorted(
            outcome.case.identifier
            for outcome in outcomes
            if outcome.baseline.passed and not outcome.shadow.passed
        ),
        "cases": rows,
    }


def _run_suite(
    cases: Sequence[_EvaluationCase],
    *,
    root: Path,
    registry: ConceptRegistry | None,
    report_limit: int,
    snapshot: Any,
) -> tuple[tuple[_CaseOutcome, ...], dict[str, Any]]:
    outcomes = tuple(
        _run_case(
            case,
            root=root,
            registry=registry,
            report_limit=report_limit,
            snapshot=snapshot,
        )
        for case in cases
    )
    return outcomes, _suite_report(outcomes)


def _gates(outcomes: Sequence[_CaseOutcome]) -> dict[str, bool]:
    return {
        "baseline_identical": all(
            outcome.baseline_identical for outcome in outcomes
        ),
        "no_critical_regression": all(
            not outcome.baseline.passed or outcome.shadow.passed
            for outcome in outcomes
            if outcome.case.critical
        ),
        "no_case_regression": all(
            not outcome.baseline.passed or outcome.shadow.passed
            for outcome in outcomes
        ),
        "no_new_forbidden": sum(len(outcome.shadow.forbidden_hits) for outcome in outcomes)
        <= sum(len(outcome.baseline.forbidden_hits) for outcome in outcomes),
        "abstention_not_regressed": all(
            not outcome.baseline.abstained or outcome.shadow.abstained
            for outcome in outcomes
        ),
        "ambiguity_never_contributes": all(
            not outcome.ontology_contributed
            for outcome in outcomes
            if outcome.case.category == "ambiguity"
        ),
        "channels_visible": all(outcome.channels_visible for outcome in outcomes),
        "bounded": all(outcome.bounded for outcome in outcomes),
    }


def evaluate_ontology_shadow(root: Path = core.ROOT, *, limit: int = 5) -> dict[str, Any]:
    """Evaluate baseline and ontology-shadow rankings without retrieval influence."""
    if not isinstance(root, Path):
        _fail("invalid_type", "root")
    report_limit = _case_limit(limit, "limit")
    cohort_document, cohort_digest = _load_cohort_document(root)
    cohort_cases = _cohort_cases(cohort_document)
    registry_value = cohort_document["registry"]
    if not isinstance(registry_value, Mapping):
        _fail("invalid_type", "cohort.registry")
    v27_cases = _load_v27_cases(root)
    v26_documents, v26_cases = _load_v26(root)
    try:
        root_snapshot = cache_v3.source_snapshot(root)
    except (OSError, TypeError, ValueError) as exc:
        raise OntologyEvaluationError("snapshot_refused", "root") from exc
    registry, materialization_stale = _materialize_registry(registry_value, root)
    if cache_v3.source_snapshot(root).fingerprint != root_snapshot.fingerprint:
        _fail("repository_changed", "root")

    v27_outcomes, v27_report = _run_suite(
        v27_cases,
        root=root,
        registry=registry,
        report_limit=report_limit,
        snapshot=root_snapshot,
    )
    with tempfile.TemporaryDirectory(prefix="palimnex-ontology-shadow-") as directory:
        challenge_root = Path(directory)
        write_project(challenge_root, v26_documents)
        challenge_snapshot = cache_v3.source_snapshot(challenge_root)
        challenge_outcomes, challenge_report = _run_suite(
            v26_cases,
            root=challenge_root,
            registry=None,
            report_limit=report_limit,
            snapshot=challenge_snapshot,
        )
    cohort_outcomes, cohort_report = _run_suite(
        cohort_cases,
        root=root,
        registry=registry,
        report_limit=report_limit,
        snapshot=root_snapshot,
    )
    if cache_v3.source_snapshot(root).fingerprint != root_snapshot.fingerprint:
        _fail("repository_changed", "root")

    all_outcomes = v27_outcomes + challenge_outcomes + cohort_outcomes
    stale = sorted(
        set(materialization_stale).union(
            *(set(outcome.stale_concept_ids) for outcome in all_outcomes)
        )
    )
    report: dict[str, Any] = {
        "schema": EVALUATION_SCHEMA,
        "cohort_digest": cohort_digest,
        "registry_digest": registry.registry_digest,
        "stale_concept_ids": stale,
        "limit": report_limit,
        "suites": {
            "v27": v27_report,
            "challenges_v26": challenge_report,
            "cohort": cohort_report,
        },
        "gates": _gates(all_outcomes),
        "promotion_authorized": False,
        "retrieval_influence": False,
        "authority": "evidence_only",
        "authorizes_actions": False,
    }
    # Prove the public result is canonical-JSON safe before returning it.
    try:
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise OntologyEvaluationError("canonicalization_failed", "report") from exc
    return report
