"""Deterministic structure extraction for Markdown and generic text/config files."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse


DOCUMENT_EXTRACTOR_ID = "document-structure:v2"
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
FILE_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:\.?[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)(?![A-Za-z0-9_.-])"
)
COMMIT_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{7,40})(?![0-9a-f])")
CONFIG_KEY_RE = re.compile(r"^\s*[\"']?([A-Za-z_][A-Za-z0-9_.-]*)[\"']?\s*(?:=|:)\s*")
EXPLICIT_RELATION_RE = re.compile(
    r"^\s*(Status|Decision|Supersedes|Contradicts|Evidence|Rollback)\s*:\s*(.+)$",
    re.IGNORECASE,
)
FENCE_RE = re.compile(r"^\s*(```+|~~~+)(.*)$")


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9 _-]", "", value.lower()).strip()
    return re.sub(r"[ _]+", "-", value)


def _document_name(path: str) -> str:
    return f"document:{path}"


def _edge(
    *,
    source_id: str,
    target: str,
    kind: str,
    path: str,
    line: int,
    parser: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "target": target,
        "kind": kind,
        "path": path,
        "line": line,
        "parser": parser,
        "extraction_confidence": "authoritative",
        "binding_applied": False,
        "resolution": {
            "status": "unresolved",
            "confidence": "unknown",
            "target_id": None,
        },
    }


def _symbol(
    path: str,
    name: str,
    qualified: str,
    kind: str,
    start: int,
    end: int,
    parser: str,
    symbol_id: Callable[[str, str, str, int], str],
) -> dict[str, Any]:
    return {
        "id": symbol_id(path, qualified, kind, start),
        "name": name,
        "qualified_name": qualified,
        "kind": kind,
        "path": path,
        "start_line": start,
        "end_line": end,
        "parser": parser,
        "confidence": "authoritative",
    }


def _internal_link_target(
    path: str, target: str, known_paths: frozenset[str]
) -> str | None:
    parsed = urlparse(target)
    if parsed.scheme or target.startswith(("//", "mailto:")):
        return None
    file_part, _, anchor = target.partition("#")
    if file_part:
        root_candidate = posixpath.normpath(file_part.removeprefix("./"))
        if root_candidate in known_paths:
            normalized = root_candidate
        else:
            base = str(PurePosixPath(path).parent)
            normalized = posixpath.normpath(posixpath.join(base, file_part))
    else:
        normalized = path
    qualified = _document_name(normalized)
    return f"{qualified}#{_slug(anchor)}" if anchor else qualified


def _reference_edges(
    path: str,
    line_text: str,
    line: int,
    source_id: str,
    parser: str,
    known_paths: frozenset[str],
) -> list[dict[str, Any]]:
    edges = []
    for match in MARKDOWN_LINK_RE.finditer(line_text):
        target = match.group(1).strip("<>")
        internal = _internal_link_target(path, target, known_paths)
        edges.append(
            _edge(
                source_id=source_id,
                target=internal or target,
                kind="links_to" if internal else "links_external",
                path=path,
                line=line,
                parser=parser,
            )
        )
    linked = {match.group(1).split("#", 1)[0] for match in MARKDOWN_LINK_RE.finditer(line_text)}
    for match in FILE_REFERENCE_RE.finditer(line_text):
        target = match.group(1).rstrip(".,;:)")
        if target in linked:
            continue
        internal = _internal_link_target(path, target, known_paths)
        if internal:
            edges.append(
                _edge(
                    source_id=source_id,
                    target=internal,
                    kind="references_file",
                    path=path,
                    line=line,
                    parser=parser,
                )
            )
    return edges


def markdown_graph(
    path: str,
    text: str,
    *,
    schema: str,
    symbol_id: Callable[[str, str, str, int], str],
    known_paths: frozenset[str],
) -> dict[str, Any]:
    parser = DOCUMENT_EXTRACTOR_ID
    lines = text.splitlines()
    end = max(1, len(lines))
    root = _symbol(
        path, PurePosixPath(path).name, _document_name(path), "document", 1, end, parser, symbol_id
    )
    symbols = [root]
    edges = []
    heading_stack: list[tuple[int, dict[str, Any]]] = []
    current = root
    fence: tuple[str, int, str] | None = None
    table_start: int | None = None
    table_owner: dict[str, Any] | None = None
    used_anchors: dict[str, int] = {}

    for line_number, line_text in enumerate(lines, 1):
        fence_match = FENCE_RE.match(line_text)
        if fence_match:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = (marker, line_number, fence_match.group(2).strip() or "plain")
            elif fence[0] == marker:
                _, start, language = fence
                qualified = f"{_document_name(path)}#code-{start}"
                item = _symbol(path, language, qualified, "code_fence", start, line_number, parser, symbol_id)
                symbols.append(item)
                edges.append(
                    _edge(
                        source_id=current["id"], target=qualified, kind="contains", path=path,
                        line=start, parser=parser,
                    )
                )
                fence = None
            continue
        if fence is not None:
            continue

        heading = MARKDOWN_HEADING_RE.match(line_text)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            anchor = _slug(title) or f"heading-{line_number}"
            used_anchors[anchor] = used_anchors.get(anchor, 0) + 1
            if used_anchors[anchor] > 1:
                anchor = f"{anchor}-{used_anchors[anchor]}"
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent = heading_stack[-1][1] if heading_stack else root
            qualified = f"{_document_name(path)}#{anchor}"
            current = _symbol(path, title, qualified, "heading", line_number, end, parser, symbol_id)
            symbols.append(current)
            edges.append(
                _edge(
                    source_id=parent["id"], target=qualified, kind="contains", path=path,
                    line=line_number, parser=parser,
                )
            )
            heading_stack.append((level, current))

        is_table = line_text.lstrip().startswith("|") and line_text.count("|") >= 2
        if is_table and table_start is None:
            table_start = line_number
            table_owner = current
        if not is_table and table_start is not None:
            qualified = f"{_document_name(path)}#table-{table_start}"
            item = _symbol(path, f"table-{table_start}", qualified, "table", table_start, line_number - 1, parser, symbol_id)
            symbols.append(item)
            edges.append(
                _edge(
                    source_id=table_owner["id"], target=qualified, kind="contains", path=path,
                    line=table_start, parser=parser,
                )
            )
            table_start = None
            table_owner = None

        relation = EXPLICIT_RELATION_RE.match(line_text)
        if relation:
            label = relation.group(1).lower()
            value = relation.group(2).strip()
            qualified = f"{_document_name(path)}#{label}-{line_number}"
            item = _symbol(path, label, qualified, label, line_number, line_number, parser, symbol_id)
            symbols.append(item)
            edges.append(
                _edge(
                    source_id=current["id"], target=qualified, kind="documents", path=path,
                    line=line_number, parser=parser,
                )
            )
            relation_kind = {
                "supersedes": "supersedes",
                "contradicts": "contradicts",
                "evidence": "evidence",
                "rollback": "rollback_for",
            }.get(label, "documents")
            for reference in FILE_REFERENCE_RE.findall(value):
                target = _internal_link_target(path, reference, known_paths)
                if target:
                    edges.append(
                        _edge(
                            source_id=item["id"], target=target, kind=relation_kind, path=path,
                            line=line_number, parser=parser,
                        )
                    )
        edges.extend(
            _reference_edges(
                path, line_text, line_number, current["id"], parser, known_paths
            )
        )

        for commit in dict.fromkeys(COMMIT_RE.findall(line_text)):
            qualified = f"{_document_name(path)}#commit-{commit}-{line_number}"
            item = _symbol(path, commit, qualified, "commit_reference", line_number, line_number, parser, symbol_id)
            symbols.append(item)
            edges.append(
                _edge(
                    source_id=current["id"], target=qualified, kind="evidence", path=path,
                    line=line_number, parser=parser,
                )
            )

    if table_start is not None:
        assert table_owner is not None
        qualified = f"{_document_name(path)}#table-{table_start}"
        item = _symbol(path, f"table-{table_start}", qualified, "table", table_start, end, parser, symbol_id)
        symbols.append(item)
        edges.append(
            _edge(
                source_id=table_owner["id"], target=qualified, kind="contains", path=path,
                line=table_start, parser=parser,
            )
        )
    if fence is not None:
        return {
            "schema": schema,
            "language": "markdown",
            "parser": parser,
            "symbols": symbols,
            "edges": edges,
            "diagnostics": [f"unterminated code fence at line {fence[1]}"],
        }
    return {
        "schema": schema,
        "language": "markdown",
        "parser": parser,
        "symbols": symbols,
        "edges": edges,
        "diagnostics": [],
    }


def generic_graph(
    path: str,
    text: str,
    *,
    schema: str,
    symbol_id: Callable[[str, str, str, int], str],
    known_paths: frozenset[str],
) -> dict[str, Any]:
    parser = DOCUMENT_EXTRACTOR_ID
    lines = text.splitlines()
    end = max(1, len(lines))
    root = _symbol(
        path, PurePosixPath(path).name, _document_name(path), "document", 1, end, parser, symbol_id
    )
    symbols = [root]
    edges = []
    seen_keys: dict[str, int] = {}
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for position, key in enumerate(parsed, 1):
                name = str(key)
                qualified = f"{_document_name(path)}#key-{_slug(name) or position}"
                item = _symbol(path, name, qualified, "config_key", 1, 1, parser, symbol_id)
                symbols.append(item)
                edges.append(
                    _edge(
                        source_id=root["id"], target=qualified, kind="contains", path=path,
                        line=1, parser=parser,
                    )
                )
    for line_number, line_text in enumerate(lines, 1):
        key_match = CONFIG_KEY_RE.match(line_text)
        if key_match:
            name = key_match.group(1)
            seen_keys[name] = seen_keys.get(name, 0) + 1
            qualified = f"{_document_name(path)}#key-{_slug(name)}-{seen_keys[name]}"
            item = _symbol(path, name, qualified, "config_key", line_number, line_number, parser, symbol_id)
            symbols.append(item)
            edges.append(
                _edge(
                    source_id=root["id"], target=qualified, kind="contains", path=path,
                    line=line_number, parser=parser,
                )
            )
        edges.extend(
            _reference_edges(
                path, line_text, line_number, root["id"], parser, known_paths
            )
        )
    return {
        "schema": schema,
        "language": "config" if symbols[1:] else "text",
        "parser": parser,
        "symbols": symbols,
        "edges": edges,
        "diagnostics": [],
    }


def extract_document_graph(
    path: str,
    text: str,
    *,
    schema: str,
    symbol_id: Callable[[str, str, str, int], str],
    known_paths: frozenset[str] | None = None,
) -> dict[str, Any]:
    corpus_paths = frozenset({path}) if known_paths is None else known_paths
    if PurePosixPath(path).suffix.lower() in {".md", ".markdown", ".rst"}:
        return markdown_graph(
            path,
            text,
            schema=schema,
            symbol_id=symbol_id,
            known_paths=corpus_paths,
        )
    return generic_graph(
        path,
        text,
        schema=schema,
        symbol_id=symbol_id,
        known_paths=corpus_paths,
    )
