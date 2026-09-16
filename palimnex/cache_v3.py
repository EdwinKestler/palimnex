"""Compact v3 source-discovery cache with immutable reader generations."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import math
import secrets
import struct
import sys
import time
import uuid
import zlib
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import core as legacy
from .documents import DOCUMENT_EXTRACTOR_ID
from .security import policy_digest as scanner_policy_digest
from .security import read_bounded_file, scan_bytes


CACHE_SCHEMA = "project-memory:cache:v3"
CACHE_RECORD_SCHEMA = "project-memory:cache-chunk:v1"
GRAPH_RECORD_SCHEMA = "project-memory:document-graph:v2"
GRAPH_RECORD_CODEC = "zlib-canonical-json:v1"
INDEX_POLICY_VERSION = "project-memory:index-policy:v1"
ADMISSION_POLICY_VERSION = "project-memory:source-admission:v1"
TOKENIZER_ID = "unicode-alnum-underscore-lower:v1"
EMBEDDING_ID = "feature-hash-sha256-unigram-bigram-int8:v2"
DIMENSIONS = 384
GENERATION_RETENTION = 3
GENERATION_GRACE_MS = 60_000
MAX_UNLEASED_GRACE_GENERATIONS = 2
LEASE_TTL_MS = 120_000
MAX_CANDIDATES = 512
MAX_SOURCE_BYTES = 1_000_000
MAX_CORPUS_BYTES = 64 * 1024 * 1024
MAX_CORPUS_CHUNKS = 100_000
MAX_POSTING_TERMS = 100_000
MAX_QUERY_BYTES = 8 * 1024
MAX_QUERY_TERMS = 128
CACHE_MODES = ("off", "shadow", "on")
MIGRATION_SIZE_RATIO_MAX = 0.60
MIGRATION_P95_RATIO_MAX = 10.0
MIGRATION_LATENCY_RUNS = 3
BM25_K1 = 1.2
BM25_B = 0.75
POSTING_MAGIC = b"PM25P1"
POSTING_HEADER = struct.Struct(">6s16sI")
POSTING_ENTRY = struct.Struct(">16sII")
GRAPH_MAGIC = b"PM25G1"
GRAPH_HEADER = struct.Struct(">6sI32s")
MAX_GRAPH_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class SourceFile:
    path: str
    raw: bytes
    text: str
    digest: str


@dataclass(frozen=True)
class SourceSnapshot:
    files: tuple[SourceFile, ...]
    fingerprint: str

    @property
    def by_path(self) -> dict[str, SourceFile]:
        return {item.path: item for item in self.files}


def project_id(root: Path) -> str:
    configured = legacy.project_config(root).get("project_id")
    if not isinstance(configured, str):
        raise ValueError(f"{legacy.CONFIG_FILE} project_id must be a committed UUID")
    try:
        return str(uuid.UUID(configured))
    except ValueError as exc:
        raise ValueError(f"{legacy.CONFIG_FILE} project_id must be a UUID") from exc


def configured_cache_mode(root: Path = legacy.ROOT) -> str:
    """Return the explicit migration feature flag; old configurations stay on v2."""
    value = legacy.project_config(root).get("cache_mode", "off")
    if value not in CACHE_MODES:
        raise ValueError(
            f"{legacy.CONFIG_FILE} cache_mode must be one of {', '.join(CACHE_MODES)}"
        )
    return value


def namespace(root: Path = legacy.ROOT) -> str:
    identity = uuid.UUID(project_id(root)).hex
    return f"{legacy.project_slug(root)}:{identity}:{CACHE_SCHEMA}"


def hot_namespace(root: Path = legacy.ROOT) -> str:
    identity = uuid.UUID(project_id(root)).hex
    return f"{legacy.project_slug(root)}:{identity}:project-memory:hot:v1"


def _term_digest_key(root: Path) -> bytes:
    return uuid.UUID(project_id(root)).bytes


def token_digest(token: str, root: Path, *, key: bytes | None = None) -> str:
    key = _term_digest_key(root) if key is None else key
    return hashlib.blake2b(token.encode("utf-8"), key=key, digest_size=16).hexdigest()


def index_policy_digest(root: Path) -> str:
    config = legacy.project_config(root)
    admission_material = {
        "version": ADMISSION_POLICY_VERSION,
        "text_suffixes": sorted(legacy.TEXT_SUFFIXES),
        "text_exact_names": sorted(legacy.TEXT_EXACT_NAMES),
        "text_probe_bytes": legacy.TEXT_PROBE_BYTES,
        "default_patterns": list(legacy.DEFAULT_PATTERNS),
        "sensitive_data_suffixes": sorted(legacy.SENSITIVE_DATA_SUFFIXES),
        "sensitive_token_patterns": [
            {"pattern": item.pattern, "flags": item.flags}
            for item in legacy.SENSITIVE_TOKEN_PATTERNS
        ],
        "include_patterns": config.get("include_patterns"),
        "exclude_directories": config.get("exclude_directories"),
        "exclude_paths": config.get("exclude_paths"),
        "include_palimnex": config.get("include_palimnex", False),
    }
    material = {
        "policy": INDEX_POLICY_VERSION,
        "scanner": scanner_policy_digest(),
        "source_admission": hashlib.sha256(
            json.dumps(admission_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "content_allowlist_sha256": sorted(_content_allowlist(root)),
        "tokenizer": TOKENIZER_ID,
        "embedding": EMBEDDING_ID,
        "dimensions": DIMENSIONS,
        "chunk_lines": legacy.CHUNK_LINES,
        "chunk_overlap": legacy.CHUNK_OVERLAP,
        "max_source_bytes": MAX_SOURCE_BYTES,
        "max_corpus_bytes": MAX_CORPUS_BYTES,
        "max_corpus_chunks": MAX_CORPUS_CHUNKS,
        "graph_schema": legacy.GRAPH_SCHEMA,
        "document_extractor": DOCUMENT_EXTRACTOR_ID,
        "graph_record_schema": GRAPH_RECORD_SCHEMA,
        "graph_record_codec": GRAPH_RECORD_CODEC,
        "chunk_record_schema": CACHE_RECORD_SCHEMA,
        "posting_codec": "redis-hash+pm25p1-binary:v1",
        "project_id": project_id(root),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _content_allowlist(root: Path) -> set[str]:
    configured = legacy.project_config(root).get("content_scan_allowlist_sha256", [])
    if not isinstance(configured, list) or not all(
        isinstance(item, str)
        and len(item) == 64
        and all(character in "0123456789abcdef" for character in item)
        for item in configured
    ):
        raise ValueError(
            f"{legacy.CONFIG_FILE} content_scan_allowlist_sha256 must contain lowercase SHA-256 values"
        )
    return set(configured)


def _bounded_query_tokens(query: str, label: str) -> list[str]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"{label} must not be empty")
    if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
        raise ValueError(f"{label} exceeds {MAX_QUERY_BYTES} UTF-8 bytes")
    tokens = legacy.tokenize(query)
    if len(tokens) > MAX_QUERY_TERMS:
        raise ValueError(f"{label} exceeds {MAX_QUERY_TERMS} lexical terms")
    return tokens


def source_snapshot(root: Path = legacy.ROOT) -> SourceSnapshot:
    files = []
    digest = hashlib.sha256()
    allowlist = _content_allowlist(root)
    total_bytes = 0
    for path in legacy.included_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            raw = read_bounded_file(root, relative, max_bytes=MAX_SOURCE_BYTES)
        except ValueError as exc:
            raise ValueError(f"cannot safely open source snapshot file: {relative}") from exc
        total_bytes += len(raw)
        if total_bytes > MAX_CORPUS_BYTES:
            raise ValueError(f"source corpus exceeds {MAX_CORPUS_BYTES} bytes")
        findings = scan_bytes(raw, allowed_sha256=allowlist)
        if findings:
            summary = ", ".join(f"{item.rule}@{item.line}" for item in findings[:5])
            raise ValueError(f"content privacy scan rejected {relative}: {summary}")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError(f"source changed to non-UTF-8 during snapshot: {relative}") from exc
        path_raw = relative.encode("utf-8")
        digest.update(struct.pack(">I", len(path_raw)))
        digest.update(path_raw)
        digest.update(struct.pack(">Q", len(raw)))
        digest.update(raw)
        files.append(SourceFile(relative, raw, text, hashlib.sha256(raw).hexdigest()))
    return SourceSnapshot(tuple(files), digest.hexdigest())


def _chunk_terms(text: str, root: Path) -> Counter[str]:
    key = _term_digest_key(root)
    return Counter(token_digest(token, root, key=key) for token in legacy.tokenize(text))


def _encode_vector(text: str) -> str:
    values = legacy.embedding(text, DIMENSIONS)
    quantized = bytes((max(-127, min(127, round(value * 127))) + 256) % 256 for value in values)
    return base64.b64encode(quantized).decode("ascii")


def _decode_vector(value: str) -> tuple[float, ...]:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid quantized vector") from exc
    if len(raw) != DIMENSIONS:
        raise ValueError("invalid quantized vector dimensions")
    return tuple((byte if byte < 128 else byte - 256) / 127.0 for byte in raw)


def _encode_posting(term: str, documents: list[tuple[str, int, int]]) -> bytes:
    if (
        len(term) != 32
        or any(character not in "0123456789abcdef" for character in term)
        or len(documents) > MAX_CORPUS_CHUNKS
    ):
        raise ValueError("posting term or document count exceeds its boundary")
    encoded = bytearray(POSTING_HEADER.pack(POSTING_MAGIC, bytes.fromhex(term), len(documents)))
    seen = set()
    for chunk_id, frequency, document_length in sorted(documents):
        if (
            len(chunk_id) != 32
            or any(character not in "0123456789abcdef" for character in chunk_id)
            or chunk_id in seen
            or type(frequency) is not int
            or not 0 < frequency <= 0xFFFFFFFF
            or type(document_length) is not int
            or not 0 <= document_length <= 0xFFFFFFFF
        ):
            raise ValueError("posting contains an invalid chunk record")
        seen.add(chunk_id)
        encoded.extend(
            POSTING_ENTRY.pack(bytes.fromhex(chunk_id), frequency, document_length)
        )
    return bytes(encoded)


def _decode_posting(raw: bytes | None, term: str) -> list[tuple[str, int, int]] | None:
    try:
        if raw is None or len(raw) < POSTING_HEADER.size:
            return None
        magic, encoded_term, count = POSTING_HEADER.unpack_from(raw)
        if (
            magic != POSTING_MAGIC
            or encoded_term.hex() != term
            or count > MAX_CORPUS_CHUNKS
            or len(raw) != POSTING_HEADER.size + count * POSTING_ENTRY.size
        ):
            return None
        documents = []
        seen = set()
        offset = POSTING_HEADER.size
        for _ in range(count):
            chunk_id, frequency, document_length = POSTING_ENTRY.unpack_from(raw, offset)
            offset += POSTING_ENTRY.size
            identity = chunk_id.hex()
            if identity in seen or frequency < 1:
                return None
            seen.add(identity)
            documents.append((identity, frequency, document_length))
        return documents
    except (TypeError, ValueError, struct.error):
        return None


def _posting_digest(postings: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for term, payload in sorted(postings.items()):
        field = term.encode("ascii")
        digest.update(struct.pack(">I", len(field)) + field)
        digest.update(struct.pack(">Q", len(payload)) + payload)
    return digest.hexdigest()


def _chunk_id(path: str, start: int, end: int, text: str, policy: str) -> str:
    return hashlib.sha256(
        b"\0".join(
            (
                path.encode(),
                str(start).encode(),
                str(end).encode(),
                policy.encode(),
                text.encode(),
            )
        )
    ).hexdigest()[:32]


def _chunk_payload(
    *,
    path: str,
    file_hash: str,
    start: int,
    end: int,
    text: str,
    root: Path,
    policy: str,
) -> tuple[str, dict[str, Any], Counter[str]]:
    terms = _chunk_terms(text, root)
    identity = _chunk_id(path, start, end, text, policy)
    payload = {
        "schema": CACHE_RECORD_SCHEMA,
        "id": identity,
        "path": path,
        "file_hash": file_hash,
        "start_line": start,
        "end_line": end,
        "content_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "term_count": sum(terms.values()),
        "vector": _encode_vector(text),
        "index_policy_digest": policy,
    }
    return identity, payload, terms


def _graph_identity(path: str, file_hash: str, policy: str) -> str:
    return hashlib.sha256(
        b"\0".join((GRAPH_RECORD_SCHEMA.encode(), path.encode(), file_hash.encode(), policy.encode()))
    ).hexdigest()


def _graph_payload(
    path: str, file_hash: str, policy: str, graph: dict[str, Any]
) -> bytes:
    logical = _compact_json({
        "schema": GRAPH_RECORD_SCHEMA,
        "path": path,
        "file_hash": file_hash,
        "index_policy_digest": policy,
        "graph": graph,
    }).encode("utf-8")
    if len(logical) > MAX_GRAPH_BYTES:
        raise ValueError("document graph exceeds its logical size boundary")
    return (
        GRAPH_HEADER.pack(GRAPH_MAGIC, len(logical), hashlib.sha256(logical).digest())
        + zlib.compress(logical, level=9)
    )


def _json(raw: bytes | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode_graph_payload(raw: bytes | None) -> Any:
    if raw is None or len(raw) < GRAPH_HEADER.size:
        return None
    try:
        magic, logical_size, digest = GRAPH_HEADER.unpack_from(raw)
        compressed = raw[GRAPH_HEADER.size :]
        if magic != GRAPH_MAGIC or not compressed or logical_size > MAX_GRAPH_BYTES:
            return None
        decompressor = zlib.decompressobj()
        logical = decompressor.decompress(compressed, MAX_GRAPH_BYTES + 1)
        logical += decompressor.flush()
        if (
            len(logical) != logical_size
            or decompressor.unconsumed_tail
            or not decompressor.eof
            or decompressor.unused_data
            or hashlib.sha256(logical).digest() != digest
        ):
            return None
        payload = _json(logical)
        if _compact_json(payload).encode("utf-8") != logical:
            return None
        return payload
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError, zlib.error):
        return None


def _valid_chunk(
    raw: bytes | None,
    *,
    expected_key: str | None = None,
    expected_path: str | None = None,
    expected_policy: str | None = None,
) -> dict[str, Any] | None:
    try:
        payload = _json(raw)
        if not isinstance(payload, dict) or payload.get("schema") != CACHE_RECORD_SCHEMA:
            return None
        required = {
            "id": str,
            "path": str,
            "file_hash": str,
            "start_line": int,
            "end_line": int,
            "content_digest": str,
            "term_count": int,
            "vector": str,
            "index_policy_digest": str,
        }
        if (
            set(payload) != {"schema", *required}
            or any(not isinstance(payload.get(key), value) for key, value in required.items())
        ):
            return None
        if (
            len(payload["id"]) != 32
            or any(character not in "0123456789abcdef" for character in payload["id"])
            or len(payload["file_hash"]) != 64
            or any(character not in "0123456789abcdef" for character in payload["file_hash"])
            or len(payload["content_digest"]) != 64
            or any(character not in "0123456789abcdef" for character in payload["content_digest"])
            or len(payload["index_policy_digest"]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in payload["index_policy_digest"]
            )
        ):
            return None
        if payload["start_line"] < 1 or payload["end_line"] < payload["start_line"]:
            return None
        if payload["term_count"] < 0:
            return None
        _decode_vector(payload["vector"])
        if expected_key is not None and not expected_key.endswith(":" + payload["id"]):
            return None
        if expected_path is not None and payload["path"] != expected_path:
            return None
        if expected_policy is not None and payload["index_policy_digest"] != expected_policy:
            return None
        return payload
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


def _valid_graph(
    raw: bytes | None,
    *,
    path: str,
    file_hash: str,
    policy: str,
) -> dict[str, Any] | None:
    try:
        payload = _decode_graph_payload(raw)
        if (
            not isinstance(payload, dict)
            or set(payload) != {
                "schema", "path", "file_hash", "index_policy_digest", "graph"
            }
            or payload.get("schema") != GRAPH_RECORD_SCHEMA
            or payload.get("path") != path
            or payload.get("file_hash") != file_hash
            or payload.get("index_policy_digest") != policy
            or not isinstance(payload.get("graph"), dict)
            or not legacy._valid_graphs({path: payload["graph"]}, [path])
        ):
            return None
        return payload["graph"]
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None


def _manifest_summary(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        key: manifest.get(key)
        for key in (
            "bundle_version",
            "generation",
            "fingerprint",
            "file_count",
            "chunk_count",
            "symbol_count",
            "edge_count",
            "index_policy_digest",
            "activated_at",
        )
    }


def _public_manifest(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {key: value for key, value in manifest.items() if not key.startswith("_")}


def _active_manifest_key(client: Any, root: Path) -> str | None:
    raw = client.execute("GET", f"{namespace(root)}:active-generation")
    if raw is None:
        return None
    value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return value if isinstance(value, str) and value.startswith(namespace(root) + ":generation:") else None


def _load_manifest(client: Any, key: str | None, root: Path) -> dict[str, Any] | None:
    if key is None:
        return None
    try:
        value = _json(client.execute("GET", key))
    except (UnicodeError, json.JSONDecodeError):
        return None
    required = {
        "schema",
        "namespace",
        "bundle_version",
        "generation",
        "fingerprint",
        "files",
        "file_hashes",
        "file_chunks",
        "file_graphs",
        "chunk_keys",
        "posting_hash_key",
        "posting_count",
        "posting_digest",
        "chunk_count",
        "file_count",
        "symbol_count",
        "edge_count",
        "resolution_metrics",
        "index_policy_digest",
        "scanner_policy_digest",
        "average_document_length",
        "activated_at",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value["schema"] != CACHE_SCHEMA
        or value["namespace"] != namespace(root)
        or value["bundle_version"] != legacy.BUNDLE_VERSION
        or not isinstance(value["generation"], str)
        or key != f"{namespace(root)}:generation:{value['generation']}:manifest"
        or not isinstance(value["fingerprint"], str)
        or len(value["fingerprint"]) != 64
        or any(character not in "0123456789abcdef" for character in value["fingerprint"])
        or not isinstance(value["files"], list)
        or not all(isinstance(item, str) for item in value["files"])
        or len(set(value["files"])) != len(value["files"])
        or not isinstance(value["file_hashes"], dict)
        or not isinstance(value["file_chunks"], dict)
        or not isinstance(value["file_graphs"], dict)
        or not isinstance(value["chunk_keys"], list)
        or not all(isinstance(item, str) for item in value["chunk_keys"])
        or not isinstance(value["posting_hash_key"], str)
        or type(value["posting_count"]) is not int
        or type(value["chunk_count"]) is not int
        or type(value["file_count"]) is not int
        or type(value["symbol_count"]) is not int
        or type(value["edge_count"]) is not int
        or any(value[item] < 0 for item in (
            "posting_count", "chunk_count", "file_count", "symbol_count", "edge_count"
        ))
        or not isinstance(value["posting_digest"], str)
        or len(value["posting_digest"]) != 64
        or any(character not in "0123456789abcdef" for character in value["posting_digest"])
        or not isinstance(value["resolution_metrics"], dict)
        or not isinstance(value["average_document_length"], (int, float))
        or isinstance(value["average_document_length"], bool)
        or not math.isfinite(value["average_document_length"])
        or value["average_document_length"] < 0
        or type(value["activated_at"]) is not int
        or value["activated_at"] < 0
        or not isinstance(value["scanner_policy_digest"], str)
        or value["scanner_policy_digest"] != scanner_policy_digest()
        or not isinstance(value["index_policy_digest"], str)
        or value["index_policy_digest"] != index_policy_digest(root)
    ):
        return None
    return value


def _reader_lease_key(root: Path, manifest_key: str) -> str:
    return (
        f"{namespace(root)}:reader-lease:"
        f"{hashlib.sha1(manifest_key.encode('utf-8')).hexdigest()}"
    )


@contextmanager
def generation_reader(client: Any, root: Path):
    active_key = f"{namespace(root)}:active-generation"
    lease_prefix = f"{namespace(root)}:reader-lease:"
    acquired = client.execute(
        "EVAL",
        "local m=redis.call('get',KEYS[1]); if not m then return nil end; "
        "local l=ARGV[1]..redis.sha1hex(m); local n=redis.call('incr',l); "
        "redis.call('pexpire',l,ARGV[2]); return {m,l,n}",
        "1",
        active_key,
        lease_prefix,
        str(LEASE_TTL_MS),
    )
    if acquired is None:
        yield None
        return
    if not isinstance(acquired, list) or len(acquired) != 3:
        raise ValueError("Palimnex reader lease response is malformed")
    manifest_raw, lease_raw, _ = acquired
    manifest_key = (
        manifest_raw.decode("utf-8") if isinstance(manifest_raw, bytes) else str(manifest_raw)
    )
    lease_key = lease_raw.decode("utf-8") if isinstance(lease_raw, bytes) else str(lease_raw)
    if (
        not manifest_key.startswith(namespace(root) + ":generation:")
        or lease_key != lease_prefix + hashlib.sha1(manifest_key.encode("utf-8")).hexdigest()
    ):
        raise ValueError("Palimnex reader lease selected an invalid generation")
    try:
        manifest = _load_manifest(client, manifest_key, root)
        if manifest is None:
            raise ValueError("active cache generation is missing or malformed")
        manifest = dict(manifest)
        manifest["_reader_lease_key"] = lease_key
        yield manifest
    finally:
        active_exception = sys.exc_info()[0] is not None
        try:
            client.execute(
                "EVAL",
                "local n=tonumber(redis.call('get',KEYS[1]) or '0'); "
                "if n <= 1 then return redis.call('del',KEYS[1]) "
                "else return redis.call('decr',KEYS[1]) end",
                "1",
                lease_key,
            )
        except Exception:
            if not active_exception:
                raise


def _refresh_reader_lease(client: Any, manifest: dict[str, Any]) -> None:
    lease_key = manifest.get("_reader_lease_key")
    if not isinstance(lease_key, str) or client.execute("PEXPIRE", lease_key, str(LEASE_TTL_MS)) != 1:
        raise ValueError("Palimnex reader lease expired during the operation")


@contextmanager
def _writer_lock(client: Any, root: Path):
    prefix = namespace(root)
    key = f"{prefix}:index-lock"
    owner = secrets.token_hex(16)
    if client.execute("SET", key, owner, "NX", "PX", str(legacy.INDEX_LOCK_MS)) != "OK":
        raise ValueError("another Palimnex v3 indexer is active")
    try:
        yield owner
    finally:
        active_exception = sys.exc_info()[0] is not None
        try:
            client.execute(
                "EVAL",
                "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                "1",
                key,
                owner,
            )
        except Exception:
            if not active_exception:
                raise


def _refresh_lock(client: Any, root: Path, owner: str) -> None:
    if client.execute(
        "EVAL",
        "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('pexpire',KEYS[1],ARGV[2]) else return 0 end",
        "1",
        f"{namespace(root)}:index-lock",
        owner,
        str(legacy.INDEX_LOCK_MS),
    ) != 1:
        raise ValueError("Palimnex v3 index lock ownership was lost")


def _activate(client: Any, root: Path, owner: str, manifest_key: str) -> None:
    if client.execute(
        "EVAL",
        "if redis.call('get',KEYS[1]) == ARGV[1] then redis.call('set',KEYS[2],ARGV[2]); return 1 else return 0 end",
        "2",
        f"{namespace(root)}:index-lock",
        f"{namespace(root)}:active-generation",
        owner,
        manifest_key,
    ) != 1:
        raise ValueError("Palimnex v3 index lock ownership was lost before activation")


def _registry(client: Any, root: Path, *, required: bool = False) -> dict[str, Any]:
    raw = client.execute("GET", f"{namespace(root)}:registry")
    if raw is None:
        if required:
            raise ValueError("Palimnex v3 registry is missing")
        return {"schema": "project-memory:registry:v1", "generations": []}
    try:
        value = _json(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Palimnex v3 registry is malformed") from None
    if not isinstance(value, dict) or set(value) != {"schema", "generations"} or (
        value.get("schema") != "project-memory:registry:v1"
        or not isinstance(value.get("generations"), list)
    ):
        raise ValueError("Palimnex v3 registry is malformed")
    prefix = namespace(root) + ":"
    seen = set()
    required_fields = {
        "manifest_key", "activated_at", "state", "chunk_keys", "graph_keys", "posting_keys"
    }
    for item in value["generations"]:
        if (
            not isinstance(item, dict)
            or set(item) != required_fields
            or not isinstance(item.get("manifest_key"), str)
            or not item["manifest_key"].startswith(prefix + "generation:")
            or item["manifest_key"] in seen
            or type(item.get("activated_at")) is not int
            or item["activated_at"] < 0
            or item.get("state") not in {"staging", "complete"}
            or any(
                not isinstance(item.get(field), list)
                or not all(isinstance(key, str) and key.startswith(prefix) for key in item[field])
                for field in ("chunk_keys", "graph_keys", "posting_keys")
            )
        ):
            raise ValueError("Palimnex v3 registry contains an invalid generation")
        seen.add(item["manifest_key"])
    return value


def _fenced_set(
    client: Any, root: Path, owner: str, key: str, value: str
) -> None:
    changed = client.execute(
        "EVAL",
        "if redis.call('get',KEYS[1]) == ARGV[1] then "
        "redis.call('set',KEYS[2],ARGV[2]); return 1 else return 0 end",
        "2",
        f"{namespace(root)}:index-lock",
        key,
        owner,
        value,
    )
    if changed != 1:
        raise ValueError("Palimnex v3 index lock ownership was lost before a write")


def _fenced_delete(
    client: Any, root: Path, owner: str, keys: list[str]
) -> int:
    if not keys:
        return 0
    response = client.execute(
        "EVAL",
        "if redis.call('get',KEYS[1]) ~= ARGV[1] then return -1 end "
        "local n=0; for i=2,#KEYS do n=n+redis.call('del',KEYS[i]) end; return n",
        str(len(keys) + 1),
        f"{namespace(root)}:index-lock",
        *keys,
        owner,
    )
    if response == -1:
        raise ValueError("Palimnex v3 index lock ownership was lost before garbage collection")
    return int(response)


def _fenced_write_batch(
    client: Any,
    root: Path,
    owner: str,
    entries: list[tuple[str, str | bytes]],
) -> None:
    for start in range(0, len(entries), 50):
        batch = entries[start : start + 50]
        keys = [key for key, _ in batch]
        values = [value for _, value in batch]
        response = client.execute(
            "EVAL",
            "if redis.call('get',KEYS[1]) ~= ARGV[1] then return 0 end "
            "for i=2,#KEYS do redis.call('set',KEYS[i],ARGV[i]) end; return 1",
            str(len(keys) + 1),
            f"{namespace(root)}:index-lock",
            *keys,
            owner,
            *values,
        )
        if response != 1:
            raise ValueError("Palimnex v3 index lock ownership was lost during staged writes")


def _fenced_hash_batch(
    client: Any,
    root: Path,
    owner: str,
    hash_key: str,
    entries: dict[str, bytes],
) -> None:
    ordered = sorted(entries.items())
    for start in range(0, len(ordered), 200):
        arguments: list[str | bytes] = [owner]
        for field, value in ordered[start : start + 200]:
            arguments.extend((field, value))
        response = client.execute(
            "EVAL",
            "if redis.call('get',KEYS[1]) ~= ARGV[1] then return 0 end "
            "for i=2,#ARGV,2 do redis.call('hset',KEYS[2],ARGV[i],ARGV[i+1]) end; return 1",
            "2",
            f"{namespace(root)}:index-lock",
            hash_key,
            *arguments,
        )
        if response != 1:
            raise ValueError(
                "Palimnex v3 index lock ownership was lost during posting writes"
            )


def status(
    client: Any,
    root: Path = legacy.ROOT,
    *,
    verbose: bool = False,
) -> tuple[dict[str, Any], bool]:
    snapshot = source_snapshot(root)
    manifest = _load_manifest(client, _active_manifest_key(client, root), root)
    fresh = bool(
        manifest
        and manifest["fingerprint"] == snapshot.fingerprint
        and _validate_manifest_shape(manifest, snapshot, root)
    )
    return {
        "status": "fresh" if fresh else ("stale" if manifest else "missing_or_invalid"),
        "fresh": fresh,
        "namespace": namespace(root),
        "schema": CACHE_SCHEMA,
        "current_fingerprint": snapshot.fingerprint,
        "manifest": _public_manifest(manifest) if verbose else _manifest_summary(manifest),
        "legacy_namespace": legacy.namespace(root),
        "legacy_preserved": _active_manifest_key_legacy(client, root) is not None,
    }, fresh


def _active_manifest_key_legacy(client: Any, root: Path) -> str | None:
    raw = client.execute("GET", f"{legacy.namespace(root)}:active-generation")
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


def _validate_manifest_shape(manifest: dict[str, Any], snapshot: SourceSnapshot, root: Path) -> bool:
    files = [item.path for item in snapshot.files]
    try:
        flattened_chunks = [
            key for path in files for key in manifest["file_chunks"][path]
        ]
        resolution_keys = {
            "exact_qualified", "lexical_scope", "import_binding",
            "heuristic_unique_short_name", "ambiguous", "unresolved",
        }
        return bool(
            manifest["files"] == files
            and manifest["file_count"] == len(files)
            and set(manifest["file_hashes"]) == set(files)
            and manifest["file_hashes"] == {item.path: item.digest for item in snapshot.files}
            and all(
                isinstance(value, str)
                and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
                for value in manifest["file_hashes"].values()
            )
            and set(manifest["file_chunks"]) == set(files)
            and all(
                isinstance(value, list) and all(isinstance(key, str) for key in value)
                for value in manifest["file_chunks"].values()
            )
            and flattened_chunks == manifest["chunk_keys"]
            and set(manifest["file_graphs"]) == set(files)
            and all(isinstance(value, str) for value in manifest["file_graphs"].values())
            and manifest["chunk_count"] == len(manifest["chunk_keys"])
            and len(set(manifest["chunk_keys"])) == manifest["chunk_count"]
            and 0 <= manifest["posting_count"] <= MAX_POSTING_TERMS
            and all(
                key.startswith(namespace(root) + ":chunk:")
                for key in manifest["chunk_keys"]
            )
            and all(
                key.startswith(namespace(root) + ":graph:")
                for key in manifest["file_graphs"].values()
            )
            and manifest["posting_hash_key"].startswith(namespace(root) + ":postings:")
            and set(manifest["resolution_metrics"]) == resolution_keys
            and all(
                type(value) is int and value >= 0
                for value in manifest["resolution_metrics"].values()
            )
            and sum(manifest["resolution_metrics"].values()) == manifest["edge_count"]
        )
    except (KeyError, TypeError):
        return False


def validate(
    client: Any,
    root: Path = legacy.ROOT,
    *,
    deep: bool = False,
    verbose: bool = False,
) -> tuple[dict[str, Any], bool]:
    snapshot = source_snapshot(root)
    valid = False
    manifest: dict[str, Any] | None = None
    with generation_reader(client, root) as candidate:
        manifest = candidate
        if manifest and _validate_manifest_shape(manifest, snapshot, root):
            valid = manifest["fingerprint"] == snapshot.fingerprint
            if valid and deep:
                valid = _deep_validate(client, manifest, snapshot, root)
    return {
        "status": "fresh" if valid else ("stale" if manifest else "missing_or_invalid"),
        "fresh": valid,
        "namespace": namespace(root),
        "schema": CACHE_SCHEMA,
        "current_fingerprint": snapshot.fingerprint,
        "manifest": _public_manifest(manifest) if verbose else _manifest_summary(manifest),
        "validation": "passed" if valid else "failed",
        "deep": deep,
        "legacy_namespace": legacy.namespace(root),
        "legacy_preserved": _active_manifest_key_legacy(client, root) is not None,
    }, valid


def _deep_validate(client: Any, manifest: dict[str, Any], snapshot: SourceSnapshot, root: Path) -> bool:
    policy = index_policy_digest(root)
    source_by_path = snapshot.by_path
    known_paths = frozenset(source_by_path)
    values = legacy._mget_batched(client, manifest["chunk_keys"])
    _refresh_reader_lease(client, manifest)
    for key, raw in zip(manifest["chunk_keys"], values, strict=True):
        payload = _valid_chunk(raw, expected_key=key, expected_policy=policy)
        if payload is None or payload["path"] not in source_by_path:
            return False
        source = source_by_path[payload["path"]]
        if payload["file_hash"] != source.digest:
            return False
        lines = source.text.splitlines()
        text = "\n".join(lines[payload["start_line"] - 1 : payload["end_line"]])
        identity, expected, _ = _chunk_payload(
            path=payload["path"],
            file_hash=source.digest,
            start=payload["start_line"],
            end=payload["end_line"],
            text=text,
            root=root,
            policy=policy,
        )
        if identity != payload["id"] or expected != payload:
            return False
    graphs = _load_graphs(client, manifest, root, snapshot)
    _refresh_reader_lease(client, manifest)
    if not _validate_posting_hash(client, manifest, root):
        return False
    _refresh_reader_lease(client, manifest)
    expected_graphs = {
        item.path: legacy.extract_file_graph(
            item.path, item.text, known_paths=known_paths
        )
        for item in snapshot.files
    }
    if graphs != expected_graphs:
        return False
    resolved = json.loads(json.dumps(graphs))
    symbols, edges, metrics = legacy._resolve_graph(resolved)
    return (
        symbols == manifest["symbol_count"]
        and edges == manifest["edge_count"]
        and metrics == manifest["resolution_metrics"]
    )


def build_index(
    client: Any,
    root: Path = legacy.ROOT,
    *,
    repair_deep: bool = False,
) -> dict[str, Any]:
    client.require_trusted_write_endpoint()
    # Complete source admission before even the short-lived writer lock is
    # created.  This makes a privacy refusal a true zero-write operation.
    snapshot = source_snapshot(root)
    with _writer_lock(client, root) as owner:
        return _build_locked(
            client,
            root,
            owner=owner,
            repair_deep=repair_deep,
            snapshot=snapshot,
        )


def _build_locked(
    client: Any,
    root: Path,
    *,
    owner: str,
    repair_deep: bool,
    snapshot: SourceSnapshot,
) -> dict[str, Any]:
    started = time.monotonic()
    prefix = namespace(root)
    policy = index_policy_digest(root)
    old_manifest = _load_manifest(client, _active_manifest_key(client, root), root)
    policy_reusable = bool(old_manifest and old_manifest.get("index_policy_digest") == policy)
    old_hashes = old_manifest.get("file_hashes", {}) if policy_reusable else {}
    old_chunks = old_manifest.get("file_chunks", {}) if policy_reusable else {}
    old_graphs = old_manifest.get("file_graphs", {}) if policy_reusable else {}
    build_id = secrets.token_hex(16)
    generation = f"{snapshot.fingerprint}:{policy[:16]}:{build_id[:16]}"
    manifest_key = f"{prefix}:generation:{generation}:manifest"

    file_hashes: dict[str, str] = {}
    file_chunks: dict[str, list[str]] = {}
    file_graphs: dict[str, str] = {}
    chunk_payloads: dict[str, dict[str, Any]] = {}
    graph_payloads: dict[str, bytes] = {}
    postings: dict[str, list[tuple[str, int, int]]] = {}
    generated = 0
    reused = 0
    graphs_generated = 0
    graphs_reused = 0
    document_lengths = []
    known_paths = frozenset(item.path for item in snapshot.files)

    for source in snapshot.files:
        file_hashes[source.path] = source.digest
        reusable_file = old_hashes.get(source.path) == source.digest
        owned_keys = old_chunks.get(source.path, []) if reusable_file else []
        reusable_payloads: list[dict[str, Any]] = []
        if owned_keys:
            raws = legacy._mget_batched(client, owned_keys)
            reusable_payloads = [
                payload
                for key, raw in zip(owned_keys, raws, strict=True)
                if (payload := _valid_chunk(raw, expected_key=key, expected_path=source.path, expected_policy=policy))
            ]
            if len(reusable_payloads) != len(owned_keys) or repair_deep:
                reusable_payloads = []
        chunks = legacy.split_chunks(source.path, source.text)
        keys = []
        if reusable_payloads and len(reusable_payloads) == len(chunks):
            for key, payload, chunk in zip(owned_keys, reusable_payloads, chunks, strict=True):
                # Identity omits file_hash, so an unchanged chunk from an
                # edited file can sit at the same key with a stale digest.
                if (
                    payload["content_digest"] != hashlib.sha256(chunk.text.encode()).hexdigest()
                    or payload["file_hash"] != source.digest
                ):
                    reusable_payloads = []
                    break
        if reusable_payloads:
            for key, payload, chunk in zip(owned_keys, reusable_payloads, chunks, strict=True):
                terms = _chunk_terms(chunk.text, root)
                keys.append(key)
                reused += 1
                document_lengths.append(payload["term_count"])
                for term, frequency in terms.items():
                    postings.setdefault(term, []).append(
                        (payload["id"], frequency, payload["term_count"])
                    )
        else:
            for chunk in chunks:
                identity, payload, terms = _chunk_payload(
                    path=source.path,
                    file_hash=source.digest,
                    start=chunk.start_line,
                    end=chunk.end_line,
                    text=chunk.text,
                    root=root,
                    policy=policy,
                )
                key = f"{prefix}:chunk:{identity}"
                chunk_payloads[key] = payload
                keys.append(key)
                generated += 1
                document_lengths.append(payload["term_count"])
                for term, frequency in terms.items():
                    postings.setdefault(term, []).append(
                        (identity, frequency, payload["term_count"])
                    )
        file_chunks[source.path] = keys

        graph_key = f"{prefix}:graph:{_graph_identity(source.path, source.digest, policy)}"
        file_graphs[source.path] = graph_key
        reusable_graph = old_graphs.get(source.path) == graph_key
        if reusable_graph:
            graph = _valid_graph(
                client.execute("GET", graph_key),
                path=source.path,
                file_hash=source.digest,
                policy=policy,
            )
        else:
            graph = None
        if graph is None or repair_deep:
            graph = legacy.extract_file_graph(
                source.path, source.text, known_paths=known_paths
            )
            graph_payloads[graph_key] = _graph_payload(source.path, source.digest, policy, graph)
            graphs_generated += 1
        else:
            graphs_reused += 1

    graph_values: dict[str, dict[str, Any]] = {}
    for source in snapshot.files:
        key = file_graphs[source.path]
        graph_values[source.path] = (
            _valid_graph(
                graph_payloads[key],
                path=source.path,
                file_hash=source.digest,
                policy=policy,
            )
            if key in graph_payloads
            else _valid_graph(
                client.execute("GET", key),
                path=source.path,
                file_hash=source.digest,
                policy=policy,
            )
        )
    if any(value is None for value in graph_values.values()):
        raise ValueError("reused graph vanished during indexing")
    resolved_graphs = json.loads(json.dumps(graph_values))
    symbol_count, edge_count, resolution_metrics = legacy._resolve_graph(resolved_graphs)

    if len(postings) > MAX_POSTING_TERMS:
        raise ValueError(f"source corpus exceeds {MAX_POSTING_TERMS} posting terms")
    posting_payloads = {
        term: _encode_posting(term, documents) for term, documents in postings.items()
    }
    posting_digest = _posting_digest(posting_payloads)
    posting_hash_key = f"{prefix}:postings:{posting_digest}"
    writes: list[tuple[str, str | bytes]] = []
    for key, payload in chunk_payloads.items():
        existing = _valid_chunk(
            client.execute("GET", key),
            expected_key=key,
            expected_policy=policy,
        )
        if existing != payload:
            writes.append((key, _compact_json(payload)))
    for key, payload in graph_payloads.items():
        writes.append((key, payload))

    chunk_keys = [key for source in snapshot.files for key in file_chunks[source.path]]
    if len(chunk_keys) > MAX_CORPUS_CHUNKS:
        raise ValueError(f"source corpus exceeds {MAX_CORPUS_CHUNKS} chunks")
    graph_keys = list(file_graphs.values())
    activated_at = int(time.time() * 1_000)
    registry = _registry(client, root)
    generations = [
        item
        for item in registry.get("generations", [])
        if isinstance(item, dict) and item.get("manifest_key") != manifest_key
    ]
    generations.append(
        {
            "manifest_key": manifest_key,
            "activated_at": activated_at,
            "state": "staging",
            "chunk_keys": chunk_keys,
            "graph_keys": graph_keys,
            "posting_keys": [posting_hash_key],
        }
    )
    _refresh_lock(client, root, owner)
    _fenced_set(
        client,
        root,
        owner,
        f"{prefix}:registry",
        _compact_json({"schema": "project-memory:registry:v1", "generations": generations}),
    )
    _fenced_write_batch(client, root, owner, writes)
    _fenced_hash_batch(client, root, owner, posting_hash_key, posting_payloads)
    _refresh_lock(client, root, owner)
    manifest = {
        "schema": CACHE_SCHEMA,
        "bundle_version": legacy.BUNDLE_VERSION,
        "namespace": prefix,
        "generation": generation,
        "fingerprint": snapshot.fingerprint,
        "files": [item.path for item in snapshot.files],
        "file_count": len(snapshot.files),
        "file_hashes": file_hashes,
        "file_chunks": file_chunks,
        "file_graphs": file_graphs,
        "chunk_keys": chunk_keys,
        "posting_hash_key": posting_hash_key,
        "posting_count": len(posting_payloads),
        "posting_digest": posting_digest,
        "chunk_count": len(chunk_keys),
        "symbol_count": symbol_count,
        "edge_count": edge_count,
        "resolution_metrics": resolution_metrics,
        "index_policy_digest": policy,
        "average_document_length": (
            sum(document_lengths) / len(document_lengths) if document_lengths else 0.0
        ),
        "scanner_policy_digest": scanner_policy_digest(),
        "activated_at": activated_at,
    }
    _fenced_set(client, root, owner, manifest_key, _compact_json(manifest))
    generations[-1]["state"] = "complete"
    _fenced_set(
        client,
        root,
        owner,
        f"{prefix}:registry",
        _compact_json({"schema": "project-memory:registry:v1", "generations": generations}),
    )
    _refresh_lock(client, root, owner)

    final_snapshot = source_snapshot(root)
    if final_snapshot.fingerprint != snapshot.fingerprint:
        raise ValueError("repository changed during indexing; staged generation was not activated")
    _activate(client, root, owner, manifest_key)
    _refresh_lock(client, root, owner)
    deleted = _collect_garbage(
        client, root, owner=owner, current_manifest_key=manifest_key
    )
    elapsed = round((time.monotonic() - started) * 1_000)
    return {
        "manifest": _manifest_summary(manifest),
        "metrics": {
            "files": len(snapshot.files),
            "chunks": {
                "total": len(chunk_keys),
                "generated": generated,
                "reused": reused,
            },
            "graphs": {"generated": graphs_generated, "reused": graphs_reused},
            "postings": len(posting_payloads),
            "garbage_collected_keys": deleted,
            "total_ms": elapsed,
        },
        "legacy_namespace_preserved": _active_manifest_key_legacy(client, root) is not None,
    }


def _collect_garbage(
    client: Any,
    root: Path,
    *,
    owner: str,
    current_manifest_key: str,
) -> int:
    registry = _registry(client, root)
    entries = [item for item in registry.get("generations", []) if isinstance(item, dict)]
    now = int(time.time() * 1_000)
    complete = [item for item in entries if item.get("state", "complete") == "complete"]
    staged = [item for item in entries if item.get("state") == "staging"]
    retained = complete[-GENERATION_RETENTION:]
    candidates = complete[:-GENERATION_RETENTION] + staged
    grace_candidates = []
    for item in candidates:
        manifest_key = item.get("manifest_key")
        age = now - int(item.get("activated_at", 0))
        lease_key = _reader_lease_key(root, str(manifest_key))
        raw_count = client.execute("GET", lease_key)
        count = int(raw_count or 0)
        if count > 0:
            retained.append(item)
        elif item.get("state") == "complete" and age < GENERATION_GRACE_MS:
            grace_candidates.append(item)
    if MAX_UNLEASED_GRACE_GENERATIONS:
        retained.extend(
            sorted(
                grace_candidates,
                key=lambda item: (
                    int(item.get("activated_at", 0)), str(item.get("manifest_key", ""))
                ),
            )[-MAX_UNLEASED_GRACE_GENERATIONS:]
        )
    retained_keys = {item.get("manifest_key") for item in retained}
    retained = [item for item in entries if item.get("manifest_key") in retained_keys]
    doomed_entries = [item for item in candidates if item.get("manifest_key") not in retained_keys]
    retained_manifests = [
        manifest
        for item in retained
        if (manifest := _load_manifest(client, item.get("manifest_key"), root)) is not None
    ]
    used = {current_manifest_key}
    for manifest in retained_manifests:
        used.add(f"{namespace(root)}:generation:{manifest['generation']}:manifest")
        used.update(manifest["chunk_keys"])
        used.update(manifest["file_graphs"].values())
        used.add(manifest["posting_hash_key"])
    doomed = set()
    for item in doomed_entries:
        key = item.get("manifest_key")
        manifest = _load_manifest(client, key, root)
        if manifest:
            doomed.update(manifest["chunk_keys"])
            doomed.update(manifest["file_graphs"].values())
            doomed.add(manifest["posting_hash_key"])
        else:
            doomed.update(
                item_key
                for field in ("chunk_keys", "graph_keys", "posting_keys")
                for item_key in item.get(field, [])
                if isinstance(item_key, str) and item_key.startswith(namespace(root) + ":")
            )
        if isinstance(key, str):
            doomed.add(key)
    removable = sorted(doomed - used)
    deleted = 0
    if removable:
        for start in range(0, len(removable), 999):
            deleted += _fenced_delete(client, root, owner, removable[start : start + 999])
    _fenced_set(
        client,
        root,
        owner,
        f"{namespace(root)}:registry",
        _compact_json({"schema": "project-memory:registry:v1", "generations": retained}),
    )
    return deleted


def _fresh_context(
    client: Any,
    root: Path,
    *,
    snapshot: SourceSnapshot | None = None,
    manifest: dict[str, Any] | None = None,
):
    snapshot = source_snapshot(root) if snapshot is None else snapshot
    manager = generation_reader(client, root) if manifest is None else contextlib.nullcontext(manifest)
    manifest = manager.__enter__()
    if manifest is None:
        manager.__exit__(None, None, None)
        raise ValueError("v3 cache is missing; run index")
    if (
        manifest["fingerprint"] != snapshot.fingerprint
        or not _validate_manifest_shape(manifest, snapshot, root)
    ):
        manager.__exit__(None, None, None)
        raise ValueError("v3 cache is stale; run index")
    return manager, manifest, snapshot


def _load_graphs(
    client: Any,
    manifest: dict[str, Any],
    root: Path,
    snapshot: SourceSnapshot,
    paths: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    _refresh_reader_lease(client, manifest)
    selected_paths = manifest["files"] if paths is None else sorted(set(paths))
    if any(path not in manifest["file_graphs"] for path in selected_paths):
        raise ValueError("v3 graph selection is outside the active manifest")
    keys = [manifest["file_graphs"][path] for path in selected_paths]
    values = legacy._mget_batched(client, keys)
    graphs = {}
    known_paths = frozenset(item.path for item in snapshot.files)
    for path, key, raw in zip(selected_paths, keys, values, strict=True):
        graph = _valid_graph(
            raw,
            path=path,
            file_hash=manifest["file_hashes"][path],
            policy=manifest["index_policy_digest"],
        )
        if graph is None:
            raise ValueError("v3 cache contains malformed graph data; re-index required")
        source = snapshot.by_path.get(path)
        if source is None or graph != legacy.extract_file_graph(
            path,
            source.text,
            known_paths=known_paths,
        ):
            raise ValueError("v3 graph differs from the current source snapshot")
        graphs[path] = graph
    return graphs


def _load_all_postings(
    client: Any, manifest: dict[str, Any], root: Path
) -> dict[str, list[tuple[str, int, int]]]:
    hash_key = manifest["posting_hash_key"]
    if int(client.execute("HLEN", hash_key)) != manifest["posting_count"]:
        raise ValueError("v3 posting hash length differs from its manifest")
    cursor = "0"
    seen_cursors = set()
    raw_postings: dict[str, bytes] = {}
    while True:
        if cursor in seen_cursors:
            raise ValueError("v3 posting hash scan repeated a cursor")
        seen_cursors.add(cursor)
        response = client.execute("HSCAN", hash_key, cursor, "COUNT", "1000")
        if not isinstance(response, list) or len(response) != 2:
            raise ValueError("v3 posting hash scan returned a malformed response")
        cursor_raw, flat = response
        cursor = cursor_raw.decode("ascii") if isinstance(cursor_raw, bytes) else str(cursor_raw)
        if not isinstance(flat, list) or len(flat) % 2:
            raise ValueError("v3 posting hash scan returned malformed fields")
        for field_raw, value in zip(flat[::2], flat[1::2], strict=True):
            field = field_raw.decode("ascii") if isinstance(field_raw, bytes) else str(field_raw)
            if not isinstance(value, bytes) or _decode_posting(value, field) is None:
                raise ValueError("v3 posting hash contains malformed data")
            previous = raw_postings.get(field)
            if previous is not None and previous != value:
                raise ValueError("v3 posting hash scan changed during validation")
            raw_postings[field] = value
            if len(raw_postings) > MAX_POSTING_TERMS:
                raise ValueError("v3 posting hash exceeds its term boundary")
        if cursor == "0":
            break
        if not cursor.isdigit():
            raise ValueError("v3 posting hash returned a malformed cursor")
    if len(raw_postings) != manifest["posting_count"]:
        raise ValueError("v3 posting hash field count differs from its manifest")
    if _posting_digest(raw_postings) != manifest["posting_digest"]:
        raise ValueError("v3 posting hash digest differs from its manifest")
    allowed_chunk_ids = {key.rsplit(":", 1)[-1] for key in manifest["chunk_keys"]}
    decoded = {}
    for term, value in raw_postings.items():
        documents = _decode_posting(value, term)
        if documents is None or any(item[0] not in allowed_chunk_ids for item in documents):
            raise ValueError("v3 posting hash references an unowned chunk")
        decoded[term] = documents
    return decoded


def _validate_posting_hash(
    client: Any, manifest: dict[str, Any], root: Path
) -> bool:
    try:
        _load_all_postings(client, manifest, root)
        return True
    except (TypeError, ValueError, UnicodeError):
        return False


def _posting_candidates(
    client: Any,
    manifest: dict[str, Any],
    query: str,
    root: Path,
    snapshot: SourceSnapshot,
) -> tuple[dict[str, float], set[str], dict[str, int]]:
    term_key = _term_digest_key(root)
    query_tokens = set(_bounded_query_tokens(query, "search query"))
    query_terms = {token_digest(token, root, key=term_key) for token in query_tokens}
    ordered_terms = sorted(query_terms)
    values = (
        client.execute("HMGET", manifest["posting_hash_key"], *ordered_terms)
        if ordered_terms
        else []
    )
    if not isinstance(values, list) or len(values) != len(ordered_terms):
        raise ValueError("v3 posting hash returned a malformed response")
    _refresh_reader_lease(client, manifest)
    expected_postings: dict[str, list[tuple[str, int, int]]] = {
        term: [] for term in ordered_terms
    }
    policy = manifest["index_policy_digest"]
    for source in snapshot.files:
        for chunk in legacy.split_chunks(source.path, source.text):
            plain_terms = Counter(legacy.tokenize(chunk.text))
            matching_tokens = query_tokens & plain_terms.keys()
            if not matching_tokens:
                continue
            identity = _chunk_id(
                source.path, chunk.start_line, chunk.end_line, chunk.text, policy
            )
            document_length = sum(plain_terms.values())
            for token in matching_tokens:
                expected_postings[token_digest(token, root, key=term_key)].append(
                    (identity, plain_terms[token], document_length)
                )
    document_count = max(1, manifest["chunk_count"])
    average_length = max(1.0, float(manifest["average_document_length"]))
    decoded: list[tuple[str, float, dict[str, tuple[int, int]]]] = []
    for term, raw in zip(ordered_terms, values, strict=True):
        if raw is None:
            if expected_postings[term]:
                raise ValueError(f"v3 posting is missing for queried term {term}")
            continue
        try:
            documents = _decode_posting(raw, term)
            if documents is None or documents != sorted(expected_postings[term]):
                raise ValueError
            frequency = len(documents)
            if frequency > document_count:
                raise ValueError
            inverse = math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))
            ranked_documents = sorted(
                documents,
                key=lambda item: (-item[1], item[2], item[0]),
            )
            decoded.append(
                (
                    term,
                    inverse,
                    {
                        chunk_id: (term_frequency, document_length)
                        for chunk_id, term_frequency, document_length in ranked_documents
                    },
                )
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                f"v3 posting is malformed or differs from source for queried term {term}"
            ) from exc

    # Select fairly across query terms before computing BM25. A single common
    # term cannot make the scorer touch the whole corpus or crowd every other
    # term out of the bounded candidate set.
    selected: list[str] = []
    selected_set: set[str] = set()
    ranked_ids = [list(documents) for _, _, documents in decoded]
    position = 0
    while len(selected) < MAX_CANDIDATES:
        added = False
        for identifiers in ranked_ids:
            if position >= len(identifiers):
                continue
            identity = identifiers[position]
            if identity not in selected_set:
                selected.append(identity)
                selected_set.add(identity)
                added = True
                if len(selected) == MAX_CANDIDATES:
                    break
        if not added and all(position + 1 >= len(items) for items in ranked_ids):
            break
        position += 1

    scores: dict[str, float] = {}
    matching_term_counts: dict[str, int] = {}
    for chunk_id in selected:
        chunk_key = f"{namespace(root)}:chunk:{chunk_id}"
        score = 0.0
        matching_terms = 0
        for _, inverse, documents in decoded:
            document = documents.get(chunk_id)
            if document is not None:
                matching_terms += 1
                term_frequency, document_length = document
                denominator = term_frequency + BM25_K1 * (
                    1.0 - BM25_B + BM25_B * document_length / average_length
                )
                score += inverse * (
                    term_frequency * (BM25_K1 + 1.0) / denominator
                )
        scores[chunk_key] = score
        matching_term_counts[chunk_key] = matching_terms
    ranked = sorted(scores, key=lambda item: (-scores[item], item))[:MAX_CANDIDATES]
    return (
        {key: scores[key] for key in ranked},
        query_terms,
        {key: matching_term_counts[key] for key in ranked},
    )


def search(
    client: Any,
    query: str,
    limit: int,
    root: Path = legacy.ROOT,
    *,
    _snapshot: SourceSnapshot | None = None,
    _manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _bounded_query_tokens(query, "search query")
    manager, manifest, snapshot = _fresh_context(
        client, root, snapshot=_snapshot, manifest=_manifest
    )
    try:
        candidate_scores, query_terms, matching_term_counts = _posting_candidates(
            client, manifest, query, root, snapshot
        )
        candidate_keys = list(candidate_scores)
        values = legacy._mget_batched(client, candidate_keys) if candidate_keys else []
        _refresh_reader_lease(client, manifest)
        source_by_path = snapshot.by_path
        query_vector = legacy.embedding(query, DIMENSIONS)
        term_key = _term_digest_key(root)
        normalized = query.strip().lower()
        results = []
        prepared: list[tuple[str, dict[str, Any], str]] = []
        boundaries_by_path: dict[str, set[tuple[int, int, str]]] = {}
        for key, raw in zip(candidate_keys, values, strict=True):
            chunk = _valid_chunk(raw, expected_key=key, expected_policy=manifest["index_policy_digest"])
            if chunk is None:
                raise ValueError("v3 cache contains malformed chunk data; re-index required")
            source = source_by_path.get(chunk["path"])
            if source is None or source.digest != chunk["file_hash"]:
                raise ValueError("v3 chunk source ownership mismatch")
            lines = source.text.splitlines()
            text = "\n".join(lines[chunk["start_line"] - 1 : chunk["end_line"]])
            if source.path not in boundaries_by_path:
                boundaries_by_path[source.path] = {
                    (item.start_line, item.end_line, item.text)
                    for item in legacy.split_chunks(source.path, source.text)
                }
            boundaries = boundaries_by_path[source.path]
            identity, expected_chunk, _ = _chunk_payload(
                path=source.path,
                file_hash=source.digest,
                start=chunk["start_line"],
                end=chunk["end_line"],
                text=text,
                root=root,
                policy=manifest["index_policy_digest"],
            )
            if (
                (chunk["start_line"], chunk["end_line"], text) not in boundaries
                or identity != chunk["id"]
                or chunk != expected_chunk
            ):
                raise ValueError("v3 chunk differs from the current source snapshot")
            prepared.append((key, chunk, text))
        graphs = _load_graphs(
            client,
            manifest,
            root,
            snapshot,
            (chunk["path"] for _, chunk, _ in prepared),
        )
        symbols_by_path = {path: graph.get("symbols", []) for path, graph in graphs.items()}
        for key, chunk, text in prepared:
            vector = _decode_vector(chunk["vector"])
            cosine = sum(a * b for a, b in zip(query_vector, vector, strict=True))
            overlap = matching_term_counts[key] / len(query_terms) if query_terms else 0.0
            if query_terms and overlap == 0:
                raise ValueError("v3 posting points to a chunk without the queried term")
            matching_symbols = [
                symbol
                for symbol in symbols_by_path.get(chunk["path"], [])
                if symbol["start_line"] <= chunk["end_line"]
                and symbol["end_line"] >= chunk["start_line"]
                and (
                    symbol["name"].lower() == normalized
                    or symbol["qualified_name"].lower() == normalized
                    or token_digest(symbol["name"].lower(), root, key=term_key) in query_terms
                )
            ]
            symbol_boost = 0.2 if matching_symbols else 0.0
            bm25 = candidate_scores[key]
            score = bm25 + 0.3 * cosine + 0.2 * overlap + symbol_boost
            results.append(
                {
                    "path": chunk["path"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                    "score": round(score, 6),
                    "pointer": f"{chunk['path']}:{chunk['start_line']}-{chunk['end_line']}",
                    "text": text,
                    "matches": [
                        {
                            "type": "symbol",
                            "name": symbol["qualified_name"],
                            "kind": symbol["kind"],
                            "parser": symbol["parser"],
                            "confidence": symbol["confidence"],
                        }
                        for symbol in matching_symbols
                    ],
                    "explanation": {
                        "bm25": round(bm25, 6),
                        "cosine": round(cosine, 6),
                        "lexical": round(overlap, 6),
                        "symbol_boost": symbol_boost,
                        "candidate_chunks": len(candidate_keys),
                    },
                }
            )
        results.sort(key=lambda item: (-item["score"], item["path"], item["start_line"]))
        return {"query": query, "fresh": True, "results": results[:limit]}
    finally:
        manager.__exit__(None, None, None)


def symbols(
    client: Any,
    query: str,
    limit: int,
    root: Path = legacy.ROOT,
    *,
    _snapshot: SourceSnapshot | None = None,
    _manifest: dict[str, Any] | None = None,
    _graphs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _bounded_query_tokens(query, "symbol query")
    manager, manifest, snapshot = _fresh_context(
        client, root, snapshot=_snapshot, manifest=_manifest
    )
    try:
        graphs = _load_graphs(client, manifest, root, snapshot) if _graphs is None else _graphs
        normalized = query.strip().lower()
        results = []
        for graph in graphs.values():
            for symbol in graph.get("symbols", []):
                name = symbol["name"].lower()
                qualified = symbol["qualified_name"].lower()
                if normalized not in name and normalized not in qualified:
                    continue
                rank = 0 if normalized in {name, qualified} else (1 if normalized in qualified else 2)
                results.append(
                    {
                        **symbol,
                        "pointer": f"{symbol['path']}:{symbol['start_line']}-{symbol['end_line']}",
                        "explanation": "exact symbol" if rank == 0 else "symbol substring",
                        "_rank": rank,
                    }
                )
        results.sort(key=lambda item: (item["_rank"], item["qualified_name"], item["path"]))
        for item in results:
            item.pop("_rank")
        return {"query": query, "fresh": True, "results": results[:limit]}
    finally:
        manager.__exit__(None, None, None)


def impact(
    client: Any,
    query: str,
    limit: int,
    root: Path = legacy.ROOT,
    *,
    _snapshot: SourceSnapshot | None = None,
    _manifest: dict[str, Any] | None = None,
    _graphs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _bounded_query_tokens(query, "impact query")
    manager, manifest, snapshot = _fresh_context(
        client, root, snapshot=_snapshot, manifest=_manifest
    )
    try:
        graphs = _load_graphs(client, manifest, root, snapshot) if _graphs is None else _graphs
        legacy._resolve_graph(graphs)
        all_symbols = [symbol for graph in graphs.values() for symbol in graph.get("symbols", [])]
        normalized = query.strip().lower()
        targets = {
            symbol["id"]
            for symbol in all_symbols
            if normalized in {symbol["name"].lower(), symbol["qualified_name"].lower()}
        }
        symbols_by_id = {symbol["id"]: symbol for symbol in all_symbols}
        results = []
        seen = set()
        for graph in graphs.values():
            for edge in graph.get("edges", []):
                target = edge.get("target", "").lower()
                short = __import__("re").split(r"[.:]+", target)[-1]
                resolution = edge["resolution"]
                if resolution.get("target_id") not in targets and normalized not in {target, short}:
                    continue
                source = symbols_by_id.get(edge["source_id"])
                if source is None or source["id"] in seen:
                    continue
                seen.add(source["id"])
                results.append(
                    {
                        "source": source,
                        "edge": edge,
                        "pointer": f"{edge['path']}:{edge['line']}",
                        "explanation": f"{edge['kind']} edge ({resolution['status']}/{resolution['confidence']})",
                    }
                )
        results.sort(key=lambda item: (item["edge"]["kind"], item["pointer"]))
        return {"query": query, "fresh": True, "target_ids": sorted(targets), "results": results[:limit]}
    finally:
        manager.__exit__(None, None, None)


def dependency_path(
    client: Any,
    source_query: str,
    target_query: str,
    *,
    direction: str = "forward",
    edge_kinds: Iterable[str] | None = None,
    max_depth: int = legacy.DEFAULT_PATH_MAX_DEPTH,
    include_probable: bool = False,
    root: Path = legacy.ROOT,
) -> dict[str, Any]:
    _bounded_query_tokens(source_query, "dependency source query")
    _bounded_query_tokens(target_query, "dependency target query")
    manager, manifest, snapshot = _fresh_context(client, root)
    try:
        graphs = _load_graphs(client, manifest, root, snapshot)
        return {
            "fresh": True,
            **legacy.shortest_dependency_path(
                graphs,
                source_query,
                target_query,
                direction=direction,
                edge_kinds=edge_kinds,
                max_depth=max_depth,
                include_probable=include_probable,
            ),
        }
    finally:
        manager.__exit__(None, None, None)


def _evaluation_cases(root: Path) -> list[dict[str, Any]]:
    config = legacy.project_config(root)
    configured = config.get("evaluation_fixture")
    configured_digest = config.get("evaluation_fixture_sha256")
    if not isinstance(configured, str) or not configured:
        raise ValueError(f"{legacy.CONFIG_FILE} evaluation_fixture must name a frozen JSON file")
    if (
        not isinstance(configured_digest, str)
        or len(configured_digest) != 64
        or any(character not in "0123456789abcdef" for character in configured_digest)
    ):
        raise ValueError(
            f"{legacy.CONFIG_FILE} evaluation_fixture_sha256 must pin the frozen fixture"
        )
    relative = Path(configured)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("evaluation_fixture must be repository-relative")
    path = root / relative
    if path in legacy.included_files(root):
        raise ValueError("evaluation_fixture must be excluded from the indexed corpus")
    try:
        raw = read_bounded_file(root, relative, max_bytes=MAX_SOURCE_BYTES)
        if hashlib.sha256(raw).hexdigest() != configured_digest:
            raise ValueError("evaluation fixture digest differs from its frozen configuration")
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("evaluation_fixture is missing or invalid") from exc
    cases = (
        document.get("cases")
        if isinstance(document, dict)
        and set(document) == {"schema", "frozen", "description", "cases"}
        and document.get("schema") == "project-memory:evaluation:v1"
        and document.get("frozen") is True
        and isinstance(document.get("description"), str)
        and bool(document["description"].strip())
        else None
    )
    if not isinstance(cases, list) or len(cases) < 20:
        raise ValueError("evaluation_fixture must contain at least 20 cases")
    identifiers = []
    allowed = {
        "id", "mode", "query", "expected_paths", "forbidden_paths", "limit", "critical"
    }
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) != allowed
            or not isinstance(case.get("id"), str)
            or not case["id"].strip()
            or case.get("mode") not in {"search", "symbols", "impact"}
            or not isinstance(case.get("query"), str)
            or not case["query"].strip()
            or not isinstance(case.get("expected_paths"), list)
            or not case["expected_paths"]
            or not isinstance(case.get("forbidden_paths"), list)
            or not all(
                isinstance(item, str)
                and item
                and not Path(item).is_absolute()
                and ".." not in Path(item).parts
                for item in case["expected_paths"] + case["forbidden_paths"]
            )
            or set(case["expected_paths"]) & set(case["forbidden_paths"])
            or type(case.get("limit")) is not int
            or not 1 <= case["limit"] <= 100
            or type(case.get("critical")) is not bool
        ):
            raise ValueError("evaluation_fixture contains an invalid case")
        identifiers.append(case["id"])
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("evaluation_fixture case identifiers must be unique")
    return cases


def _evaluate_loaded(
    client: Any,
    limit: int,
    root: Path,
    snapshot: SourceSnapshot,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    outcomes = []
    reciprocal_ranks = []
    expected_total = 0
    found_total = 0
    critical_passed = True
    if not _deep_validate(client, manifest, snapshot, root):
        raise ValueError("frozen evaluation requires a deep-valid v3 generation")
    shared_graphs = _load_graphs(client, manifest, root, snapshot)
    for case in _evaluation_cases(root):
        if (
            not isinstance(case, dict)
            or case.get("mode") not in {"search", "symbols", "impact"}
            or not isinstance(case.get("query"), str)
            or not isinstance(case.get("expected_paths"), list)
            or not all(isinstance(path, str) for path in case["expected_paths"])
            or not isinstance(case.get("forbidden_paths", []), list)
        ):
            raise ValueError("evaluation_fixture contains an invalid case")
        lookup = {"symbols": symbols, "impact": impact}.get(case["mode"])
        context: dict[str, Any] = {
            "_snapshot": snapshot,
            "_manifest": manifest,
        }
        if case["mode"] in {"symbols", "impact"}:
            context["_graphs"] = shared_graphs
        response = (
            search(
                client,
                case["query"],
                case.get("limit", limit),
                root,
                _snapshot=snapshot,
                _manifest=manifest,
            )
            if case["mode"] == "search"
            else lookup(
                client, case["query"], case.get("limit", limit), root, **context
            )
        )
        if case["mode"] in {"search", "symbols"}:
            returned = [item["path"] for item in response["results"]]
        else:
            returned = [item["source"]["path"] for item in response["results"]]
        expected = case["expected_paths"]
        forbidden = case.get("forbidden_paths", [])
        missing = sorted(set(expected) - set(returned))
        forbidden_hits = sorted(set(forbidden) & set(returned))
        expected_total += len(expected)
        found_total += len(expected) - len(missing)
        ranks = [returned.index(path) + 1 for path in expected if path in returned]
        reciprocal = 1.0 / min(ranks) if ranks else 0.0
        reciprocal_ranks.append(reciprocal)
        passed = not missing and not forbidden_hits
        if case.get("critical", False) and not passed:
            critical_passed = False
        outcomes.append(
            {
                "id": case.get("id"),
                "mode": case["mode"],
                "query": case["query"],
                "critical": bool(case.get("critical", False)),
                "expected_paths": expected,
                "returned_paths": returned,
                "missing_paths": missing,
                "forbidden_hits": forbidden_hits,
                "reciprocal_rank": reciprocal,
                "passed": passed,
            }
        )
    recall = found_total / expected_total if expected_total else 0.0
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    passed_count = sum(item["passed"] for item in outcomes)
    forbidden_clear = not any(item["forbidden_hits"] for item in outcomes)
    passed = critical_passed and forbidden_clear and recall >= 0.95
    return {
        "status": "passed" if passed else "failed",
        "cases": len(outcomes),
        "passed": passed_count,
        "critical_passed": critical_passed,
        "forbidden_clear": forbidden_clear,
        "recall_at_limit": recall,
        "mrr": mrr,
        "limit": limit,
        "outcomes": outcomes,
    }


def evaluate(client: Any, limit: int, root: Path = legacy.ROOT) -> dict[str, Any]:
    snapshot = source_snapshot(root)
    manager, manifest, _ = _fresh_context(client, root, snapshot=snapshot)
    try:
        result = _evaluate_loaded(client, limit, root, snapshot, manifest)
    finally:
        manager.__exit__(None, None, None)
    if source_snapshot(root).fingerprint != snapshot.fingerprint:
        raise ValueError("repository changed during frozen evaluation")
    return result


def _legacy_active_keys(client: Any, root: Path) -> list[str]:
    state, fresh = legacy.status(client, root)
    manifest = state.get("manifest")
    manifest_key = _active_manifest_key_legacy(client, root)
    if not fresh or not isinstance(manifest, dict) or not isinstance(manifest_key, str):
        raise ValueError("migration requires a fresh preserved v2.4 baseline at the equal corpus")
    prefix = legacy.namespace(root)
    keys = {
        f"{prefix}:active-generation",
        f"{prefix}:chunk-registry",
        manifest_key,
        *manifest.get("chunk_keys", []),
    }
    graphs = manifest.get("file_graphs", {})
    if isinstance(graphs, dict):
        keys.update(value for value in graphs.values() if isinstance(value, str))
    if any(not isinstance(key, str) or not key.startswith(prefix + ":") for key in keys):
        raise ValueError("legacy baseline cannot prove ownership of its active generation")
    return sorted(keys)


def _v3_owned_keys(client: Any, root: Path) -> list[str]:
    registry = _registry(client, root, required=True)
    prefix = namespace(root)
    keys = {
        f"{prefix}:active-generation",
        f"{prefix}:registry",
    }
    for generation in registry["generations"]:
        if generation["state"] != "complete":
            raise ValueError("v3 migration measurement found an incomplete generation")
        manifest_key = generation["manifest_key"]
        manifest = _load_manifest(client, manifest_key, root)
        if manifest is None:
            raise ValueError("v3 retained generation is missing during migration measurement")
        keys.add(manifest_key)
        keys.update(generation["chunk_keys"])
        keys.update(generation["graph_keys"])
        keys.update(generation["posting_keys"])
    if any(not isinstance(key, str) or not key.startswith(prefix + ":") for key in keys):
        raise ValueError("v3 baseline cannot prove ownership of its retained generations")
    return sorted(keys)


def _string_snapshot_digest(client: Any, keys: list[str]) -> str:
    values = legacy._mget_batched(client, keys)
    if any(value is None for value in values):
        raise ValueError("migration baseline lost a registered Redis record")
    digest = hashlib.sha256()
    for key, value in zip(keys, values, strict=True):
        raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
        encoded_key = key.encode("utf-8")
        digest.update(struct.pack(">I", len(encoded_key)) + encoded_key)
        digest.update(struct.pack(">Q", len(raw)) + raw)
    return digest.hexdigest()


def _redis_memory_bytes(client: Any, keys: list[str]) -> int:
    total = 0
    for key in keys:
        value = client.execute("MEMORY", "USAGE", key, "SAMPLES", "0")
        if type(value) is not int or value <= 0:
            raise ValueError("Redis MEMORY USAGE did not account for every registered record")
        total += value
    return total


def _legacy_comparison_status(
    comparisons: list[dict[str, Any]], search_cases: list[dict[str, Any]]
) -> str:
    """Require both backends to return every expected frozen-search path."""
    expected = {
        case["id"]: set(case["expected_paths"])
        for case in search_cases
        if isinstance(case.get("id"), str) and isinstance(case.get("expected_paths"), list)
    }
    if (
        not comparisons
        or not expected
        or {item.get("id") for item in comparisons} != set(expected)
    ):
        return "failed"
    for item in comparisons:
        want = expected[item["id"]]
        legacy_paths = item.get("legacy_paths")
        v3_paths = item.get("v3_paths")
        if not isinstance(legacy_paths, list) or not isinstance(v3_paths, list):
            return "failed"
        if not want.issubset(v3_paths):
            return "failed"
        if not legacy_paths or not all(isinstance(path, str) and path for path in legacy_paths):
            return "failed"
    return "passed"


def _p95_ms(samples_ns: list[int]) -> float:
    if not samples_ns:
        raise ValueError("migration latency benchmark produced no samples")
    ordered = sorted(samples_ns)
    rank = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[rank] / 1_000_000


def _legacy_hot_context(
    client: Any, root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Deep-validate and decode v2 once; timed samples measure only hot retrieval."""
    state, fresh = legacy.validate(client, root, deep=True)
    manifest = state.get("manifest")
    if not fresh or not isinstance(manifest, dict):
        raise ValueError("legacy hot-query baseline is not fresh")
    values = legacy._mget_batched(client, manifest["chunk_keys"])
    if any(value is None for value in values):
        raise ValueError("legacy hot-query baseline lost a chunk")
    graphs = legacy._load_manifest_graphs(client, manifest, root)
    prepared = []
    try:
        for raw in values:
            chunk = legacy._json_load(raw)
            prepared.append(
                {
                    "path": chunk["path"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                    "vector": legacy.decode_vector(chunk["vector"]),
                    "tokens": frozenset(chunk["tokens"]),
                }
            )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("legacy hot-query baseline contains a malformed chunk") from exc
    return manifest, prepared, graphs


def _legacy_hot_search(
    context: tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]],
    query: str,
    limit: int,
) -> dict[str, Any]:
    """Run the v2 scorer over a prevalidated in-process hot snapshot."""
    _bounded_query_tokens(query, "migration hot-query")
    _, chunks, graphs = context
    query_vector = legacy.embedding(query)
    query_tokens = set(legacy.tokenize(query))
    normalized = query.strip().lower()
    symbols_by_path = {path: graph.get("symbols", []) for path, graph in graphs.items()}
    results = []
    for chunk in chunks:
        cosine = sum(a * b for a, b in zip(query_vector, chunk["vector"], strict=True))
        lexical = len(query_tokens & chunk["tokens"]) / len(query_tokens) if query_tokens else 0.0
        matching_symbols = [
            symbol
            for symbol in symbols_by_path.get(chunk["path"], [])
            if symbol["start_line"] <= chunk["end_line"]
            and symbol["end_line"] >= chunk["start_line"]
            and (
                symbol["name"].lower() == normalized
                or symbol["qualified_name"].lower() == normalized
                or symbol["name"].lower() in query_tokens
            )
        ]
        score = 0.72 * cosine + 0.18 * lexical + (0.2 if matching_symbols else 0.0)
        results.append(
            {
                "path": chunk["path"],
                "start_line": chunk["start_line"],
                "end_line": chunk["end_line"],
                "score": round(score, 6),
            }
        )
    results.sort(key=lambda item: (-item["score"], item["path"], item["start_line"]))
    return {"query": query, "fresh": True, "results": results[:limit]}


