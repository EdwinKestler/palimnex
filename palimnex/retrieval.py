"""Opt-in, source-backed rank fusion. No persistent state or model calls."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cache_v3, core
from .concepts import ConceptRegistry
from .locators import SourceResolver
from .ontology_shadow import (
    build_shadow_comparison,
    ontology_channel,
    validate_shadow_comparison,
)

MAX_SEEDS = 16
MAX_GRAPH_NODES = 128
RRF_K = 60


@dataclass(frozen=True)
class _ChannelRankings:
    chunks: list[dict[str, Any]]
    rankings: tuple[tuple[str, tuple[int, ...]], ...]
    snapshot: Any
    cache_consulted: bool
    retrieval_mode: str


@dataclass(frozen=True)
class _Fusion:
    results: list[dict[str, Any]]
    candidate_count: int
    items_bytes: int


def budget_items(items: list[dict[str, Any]], budget: int) -> tuple[list[dict[str, Any]], int]:
    """Conservative UTF-8-byte budget for serialized items, not a model tokenizer."""
    if type(budget) is not int or not 128 <= budget <= 65536:
        raise ValueError("context byte budget must be between 128 and 65536")
    selected: list[dict[str, Any]] = []
    used = 2
    for item in items:
        size = len(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")) + (2 if selected else 0)
        if used + size <= budget:
            selected.append(item)
            used += size
    return selected, used


def _rank_channels(query: str, *, root: Path, limit: int, byte_budget: int,
                   include_graph: bool, client: Any, snapshot: Any) -> _ChannelRankings:
    terms = set(cache_v3._bounded_query_tokens(query, "context query"))
    if not terms or not query.strip():
        raise ValueError("context query must contain a lexical term")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("context limit must be between 1 and 100")
    budget_items([], byte_budget)
    snapshot = snapshot or cache_v3.source_snapshot(root)
    chunks, vectors = [], []
    for source in snapshot.files:
        for source_chunk in core.split_chunks(source.path, source.text):
            chunks.append({"path": source.path, "start_line": source_chunk.start_line,
                           "end_line": source_chunk.end_line, "text": source_chunk.text,
                           "file_hash": source.digest,
                           "content_digest": hashlib.sha256(source_chunk.text.encode()).hexdigest(),
                           "pointer": f"{source.path}:{source_chunk.start_line}-{source_chunk.end_line}",
                           "source_status": "current_snapshot"})
            vectors.append(Counter(core.tokenize(source_chunk.text)))
            if len(chunks) > cache_v3.MAX_CORPUS_CHUNKS:
                raise ValueError("context corpus exceeds chunk quota")
    known = frozenset(source.path for source in snapshot.files)
    graphs = {source.path: core.extract_file_graph(source.path, source.text, known_paths=known)
              for source in snapshot.files}
    core._resolve_graph(graphs)
    lexical: dict[int, float] = {}
    if client is not None:
        manager, manifest, _ = cache_v3._fresh_context(client, root, snapshot=snapshot)
        try:
            scores, _, _ = cache_v3._posting_candidates(client, manifest, query, root, snapshot)
            # Verify graph records too; current source extraction is the result authority.
            cache_v3._load_graphs(client, manifest, root, snapshot)
            for index, chunk_data in enumerate(chunks):
                identity = cache_v3._chunk_id(
                    chunk_data["path"], chunk_data["start_line"], chunk_data["end_line"],
                    chunk_data["text"], manifest["index_policy_digest"]
                )
                key = f"{cache_v3.namespace(root)}:chunk:{identity}"
                if key in scores:
                    lexical[index] = scores[key]
        finally:
            manager.__exit__(None, None, None)
    else:
        count = max(1, len(chunks))
        average = max(1.0, sum(sum(v.values()) for v in vectors) / count)
        frequencies = {term: sum(term in v for v in vectors) for term in terms}
        for index, vector in enumerate(vectors):
            length = sum(vector.values())
            score = 0.0
            for term in terms & vector.keys():
                frequency = frequencies[term]
                inverse = math.log(1 + (count - frequency + .5) / (frequency + .5))
                tf = vector[term]
                score += inverse * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / average))
            if score:
                lexical[index] = score
    lexical_rank = sorted(lexical, key=lambda i: (-lexical[i], chunks[i]["pointer"]))[:512]
    symbols = {s["id"]: s for graph in graphs.values() for s in graph["symbols"]}
    by_path: dict[str, list[int]] = defaultdict(list)
    for i, chunk_data in enumerate(chunks):
        by_path[chunk_data["path"]].append(i)

    def symbol_chunks(symbol: dict[str, Any]) -> list[int]:
        return [i for i in by_path[symbol["path"]]
                if chunks[i]["start_line"] <= symbol["end_line"]
                and chunks[i]["end_line"] >= symbol["start_line"]]

    symbol_scores: dict[int, int] = {}
    matched = []
    normalized = query.strip().lower()
    for sid, symbol in symbols.items():
        names = (symbol["name"].lower(), symbol["qualified_name"].lower())
        score = 3 if normalized in names else (1 if terms & set(core.tokenize(" ".join(names))) else 0)
        if score:
            matched.append((score, sid))
            for i in symbol_chunks(symbol):
                symbol_scores[i] = max(symbol_scores.get(i, 0), score)
    symbol_rank = sorted(symbol_scores, key=lambda i: (-symbol_scores[i], chunks[i]["pointer"]))[:512]
    graph_rank = []
    if include_graph:
        seed_ids = [sid for _, sid in sorted(matched, key=lambda pair: (-pair[0], pair[1]))[:MAX_SEEDS]]
        for sid, symbol in symbols.items():
            if len(seed_ids) >= MAX_SEEDS:
                break
            if any(i in lexical_rank[:4] for i in symbol_chunks(symbol)) and sid not in seed_ids:
                seed_ids.append(sid)
        adjacency: dict[str, set[str]] = defaultdict(set)
        for graph in graphs.values():
            for edge in graph["edges"]:
                resolution = edge.get("resolution", {})
                a, b = edge["source_id"], resolution.get("target_id")
                if resolution.get("confidence") == "strong" and a in symbols and b in symbols and edge["kind"] != "contains":
                    adjacency[a].add(b)
                    adjacency[b].add(a)
        neighbors = sorted({target for sid in seed_ids for target in adjacency[sid]})[:MAX_GRAPH_NODES]
        graph_rank = sorted({i for sid in neighbors for i in symbol_chunks(symbols[sid])},
                            key=lambda i: chunks[i]["pointer"])[:512]
    return _ChannelRankings(
        chunks=chunks,
        rankings=(
            ("lexical", tuple(lexical_rank)),
            ("symbol", tuple(symbol_rank)),
            ("graph", tuple(graph_rank)),
        ),
        snapshot=snapshot,
        cache_consulted=client is not None,
        retrieval_mode="verified_cache_rrf" if client is not None else "local_snapshot_rrf",
    )


def _fuse_rankings(chunks: list[dict[str, Any]],
                   rankings: tuple[tuple[str, tuple[int, ...]], ...], *,
                   limit: int, byte_budget: int) -> _Fusion:
    fused: dict[int, float] = defaultdict(float)
    channels: dict[int, dict[str, int]] = defaultdict(dict)
    for name, ranking in rankings:
        for rank, i in enumerate(ranking, 1):
            fused[i] += 1 / (RRF_K + rank)
            channels[i][name] = rank
    ordered = sorted(fused, key=lambda i: (-fused[i], chunks[i]["pointer"]))[:512]
    items = [{**chunks[i], "score": fused[i], "channels": channels[i]} for i in ordered]
    selected, _ = budget_items(items, byte_budget)
    selected = selected[:limit]
    _, used = budget_items(selected, byte_budget)
    return _Fusion(selected, len(items), used)


def _retrieval_result(query: str, *, root: Path, byte_budget: int,
                      state: _ChannelRankings, fusion: _Fusion) -> dict[str, Any]:
    return {"query": query, "results": fusion.results,
            "candidate_count": fusion.candidate_count,
            "omitted_count": fusion.candidate_count - len(fusion.results),
            "byte_budget": byte_budget,
            "items_bytes": fusion.items_bytes, "budget_unit": "serialized_utf8_bytes",
            "cache_consulted": state.cache_consulted,
            "retrieval_mode": state.retrieval_mode,
            "scan_scope": "full_admitted_corpus", "corpus_fingerprint": state.snapshot.fingerprint,
            "checkout_id": hashlib.sha256(str(root.resolve()).encode()).hexdigest(),
            "semantic_influence": False, "authorizes_actions": False}


def retrieve_sources(query: str, *, root: Path = core.ROOT, limit: int = 5,
                     byte_budget: int = 8192, include_graph: bool = True,
                     client: Any = None, snapshot: Any = None) -> dict[str, Any]:
    """Local mode is explicit (client=None); cache errors never silently downgrade."""
    state = _rank_channels(
        query,
        root=root,
        limit=limit,
        byte_budget=byte_budget,
        include_graph=include_graph,
        client=client,
        snapshot=snapshot,
    )
    fusion = _fuse_rankings(
        state.chunks,
        state.rankings,
        limit=limit,
        byte_budget=byte_budget,
    )
    return _retrieval_result(
        query,
        root=root,
        byte_budget=byte_budget,
        state=state,
        fusion=fusion,
    )


def shadow_retrieve(query: str, *, registry: ConceptRegistry | None,
                    root: Path = core.ROOT, limit: int = 5,
                    byte_budget: int = 8192, include_graph: bool = True,
                    client: Any = None, snapshot: Any = None,
                    resolvers: Mapping[str, SourceResolver] | None = None) -> dict[str, Any]:
    """Return the unchanged baseline beside an evidence-only shadow comparison."""
    state = _rank_channels(
        query,
        root=root,
        limit=limit,
        byte_budget=byte_budget,
        include_graph=include_graph,
        client=client,
        snapshot=snapshot,
    )
    baseline_fusion = _fuse_rankings(
        state.chunks,
        state.rankings,
        limit=limit,
        byte_budget=byte_budget,
    )
    baseline = _retrieval_result(
        query,
        root=root,
        byte_budget=byte_budget,
        state=state,
        fusion=baseline_fusion,
    )
    channel = ontology_channel(
        registry,
        query,
        state.chunks,
        root=root,
        resolvers=resolvers,
    )
    shadow_fusion = _fuse_rankings(
        state.chunks,
        state.rankings + (("ontology", channel.ranking),),
        limit=limit,
        byte_budget=byte_budget,
    )
    comparison = build_shadow_comparison(
        query=query,
        registry=registry,
        channel=channel,
        baseline=baseline,
        shadow_results=shadow_fusion.results,
        shadow_candidate_count=shadow_fusion.candidate_count,
        shadow_items_bytes=shadow_fusion.items_bytes,
        limit=limit,
    )
    validate_shadow_comparison(comparison)
    return {"baseline": baseline, "comparison": comparison}
