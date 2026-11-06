"""Deterministic, evidence-only ontology ranking for shadow evaluation.

This module never changes retrieval results.  It computes an isolated channel
over already-derived retrieval chunks and emits a bounded comparison document
that contains pointers and digests, never query or source text.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn, cast

from .concepts import (
    MAX_CONCEPT_ID_CHARS,
    MIN_CONCEPT_ID_CHARS,
    Concept,
    ConceptRegistry,
    match_aliases,
    verify_source_bindings,
)
from .coverage import QUERY_DIGEST_POLICY, CoverageError, query_digest
from .durable import canonical_json
from .locators import RepositoryResolver, SourceLocator, SourceResolver
from .security import scan_bytes, scan_text


SHADOW_COMPARISON_SCHEMA = "palimnex:ontology-shadow-comparison:v1"
MAX_ONTOLOGY_CANDIDATES = 512
MAX_COMPARISON_ITEMS = 100
MAX_POINTER_CHARS = 4096
MAX_COUNT = 1_000_000
_CHANNEL_NAMES = ("lexical", "symbol", "graph", "ontology")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_CONCEPT_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*")


class ShadowComparisonError(ValueError):
    """A non-echoing shadow refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str = "comparison") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"ontology shadow refused: {reason} at {field}")


@dataclass(frozen=True)
class OntologyChannel:
    ranking: tuple[int, ...]
    recognized_concept_ids: tuple[str, ...]
    ambiguous_concept_ids: tuple[str, ...]
    contributing_concept_ids: tuple[str, ...]
    excluded_ambiguous: tuple[str, ...]
    excluded_stale: tuple[str, ...]
    excluded_uncovered: tuple[str, ...]
    candidate_count: int
    truncated: bool


def _fail(reason: str, field: str) -> NoReturn:
    raise ShadowComparisonError(reason, field)


def _empty_channel() -> OntologyChannel:
    return OntologyChannel((), (), (), (), (), (), (), 0, False)


def _applicable_bindings(
    concept: Concept,
    resolvers: Mapping[str, SourceResolver],
) -> tuple[SourceLocator, ...]:
    return tuple(
        locator
        for locator in concept.source_bindings
        if locator.scheme == "repo"
        or (
            locator.scheme in resolvers
            and getattr(resolvers[locator.scheme], "api_version", None) == 1
        )
    )


def _chunk_fields(chunk: Mapping[str, Any], index: int) -> tuple[str, int, int, str]:
    field = f"chunks[{index}]"
    try:
        path = chunk["path"]
        start = chunk["start_line"]
        end = chunk["end_line"]
        pointer = chunk["pointer"]
    except (KeyError, TypeError):
        _fail("invalid_chunk", field)
    if not isinstance(path, str) or not path or len(path) > MAX_POINTER_CHARS:
        _fail("invalid_chunk_path", field + ".path")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= MAX_COUNT:
        _fail("invalid_chunk_range", field)
    if not isinstance(pointer, str) or not pointer or len(pointer) > MAX_POINTER_CHARS:
        _fail("invalid_pointer", field + ".pointer")
    if scan_text(path) or scan_text(pointer):
        _fail("chunk_privacy_refused", field)
    return path, start, end, pointer


def _byte_range_lines(raw: bytes, locator: SourceLocator) -> tuple[int, int] | None:
    """Map a non-empty half-open byte range to inclusive one-based lines."""
    bounds = locator.range
    if bounds.unit == "lines":
        return bounds.start, bounds.end
    if bounds.start == bounds.end:
        return None
    if bounds.end > len(raw):
        _fail("source_range_changed", "source_bindings.range")
    # A newline byte belongs to the line it terminates.  Consequently the last
    # line is computed from the final included byte, not the exclusive end.
    first = raw[: bounds.start].count(b"\n") + 1
    last = raw[: bounds.end - 1].count(b"\n") + 1
    return first, last


def _repo_binding_lines(
    locator: SourceLocator,
    *,
    root: Path,
) -> tuple[int, int] | None:
    try:
        source = RepositoryResolver(root).resolve(locator.source_id, locator.version)
    except ValueError as exc:
        raise ShadowComparisonError("source_unavailable", "source_bindings") from exc
    try:
        findings = scan_bytes(source.content)
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ShadowComparisonError("source_privacy_refused", "source_bindings") from exc
    if findings:
        _fail("source_privacy_refused", "source_bindings")
    if source.version != locator.version:
        _fail("source_changed", "source_bindings")
    return _byte_range_lines(source.content, locator)


