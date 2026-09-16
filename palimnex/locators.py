"""Version 1 source references and explicitly registered, bounded resolvers."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .security import read_bounded_file, scan_bytes, scan_text

LOCATOR_SCHEMA = "palimnex:source-locator:v1"
LOCATOR_PREFIX = LOCATOR_SCHEMA + ":"
MAX_SOURCE_BYTES = 1_000_000


@dataclass(frozen=True)
class SourceRange:
    """Inclusive one-based lines, or half-open zero-based byte offsets."""
    unit: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.unit not in {"lines", "bytes"}:
            raise ValueError("unsupported source range unit")
        lower = 1 if self.unit == "lines" else 0
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("source range requires integer bounds")
        if not lower <= self.start <= self.end <= MAX_SOURCE_BYTES:
            raise ValueError("invalid source range bounds")


@dataclass(frozen=True)
class SourceLocator:
    scheme: str
    source_id: str
    version: str
    range: SourceRange
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.scheme, str) or not re.fullmatch(r"[a-z][a-z0-9+.-]{0,31}", self.scheme):
            raise ValueError("invalid source scheme")
        for value in (self.source_id, self.version):
            if not isinstance(value, str) or not value or len(value.encode()) > 2048:
                raise ValueError("invalid source identity or version")
            if any(ord(c) < 32 for c in value) or scan_text(value):
                raise ValueError("unsafe source identity or version")
        if not isinstance(self.range, SourceRange):
            raise ValueError("source range is required")
        if not isinstance(self.digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("source digest must be lowercase SHA-256")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def encode(self) -> str:
        return LOCATOR_PREFIX + json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SourceLocator:
        if not isinstance(value, dict) or set(value) != {"scheme", "source_id", "version", "range", "digest"}:
            raise ValueError("invalid source locator fields")
        bounds = value["range"]
        if not isinstance(bounds, dict) or set(bounds) != {"unit", "start", "end"}:
            raise ValueError("invalid source range fields")
        return cls(value["scheme"], value["source_id"], value["version"], SourceRange(**bounds), value["digest"])

    @classmethod
    def decode(cls, value: str) -> SourceLocator:
        if not value.startswith(LOCATOR_PREFIX) or len(value.encode()) > 8192:
            raise ValueError("invalid encoded source locator")
        locator = cls.from_dict(json.loads(value[len(LOCATOR_PREFIX):]))
        if locator.encode() != value:
            raise ValueError("source locator must be canonical")
        return locator


@dataclass(frozen=True)
class ResolvedSource:
    content: bytes
    version: str


@runtime_checkable
class SourceResolver(Protocol):
    """Return the complete versioned object; caller applies and verifies range."""
    api_version: int

    def resolve(self, source_id: str, version: str) -> ResolvedSource: ...


class RepositoryResolver:
    api_version = 1

    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, source_id: str, version: str) -> ResolvedSource:
        relative = Path(source_id)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("repository source must be relative")
        raw = read_bounded_file(self.root, relative, max_bytes=MAX_SOURCE_BYTES)
        return ResolvedSource(raw, hashlib.sha256(raw).hexdigest())


def select_range(raw: bytes, bounds: SourceRange) -> bytes:
    if not isinstance(raw, bytes) or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds byte limit")
    if scan_bytes(raw):
        raise ValueError("source privacy admission refused")
    if bounds.unit == "bytes":
        if bounds.end > len(raw):
            raise ValueError("source range outside object")
        return raw[bounds.start:bounds.end]
    lines = raw.decode("utf-8", errors="strict").splitlines()
    if bounds.end > len(lines):
        raise ValueError("source range outside object")
    return "\n".join(lines[bounds.start - 1:bounds.end]).encode()


def resolve_locator(locator: SourceLocator, root: Path,
                    resolvers: Mapping[str, SourceResolver]) -> bytes:
    resolver = RepositoryResolver(root) if locator.scheme == "repo" else resolvers.get(locator.scheme)
    try:
        if resolver is None or resolver.api_version != 1:
            raise ValueError("source resolver not registered or incompatible")
        source = resolver.resolve(locator.source_id, locator.version)
        if not isinstance(source, ResolvedSource) or source.version != locator.version:
            raise ValueError("source version changed")
        raw = select_range(source.content, locator.range)
        if hashlib.sha256(raw).hexdigest() != locator.digest:
            raise ValueError("source digest changed")
        return raw
    except Exception:
        # Provider exceptions may contain URLs, credentials or raw records.
        raise ValueError("source unavailable or version/digest mismatch") from None


def repository_locator(root: Path, legacy: str) -> SourceLocator:
    match = re.fullmatch(r"([^:]+):(\d+)(?:-(\d+))?", legacy)
    if match is None:
        raise ValueError("expected path:start or path:start-end")
    path, first, last = match.groups()
    source = RepositoryResolver(root).resolve(path, "current")
    bounds = SourceRange("lines", int(first), int(last or first))
    return SourceLocator("repo", path, source.version, bounds,
                         hashlib.sha256(select_range(source.content, bounds)).hexdigest())
