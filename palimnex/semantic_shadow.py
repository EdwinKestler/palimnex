"""Evidence-only semantic ranking beside the unchanged retrieval baseline.

The semantic channel is deliberately isolated from production retrieval.  It
uses admitted source chunks, keeps vectors only in process, and emits a
pointer-only comparison that cannot authorize actions or retrieval influence.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from . import core, retrieval
from .durable import canonical_json
from .security import scan_text
from .semantic_local import (
    MAX_EMBED_BATCH,
    SemanticProviderError,
    checked_embed,
    identity_digest,
    provider_identity,
)


COMPARISON_SCHEMA = "palimnex:semantic-shadow-comparison:v1"
POLICY_SCHEMA = "palimnex:semantic-channel-policy:v1"
SEMANTIC_TOP_K = 64
SIMILARITY_FLOOR = 0.0
MEMO_CAPACITY = 20_000
CHANNELS = ("lexical", "symbol", "graph", "semantic")

_MAX_RESULTS = 100
_MAX_COUNT = 1_000_000
_MAX_POINTER_CHARS = 4096
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_PROVIDER_FIELDS = frozenset(
    {
        "schema",
        "interface",
        "provider_id",
        "revision",
        "dimensions",
        "implementation_digest",
        "execution",
        "network",
        "model_download",
        "persistent_store",
        "retrieval_influence",
    }
)


class SemanticShadowError(ValueError):
    """A non-echoing semantic-shadow refusal with a stable machine reason."""

    def __init__(self, reason: str, field: str) -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"semantic shadow refused: {reason} at {field}")


@dataclass(frozen=True)
class SemanticChannel:
    ranking: tuple[int, ...]
    candidate_count: int
    truncated: bool
    suppressed: str | None


class EmbeddingMemo:
    """Bounded content-keyed vector memo; it is never persisted."""

    def __init__(self, capacity: int = MEMO_CAPACITY) -> None:
        if type(capacity) is not int or not 1 <= capacity <= _MAX_COUNT:
            _fail("invalid_input", "memo.capacity")
        self._capacity = capacity
        self._vectors: dict[tuple[str, str], tuple[float, ...]] = {}

    def __len__(self) -> int:
        return len(self._vectors)

    def _get(self, key: tuple[str, str]) -> tuple[float, ...] | None:
        return self._vectors.get(key)

    def _put(self, key: tuple[str, str], vector: tuple[float, ...]) -> None:
        if key in self._vectors:
            return
        if len(self._vectors) >= self._capacity:
            self._vectors.clear()
        self._vectors[key] = vector


def _fail(reason: str, field: str) -> NoReturn:
    raise SemanticShadowError(reason, field)


def _provider_failure(error: SemanticProviderError) -> NoReturn:
    raise SemanticShadowError(error.reason, error.field) from error


def _identity(provider: object) -> dict[str, Any]:
    try:
        return provider_identity(provider)
    except SemanticProviderError as exc:
        _provider_failure(exc)


def _embed(
    provider: object,
    texts: Sequence[str],
    *,
    dimensions: int,
) -> tuple[tuple[float, ...], ...]:
    try:
        return checked_embed(provider, texts, expected_dimensions=dimensions)
    except SemanticProviderError as exc:
        _provider_failure(exc)


def _check_query(query: object) -> str:
    if not isinstance(query, str):
        _fail("invalid_input", "query")
    try:
        query.encode("utf-8", errors="strict")
        findings = scan_text(query)
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise SemanticShadowError("query_privacy_refused", "query") from exc
    if findings:
        _fail("query_privacy_refused", "query")
    return query


def _chunk_texts(
    chunks: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    if isinstance(chunks, (str, bytes, bytearray)) or not isinstance(chunks, Sequence):
        _fail("invalid_input", "chunks")
    if len(chunks) > _MAX_COUNT:
        _fail("invalid_input", "chunks")
    result: list[tuple[str, str]] = []
    pointers: set[str] = set()
    for index, chunk in enumerate(chunks):
        field = f"chunks[{index}]"
        if not isinstance(chunk, Mapping):
            _fail("invalid_input", field)
        text = chunk.get("text")
        pointer = chunk.get("pointer")
        if not isinstance(text, str):
            _fail("invalid_input", field + ".text")
        try:
            text.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise SemanticShadowError("invalid_input", field + ".text") from exc
        if (
            not isinstance(pointer, str)
            or not pointer
            or len(pointer) > _MAX_POINTER_CHARS
            or any(ord(character) < 32 for character in pointer)
            or pointer in pointers
        ):
            _fail("invalid_input", field + ".pointer")
        pointers.add(pointer)
        result.append((text, pointer))
    return tuple(result)


def _cosine(
    query_vector: tuple[float, ...],
    chunk_vector: tuple[float, ...],
) -> float:
    query_squared = 0.0
    chunk_squared = 0.0
    dot = 0.0
    for index in range(len(query_vector)):
        query_value = query_vector[index]
        chunk_value = chunk_vector[index]
        query_squared += query_value * query_value
        chunk_squared += chunk_value * chunk_value
        dot += query_value * chunk_value
    if query_squared == 0.0 or chunk_squared == 0.0:
        return 0.0
    return dot / (math.sqrt(query_squared) * math.sqrt(chunk_squared))


def _semantic_channel(
    provider: object,
    query: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    memo: EmbeddingMemo,
    baseline_candidate_count: int,
    identity: Mapping[str, Any] | None,
) -> SemanticChannel:
    checked_query = _check_query(query)
    if type(baseline_candidate_count) is not int or not 0 <= baseline_candidate_count <= _MAX_COUNT:
        _fail("invalid_input", "baseline_candidate_count")
    if not isinstance(memo, EmbeddingMemo):
        _fail("invalid_input", "memo")
    chunk_data = _chunk_texts(chunks)
    if baseline_candidate_count == 0:
        return SemanticChannel((), 0, False, "baseline_abstained")
    if not chunk_data:
        _fail("invalid_input", "chunks")

    active_identity = _identity(provider) if identity is None else dict(identity)
    dimensions = active_identity.get("dimensions")
    if type(dimensions) is not int:
        _fail("identity_invalid", "dimensions")
    provider_digest = identity_digest(active_identity)
    query_vector = _embed(provider, (checked_query,), dimensions=dimensions)[0]

    vectors: list[tuple[float, ...] | None] = [None] * len(chunk_data)
    missing: dict[tuple[str, str], tuple[str, list[int]]] = {}
    for index, (text, _pointer) in enumerate(chunk_data):
        content_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        key = (provider_digest, content_digest)
        cached = memo._get(key)
        if cached is not None:
            vectors[index] = cached
            continue
        entry = missing.get(key)
        if entry is None:
            missing[key] = (text, [index])
        else:
            entry[1].append(index)

    missing_items = list(missing.items())
    embedded: list[tuple[tuple[str, str], tuple[float, ...]]] = []
    for offset in range(0, len(missing_items), MAX_EMBED_BATCH):
        batch = missing_items[offset : offset + MAX_EMBED_BATCH]
        batch_vectors = _embed(
            provider,
            tuple(value[0] for _key, value in batch),
            dimensions=dimensions,
        )
        embedded.extend((key, vector) for (key, _value), vector in zip(batch, batch_vectors))
    for key, vector in embedded:
        memo._put(key, vector)
        for index in missing[key][1]:
            vectors[index] = vector

    scores: dict[int, float] = {}
    for index, maybe_vector in enumerate(vectors):
        if maybe_vector is None:
            _fail("provider_failed", "vectors")
        similarity = _cosine(query_vector, maybe_vector)
        if similarity > SIMILARITY_FLOOR:
            scores[index] = similarity
    ordered = sorted(scores, key=lambda index: (-scores[index], chunk_data[index][1]))
    candidate_count = len(ordered)
    return SemanticChannel(
        tuple(ordered[:SEMANTIC_TOP_K]),
        candidate_count,
        candidate_count > SEMANTIC_TOP_K,
        None,
    )


def semantic_channel(
    provider: object,
    query: str,
    chunks: Sequence[Mapping[str, Any]],
    *,
    memo: EmbeddingMemo,
    baseline_candidate_count: int,
) -> SemanticChannel:
    """Build the fixed R14 semantic ranking over already-admitted chunks."""
    return _semantic_channel(
        provider,
        query,
        chunks,
        memo=memo,
        baseline_candidate_count=baseline_candidate_count,
        identity=None,
    )


def policy_digest() -> str:
    """Return the digest of the fixed semantic-channel policy."""
    policy = {
        "schema": POLICY_SCHEMA,
        "top_k": SEMANTIC_TOP_K,
        "similarity_floor": SIMILARITY_FLOOR,
        "memo_capacity": MEMO_CAPACITY,
        "rrf_k": retrieval.RRF_K,
        "abstention": "suppress_when_baseline_has_no_candidates",
        "privacy": "scan_query_before_provider",
        "channels": list(CHANNELS),
    }
    return hashlib.sha256(canonical_json(policy)).hexdigest()


def _comparison_item(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pointer": item["pointer"],
        "path": item["path"],
        "start_line": item["start_line"],
        "end_line": item["end_line"],
        "content_digest": item["content_digest"],
        "score": item["score"],
        "channels": dict(item["channels"]),
    }


def semantic_shadow_retrieve(
    query: str,
    *,
    provider: object,
    root: Path = core.ROOT,
    limit: int = 5,
    byte_budget: int = 8192,
    include_graph: bool = True,
    client: Any = None,
    snapshot: Any = None,
    memo: EmbeddingMemo | None = None,
) -> dict[str, Any]:
    """Return the unchanged baseline and isolated semantic-shadow evidence."""
    baseline, state = retrieval._retrieve_sources_with_state(
        query,
        root=root,
        limit=limit,
        byte_budget=byte_budget,
        include_graph=include_graph,
        client=client,
        snapshot=snapshot,
        influence="off",
    )
    checked_query = _check_query(query)
    identity = _identity(provider)
    active_memo = EmbeddingMemo() if memo is None else memo
    channel = _semantic_channel(
        provider,
        checked_query,
        state.chunks,
        memo=active_memo,
        baseline_candidate_count=cast(int, baseline["candidate_count"]),
        identity=identity,
    )
    shadow_fusion = retrieval._fuse_rankings(
        state.chunks,
        state.rankings + (("semantic", channel.ranking),),
        limit=limit,
        byte_budget=byte_budget,
    )
    baseline_pointers = [item["pointer"] for item in baseline["results"]]
    shadow_items = [_comparison_item(item) for item in shadow_fusion.results]
    shadow_pointers = [item["pointer"] for item in shadow_items]
    baseline_set = set(baseline_pointers)
    shadow_set = set(shadow_pointers)
    comparison: dict[str, Any] = {
        "schema": COMPARISON_SCHEMA,
        "query_digest": hashlib.sha256(checked_query.encode("utf-8")).hexdigest(),
        "limit": limit,
        "byte_budget": byte_budget,
        "channels": list(CHANNELS),
        "provider": identity,
        "provider_identity_digest": identity_digest(identity),
        "policy_digest": policy_digest(),
        "semantic_channel": {
            "candidate_count": channel.candidate_count,
            "ranked_count": len(channel.ranking),
            "truncated": channel.truncated,
            "suppressed": channel.suppressed,
            "top_k": SEMANTIC_TOP_K,
            "similarity_floor": SIMILARITY_FLOOR,
        },
        "baseline": {
            "pointers": baseline_pointers,
            "candidate_count": baseline["candidate_count"],
            "items_bytes": baseline["items_bytes"],
        },
        "shadow": {
            "items": shadow_items,
            "candidate_count": shadow_fusion.candidate_count,
            "items_bytes": shadow_fusion.items_bytes,
        },
        "diff": {
            "identical": baseline_pointers == shadow_pointers,
            "added": sorted(shadow_set - baseline_set),
            "removed": sorted(baseline_set - shadow_set),
        },
        "corpus_fingerprint": baseline["corpus_fingerprint"],
        "retrieval_influence": False,
        "promotion_authorized": False,
        "authorizes_actions": False,
    }
    validate_semantic_comparison(comparison)
    return {"baseline": baseline, "comparison": comparison}


def _exact_fields(value: Mapping[str, Any], fields: frozenset[str], field: str) -> None:
    if set(value) != fields:
        _fail("comparison_invalid", field)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("comparison_invalid", field)
    return dict(value)


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("comparison_invalid", field)
    return cast(int, value)


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        _fail("comparison_invalid", field)
    return value


def _text(value: object, field: str, *, maximum: int = _MAX_POINTER_CHARS) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or not value.isprintable()
        or scan_text(value)
    ):
        _fail("comparison_invalid", field)
    return value


def _pointer_list(value: object, field: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        _fail("comparison_invalid", field)
    pointers = [_text(item, field) for item in value]
    if len(pointers) != len(set(pointers)):
        _fail("comparison_invalid", field)
    return pointers


def _validate_provider(value: object) -> dict[str, Any]:
    provider = _mapping(value, "provider")
    _exact_fields(provider, _PROVIDER_FIELDS, "provider")
    if (
        provider["schema"] != "palimnex:semantic-provider-identity:v1"
        or provider["interface"] != "project-memory:semantic-provider:v1"
        or provider["execution"] != "in_process"
        or provider["network"] is not False
        or provider["model_download"] is not False
        or provider["persistent_store"] is not False
        or provider["retrieval_influence"] is not False
    ):
        _fail("comparison_invalid", "provider")
    _text(provider["provider_id"], "provider.provider_id", maximum=128)
    _text(provider["revision"], "provider.revision", maximum=128)
    _integer(provider["dimensions"], "provider.dimensions", 8, 4096)
    _digest(provider["implementation_digest"], "provider.implementation_digest")
    return provider


def _validate_semantic_channel(value: object) -> None:
    channel = _mapping(value, "semantic_channel")
    _exact_fields(
        channel,
        frozenset(
            {
                "candidate_count",
                "ranked_count",
                "truncated",
                "suppressed",
                "top_k",
                "similarity_floor",
            }
        ),
        "semantic_channel",
    )
    count = _integer(channel["candidate_count"], "semantic_channel.candidate_count", 0, _MAX_COUNT)
    ranked = _integer(channel["ranked_count"], "semantic_channel.ranked_count", 0, SEMANTIC_TOP_K)
    if ranked != min(count, SEMANTIC_TOP_K):
        _fail("comparison_invalid", "semantic_channel.ranked_count")
    if type(channel["truncated"]) is not bool or channel["truncated"] is not (count > SEMANTIC_TOP_K):
        _fail("comparison_invalid", "semantic_channel.truncated")
    suppressed = channel["suppressed"]
    if suppressed not in (None, "baseline_abstained"):
        _fail("comparison_invalid", "semantic_channel.suppressed")
    if suppressed is not None and (count != 0 or ranked != 0):
        _fail("comparison_invalid", "semantic_channel.suppressed")
    if channel["top_k"] != SEMANTIC_TOP_K:
        _fail("comparison_invalid", "semantic_channel.top_k")
    if (
        isinstance(channel["similarity_floor"], bool)
        or not isinstance(channel["similarity_floor"], (int, float))
        or float(channel["similarity_floor"]) != SIMILARITY_FLOOR
    ):
        _fail("comparison_invalid", "semantic_channel.similarity_floor")


def validate_semantic_comparison(document: Mapping[str, Any]) -> None:
    """Validate the complete comparison, including deterministic cross-fields."""
    if not isinstance(document, Mapping):
        _fail("comparison_invalid", "comparison")
    value = dict(document)
    _exact_fields(
        value,
        frozenset(
            {
                "schema",
                "query_digest",
                "limit",
                "byte_budget",
                "channels",
                "provider",
                "provider_identity_digest",
                "policy_digest",
                "semantic_channel",
                "baseline",
                "shadow",
                "diff",
                "corpus_fingerprint",
                "retrieval_influence",
                "promotion_authorized",
                "authorizes_actions",
            }
        ),
        "comparison",
    )
    if value["schema"] != COMPARISON_SCHEMA:
        _fail("comparison_invalid", "schema")
    _digest(value["query_digest"], "query_digest")
    limit = _integer(value["limit"], "limit", 1, _MAX_RESULTS)
    byte_budget = _integer(value["byte_budget"], "byte_budget", 128, 65_536)
    if value["channels"] != list(CHANNELS):
        _fail("comparison_invalid", "channels")
    provider = _validate_provider(value["provider"])
    provider_digest = _digest(value["provider_identity_digest"], "provider_identity_digest")
    if provider_digest != identity_digest(provider):
        _fail("comparison_invalid", "provider_identity_digest")
    if _digest(value["policy_digest"], "policy_digest") != policy_digest():
        _fail("comparison_invalid", "policy_digest")
    _validate_semantic_channel(value["semantic_channel"])

    baseline = _mapping(value["baseline"], "baseline")
    _exact_fields(baseline, frozenset({"pointers", "candidate_count", "items_bytes"}), "baseline")
    baseline_pointers = _pointer_list(baseline["pointers"], "baseline.pointers", limit)
    baseline_count = _integer(baseline["candidate_count"], "baseline.candidate_count", 0, _MAX_COUNT)
    if baseline_count < len(baseline_pointers):
        _fail("comparison_invalid", "baseline.candidate_count")
    _integer(baseline["items_bytes"], "baseline.items_bytes", 0, byte_budget)

    shadow = _mapping(value["shadow"], "shadow")
    _exact_fields(shadow, frozenset({"items", "candidate_count", "items_bytes"}), "shadow")
    items = shadow["items"]
    if not isinstance(items, list) or len(items) > limit:
        _fail("comparison_invalid", "shadow.items")
    shadow_pointers: list[str] = []
    ranks: dict[str, set[int]] = {name: set() for name in CHANNELS}
    for index, raw_item in enumerate(items):
        field = f"shadow.items[{index}]"
        item = _mapping(raw_item, field)
        _exact_fields(
            item,
            frozenset({"pointer", "path", "start_line", "end_line", "content_digest", "score", "channels"}),
            field,
        )
        pointer = _text(item["pointer"], field + ".pointer")
        path = _text(item["path"], field + ".path")
        start = _integer(item["start_line"], field + ".start_line", 1, _MAX_COUNT)
        end = _integer(item["end_line"], field + ".end_line", start, _MAX_COUNT)
        if pointer != f"{path}:{start}-{end}":
            _fail("comparison_invalid", field + ".pointer")
        _digest(item["content_digest"], field + ".content_digest")
        score = item["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            _fail("comparison_invalid", field + ".score")
        channels = _mapping(item["channels"], field + ".channels")
        if not channels or set(channels) - set(CHANNELS):
            _fail("comparison_invalid", field + ".channels")
        for name, raw_rank in channels.items():
            maximum = SEMANTIC_TOP_K if name == "semantic" else 512
            rank = _integer(raw_rank, field + f".channels.{name}", 1, maximum)
            if rank in ranks[name]:
                _fail("comparison_invalid", field + f".channels.{name}")
            ranks[name].add(rank)
        shadow_pointers.append(pointer)
    if len(shadow_pointers) != len(set(shadow_pointers)):
        _fail("comparison_invalid", "shadow.items")
    shadow_count = _integer(shadow["candidate_count"], "shadow.candidate_count", 0, _MAX_COUNT)
    if shadow_count < len(shadow_pointers):
        _fail("comparison_invalid", "shadow.candidate_count")
    _integer(shadow["items_bytes"], "shadow.items_bytes", 0, byte_budget)

    diff = _mapping(value["diff"], "diff")
    _exact_fields(diff, frozenset({"identical", "added", "removed"}), "diff")
    baseline_set = set(baseline_pointers)
    shadow_set = set(shadow_pointers)
    if type(diff["identical"]) is not bool or diff["identical"] is not (
        baseline_pointers == shadow_pointers
    ):
        _fail("comparison_invalid", "diff.identical")
    added = _pointer_list(diff["added"], "diff.added", limit)
    removed = _pointer_list(diff["removed"], "diff.removed", limit)
    if added != sorted(added) or added != sorted(shadow_set - baseline_set):
        _fail("comparison_invalid", "diff.added")
    if removed != sorted(removed) or removed != sorted(baseline_set - shadow_set):
        _fail("comparison_invalid", "diff.removed")

    _digest(value["corpus_fingerprint"], "corpus_fingerprint")
    if value["retrieval_influence"] is not False:
        _fail("comparison_invalid", "retrieval_influence")
    if value["promotion_authorized"] is not False:
        _fail("comparison_invalid", "promotion_authorized")
    if value["authorizes_actions"] is not False:
        _fail("comparison_invalid", "authorizes_actions")