def migration_shadow(client: Any, root: Path = legacy.ROOT, *, limit: int = 5) -> dict[str, Any]:
    """Build v3 beside a byte-stable v2 and enforce equal-corpus promotion gates."""
    client.require_trusted_write_endpoint()
    legacy_keys_before = _legacy_active_keys(client, root)
    legacy_digest_before = _string_snapshot_digest(client, legacy_keys_before)
    index_builds = [build_index(client, root)]
    while len(
        [item for item in _registry(client, root, required=True)["generations"]
         if item["state"] == "complete"]
    ) < GENERATION_RETENTION:
        index_builds.append(build_index(client, root))
    indexed = index_builds[-1]
    legacy_keys_after = _legacy_active_keys(client, root)
    legacy_digest_after = _string_snapshot_digest(client, legacy_keys_after)
    v2_unchanged = (
        legacy_keys_before == legacy_keys_after
        and legacy_digest_before == legacy_digest_after
    )
    if not v2_unchanged:
        raise ValueError("v3 migration modified the preserved v2.4 baseline")

    v3_state, v3_fresh = status(client, root)
    legacy_state, legacy_fresh = legacy.status(client, root)
    v3_manifest = _load_manifest(client, _active_manifest_key(client, root), root)
    legacy_manifest = legacy_state.get("manifest")
    equal_corpus = bool(
        v3_fresh
        and legacy_fresh
        and isinstance(v3_manifest, dict)
        and isinstance(legacy_manifest, dict)
        and v3_manifest["files"] == legacy_manifest.get("files")
        and v3_manifest["file_hashes"] == legacy_manifest.get("file_hashes")
    )
    if not equal_corpus:
        raise ValueError("v2.4 and v3 migration measurements are not over the same corpus")

    v3_evaluation = evaluate(client, limit, root)
    comparisons = []
    search_cases = [case for case in _evaluation_cases(root) if case["mode"] == "search"]
    if not search_cases:
        raise ValueError("migration latency gate requires frozen search cases")
    benchmark_snapshot = source_snapshot(root)
    benchmark_manager, benchmark_manifest, _ = _fresh_context(
        client, root, snapshot=benchmark_snapshot
    )
    legacy_samples: list[int] = []
    v3_samples: list[int] = []
    try:

        def legacy_lookup(case: dict[str, Any]) -> dict[str, Any]:
            return legacy.search(
                client, case["query"], case.get("limit", limit), root
            )

        def v3_lookup(case: dict[str, Any]) -> dict[str, Any]:
            return search(
                client,
                case["query"],
                case.get("limit", limit),
                root,
                _snapshot=benchmark_snapshot,
                _manifest=benchmark_manifest,
            )

        for case in search_cases:
            old = legacy_lookup(case)
            new = v3_lookup(case)
            comparisons.append(
                {
                    "id": case.get("id"),
                    "legacy_paths": [item["path"] for item in old["results"]],
                    "v3_paths": [item["path"] for item in new["results"]],
                }
            )

        # Warm both prevalidated paths before alternating order to reduce bias.
        legacy_lookup(search_cases[0])
        v3_lookup(search_cases[0])
        for run in range(MIGRATION_LATENCY_RUNS):
            for position, case in enumerate(search_cases):
                ordered = (
                    ((legacy_lookup, legacy_samples), (v3_lookup, v3_samples))
                    if (run + position) % 2 == 0
                    else ((v3_lookup, v3_samples), (legacy_lookup, legacy_samples))
                )
                for lookup, samples in ordered:
                    started = time.perf_counter_ns()
                    lookup(case)
                    samples.append(time.perf_counter_ns() - started)
    finally:
        benchmark_manager.__exit__(None, None, None)
    if source_snapshot(root).fingerprint != benchmark_snapshot.fingerprint:
        raise ValueError("repository changed during migration benchmark")

    v2_bytes = _redis_memory_bytes(client, legacy_keys_after)
    v3_keys = _v3_owned_keys(client, root)
    retained_generation_count = len(
        [
            item
            for item in _registry(client, root, required=True)["generations"]
            if item["state"] == "complete"
        ]
    )
    v3_bytes = _redis_memory_bytes(client, v3_keys)
    size_ratio = v3_bytes / v2_bytes
    legacy_p95 = _p95_ms(legacy_samples)
    v3_p95 = _p95_ms(v3_samples)
    latency_ratio = v3_p95 / legacy_p95 if legacy_p95 else math.inf
    size_passed = size_ratio <= MIGRATION_SIZE_RATIO_MAX
    latency_passed = latency_ratio <= MIGRATION_P95_RATIO_MAX
    legacy_comparison = _legacy_comparison_status(comparisons, search_cases)
    passed = (
        v2_unchanged
        and equal_corpus
        and v3_evaluation["status"] == "passed"
        and size_passed
        and latency_passed
        and legacy_comparison == "passed"
    )
    return {
        "status": "passed" if passed else "failed",
        "mode": "shadow",
        "legacy_namespace": legacy.namespace(root),
        "legacy_present": True,
        "v3_namespace": namespace(root),
        "v2_modified": not v2_unchanged,
        "equal_corpus": equal_corpus,
        "index": indexed,
        "retention_fill_builds": len(index_builds),
        "configured_generation_retention": GENERATION_RETENTION,
        "retained_generations_measured": retained_generation_count,
        "evaluation": v3_evaluation,
        "legacy_comparison": legacy_comparison,
        "comparisons": comparisons,
        "size_gate": {
            "v2_active_bytes": v2_bytes,
            "v3_total_retained_bytes": v3_bytes,
            "scope": "all registry-owned complete generations; transient lock and leases excluded",
            "ratio": size_ratio,
            "maximum": MIGRATION_SIZE_RATIO_MAX,
            "passed": size_passed,
        },
        "latency_gate": {
            "boundary": "shipped search() on both backends over the same deep-validated corpus",
            "samples_per_backend": len(legacy_samples),
            "runs": MIGRATION_LATENCY_RUNS,
            "v2_p95_ms": legacy_p95,
            "v3_p95_ms": v3_p95,
            "ratio": latency_ratio,
            "maximum": MIGRATION_P95_RATIO_MAX,
            "passed": latency_passed,
        },
    }


