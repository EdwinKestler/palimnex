"""Deterministic, evidence-only ontology coverage receipts.

The coverage engine consumes an already-produced search result without changing
or ranking it.  Phase 1 deliberately collapses ordinary binding failures to the
public ``source_drift`` reason.  This module first uses that verifier, then
refines a drifted *applicable* binding at the same public locator boundaries:
missing object -> ``missing``; changed resolver version ->
``version_changed``; changed selected-byte digest -> ``digest_changed``; and
resolver, range, race, or malformed-result failures -> ``unavailable``.
Phase 1's unsafe-input reasons remain exceptions and never become receipt state.
"""

from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

from . import cache_v3
from .concepts import (
    Concept,
    ConceptRegistry,
    ConceptRegistryError,
    ProjectIdentity,
    match_aliases,
    verify_source_bindings,
)
from .core import project_slug
from .durable import canonical_json
from .locators import (
    RepositoryResolver,
    ResolvedSource,
    SourceLocator,
    SourceResolver,
    select_range,
)
from .security import scan_bytes


COVERAGE_SCHEMA = "palimnex:retrieval-coverage:v1"
EXPLAIN_SEARCH_SCHEMA = "palimnex:explain-search:v1"
QUERY_DIGEST_POLICY = "sha256-utf8-nfc-lf-preserve-whitespace-case:v1"

MAX_QUERY_BYTES = 8 * 1024
MAX_COVERAGE_COLLECTION_ITEMS = 256
MAX_COVERAGE_COLLECTION_TOTAL = 4_096
MAX_NESTED_DETAIL_ITEMS = 16
MAX_NESTED_DETAIL_TOTAL = 64
MAX_RECEIPT_BYTE_STATE = 64 * 1024 * 1024
MAX_REGISTRY_PATH_CHARS = 512

_HEX_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_CONCEPT_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*")
_PROJECT_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_PROJECT_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]{0,31}")

_COVERAGE_KEYS = frozenset(
    {
        "schema",
        "query_digest",
        "query_digest_policy",
        "identities",
        "recognized_concepts",
        "covered_concepts",
        "uncovered_concepts",
        "ambiguous_concepts",
        "stale_concepts",
        "coverage",
        "retrieval_state",
        "semantic_disclosure",
        "status",
        "receipt_digest",
        "authority",
        "authorizes_actions",
    }
)
_STALE_REASONS = frozenset(
    {"missing", "version_changed", "digest_changed", "unavailable"}
)
_SEMANTIC_DISCLOSURE: dict[str, Any] = {
    "interface": "project-memory:semantic-provider:v1",
    "mode": "disabled",
    "external_network_enabled": False,
    "provider_registered": False,
    "hnsw_enabled": False,
    "retrieval_influence": False,
}

CoverageStatus = Literal["answerable", "partial", "ambiguous", "unanswerable"]
StaleReason = Literal["missing", "version_changed", "digest_changed", "unavailable"]


