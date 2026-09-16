"""Content privacy admission and credential-finding policy digest controls.

The scanner reports only rule identifiers and line numbers.  It deliberately
never returns the matched value: diagnostics must not become a second copy of
a credential.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAX_SCAN_BYTES = 1_000_000
SCANNER_VERSION = "content-privacy:v2"
ENTROPY_THRESHOLD = 3.5


@dataclass(frozen=True)
class ContentFinding:
    rule: str
    line: int


class _JsonObjectPairs(list[tuple[str, object]]):
    """Distinct JSON object representation that preserves duplicate keys."""


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key-pem",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github-token",
        re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9_]{20,}\b"),
    ),
    (
        "openai-token",
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "bitcoin-wif",
        re.compile(r"(?<![A-Za-z0-9])[59KLc][1-9A-HJ-NP-Za-km-z]{50,51}(?![A-Za-z0-9])"),
    ),
    (
        "private-key-pem-variant",
        re.compile(r"-----BEGIN (?:ENCRYPTED |DSA )PRIVATE KEY-----"),
    ),
)

_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*(?:export\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\s*(?:=|:)\s*[\"']?(?P<value>[^\s\"'#][^\r\n#]{7,})"
)
_SENSITIVE_ASSIGNMENT_NAME_RE = re.compile(
    r"(?:^|[_.-])(?:secret|token|password|passwd|private[_-]?key|"
    r"api[_-]?keys?|access[_-]?keys?|credentials?|mnemonic|seed)(?:$|[_.-])",
    re.IGNORECASE,
)
_JSON_STRING_ASSIGNMENT_RE = re.compile(
    r'(?P<name>"(?:\\.|[^"\\])*")\s*:\s*'
    r'(?P<value>"(?:\\.|[^"\\])*")'
)
_HEX_PRIVATE_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")
_MNEMONIC_RE = re.compile(r"^(?:[a-z]+\s+){11,23}[a-z]+$")
_OPAQUE_CREDENTIAL_RE = re.compile(r"[A-Za-z0-9_./+=:@-]{20,}")
_PLACEHOLDERS = {
    "changeme",
    "example",
    "example-only",
    "none",
    "null",
    "placeholder",
    "redacted",
    "test",
    "unset",
}
_PLACEHOLDER_PREFIXES = (
    "dummy-",
    "dummy_",
    "example-",
    "example_",
    "fake-",
    "fake_",
    "placeholder-",
    "placeholder_",
    "redacted-",
    "redacted_",
    "test-",
    "test_",
)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {character: value.count(character) for character in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    return (
        not normalized
        or normalized in _PLACEHOLDERS
        or normalized.startswith(_PLACEHOLDER_PREFIXES)
        or normalized.startswith(("${", "<", "your_", "your-"))
        or normalized.endswith(("_here", "-here"))
    )


def _normalized_assignment_name(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _credential_assignment_rule(name: str, value: str) -> str | None:
    value = value.strip().strip("\"'")
    if _looks_like_placeholder(value):
        return None
    lowered_name = _normalized_assignment_name(name)
    if _SENSITIVE_ASSIGNMENT_NAME_RE.search(lowered_name) is None:
        return None
    if "mnemonic" in lowered_name or lowered_name.endswith("seed"):
        if _MNEMONIC_RE.fullmatch(value.lower()):
            return "mnemonic-assignment"
    elif "private" in lowered_name and _HEX_PRIVATE_RE.fullmatch(value):
        return "private-key-assignment"
    elif _OPAQUE_CREDENTIAL_RE.fullmatch(value) and _entropy(value) >= ENTROPY_THRESHOLD:
        return "high-entropy-credential-assignment"
    return None


def _structured_json_findings(text: str) -> set[ContentFinding]:
    """Inspect JSON keys without exposing values or relying on line layout."""
    findings: set[ContentFinding] = set()

    # Preserve coverage of duplicate object keys: json.loads keeps only the
    # last value, while every encoded credential must be rejected.
    for match in _JSON_STRING_ASSIGNMENT_RE.finditer(text):
        try:
            name = json.loads(match.group("name"))
            value = json.loads(match.group("value"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(name, str) and isinstance(value, str):
            rule = _credential_assignment_rule(name, value)
            if rule:
                findings.add(ContentFinding(rule, _line_number(text, match.start())))

    try:
        document = json.loads(text, object_pairs_hook=_JsonObjectPairs)
    except RecursionError:
        # A syntactically JSON-shaped document can exceed CPython's decoder
        # recursion limit before the iterative value walk below gets a chance
        # to inspect sensitive list values.  Admission must fail closed: a
        # regex-only fallback would let deeply nested credentials through.
        # Report only a rule identifier, never any part of the document.
        findings.add(ContentFinding("json-structure-too-deep", 1))
        return findings
    except json.JSONDecodeError:
        return findings

    # The iterative walk also covers credentials nested below a sensitive key
    # and list-valued mnemonic/seed material without recursion-depth risk.
    stack: list[tuple[str, object, int]] = [("", document, 1)]
    while stack:
        parent_name, value, inherited_line = stack.pop()
        if isinstance(value, _JsonObjectPairs):
            for name, child in value:
                if not isinstance(name, str):
                    continue
                qualified = f"{parent_name}.{name}" if parent_name else name
                encoded_name = json.dumps(name, ensure_ascii=False)
                offset = text.find(encoded_name)
                line = _line_number(text, offset) if offset >= 0 else inherited_line
                stack.append((qualified, child, line))
        elif isinstance(value, list):
            if value and all(isinstance(item, str) for item in value):
                joined = " ".join(value)
                rule = _credential_assignment_rule(parent_name, joined)
                if rule:
                    findings.add(ContentFinding(rule, inherited_line))
            for child in value:
                stack.append((parent_name, child, inherited_line))
        elif isinstance(value, str):
            rule = _credential_assignment_rule(parent_name, value)
            if rule:
                findings.add(ContentFinding(rule, inherited_line))
    return findings


def scan_text(text: str) -> list[ContentFinding]:
    """Return deterministic credential-shaped findings without secret values."""
    findings: set[ContentFinding] = set()
    for rule, pattern in _RULES:
        for match in pattern.finditer(text):
            findings.add(ContentFinding(rule, _line_number(text, match.start())))

    for match in _ASSIGNMENT_RE.finditer(text):
        rule = _credential_assignment_rule(match.group("name"), match.group("value"))
        if rule:
            findings.add(ContentFinding(rule, _line_number(text, match.start())))

    findings.update(_structured_json_findings(text))

    return sorted(findings, key=lambda item: (item.line, item.rule))


def scan_bytes(
    raw: bytes,
    *,
    allowed_sha256: Iterable[str] = (),
) -> list[ContentFinding]:
    """Scan the exact UTF-8 bytes that a caller will stage or persist."""
    if len(raw) > MAX_SCAN_BYTES:
        return [ContentFinding("content-too-large", 1)]
    digest = hashlib.sha256(raw).hexdigest()
    if digest in set(allowed_sha256):
        return []
    return scan_text(raw.decode("utf-8", errors="strict"))


def scan_file(
    path: Path,
    *,
    allowed_sha256: Iterable[str] = (),
) -> list[ContentFinding]:
    """Convenience wrapper; staging code must instead scan its already-read bytes."""
    return scan_bytes(path.read_bytes(), allowed_sha256=allowed_sha256)


def read_bounded_file(root: Path, relative: str | Path, *, max_bytes: int) -> bytes:
    """Read one regular file beneath root without following any path symlink."""
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
        or max_bytes < 0
    ):
        raise ValueError("bounded source path must be a normalized repository-relative path")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        current = os.open(root.resolve(strict=True), directory_flags)
        descriptors.append(current)
        for component in relative_path.parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        descriptor = os.open(relative_path.parts[-1], file_flags, dir_fd=current)
        descriptors.append(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise ValueError("bounded source is not a regular file within the size limit")
        chunks = []
        remaining = max_bytes + 1
        while remaining:
            block = os.read(descriptor, min(65_536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        raw = b"".join(chunks)
        final_metadata = os.fstat(descriptor)
        if (
            len(raw) > max_bytes
            or final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
            or final_metadata.st_size != len(raw)
        ):
            raise ValueError("bounded source changed or grew while it was read")
        return raw
    except OSError as exc:
        raise ValueError("bounded source could not be opened without following symlinks") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def policy_digest() -> str:
    """Identify the scanner policy recorded in each cache generation and pack."""
    values = [
        SCANNER_VERSION,
        f"max_scan_bytes={MAX_SCAN_BYTES}",
        f"entropy_threshold={ENTROPY_THRESHOLD}",
        "placeholders=" + ",".join(sorted(_PLACEHOLDERS)),
        "placeholder_prefixes=" + ",".join(_PLACEHOLDER_PREFIXES),
    ]
    values.extend(
        f"rule={name};flags={pattern.flags};pattern={pattern.pattern}"
        for name, pattern in _RULES
    )
    values.extend(
        (
            f"assignment;flags={_ASSIGNMENT_RE.flags};pattern={_ASSIGNMENT_RE.pattern}",
            "assignment-name;flags="
            f"{_SENSITIVE_ASSIGNMENT_NAME_RE.flags};pattern={_SENSITIVE_ASSIGNMENT_NAME_RE.pattern}",
            "assignment-name-normalization=camel-boundary-to-underscore:v1",
            "json-string-assignment;flags="
            f"{_JSON_STRING_ASSIGNMENT_RE.flags};pattern={_JSON_STRING_ASSIGNMENT_RE.pattern}",
            "structured-json-walk=iterative-duplicate-pairs-sensitive-path-string-list-fail-closed-depth:v2",
            f"hex-private;flags={_HEX_PRIVATE_RE.flags};pattern={_HEX_PRIVATE_RE.pattern}",
            f"mnemonic;flags={_MNEMONIC_RE.flags};pattern={_MNEMONIC_RE.pattern}",
            "opaque-credential;flags="
            f"{_OPAQUE_CREDENTIAL_RE.flags};pattern={_OPAQUE_CREDENTIAL_RE.pattern}",
        )
    )
    material = "\n".join(values)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