def ontology_channel(
    registry: ConceptRegistry | None,
    query: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    resolvers: Mapping[str, SourceResolver] | None = None,
) -> OntologyChannel:
    """Rank chunks supported by current bindings of unambiguous concepts."""
    if registry is None:
        return _empty_channel()
    if not isinstance(registry, ConceptRegistry):
        _fail("invalid_type", "registry")
    if registry.registry_kind != "approved_registry":
        _fail("registry_kind_mismatch", "registry.registry_kind")
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes, bytearray)):
        _fail("invalid_type", "chunks")
    active_resolvers: Mapping[str, SourceResolver] = {} if resolvers is None else resolvers

    # match_aliases performs bounded query normalization and privacy admission.
    matches = match_aliases(registry, query)
    recognized = tuple(sorted(matches.recognized_concept_ids))
    ambiguous = tuple(sorted(matches.ambiguous_concept_ids))
    ambiguous_set = set(ambiguous)
    by_id = {concept.concept_id: concept for concept in registry.active_concepts}

    uncovered: list[str] = []
    verification_concepts: list[Concept] = []
    for concept_id in recognized:
        if concept_id in ambiguous_set:
            continue
        concept = by_id.get(concept_id)
        if concept is None:
            _fail("recognized_concept_missing", "registry.concepts")
        applicable = _applicable_bindings(concept, active_resolvers)
        if not applicable:
            uncovered.append(concept_id)
        else:
            verification_concepts.append(replace(concept, source_bindings=applicable))

    verified_by_id: dict[str, list[SourceLocator]] = {}
    stale: list[str] = []
    if verification_concepts:
        narrowed = replace(registry, concepts=tuple(verification_concepts))
        verification = verify_source_bindings(
            narrowed,
            root=root,
            resolvers=active_resolvers,
        )
        narrowed_by_id = {item.concept_id: item for item in verification_concepts}
        for result in verification.bindings:
            concept = narrowed_by_id.get(result.concept_id)
            if concept is None or not 0 <= result.binding_index < len(concept.source_bindings):
                _fail("verification_result_mismatch", "source_bindings")
            if result.verified:
                verified_by_id.setdefault(result.concept_id, []).append(
                    concept.source_bindings[result.binding_index]
                )
        for concept in verification_concepts:
            if not verified_by_id.get(concept.concept_id):
                stale.append(concept.concept_id)

    contributing = tuple(sorted(verified_by_id))
    chunk_data = [_chunk_fields(chunk, index) for index, chunk in enumerate(chunks)]
    scores: dict[int, set[str]] = {}
    for concept_id in contributing:
        for locator in verified_by_id[concept_id]:
            if locator.scheme != "repo":
                continue
            line_range = _repo_binding_lines(locator, root=root)
            if line_range is None:
                continue
            first, last = line_range
            for index, (path, chunk_start, chunk_end, _pointer) in enumerate(chunk_data):
                if path == locator.source_id and chunk_start <= last and chunk_end >= first:
                    scores.setdefault(index, set()).add(concept_id)

    ordered = sorted(
        scores,
        key=lambda index: (-len(scores[index]), chunk_data[index][3]),
    )
    candidate_count = len(ordered)
    return OntologyChannel(
        ranking=tuple(ordered[:MAX_ONTOLOGY_CANDIDATES]),
        recognized_concept_ids=recognized,
        ambiguous_concept_ids=ambiguous,
        contributing_concept_ids=contributing,
        excluded_ambiguous=ambiguous,
        excluded_stale=tuple(sorted(stale)),
        excluded_uncovered=tuple(sorted(uncovered)),
        candidate_count=candidate_count,
        truncated=candidate_count > MAX_ONTOLOGY_CANDIDATES,
    )


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("invalid_integer", field)
    return cast(int, value)