def clear(client: Any, root: Path = legacy.ROOT) -> dict[str, Any]:
    """Clear only the v3 disposable cache; never open or alter the durable ledger."""
    client.require_trusted_write_endpoint()
    with _writer_lock(client, root) as owner:
        prefix = namespace(root)
        registry = _registry(client, root, required=True)
        active_key = f"{prefix}:active-generation"
        keys = {f"{prefix}:registry", active_key}
        lease_keys: list[str] = []
        complete_manifests: set[str] = set()
        for item in registry.get("generations", []):
            if not isinstance(item, dict):
                raise ValueError("Palimnex v3 registry contains a malformed generation")
            manifest_key = item.get("manifest_key")
            if not isinstance(manifest_key, str):
                raise ValueError("Palimnex v3 registry contains an invalid manifest key")
            lease_key = _reader_lease_key(root, manifest_key)
            lease_keys.append(lease_key)
            if item.get("state") == "complete":
                complete_manifests.add(manifest_key)
            manifest = _load_manifest(client, manifest_key, root)
            keys.add(manifest_key)
            if manifest:
                keys.update(manifest["chunk_keys"])
                keys.update(manifest["file_graphs"].values())
                keys.add(manifest["posting_hash_key"])
            else:
                for field in ("chunk_keys", "graph_keys", "posting_keys"):
                    values = item.get(field, [])
                    if not isinstance(values, list) or not all(
                        isinstance(key, str) and key.startswith(prefix + ":") for key in values
                    ):
                        raise ValueError("Palimnex v3 registry cannot prove cache ownership")
                    keys.update(values)

        active_raw = client.execute("GET", active_key)
        try:
            active_manifest = (
                active_raw.decode("utf-8") if isinstance(active_raw, bytes) else active_raw
            )
        except UnicodeError as exc:
            raise ValueError("Palimnex v3 active generation is not UTF-8") from exc
        if active_manifest is not None and (
            not isinstance(active_manifest, str)
            or active_manifest not in complete_manifests
        ):
            raise ValueError("Palimnex v3 active generation is not a complete registered generation")

        # Atomically remove the only reader admission pointer while holding the
        # writer fence. A reader either leased before this delete (and is seen
        # below) or observes no active generation; it cannot enter between the
        # final lease check and deletion.
        detached_deleted = _fenced_delete(client, root, owner, [active_key])
        try:
            if any(int(client.execute("GET", lease_key) or 0) > 0 for lease_key in lease_keys):
                raise ValueError(
                    "Palimnex v3 cache has active readers and cannot be cleared"
                )
        except (TypeError, ValueError):
            if active_manifest is not None:
                _fenced_set(client, root, owner, active_key, active_manifest)
            raise
        deleted = detached_deleted
        ordered = sorted(keys)
        for start in range(0, len(ordered), 1_000):
            deleted += _fenced_delete(client, root, owner, ordered[start : start + 1_000])
        if any(client.execute("GET", key) is not None for key in ordered):
            raise ValueError("Palimnex v3 clear could not verify registered-key removal")
    return {
        "status": "cleared",
        "namespace": namespace(root),
        "deleted_keys": deleted,
        "verified_registered_keys_empty": True,
        "durable_ledger_touched": False,
        "legacy_namespace_touched": False,
    }