class CoverageError(ValueError):
    """A non-echoing coverage refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str = "coverage") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"coverage refused: {reason} at {field}")


def _fail(reason: str, field: str) -> NoReturn:
    raise CoverageError(reason, field)


def _wrap_registry_error(exc: ConceptRegistryError) -> NoReturn:
    raise CoverageError(exc.reason, exc.field) from exc


def query_digest(query: str) -> str:
    """Return the v1 digest of one bounded, non-empty admitted query."""
    if not isinstance(query, str):
        _fail("invalid_type", "query")
    try:
        encoded = query.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CoverageError("invalid_utf8", "query") from exc
    if not query.strip():
        _fail("empty_query", "query")
    if len(encoded) > MAX_QUERY_BYTES:
        _fail("query_byte_bound", "query")
    normalized = unicodedata.normalize("NFC", query.replace("\r\n", "\n").replace("\r", "\n"))
    return hashlib.sha256(normalized.encode("utf-8", errors="strict")).hexdigest()


def canonical_receipt_digest(receipt: Mapping[str, Any]) -> str:
    """Hash canonical receipt content with only ``receipt_digest`` excluded."""
    if not isinstance(receipt, Mapping):
        _fail("invalid_type", "receipt")
    body = dict(receipt)
    body.pop("receipt_digest", None)
    try:
        encoded = canonical_json(body)
    except (RecursionError, TypeError, ValueError) as exc:
        raise CoverageError("canonicalization_failed", "receipt") from exc
    return hashlib.sha256(encoded).hexdigest()


def _expected_project(root: Path) -> ProjectIdentity:
    try:
        return ProjectIdentity(project_slug(root), cache_v3.project_id(root))
    except (OSError, TypeError, ValueError) as exc:
        raise CoverageError("project_identity_unavailable", "project") from exc


def _locator_key(locator: SourceLocator) -> tuple[str, str, str, str, int, int, str]:
    return (
        locator.scheme,
        locator.source_id,
        locator.version,
        locator.range.unit,
        locator.range.start,
        locator.range.end,
        locator.digest,
    )


def _locator_dict(locator: SourceLocator) -> dict[str, Any]:
    return locator.to_dict()


def _applicable_bindings(
    concept: Concept,
    resolvers: Mapping[str, SourceResolver],
) -> tuple[SourceLocator, ...]:
    applicable: list[SourceLocator] = []
    for locator in concept.source_bindings:
        if locator.scheme == "repo":
            applicable.append(locator)
            continue
        resolver = resolvers.get(locator.scheme)
        if resolver is not None and getattr(resolver, "api_version", None) == 1:
            applicable.append(locator)
    return tuple(applicable)


def _diagnose_stale_binding(
    locator: SourceLocator,
    *,
    root: Path,
    resolvers: Mapping[str, SourceResolver],
) -> StaleReason:
    """Refine Phase 1 ``source_drift`` without exposing provider detail."""
    resolver: SourceResolver | None
    if locator.scheme == "repo":
        if not (root / locator.source_id).exists():
            return "missing"
        try:
            resolver = RepositoryResolver(root)
        except (OSError, RuntimeError):
            return "unavailable"
    else:
        resolver = resolvers.get(locator.scheme)
    if resolver is None or getattr(resolver, "api_version", None) != 1:
        return "unavailable"
    try:
        source = resolver.resolve(locator.source_id, locator.version)
    except FileNotFoundError:
        return "missing"
    except Exception:
        return "unavailable"
    if not isinstance(source, ResolvedSource):
        return "unavailable"
    if source.version != locator.version:
        return "version_changed"
    try:
        findings = scan_bytes(source.content)
    except (TypeError, UnicodeError, ValueError):
        return "unavailable"
    if findings:
        _fail("source_privacy_refused", "source_bindings")
    try:
        selected = select_range(source.content, locator.range)
    except (TypeError, UnicodeError, ValueError):
        return "unavailable"
    if hashlib.sha256(selected).hexdigest() != locator.digest:
        return "digest_changed"
    # The Phase 1 verifier observed drift, but the source is current now.  This
    # is a race disclosure, not permission to silently upgrade the result.
    return "unavailable"


def _bounded_nested(values: Sequence[Any], field: str) -> tuple[list[Any], int, bool]:
    total = len(values)
    if total > MAX_NESTED_DETAIL_TOTAL:
        _fail("nested_detail_bound", field)
    return list(values[:MAX_NESTED_DETAIL_ITEMS]), total, total > MAX_NESTED_DETAIL_ITEMS


def _collection(items: Sequence[Any], field: str) -> dict[str, Any]:
    total = len(items)
    if total > MAX_COVERAGE_COLLECTION_TOTAL:
        _fail("collection_bound", field)
    return {
        "items": list(items[:MAX_COVERAGE_COLLECTION_ITEMS]),
        "total_count": total,
        "truncated": total > MAX_COVERAGE_COLLECTION_ITEMS,
    }


def _status(covered: int, recognized: int, ambiguous_aliases: int) -> CoverageStatus:
    if ambiguous_aliases > 0:
        return "ambiguous"
    if recognized == 0:
        return "unanswerable"
    if covered == recognized:
        return "answerable"
    if covered > 0:
        return "partial"
    return "unanswerable"


def _require_search_result(search_result: Mapping[str, Any], query: str, root: Path) -> dict[str, Any]:
    if not isinstance(search_result, Mapping):
        _fail("invalid_type", "search_result")
    result = dict(search_result)
    required = {
        "query",
        "results",
        "candidate_count",
        "omitted_count",
        "byte_budget",
        "items_bytes",
        "budget_unit",
        "corpus_fingerprint",
        "checkout_id",
        "semantic_influence",
        "authorizes_actions",
    }
    if not required.issubset(result):
        _fail("missing_field", "search_result")
    if result["query"] != query:
        _fail("query_mismatch", "search_result.query")
    results = result["results"]
    if not isinstance(results, list) or len(results) > MAX_COVERAGE_COLLECTION_TOTAL:
        _fail("invalid_results", "search_result.results")
    for field, maximum in (
        ("candidate_count", 100_000),
        ("omitted_count", 100_000),
        ("byte_budget", MAX_RECEIPT_BYTE_STATE),
        ("items_bytes", MAX_RECEIPT_BYTE_STATE),
    ):
        value = result[field]
        minimum = 1 if field == "byte_budget" else 0
        if type(value) is not int or not minimum <= value <= maximum:
            _fail("invalid_integer", f"search_result.{field}")
    if result["candidate_count"] != len(results) + result["omitted_count"]:
        _fail("retrieval_count_mismatch", "search_result")
    if result["items_bytes"] > result["byte_budget"]:
        _fail("byte_budget_mismatch", "search_result")
    if result["budget_unit"] != "serialized_utf8_bytes":
        _fail("budget_unit_mismatch", "search_result.budget_unit")
    if not _is_sha256(result["corpus_fingerprint"]):
        _fail("invalid_digest", "search_result.corpus_fingerprint")
    expected_checkout = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    if result["checkout_id"] != expected_checkout:
        _fail("checkout_mismatch", "search_result.checkout_id")
    if result["semantic_influence"] is not False:
        _fail("semantic_influence_enabled", "search_result.semantic_influence")
    if result["authorizes_actions"] is not False:
        _fail("authorizes_actions", "search_result.authorizes_actions")
    return result


def _retrieval_state(
    search_result: Mapping[str, Any],
    coverage_truncated: bool,
    retrieval_limit: int | None,
) -> dict[str, Any]:
    omitted = cast(int, search_result["omitted_count"])
    used = cast(int, search_result["items_bytes"])
    budget = cast(int, search_result["byte_budget"])
    result_count = len(cast(list[Any], search_result["results"]))
    if omitted == 0:
        retrieval_truncated = False
        byte_omitted = False
    elif retrieval_limit is None:
        # Without the retrieve_sources limit, its omission cause cannot be
        # attributed from the search-result fields.
        retrieval_truncated = True
        byte_omitted = False
    elif result_count < retrieval_limit:
        retrieval_truncated = False
        byte_omitted = True
    else:
        # The limit bound. Further byte-budget drops cannot be attributed from
        # retrieve_sources fields, so disclose only retrieval truncation.
        retrieval_truncated = True
        byte_omitted = False
    return {
        "retrieval_truncated": retrieval_truncated,
        "result_item_count": result_count,
        "omitted_result_count": omitted,
        "coverage_output_truncated": coverage_truncated,
        "byte_budget_omission": {
            "omitted": byte_omitted,
            "omitted_item_count": omitted if byte_omitted else 0,
            "byte_budget": budget,
            "used_bytes": used,
        },
    }


def build_coverage_receipt(
    registry: ConceptRegistry,
    query: str,
    search_result: Mapping[str, Any],
    *,
    root: Path,
    resolvers: Mapping[str, SourceResolver] | None = None,
    retrieval_limit: int | None = None,
) -> dict[str, Any]:
    """Build one deterministic receipt over an unchanged search result."""
    digest = query_digest(query)
    if not isinstance(registry, ConceptRegistry):
        _fail("invalid_type", "registry")
    if registry.registry_kind != "approved_registry":
        _fail("registry_kind_mismatch", "registry.registry_kind")
    expected_project = _expected_project(root)
    if registry.project != expected_project:
        _fail("project_mismatch", "registry.project")
    search = _require_search_result(search_result, query, root)
    if retrieval_limit is not None and (
        type(retrieval_limit) is not int or not 1 <= retrieval_limit <= 100
    ):
        _fail("invalid_retrieval_limit", "retrieval_limit")
    if retrieval_limit is not None and len(search["results"]) > retrieval_limit:
        _fail("retrieval_limit_mismatch", "search_result.results")
    active_resolvers: Mapping[str, SourceResolver] = {} if resolvers is None else resolvers

    try:
        matches = match_aliases(registry, query)
    except ConceptRegistryError as exc:
        _wrap_registry_error(exc)
    ambiguous_ids = set(matches.ambiguous_concept_ids)
    by_id = {concept.concept_id: concept for concept in registry.active_concepts}
    recognized_ids = set(matches.recognized_concept_ids)
    eligible_ids = sorted(recognized_ids - ambiguous_ids)

    applicable_by_id: dict[str, tuple[SourceLocator, ...]] = {}
    verification_concepts: list[Concept] = []
    uncovered_ids: list[str] = []
    for concept_id in eligible_ids:
        concept = by_id.get(concept_id)
        if concept is None:
            _fail("recognized_concept_missing", "registry.concepts")
        applicable = _applicable_bindings(concept, active_resolvers)
        applicable_by_id[concept_id] = applicable
        if not applicable:
            uncovered_ids.append(concept_id)
        else:
            verification_concepts.append(replace(concept, source_bindings=applicable))

    verification_by_id: dict[str, list[tuple[SourceLocator, bool, str]]] = {}
    if verification_concepts:
        narrowed = replace(registry, concepts=tuple(verification_concepts))
        try:
            verification = verify_source_bindings(
                narrowed,
                root=root,
                resolvers=active_resolvers,
            )
        except ConceptRegistryError as exc:
            _wrap_registry_error(exc)
        narrowed_by_id = {item.concept_id: item for item in verification_concepts}
        for item in verification.bindings:
            if item.reason not in {"verified", "source_drift"}:
                _fail("unknown_verification_reason", "source_bindings")
            concept = narrowed_by_id[item.concept_id]
            locator = concept.source_bindings[item.binding_index]
            verification_by_id.setdefault(item.concept_id, []).append(
                (locator, item.verified, item.reason)
            )

    recognized_items: list[dict[str, Any]] = []
    for match in matches.recognized_concepts:
        aliases, count, truncated = _bounded_nested(
            tuple(sorted(match.matched_aliases)),
            "recognized_concepts.matched_aliases",
        )
        recognized_items.append(
            {
                "concept_id": match.concept_id,
                "matched_aliases": aliases,
                "matched_alias_count": count,
                "matched_aliases_truncated": truncated,
            }
        )

    covered_items: list[dict[str, Any]] = []
    stale_items: list[dict[str, Any]] = []
    for concept_id in sorted(verification_by_id):
        outcomes = verification_by_id[concept_id]
        verified_locators = sorted(
            (locator for locator, verified, _reason in outcomes if verified),
            key=_locator_key,
        )
        if verified_locators:
            visible, count, truncated = _bounded_nested(
                tuple(_locator_dict(item) for item in verified_locators),
                "covered_concepts.verified_bindings",
            )
            covered_items.append(
                {
                    "concept_id": concept_id,
                    "verified_bindings": visible,
                    "verified_binding_count": count,
                    "verified_bindings_truncated": truncated,
                }
            )
            continue

        failed = sorted(
            (locator for locator, _verified, reason in outcomes if reason == "source_drift"),
            key=_locator_key,
        )
        if not failed:
            _fail("verification_result_missing", "source_bindings")
        reasons = {
            _diagnose_stale_binding(locator, root=root, resolvers=active_resolvers)
            for locator in failed
        }
        stale_reason: StaleReason = next(iter(reasons)) if len(reasons) == 1 else "unavailable"
        visible, count, truncated = _bounded_nested(
            tuple(_locator_dict(item) for item in failed),
            "stale_concepts.stale_bindings",
        )
        stale_items.append(
            {
                "concept_id": concept_id,
                "stale_bindings": visible,
                "stale_binding_count": count,
                "stale_bindings_truncated": truncated,
                "reason": stale_reason,
            }
        )

    ambiguity_items: list[dict[str, Any]] = []
    for ambiguity in sorted(
        matches.ambiguities,
        key=lambda item: (item.matched_alias, item.concept_ids),
    ):
        candidates, count, truncated = _bounded_nested(
            tuple(sorted(ambiguity.concept_ids)),
            "ambiguous_concepts.candidate_concept_ids",
        )
        ambiguity_items.append(
            {
                "matched_alias": ambiguity.matched_alias,
                "candidate_concept_ids": candidates,
                "candidate_count": count,
                "candidates_truncated": truncated,
            }
        )

    recognized_collection = _collection(recognized_items, "recognized_concepts")
    covered_collection = _collection(covered_items, "covered_concepts")
    uncovered_collection = _collection(sorted(uncovered_ids), "uncovered_concepts")
    ambiguous_collection = _collection(ambiguity_items, "ambiguous_concepts")
    ambiguous_collection["distinct_candidate_concept_count"] = len(ambiguous_ids)
    stale_collection = _collection(stale_items, "stale_concepts")
    collections = (
        recognized_collection,
        covered_collection,
        uncovered_collection,
        ambiguous_collection,
        stale_collection,
    )
    nested_truncated = any(
        item.get("matched_aliases_truncated", False)
        or item.get("verified_bindings_truncated", False)
        or item.get("candidates_truncated", False)
        or item.get("stale_bindings_truncated", False)
        for collection in collections
        for item in collection["items"]
        if isinstance(item, dict)
    )
    coverage_truncated = any(item["truncated"] for item in collections) or nested_truncated

    covered_count = len(covered_items)
    recognized_count = len(recognized_ids)
    receipt: dict[str, Any] = {
        "schema": COVERAGE_SCHEMA,
        "query_digest": digest,
        "query_digest_policy": QUERY_DIGEST_POLICY,
        "identities": {
            "project": {
                "project_id": registry.project.project_id,
                "project_slug": registry.project.project_slug,
            },
            "checkout": {
                "checkout_id": search["checkout_id"],
                "derivation": "sha256-utf8-resolved-root:v1",
            },
            "corpus": {
                "fingerprint": search["corpus_fingerprint"],
                "index_policy_digest": cache_v3.index_policy_digest(root),
                "derivation": "palimnex-source-snapshot-fingerprint:v1",
            },
            "registry": {
                "schema": registry.schema,
                "digest": registry.registry_digest,
            },
        },
        "recognized_concepts": recognized_collection,
        "covered_concepts": covered_collection,
        "uncovered_concepts": uncovered_collection,
        "ambiguous_concepts": ambiguous_collection,
        "stale_concepts": stale_collection,
        "coverage": {"numerator": covered_count, "denominator": recognized_count},
        "retrieval_state": _retrieval_state(search, coverage_truncated, retrieval_limit),
        "semantic_disclosure": dict(_SEMANTIC_DISCLOSURE),
        "status": _status(covered_count, recognized_count, len(ambiguity_items)),
        "authority": "evidence_only",
        "authorizes_actions": False,
    }
    receipt["receipt_digest"] = canonical_receipt_digest(receipt)
    validate_receipt(receipt)
    return receipt


def _as_dict(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("invalid_type", field)
    return cast(dict[str, Any], value)


def _exact_fields(value: Mapping[str, Any], fields: frozenset[str], field: str) -> None:
    if set(value) != fields:
        _fail("invalid_fields", field)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX_DIGEST_RE.fullmatch(value) is not None


def _bounded_text(value: object, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        _fail("invalid_string", field)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail("forbidden_control", field)
    return value


def _concept_id(value: object, field: str) -> str:
    text = _bounded_text(value, field, 3, 128)
    if _CONCEPT_ID_RE.fullmatch(text) is None:
        _fail("invalid_pattern", field)
    return text


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("invalid_integer", field)
    return cast(int, value)


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        _fail("invalid_boolean", field)
    return cast(bool, value)


def _list(value: object, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail("invalid_list", field)
    return cast(list[Any], value)


def _unique(values: Sequence[Any], field: str) -> None:
    try:
        encoded = [canonical_json(value) for value in values]
    except (RecursionError, TypeError, ValueError) as exc:
        raise CoverageError("canonicalization_failed", field) from exc
    if len(encoded) != len(set(encoded)):
        _fail("duplicate_item", field)


def _validate_locator(value: object, field: str) -> tuple[str, str, str, str, int, int, str]:
    locator = _as_dict(value, field)
    _exact_fields(locator, frozenset({"scheme", "source_id", "version", "range", "digest"}), field)
    scheme = _bounded_text(locator["scheme"], field + ".scheme", 1, 32)
    if _SCHEME_RE.fullmatch(scheme) is None:
        _fail("invalid_pattern", field + ".scheme")
    source_id = _bounded_text(locator["source_id"], field + ".source_id", 1, 2048)
    version = _bounded_text(locator["version"], field + ".version", 1, 2048)
    bounds = _as_dict(locator["range"], field + ".range")
    _exact_fields(bounds, frozenset({"unit", "start", "end"}), field + ".range")
    unit = bounds["unit"]
    if unit not in {"lines", "bytes"}:
        _fail("invalid_value", field + ".range.unit")
    minimum = 1 if unit == "lines" else 0
    start = _integer(bounds["start"], field + ".range.start", minimum, 1_000_000)
    end = _integer(bounds["end"], field + ".range.end", minimum, 1_000_000)
    if start > end:
        _fail("range_order", field + ".range")
    digest = locator["digest"]
    if not _is_sha256(digest):
        _fail("invalid_digest", field + ".digest")
    return scheme, source_id, version, cast(str, unit), start, end, cast(str, digest)


def _validate_counted_list(
    collection: Mapping[str, Any],
    *,
    item_count: int,
    total_field: str,
    truncated_field: str,
    field: str,
    minimum: int = 0,
    maximum: int = MAX_COVERAGE_COLLECTION_TOTAL,
) -> tuple[int, bool]:
    total = _integer(collection[total_field], field + "." + total_field, minimum, maximum)
    truncated = _boolean(collection[truncated_field], field + "." + truncated_field)
    if truncated != (total > item_count):
        _fail("truncation_count_mismatch", field)
    return total, truncated


def _validate_identities(value: object) -> None:
    identities = _as_dict(value, "identities")
    _exact_fields(identities, frozenset({"project", "checkout", "corpus", "registry"}), "identities")
    project = _as_dict(identities["project"], "identities.project")
    _exact_fields(project, frozenset({"project_slug", "project_id"}), "identities.project")
    slug = _bounded_text(project["project_slug"], "identities.project.project_slug", 1, 128)
    identity = _bounded_text(project["project_id"], "identities.project.project_id", 36, 36)
    if _PROJECT_SLUG_RE.fullmatch(slug) is None or _PROJECT_ID_RE.fullmatch(identity) is None:
        _fail("invalid_pattern", "identities.project")
    checkout = _as_dict(identities["checkout"], "identities.checkout")
    _exact_fields(checkout, frozenset({"checkout_id", "derivation"}), "identities.checkout")
    if not _is_sha256(checkout["checkout_id"]):
        _fail("invalid_digest", "identities.checkout.checkout_id")
    if checkout["derivation"] != "sha256-utf8-resolved-root:v1":
        _fail("derivation_mismatch", "identities.checkout.derivation")
    corpus = _as_dict(identities["corpus"], "identities.corpus")
    _exact_fields(corpus, frozenset({"fingerprint", "index_policy_digest", "derivation"}), "identities.corpus")
    if not _is_sha256(corpus["fingerprint"]) or not _is_sha256(corpus["index_policy_digest"]):
        _fail("invalid_digest", "identities.corpus")
    if corpus["derivation"] != "palimnex-source-snapshot-fingerprint:v1":
        _fail("derivation_mismatch", "identities.corpus.derivation")
    registry = _as_dict(identities["registry"], "identities.registry")
    _exact_fields(registry, frozenset({"schema", "digest"}), "identities.registry")
    if registry["schema"] != "palimnex:concept-registry:v1" or not _is_sha256(registry["digest"]):
        _fail("registry_identity_mismatch", "identities.registry")


def _validate_recognized(value: object) -> tuple[int, set[str], bool]:
    field = "recognized_concepts"
    collection = _as_dict(value, field)
    _exact_fields(collection, frozenset({"items", "total_count", "truncated"}), field)
    items = _list(collection["items"], field + ".items", MAX_COVERAGE_COLLECTION_ITEMS)
    ids: list[str] = []
    any_nested = False
    for index, raw in enumerate(items):
        item_field = f"{field}.items[{index}]"
        item = _as_dict(raw, item_field)
        _exact_fields(item, frozenset({"concept_id", "matched_aliases", "matched_alias_count", "matched_aliases_truncated"}), item_field)
        ids.append(_concept_id(item["concept_id"], item_field + ".concept_id"))
        aliases = _list(item["matched_aliases"], item_field + ".matched_aliases", MAX_NESTED_DETAIL_ITEMS)
        if not aliases:
            _fail("empty_list", item_field + ".matched_aliases")
        checked = [_bounded_text(alias, item_field + ".matched_aliases", 1, 128) for alias in aliases]
        _unique(checked, item_field + ".matched_aliases")
        if checked != sorted(checked):
            _fail("ordering", item_field + ".matched_aliases")
        _count, nested = _validate_counted_list(
            item,
            item_count=len(aliases),
            total_field="matched_alias_count",
            truncated_field="matched_aliases_truncated",
            field=item_field,
            minimum=1,
            maximum=MAX_NESTED_DETAIL_TOTAL,
        )
        any_nested = any_nested or nested
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        _fail("ordering_or_duplicate", field + ".items")
    total, truncated = _validate_counted_list(
        collection,
        item_count=len(items),
        total_field="total_count",
        truncated_field="truncated",
        field=field,
    )
    return total, set(ids), truncated or any_nested


def _validate_covered(value: object) -> tuple[int, set[str], bool]:
    field = "covered_concepts"
    collection = _as_dict(value, field)
    _exact_fields(collection, frozenset({"items", "total_count", "truncated"}), field)
    items = _list(collection["items"], field + ".items", MAX_COVERAGE_COLLECTION_ITEMS)
    ids: list[str] = []
    any_nested = False
    for index, raw in enumerate(items):
        item_field = f"{field}.items[{index}]"
        item = _as_dict(raw, item_field)
        _exact_fields(item, frozenset({"concept_id", "verified_bindings", "verified_binding_count", "verified_bindings_truncated"}), item_field)
        ids.append(_concept_id(item["concept_id"], item_field + ".concept_id"))
        bindings = _list(item["verified_bindings"], item_field + ".verified_bindings", MAX_NESTED_DETAIL_ITEMS)
        if not bindings:
            _fail("empty_list", item_field + ".verified_bindings")
        keys = [_validate_locator(binding, item_field + ".verified_bindings") for binding in bindings]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            _fail("ordering_or_duplicate", item_field + ".verified_bindings")
        _count, nested = _validate_counted_list(
            item,
            item_count=len(bindings),
            total_field="verified_binding_count",
            truncated_field="verified_bindings_truncated",
            field=item_field,
            minimum=1,
            maximum=MAX_NESTED_DETAIL_TOTAL,
        )
        any_nested = any_nested or nested
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        _fail("ordering_or_duplicate", field + ".items")
    total, truncated = _validate_counted_list(collection, item_count=len(items), total_field="total_count", truncated_field="truncated", field=field)
    return total, set(ids), truncated or any_nested


def _validate_uncovered(value: object) -> tuple[int, set[str], bool]:
    field = "uncovered_concepts"
    collection = _as_dict(value, field)
    _exact_fields(collection, frozenset({"items", "total_count", "truncated"}), field)
    items = _list(collection["items"], field + ".items", MAX_COVERAGE_COLLECTION_ITEMS)
    ids = [_concept_id(item, field + ".items") for item in items]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        _fail("ordering_or_duplicate", field + ".items")
    total, truncated = _validate_counted_list(collection, item_count=len(items), total_field="total_count", truncated_field="truncated", field=field)
    return total, set(ids), truncated


def _validate_ambiguous(value: object) -> tuple[int, int, set[str], bool]:
    field = "ambiguous_concepts"
    collection = _as_dict(value, field)
    _exact_fields(collection, frozenset({"items", "total_count", "distinct_candidate_concept_count", "truncated"}), field)
    items = _list(collection["items"], field + ".items", MAX_COVERAGE_COLLECTION_ITEMS)
    order: list[tuple[str, tuple[str, ...]]] = []
    candidates: set[str] = set()
    any_nested = False
    for index, raw in enumerate(items):
        item_field = f"{field}.items[{index}]"
        item = _as_dict(raw, item_field)
        _exact_fields(item, frozenset({"matched_alias", "candidate_concept_ids", "candidate_count", "candidates_truncated"}), item_field)
        alias = _bounded_text(item["matched_alias"], item_field + ".matched_alias", 1, 128)
        values = _list(item["candidate_concept_ids"], item_field + ".candidate_concept_ids", MAX_NESTED_DETAIL_ITEMS)
        if len(values) < 2:
            _fail("ambiguity_cardinality", item_field)
        ids = [_concept_id(candidate, item_field + ".candidate_concept_ids") for candidate in values]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            _fail("ordering_or_duplicate", item_field + ".candidate_concept_ids")
        _count, nested = _validate_counted_list(
            item,
            item_count=len(ids),
            total_field="candidate_count",
            truncated_field="candidates_truncated",
            field=item_field,
            minimum=2,
            maximum=MAX_NESTED_DETAIL_TOTAL,
        )
        candidates.update(ids)
        order.append((alias, tuple(ids)))
        any_nested = any_nested or nested
    if order != sorted(order) or len(order) != len(set(order)):
        _fail("ordering_or_duplicate", field + ".items")
    total, truncated = _validate_counted_list(collection, item_count=len(items), total_field="total_count", truncated_field="truncated", field=field)
    distinct = _integer(collection["distinct_candidate_concept_count"], field + ".distinct_candidate_concept_count", 0, MAX_COVERAGE_COLLECTION_TOTAL)
    if not truncated and not any_nested and distinct != len(candidates):
        _fail("ambiguity_count_mismatch", field)
    if (total == 0) != (distinct == 0):
        _fail("ambiguity_count_mismatch", field)
    return total, distinct, candidates, truncated or any_nested


def _validate_stale(value: object) -> tuple[int, set[str], bool]:
    field = "stale_concepts"
    collection = _as_dict(value, field)
    _exact_fields(collection, frozenset({"items", "total_count", "truncated"}), field)
    items = _list(collection["items"], field + ".items", MAX_COVERAGE_COLLECTION_ITEMS)
    order: list[tuple[str, str, tuple[tuple[str, str, str, str, int, int, str], ...]]] = []
    ids: list[str] = []
    any_nested = False
    for index, raw in enumerate(items):
        item_field = f"{field}.items[{index}]"
        item = _as_dict(raw, item_field)
        _exact_fields(item, frozenset({"concept_id", "stale_bindings", "stale_binding_count", "stale_bindings_truncated", "reason"}), item_field)
        concept_id = _concept_id(item["concept_id"], item_field + ".concept_id")
        reason = item["reason"]
        if reason not in _STALE_REASONS:
            _fail("invalid_value", item_field + ".reason")
        bindings = _list(item["stale_bindings"], item_field + ".stale_bindings", MAX_NESTED_DETAIL_ITEMS)
        if not bindings:
            _fail("empty_list", item_field + ".stale_bindings")
        keys = tuple(_validate_locator(binding, item_field + ".stale_bindings") for binding in bindings)
        if list(keys) != sorted(keys) or len(keys) != len(set(keys)):
            _fail("ordering_or_duplicate", item_field + ".stale_bindings")
        _count, nested = _validate_counted_list(
            item,
            item_count=len(bindings),
            total_field="stale_binding_count",
            truncated_field="stale_bindings_truncated",
            field=item_field,
            minimum=1,
            maximum=MAX_NESTED_DETAIL_TOTAL,
        )
        ids.append(concept_id)
        order.append((concept_id, cast(str, reason), keys))
        any_nested = any_nested or nested
    if order != sorted(order) or len(ids) != len(set(ids)):
        _fail("ordering_or_duplicate", field + ".items")
    total, truncated = _validate_counted_list(collection, item_count=len(items), total_field="total_count", truncated_field="truncated", field=field)
    return total, set(ids), truncated or any_nested


def _validate_retrieval_state(value: object, expected_coverage_truncation: bool) -> None:
    field = "retrieval_state"
    state = _as_dict(value, field)
    _exact_fields(state, frozenset({"retrieval_truncated", "result_item_count", "omitted_result_count", "coverage_output_truncated", "byte_budget_omission"}), field)
    _boolean(state["retrieval_truncated"], field + ".retrieval_truncated")
    _integer(state["result_item_count"], field + ".result_item_count", 0, MAX_COVERAGE_COLLECTION_TOTAL)
    omitted_count = _integer(state["omitted_result_count"], field + ".omitted_result_count", 0, 100_000)
    output_truncated = _boolean(state["coverage_output_truncated"], field + ".coverage_output_truncated")
    if output_truncated != expected_coverage_truncation:
        _fail("coverage_truncation_mismatch", field + ".coverage_output_truncated")
    omission = _as_dict(state["byte_budget_omission"], field + ".byte_budget_omission")
    _exact_fields(omission, frozenset({"omitted", "omitted_item_count", "byte_budget", "used_bytes"}), field + ".byte_budget_omission")
    omitted = _boolean(omission["omitted"], field + ".byte_budget_omission.omitted")
    omitted_items = _integer(omission["omitted_item_count"], field + ".byte_budget_omission.omitted_item_count", 0, 100_000)
    budget = _integer(omission["byte_budget"], field + ".byte_budget_omission.byte_budget", 1, MAX_RECEIPT_BYTE_STATE)
    used = _integer(omission["used_bytes"], field + ".byte_budget_omission.used_bytes", 0, MAX_RECEIPT_BYTE_STATE)
    if used > budget or omitted != (omitted_items > 0) or omitted_items > omitted_count:
        _fail("byte_budget_mismatch", field + ".byte_budget_omission")


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    """Validate v1 structure, ordering, arithmetic, decision table, and digest."""
    if not isinstance(receipt, Mapping):
        _fail("invalid_type", "receipt")
    value = dict(receipt)
    _exact_fields(value, _COVERAGE_KEYS, "receipt")
    if value["schema"] != COVERAGE_SCHEMA:
        _fail("schema_mismatch", "schema")
    if not _is_sha256(value["query_digest"]):
        _fail("invalid_digest", "query_digest")
    if value["query_digest_policy"] != QUERY_DIGEST_POLICY:
        _fail("query_digest_policy_mismatch", "query_digest_policy")
    _validate_identities(value["identities"])

    recognized_total, recognized_visible, recognized_truncated = _validate_recognized(value["recognized_concepts"])
    covered_total, covered_visible, covered_truncated = _validate_covered(value["covered_concepts"])
    uncovered_total, uncovered_visible, uncovered_truncated = _validate_uncovered(value["uncovered_concepts"])
    ambiguity_total, ambiguous_distinct, ambiguous_visible, ambiguous_truncated = _validate_ambiguous(value["ambiguous_concepts"])
    stale_total, stale_visible, stale_truncated = _validate_stale(value["stale_concepts"])

    category_sets = (covered_visible, uncovered_visible, ambiguous_visible, stale_visible)
    for index, left in enumerate(category_sets):
        for right in category_sets[index + 1 :]:
            if left & right:
                _fail("classification_overlap", "receipt")
    if not recognized_truncated:
        visible_categories = set().union(*category_sets)
        if not visible_categories.issubset(recognized_visible):
            _fail("recognized_set_mismatch", "receipt")
    if recognized_total != covered_total + uncovered_total + stale_total + ambiguous_distinct:
        _fail("coverage_arithmetic", "receipt")

    coverage = _as_dict(value["coverage"], "coverage")
    _exact_fields(coverage, frozenset({"numerator", "denominator"}), "coverage")
    numerator = _integer(coverage["numerator"], "coverage.numerator", 0, MAX_COVERAGE_COLLECTION_TOTAL)
    denominator = _integer(coverage["denominator"], "coverage.denominator", 0, MAX_COVERAGE_COLLECTION_TOTAL)
    if numerator != covered_total or denominator != recognized_total:
        _fail("coverage_arithmetic", "coverage")

    expected_status = _status(covered_total, recognized_total, ambiguity_total)
    if value["status"] != expected_status:
        _fail("status_mismatch", "status")
    coverage_truncated = any(
        (
            recognized_truncated,
            covered_truncated,
            uncovered_truncated,
            ambiguous_truncated,
            stale_truncated,
        )
    )
    _validate_retrieval_state(value["retrieval_state"], coverage_truncated)
    semantic = _as_dict(value["semantic_disclosure"], "semantic_disclosure")
    if semantic != _SEMANTIC_DISCLOSURE:
        _fail("semantic_disclosure_mismatch", "semantic_disclosure")
    if value["authority"] != "evidence_only":
        _fail("authority_mismatch", "authority")
    if value["authorizes_actions"] is not False:
        _fail("authorizes_actions", "authorizes_actions")
    if not _is_sha256(value["receipt_digest"]):
        _fail("invalid_digest", "receipt_digest")
    if value["receipt_digest"] != canonical_receipt_digest(value):
        _fail("receipt_digest_mismatch", "receipt_digest")


def _registry_path(path: str) -> str:
    if not isinstance(path, str) or not path or len(path) > MAX_REGISTRY_PATH_CHARS:
        _fail("registry_path_bound", "registry.path")
    relative = Path(path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        _fail("registry_path_refused", "registry.path")
    return path


def build_explain_search(
    search_result: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    *,
    registry_path: str,
    registry_source: str,
) -> dict[str, Any]:
    """Wrap an unchanged search object and optional coverage receipt."""
    if not isinstance(search_result, Mapping):
        _fail("invalid_type", "search")
    if registry_source not in {"default", "argument"}:
        _fail("registry_source_mismatch", "registry.source")
    admitted_path = _registry_path(registry_path)
    coverage: dict[str, Any] | None
    if receipt is None:
        state = "registry_absent"
        coverage = None
    else:
        validate_receipt(receipt)
        state = "enabled"
        coverage = copy.deepcopy(dict(receipt))
    return {
        "schema": EXPLAIN_SEARCH_SCHEMA,
        "search": copy.deepcopy(dict(search_result)),
        "coverage_state": state,
        "coverage": coverage,
        "registry": {"path": admitted_path, "source": registry_source},
        "authority": "evidence_only",
        "authorizes_actions": False,
    }