def _pointer(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_POINTER_CHARS:
        _fail("invalid_pointer", field)
    if any(ord(character) < 32 for character in value) or scan_text(value):
        _fail("pointer_privacy_refused", field)
    return value


def _pointer_list(value: object, field: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        _fail("invalid_list", field)
    pointers = [_pointer(item, field) for item in value]
    if len(pointers) != len(set(pointers)):
        _fail("duplicate_pointer", field)
    return pointers


def _concept_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_COMPARISON_ITEMS:
        _fail("invalid_list", field)
    items: list[str] = []
    for item in value:
        # Keep parity with the registry contract and the public comparison
        # schema's $defs.conceptId bounds.
        if (
            not isinstance(item, str)
            or not MIN_CONCEPT_ID_CHARS <= len(item) <= MAX_CONCEPT_ID_CHARS
            or _CONCEPT_ID_RE.fullmatch(item) is None
        ):
            _fail("invalid_concept_id", field)
        items.append(item)
    # Canonical sorted order plus duplicate refusal is an intentional runtime
    # cross-field rule; JSON Schema can reject duplicates but cannot express
    # lexicographic array ordering.
    if items != sorted(items) or len(items) != len(set(items)):
        _fail("ordering_or_duplicate", field)
    return items


def _comparison_digest(document: Mapping[str, Any]) -> str:
    body = dict(document)
    body.pop("comparison_digest", None)
    try:
        raw = canonical_json(body)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ShadowComparisonError("canonicalization_failed", "comparison") from exc
    return hashlib.sha256(raw).hexdigest()


def _changed_ranks(
    baseline: list[str],
    shadow: list[str],
) -> list[dict[str, Any]]:
    baseline_ranks = {pointer: rank for rank, pointer in enumerate(baseline, 1)}
    shadow_ranks = {pointer: rank for rank, pointer in enumerate(shadow, 1)}
    changed = [
        {
            "pointer": pointer,
            "baseline_rank": baseline_ranks.get(pointer),
            "shadow_rank": shadow_ranks.get(pointer),
        }
        for pointer in sorted(set(baseline_ranks) | set(shadow_ranks))
        if baseline_ranks.get(pointer) != shadow_ranks.get(pointer)
    ]
    # Membership changes remain fully visible in entered/left.  Rank detail is
    # a deterministic bounded prefix so every comparison list stays <= 100.
    return changed[:MAX_COMPARISON_ITEMS]


def build_shadow_comparison(
    *,
    query: str,
    registry: ConceptRegistry | None,
    channel: OntologyChannel,
    baseline: Mapping[str, Any],
    shadow_results: Sequence[Mapping[str, Any]],
    shadow_candidate_count: int,
    shadow_items_bytes: int,
    limit: int,
) -> dict[str, Any]:
    """Build a canonical, pointer-only comparison over an unchanged baseline."""
    if not isinstance(query, str):
        _fail("invalid_type", "query")
    try:
        query_raw = query.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ShadowComparisonError("invalid_utf8", "query") from exc
    if scan_bytes(query_raw):
        _fail("query_privacy_refused", "query")
    try:
        digest = query_digest(query)
    except CoverageError as exc:
        raise ShadowComparisonError(exc.reason, exc.field) from exc
    if registry is not None and not isinstance(registry, ConceptRegistry):
        _fail("invalid_type", "registry")
    if not isinstance(channel, OntologyChannel):
        _fail("invalid_type", "channel")
    if registry is not None and registry.registry_kind != "approved_registry":
        _fail("registry_kind_mismatch", "registry.registry_kind")
    if not isinstance(baseline, Mapping):
        _fail("invalid_type", "baseline")
    if not isinstance(shadow_results, Sequence) or isinstance(
        shadow_results, (str, bytes, bytearray)
    ):
        _fail("invalid_type", "shadow_results")
    result_limit = _integer(limit, "limit", 1, MAX_COMPARISON_ITEMS)
    if len(shadow_results) > result_limit:
        _fail("result_limit_mismatch", "shadow_results")
    if baseline.get("query") != query:
        _fail("query_mismatch", "baseline.query")
    baseline_results = baseline.get("results")
    if not isinstance(baseline_results, list) or len(baseline_results) > result_limit:
        _fail("result_limit_mismatch", "baseline.results")
    baseline_pointers = [
        _pointer(item.get("pointer") if isinstance(item, Mapping) else None, "baseline.results")
        for item in baseline_results
    ]
    if len(baseline_pointers) != len(set(baseline_pointers)):
        _fail("duplicate_pointer", "baseline.results")
    baseline_count = _integer(baseline.get("candidate_count"), "baseline.candidate_count", 0, MAX_COUNT)
    if baseline_count < len(baseline_pointers):
        _fail("candidate_count_mismatch", "baseline.candidate_count")
    byte_budget = _integer(baseline.get("byte_budget"), "baseline.byte_budget", 128, 65_536)
    shadow_count = _integer(shadow_candidate_count, "shadow_candidate_count", 0, MAX_COUNT)
    if shadow_count < len(shadow_results):
        _fail("candidate_count_mismatch", "shadow_candidate_count")
    shadow_bytes = _integer(shadow_items_bytes, "shadow_items_bytes", 0, byte_budget)

    shadow_items: list[dict[str, Any]] = []
    shadow_pointers: list[str] = []
    for rank, raw_item in enumerate(shadow_results, 1):
        if not isinstance(raw_item, Mapping):
            _fail("invalid_type", f"shadow_results[{rank - 1}]")
        pointer = _pointer(raw_item.get("pointer"), f"shadow_results[{rank - 1}].pointer")
        raw_channels = raw_item.get("channels")
        if not isinstance(raw_channels, Mapping) or not raw_channels:
            _fail("invalid_channels", f"shadow_results[{rank - 1}].channels")
        if set(raw_channels) - set(_CHANNEL_NAMES):
            _fail("invalid_channels", f"shadow_results[{rank - 1}].channels")
        channels = {
            name: _integer(raw_channels[name], f"shadow_results[{rank - 1}].channels.{name}", 1, MAX_ONTOLOGY_CANDIDATES)
            for name in _CHANNEL_NAMES
            if name in raw_channels
        }
        shadow_pointers.append(pointer)
        shadow_items.append({"pointer": pointer, "rank": rank, "channels": channels})
    if len(shadow_pointers) != len(set(shadow_pointers)):
        _fail("duplicate_pointer", "shadow_results")

    ontology_lists = {
        "recognized_concept_ids": list(channel.recognized_concept_ids),
        "ambiguous_concept_ids": list(channel.ambiguous_concept_ids),
        "contributing_concept_ids": list(channel.contributing_concept_ids),
        "excluded_ambiguous": list(channel.excluded_ambiguous),
        "excluded_stale": list(channel.excluded_stale),
        "excluded_uncovered": list(channel.excluded_uncovered),
    }
    for field, values in ontology_lists.items():
        _concept_list(values, "ontology_channel." + field)
    channel_count = _integer(channel.candidate_count, "ontology_channel.candidate_count", 0, MAX_COUNT)
    if (
        len(channel.ranking) != min(channel_count, MAX_ONTOLOGY_CANDIDATES)
        or any(type(index) is not int or index < 0 for index in channel.ranking)
        or len(channel.ranking) != len(set(channel.ranking))
    ):
        _fail("ranking_mismatch", "ontology_channel.ranking")
    if channel.truncated is not (channel_count > MAX_ONTOLOGY_CANDIDATES):
        _fail("truncation_mismatch", "ontology_channel.truncated")

    recognized_ids = set(ontology_lists["recognized_concept_ids"])
    if registry is None:
        if recognized_ids or channel.ranking or channel_count:
            _fail("registry_channel_mismatch", "ontology_channel")
    else:
        active_ids = {concept.concept_id for concept in registry.active_concepts}
        if not recognized_ids.issubset(active_ids):
            _fail("registry_channel_mismatch", "ontology_channel")

    registry_identity = None
    if registry is not None:
        registry_identity = {"schema": registry.schema, "digest": registry.registry_digest}
    baseline_set = set(baseline_pointers)
    shadow_set = set(shadow_pointers)
    document: dict[str, Any] = {
        "schema": SHADOW_COMPARISON_SCHEMA,
        "query_digest": digest,
        "query_digest_policy": QUERY_DIGEST_POLICY,
        "registry": registry_identity,
        "channels": list(_CHANNEL_NAMES),
        "ontology_channel": {
            **ontology_lists,
            "candidate_count": channel_count,
            "truncated": channel.truncated,
        },
        "limit": result_limit,
        "byte_budget": byte_budget,
        "baseline": {"pointers": baseline_pointers, "candidate_count": baseline_count},
        "shadow": {
            "items": shadow_items,
            "candidate_count": shadow_count,
            "items_bytes": shadow_bytes,
        },
        "diff": {
            "identical": baseline_pointers == shadow_pointers,
            "overlap_count": len(baseline_set & shadow_set),
            "entered": [pointer for pointer in shadow_pointers if pointer not in baseline_set],
            "left": [pointer for pointer in baseline_pointers if pointer not in shadow_set],
            "rank_changes": _changed_ranks(baseline_pointers, shadow_pointers),
        },
        "retrieval_influence": False,
        "returned_ranking_changed": False,
        "authority": "evidence_only",
        "authorizes_actions": False,
    }
    document["comparison_digest"] = _comparison_digest(document)
    validate_shadow_comparison(document)
    return document


def _exact_fields(value: Mapping[str, Any], expected: frozenset[str], field: str) -> None:
    if set(value) != expected:
        _fail("invalid_fields", field)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_type", field)
    return dict(value)


def validate_shadow_comparison(document: Mapping[str, Any]) -> None:
    """Validate structure, bounds, canonical digest, and cross-field rules."""
    if not isinstance(document, Mapping):
        _fail("invalid_type", "comparison")
    value = dict(document)
    _exact_fields(
        value,
        frozenset(
            {
                "schema", "query_digest", "query_digest_policy", "registry", "channels",
                "ontology_channel", "limit", "byte_budget", "baseline", "shadow", "diff",
                "retrieval_influence", "returned_ranking_changed", "authority",
                "authorizes_actions", "comparison_digest",
            }
        ),
        "comparison",
    )
    if value["schema"] != SHADOW_COMPARISON_SCHEMA:
        _fail("schema_mismatch", "schema")
    if not isinstance(value["query_digest"], str) or _DIGEST_RE.fullmatch(value["query_digest"]) is None:
        _fail("invalid_digest", "query_digest")
    if value["query_digest_policy"] != QUERY_DIGEST_POLICY:
        _fail("query_digest_policy_mismatch", "query_digest_policy")
    registry = value["registry"]
    if registry is not None:
        registry_value = _mapping(registry, "registry")
        _exact_fields(registry_value, frozenset({"schema", "digest"}), "registry")
        if registry_value["schema"] != "palimnex:concept-registry:v1":
            _fail("registry_schema_mismatch", "registry.schema")
        if not isinstance(registry_value["digest"], str) or _DIGEST_RE.fullmatch(registry_value["digest"]) is None:
            _fail("invalid_digest", "registry.digest")
    if value["channels"] != list(_CHANNEL_NAMES):
        _fail("channels_mismatch", "channels")

    ontology = _mapping(value["ontology_channel"], "ontology_channel")
    list_fields = frozenset(
        {
            "recognized_concept_ids", "ambiguous_concept_ids", "contributing_concept_ids",
            "excluded_ambiguous", "excluded_stale", "excluded_uncovered",
        }
    )
    _exact_fields(ontology, list_fields | {"candidate_count", "truncated"}, "ontology_channel")
    concept_sets = {
        field: set(_concept_list(ontology[field], "ontology_channel." + field))
        for field in list_fields
    }
    if concept_sets["ambiguous_concept_ids"] != concept_sets["excluded_ambiguous"]:
        _fail("ambiguity_mismatch", "ontology_channel")
    classifications = (
        concept_sets["contributing_concept_ids"], concept_sets["excluded_ambiguous"],
        concept_sets["excluded_stale"], concept_sets["excluded_uncovered"],
    )
    for index, left_class in enumerate(classifications):
        for right in classifications[index + 1 :]:
            if left_class & right:
                _fail("classification_overlap", "ontology_channel")
    if set().union(*classifications) != concept_sets["recognized_concept_ids"]:
        _fail("recognized_set_mismatch", "ontology_channel")
    channel_count = _integer(ontology["candidate_count"], "ontology_channel.candidate_count", 0, MAX_COUNT)
    if type(ontology["truncated"]) is not bool or ontology["truncated"] is not (
        channel_count > MAX_ONTOLOGY_CANDIDATES
    ):
        _fail("truncation_mismatch", "ontology_channel.truncated")

    result_limit = _integer(value["limit"], "limit", 1, MAX_COMPARISON_ITEMS)
    byte_budget = _integer(value["byte_budget"], "byte_budget", 128, 65_536)
    baseline = _mapping(value["baseline"], "baseline")
    _exact_fields(baseline, frozenset({"pointers", "candidate_count"}), "baseline")
    baseline_pointers = _pointer_list(baseline["pointers"], "baseline.pointers", result_limit)
    baseline_count = _integer(baseline["candidate_count"], "baseline.candidate_count", 0, MAX_COUNT)
    if baseline_count < len(baseline_pointers):
        _fail("candidate_count_mismatch", "baseline.candidate_count")

    shadow = _mapping(value["shadow"], "shadow")
    _exact_fields(shadow, frozenset({"items", "candidate_count", "items_bytes"}), "shadow")
    items = shadow["items"]
    if not isinstance(items, list) or len(items) > result_limit:
        _fail("invalid_list", "shadow.items")
    shadow_pointers: list[str] = []
    ranks_by_channel: dict[str, set[int]] = {name: set() for name in _CHANNEL_NAMES}
    for index, raw_item in enumerate(items):
        item = _mapping(raw_item, f"shadow.items[{index}]")
        _exact_fields(item, frozenset({"pointer", "rank", "channels"}), f"shadow.items[{index}]")
        pointer = _pointer(item["pointer"], f"shadow.items[{index}].pointer")
        rank = _integer(item["rank"], f"shadow.items[{index}].rank", 1, result_limit)
        if rank != index + 1:
            _fail("rank_mismatch", f"shadow.items[{index}].rank")
        channels = _mapping(item["channels"], f"shadow.items[{index}].channels")
        if not channels or set(channels) - set(_CHANNEL_NAMES):
            _fail("invalid_channels", f"shadow.items[{index}].channels")
        for name, raw_rank in channels.items():
            channel_rank = _integer(raw_rank, f"shadow.items[{index}].channels.{name}", 1, MAX_ONTOLOGY_CANDIDATES)
            if channel_rank in ranks_by_channel[name]:
                _fail("duplicate_channel_rank", f"shadow.items[{index}].channels.{name}")
            ranks_by_channel[name].add(channel_rank)
        shadow_pointers.append(pointer)
    if len(shadow_pointers) != len(set(shadow_pointers)):
        _fail("duplicate_pointer", "shadow.items")
    shadow_count = _integer(shadow["candidate_count"], "shadow.candidate_count", 0, MAX_COUNT)
    if shadow_count < len(shadow_pointers):
        _fail("candidate_count_mismatch", "shadow.candidate_count")
    _integer(shadow["items_bytes"], "shadow.items_bytes", 0, byte_budget)

    diff = _mapping(value["diff"], "diff")
    _exact_fields(diff, frozenset({"identical", "overlap_count", "entered", "left", "rank_changes"}), "diff")
    if type(diff["identical"]) is not bool or diff["identical"] is not (
        baseline_pointers == shadow_pointers
    ):
        _fail("identical_mismatch", "diff.identical")
    baseline_set = set(baseline_pointers)
    shadow_set = set(shadow_pointers)
    overlap = _integer(diff["overlap_count"], "diff.overlap_count", 0, result_limit)
    if overlap != len(baseline_set & shadow_set):
        _fail("overlap_mismatch", "diff.overlap_count")
    entered = _pointer_list(diff["entered"], "diff.entered", result_limit)
    left = _pointer_list(diff["left"], "diff.left", result_limit)
    if entered != [pointer for pointer in shadow_pointers if pointer not in baseline_set]:
        _fail("entered_mismatch", "diff.entered")
    if left != [pointer for pointer in baseline_pointers if pointer not in shadow_set]:
        _fail("left_mismatch", "diff.left")
    changes = diff["rank_changes"]
    if not isinstance(changes, list) or len(changes) > MAX_COMPARISON_ITEMS:
        _fail("invalid_list", "diff.rank_changes")
    expected_changes = _changed_ranks(baseline_pointers, shadow_pointers)
    if changes != expected_changes:
        _fail("rank_changes_mismatch", "diff.rank_changes")

    if value["retrieval_influence"] is not False:
        _fail("retrieval_influence", "retrieval_influence")
    if value["returned_ranking_changed"] is not False:
        _fail("returned_ranking_changed", "returned_ranking_changed")
    if value["authority"] != "evidence_only":
        _fail("authority_mismatch", "authority")
    if value["authorizes_actions"] is not False:
        _fail("authorizes_actions", "authorizes_actions")
    if not isinstance(value["comparison_digest"], str) or _DIGEST_RE.fullmatch(value["comparison_digest"]) is None:
        _fail("invalid_digest", "comparison_digest")
    if value["comparison_digest"] != _comparison_digest(value):
        _fail("comparison_digest_mismatch", "comparison_digest")
