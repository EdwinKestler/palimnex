"""Reviewed, source-bound retrieval feedback stored as non-authorizing history.

Feedback records are explicit manual judgements.  This module deliberately has
no import path into retrieval and never gives feedback ranking influence.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from . import cache_v3, core, durable
from .durable import MemoryLedger
from .security import scan_text


FEEDBACK_SCHEMA = "palimnex:retrieval-feedback:v1"
WITHDRAWAL_SCHEMA = "palimnex:retrieval-feedback-withdrawal:v1"
REPORT_SCHEMA = "palimnex:retrieval-feedback-report:v1"
JUDGEMENTS = ("answers", "does_not_answer")
ORIGINS = ("manual", "explain_search", "context")

_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_LOCATOR = re.compile(r"([^:]+):(\d+)(?:-(\d+))?")
_FEEDBACK_FIELDS = {
    "schema",
    "query",
    "query_digest",
    "judgement",
    "source",
    "review",
    "provenance",
    "note",
    "authority",
    "authorizes_actions",
    "retrieval_influence",
}
_SOURCE_FIELDS = {"path", "start_line", "end_line", "content_digest", "file_digest"}
_REVIEW_FIELDS = {"reviewer", "method"}
_PROVENANCE_FIELDS = {"origin"}
_WITHDRAWAL_FIELDS = {
    "schema",
    "withdraws_event_id",
    "review",
    "reason",
    "authority",
    "authorizes_actions",
    "retrieval_influence",
}


class FeedbackError(ValueError):
    """A stable, non-echoing retrieval-feedback refusal."""

    def __init__(self, reason: str, field: str = "feedback") -> None:
        self.reason = reason
        self.field = field
        super().__init__(f"retrieval feedback refused: {reason} at {field}")


def _fail(reason: str, field: str) -> NoReturn:
    raise FeedbackError(reason, field)


def _strict_bytes(value: str, reason: str, field: str) -> bytes:
    try:
        return value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise FeedbackError(reason, field) from exc


def _privacy_check(value: str, reason: str, field: str) -> None:
    try:
        findings = scan_text(value)
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise FeedbackError(reason, field) from exc
    if findings:
        _fail(reason, field)


def normalize_query(query: str) -> str:
    """Return the R9 whitespace-normalized, bounded, privacy-admitted query."""
    if not isinstance(query, str):
        _fail("invalid_type", "query")
    normalized = re.sub(r"\s+", " ", query.strip())
    if not normalized:
        _fail("empty_query", "query")
    encoded = _strict_bytes(normalized, "invalid_utf8", "query")
    if len(encoded) > cache_v3.MAX_QUERY_BYTES:
        _fail("query_byte_bound", "query")
    if len(core.tokenize(normalized)) > cache_v3.MAX_QUERY_TERMS:
        _fail("query_term_bound", "query")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        _fail("query_control", "query")
    _privacy_check(normalized, "query_privacy_refused", "query")
    return normalized


def _validate_reviewer(value: object, field: str = "review.reviewer") -> str:
    if not isinstance(value, str):
        _fail("reviewer_invalid", field)
    _strict_bytes(value, "reviewer_invalid", field)
    if not 1 <= len(value) <= 128 or not all(character.isprintable() for character in value):
        _fail("reviewer_invalid", field)
    _privacy_check(value, "reviewer_privacy_refused", field)
    return value


def _validate_bounded_text(
    value: object,
    *,
    field: str,
    invalid_reason: str,
    bound_reason: str,
    privacy_reason: str,
) -> str:
    if not isinstance(value, str) or not value:
        _fail(invalid_reason, field)
    encoded = _strict_bytes(value, invalid_reason, field)
    if len(encoded) > 1024:
        _fail(bound_reason, field)
    if not all(character == "\n" or character.isprintable() for character in value):
        _fail(invalid_reason, field)
    _privacy_check(value, privacy_reason, field)
    return value


def _validate_note(value: object) -> str | None:
    if value is None:
        return None
    return _validate_bounded_text(
        value,
        field="note",
        invalid_reason="note_invalid",
        bound_reason="note_byte_bound",
        privacy_reason="note_privacy_refused",
    )


def _validate_reason(value: object) -> str:
    return _validate_bounded_text(
        value,
        field="reason",
        invalid_reason="reason_invalid",
        bound_reason="reason_byte_bound",
        privacy_reason="reason_privacy_refused",
    )


def _validate_path(value: object, field: str = "source.path") -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
    ):
        _fail("locator_invalid", field)
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or ".." in path.parts:
        _fail("locator_invalid", field)
    if not all(character.isprintable() for character in value):
        _fail("locator_invalid", field)
    return value


def _parse_locator(locator: object) -> tuple[str, int, int]:
    if not isinstance(locator, str):
        _fail("locator_invalid", "locator")
    match = _LOCATOR.fullmatch(locator)
    if match is None:
        _fail("locator_invalid", "locator")
    path_raw, start_raw, end_raw = match.groups()
    path = _validate_path(path_raw, "locator")
    try:
        start = int(start_raw)
        end = int(end_raw or start_raw)
    except ValueError as exc:
        raise FeedbackError("locator_invalid", "locator") from exc
    if start < 1 or end < start:
        _fail("range_invalid", "locator")
    return path, start, end


def _is_hex(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _validate_review(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != _REVIEW_FIELDS:
        _fail("payload_invalid", "review")
    reviewer = _validate_reviewer(value.get("reviewer"))
    if value.get("method") != "manual":
        _fail("payload_invalid", "review.method")
    return {"reviewer": reviewer, "method": "manual"}


def validate_feedback_payload(value: object) -> dict[str, Any]:
    """Validate and return one canonical v1 feedback payload."""
    if not isinstance(value, dict) or set(value) != _FEEDBACK_FIELDS:
        _fail("payload_invalid", "payload")
    if value.get("schema") != FEEDBACK_SCHEMA:
        _fail("payload_invalid", "schema")
    query_value = value.get("query")
    if not isinstance(query_value, str):
        _fail("invalid_type", "query")
    query = normalize_query(query_value)
    if query != value.get("query"):
        _fail("query_not_normalized", "query")
    query_digest = value.get("query_digest")
    expected_query_digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    if not _is_hex(query_digest, _HEX_64) or query_digest != expected_query_digest:
        _fail("query_digest_mismatch", "query_digest")
    judgement = value.get("judgement")
    if judgement not in JUDGEMENTS:
        _fail("judgement_invalid", "judgement")

    source = value.get("source")
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        _fail("payload_invalid", "source")
    path = _validate_path(source.get("path"))
    start = source.get("start_line")
    end = source.get("end_line")
    if type(start) is not int or type(end) is not int or start < 1 or end < start:
        _fail("range_invalid", "source")
    content_digest = source.get("content_digest")
    file_digest = source.get("file_digest")
    if not _is_hex(content_digest, _HEX_64):
        _fail("digest_invalid", "source.content_digest")
    if not _is_hex(file_digest, _HEX_64):
        _fail("digest_invalid", "source.file_digest")

    review = _validate_review(value.get("review"))
    provenance = value.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != _PROVENANCE_FIELDS:
        _fail("payload_invalid", "provenance")
    origin = provenance.get("origin")
    if origin not in ORIGINS:
        _fail("origin_invalid", "provenance.origin")
    note = _validate_note(value.get("note"))
    if (
        value.get("authority") != "historical_only"
        or value.get("authorizes_actions") is not False
        or value.get("retrieval_influence") is not False
    ):
        _fail("authority_invalid", "authority")
    return {
        "schema": FEEDBACK_SCHEMA,
        "query": query,
        "query_digest": query_digest,
        "judgement": judgement,
        "source": {
            "path": path,
            "start_line": start,
            "end_line": end,
            "content_digest": content_digest,
            "file_digest": file_digest,
        },
        "review": review,
        "provenance": {"origin": origin},
        "note": note,
        "authority": "historical_only",
        "authorizes_actions": False,
        "retrieval_influence": False,
    }


def build_feedback(
    query: str,
    locator: str,
    judgement: str,
    reviewer: str,
    *,
    root: Path,
    note: str | None = None,
    origin: str = "manual",
) -> dict[str, Any]:
    """Build a feedback payload bound to one currently admitted source range."""
    normalized = normalize_query(query)
    if judgement not in JUDGEMENTS:
        _fail("judgement_invalid", "judgement")
    if origin not in ORIGINS:
        _fail("origin_invalid", "origin")
    reviewer_value = _validate_reviewer(reviewer)
    note_value = _validate_note(note)
    path, start, end = _parse_locator(locator)
    try:
        snapshot = cache_v3.source_snapshot(root)
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        raise FeedbackError("source_unavailable", "root") from exc
    source_file = snapshot.by_path.get(path)
    if source_file is None:
        _fail("source_not_admitted", "locator")
    lines = source_file.text.splitlines()
    if end > len(lines):
        _fail("range_invalid", "locator")
    selected = "\n".join(lines[start - 1 : end]).encode("utf-8")
    payload: dict[str, Any] = {
        "schema": FEEDBACK_SCHEMA,
        "query": normalized,
        "query_digest": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "judgement": judgement,
        "source": {
            "path": path,
            "start_line": start,
            "end_line": end,
            "content_digest": hashlib.sha256(selected).hexdigest(),
            "file_digest": source_file.digest,
        },
        "review": {"reviewer": reviewer_value, "method": "manual"},
        "provenance": {"origin": origin},
        "note": note_value,
        "authority": "historical_only",
        "authorizes_actions": False,
        "retrieval_influence": False,
    }
    return validate_feedback_payload(payload)


def feedback_subject(payload: Mapping[str, Any]) -> str:
    """Return the opaque, query-free ledger subject for a feedback payload."""
    validated = validate_feedback_payload(dict(payload))
    source = validated["source"]
    material = (
        validated["query_digest"]
        + "\0"
        + source["path"]
        + ":"
        + str(source["start_line"])
        + "-"
        + str(source["end_line"])
    )
    return "retrieval-feedback:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_withdrawal(
    withdraws_event_id: str,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    """Build a manual, non-authorizing withdrawal payload."""
    payload: dict[str, Any] = {
        "schema": WITHDRAWAL_SCHEMA,
        "withdraws_event_id": withdraws_event_id,
        "review": {"reviewer": _validate_reviewer(reviewer), "method": "manual"},
        "reason": _validate_reason(reason),
        "authority": "historical_only",
        "authorizes_actions": False,
        "retrieval_influence": False,
    }
    return validate_withdrawal_payload(payload)


def validate_withdrawal_payload(value: object) -> dict[str, Any]:
    """Validate and return one canonical v1 feedback-withdrawal payload."""
    if not isinstance(value, dict) or set(value) != _WITHDRAWAL_FIELDS:
        _fail("payload_invalid", "payload")
    if value.get("schema") != WITHDRAWAL_SCHEMA:
        _fail("payload_invalid", "schema")
    event_id = value.get("withdraws_event_id")
    if not _is_hex(event_id, _HEX_32):
        _fail("event_invalid", "withdraws_event_id")
    review = _validate_review(value.get("review"))
    reason = _validate_reason(value.get("reason"))
    if (
        value.get("authority") != "historical_only"
        or value.get("authorizes_actions") is not False
        or value.get("retrieval_influence") is not False
    ):
        _fail("authority_invalid", "authority")
    return {
        "schema": WITHDRAWAL_SCHEMA,
        "withdraws_event_id": event_id,
        "review": review,
        "reason": reason,
        "authority": "historical_only",
        "authorizes_actions": False,
        "retrieval_influence": False,
    }


def _locator_from_payload(payload: Mapping[str, Any]) -> str:
    source = payload["source"]
    return f"{source['path']}:{source['start_line']}-{source['end_line']}"


def _write_receipt(event: Mapping[str, Any], subject: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "subject": subject,
        "payload_digest": hashlib.sha256(durable.canonical_json(payload)).hexdigest(),
        "verified": event["verified"],
        "authority": "historical_only",
        "authorizes_actions": False,
        "retrieval_influence": False,
    }


def _append_feedback(
    ledger: MemoryLedger,
    session_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    sensitivity: str,
    supersedes: str | None = None,
) -> dict[str, Any]:
    validated = validate_feedback_payload(payload)
    subject = feedback_subject(validated)
    event = ledger.append_event(
        session_id,
        kind,
        subject=subject,
        payload=validated,
        evidence=[
            {
                "kind": "source",
                "locator": _locator_from_payload(validated),
                "content_digest": validated["source"]["content_digest"],
            }
        ],
        supersedes=supersedes,
        trust="observed",
        sensitivity=sensitivity,
        retention="durable",
    )
    return _write_receipt(event, subject, validated)


def record_feedback(
    ledger: MemoryLedger,
    session_id: str,
    *,
    query: str,
    locator: str,
    judgement: str,
    reviewer: str,
    note: str | None = None,
    origin: str = "manual",
    sensitivity: str = "internal",
) -> dict[str, Any]:
    """Append one reviewed feedback fact to the supplied ledger."""
    payload = build_feedback(
        query,
        locator,
        judgement,
        reviewer,
        root=ledger.root,
        note=note,
        origin=origin,
    )
    return _append_feedback(ledger, session_id, "fact", payload, sensitivity=sensitivity)


def _event_id_bytes(event_id: object) -> bytes:
    if not isinstance(event_id, str) or _HEX_32.fullmatch(event_id) is None:
        _fail("event_invalid", "event_id")
    return bytes.fromhex(event_id)


def _event_evidence_valid(connection: Any, event_id: bytes, payload: Mapping[str, Any]) -> bool:
    rows = connection.execute(
        "SELECT kind,locator,content_digest FROM evidence WHERE event_id=? ORDER BY evidence_id",
        (event_id,),
    ).fetchall()
    if len(rows) != 1 or rows[0]["kind"] != durable.EVIDENCE_KINDS["source"]:
        return False
    try:
        locator_payload = durable.unpack_payload(rows[0]["locator"])
    except (TypeError, ValueError):
        return False
    return (
        locator_payload == {"locator": _locator_from_payload(payload)}
        and rows[0]["content_digest"] is not None
        and rows[0]["content_digest"].hex() == payload["source"]["content_digest"]
    )


def _load_current_feedback(
    ledger: MemoryLedger,
    event_id: str,
) -> tuple[dict[str, Any], str]:
    encoded = _event_id_bytes(event_id)
    with ledger.connection(create=False) as connection:
        row = connection.execute(
            "SELECT * FROM events WHERE event_id=? AND project_id=?",
            (encoded, ledger.project_id),
        ).fetchone()
        if row is None or row["kind"] not in {
            durable.EVENT_KINDS["fact"],
            durable.EVENT_KINDS["correction"],
        }:
            _fail("event_not_feedback", "event_id")
        if connection.execute(
            "SELECT 1 FROM supersessions WHERE predecessor_event_id=? LIMIT 1", (encoded,)
        ).fetchone() is not None:
            _fail("event_not_current", "event_id")
        try:
            payload = validate_feedback_payload(
                durable.unpack_payload(row["payload"], row["payload_digest"])
            )
        except (FeedbackError, TypeError, ValueError) as exc:
            raise FeedbackError("event_not_feedback", "event_id") from exc
        subject = feedback_subject(payload)
        expected_subject = hashlib.sha256(subject.encode("utf-8")).digest()
        if row["subject_digest"] != expected_subject or not _event_evidence_valid(
            connection, encoded, payload
        ):
            _fail("event_not_feedback", "event_id")
        sensitivity = durable.SENSITIVITY_NAMES[row["sensitivity"]]
    return payload, sensitivity


def correct_feedback(
    ledger: MemoryLedger,
    session_id: str,
    event_id: str,
    *,
    judgement: str,
    reviewer: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Supersede one current feedback record while retaining its query and locator."""
    prior, sensitivity = _load_current_feedback(ledger, event_id)
    payload = build_feedback(
        prior["query"],
        _locator_from_payload(prior),
        judgement,
        reviewer,
        root=ledger.root,
        note=note,
        origin=prior["provenance"]["origin"],
    )
    return _append_feedback(
        ledger,
        session_id,
        "correction",
        payload,
        sensitivity=sensitivity,
        supersedes=event_id,
    )


def withdraw_feedback(
    ledger: MemoryLedger,
    session_id: str,
    event_id: str,
    *,
    reviewer: str,
    reason: str,
) -> dict[str, Any]:
    """Append a revocation for one current feedback record; never delete it."""
    prior, sensitivity = _load_current_feedback(ledger, event_id)
    payload = build_withdrawal(event_id, reviewer, reason)
    subject = feedback_subject(prior)
    event = ledger.append_event(
        session_id,
        "revocation",
        subject=subject,
        payload=payload,
        supersedes=event_id,
        trust="observed",
        sensitivity=sensitivity,
        retention="durable",
    )
    return _write_receipt(event, subject, payload)


def _invalid_record(row: Any, reason: str) -> dict[str, Any]:
    return {
        "event_id": row["event_id"].hex(),
        "kind": durable.EVENT_KIND_NAMES[row["kind"]],
        "state": "invalid",
        "invalid_reason": reason,
        "judgement": None,
        "query_digest": None,
        "query": None,
        "source": None,
        "reviewer": None,
        "origin": None,
        "observed_at": row["observed_at"],
        "superseded_by": None,
        "withdrawn_by": None,
        "source_current": None,
    }


def _feedback_envelope_valid(connection: Any, row: Any, payload: Mapping[str, Any]) -> bool:
    if row["kind"] not in {durable.EVENT_KINDS["fact"], durable.EVENT_KINDS["correction"]}:
        return False
    if row["kind"] == durable.EVENT_KINDS["fact"] and row["supersedes_event_id"] is not None:
        return False
    if row["kind"] == durable.EVENT_KINDS["correction"] and row["supersedes_event_id"] is None:
        return False
    subject = feedback_subject(payload)
    return row["subject_digest"] == hashlib.sha256(subject.encode("utf-8")).digest() and _event_evidence_valid(
        connection, row["event_id"], payload
    )


def _withdrawal_envelope_valid(row: Any, payload: Mapping[str, Any]) -> bool:
    predecessor = row["supersedes_event_id"]
    return (
        row["kind"] == durable.EVENT_KINDS["revocation"]
        and predecessor is not None
        and payload["withdraws_event_id"] == predecessor.hex()
    )


def _source_is_current(payload: Mapping[str, Any], files: Mapping[str, Any]) -> bool:
    source = payload["source"]
    source_file = files.get(source["path"])
    if source_file is None or source_file.digest != source["file_digest"]:
        return False
    lines = source_file.text.splitlines()
    start = source["start_line"]
    end = source["end_line"]
    if end > len(lines):
        return False
    selected = "\n".join(lines[start - 1 : end]).encode("utf-8")
    return hashlib.sha256(selected).hexdigest() == source["content_digest"]


def feedback_report(ledger: MemoryLedger, *, include_history: bool = False) -> dict[str, Any]:
    """Return a deterministic, read-only report over feedback ledger events."""
    if type(include_history) is not bool:
        _fail("invalid_type", "include_history")
    feedback_rows: list[tuple[Any, dict[str, Any]]] = []
    withdrawal_rows: list[tuple[Any, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    with ledger.connection(create=False) as connection:
        rows = connection.execute(
            "SELECT * FROM events WHERE project_id=? ORDER BY observed_at,event_id",
            (ledger.project_id,),
        ).fetchall()
        for row in rows:
            try:
                unpacked = durable.unpack_payload(row["payload"], row["payload_digest"])
            except (TypeError, ValueError):
                continue
            if not isinstance(unpacked, dict):
                continue
            schema = unpacked.get("schema")
            if schema == FEEDBACK_SCHEMA:
                try:
                    payload = validate_feedback_payload(unpacked)
                    if not _feedback_envelope_valid(connection, row, payload):
                        _fail("event_envelope_invalid", "event")
                except FeedbackError as exc:
                    invalid.append(_invalid_record(row, exc.reason))
                else:
                    feedback_rows.append((row, payload))
            elif schema == WITHDRAWAL_SCHEMA:
                try:
                    payload = validate_withdrawal_payload(unpacked)
                    if not _withdrawal_envelope_valid(row, payload):
                        _fail("event_envelope_invalid", "event")
                except FeedbackError as exc:
                    invalid.append(_invalid_record(row, exc.reason))
                else:
                    withdrawal_rows.append((row, payload))

    try:
        admitted_files: Mapping[str, Any] = cache_v3.source_snapshot(ledger.root).by_path
    except (OSError, TypeError, UnicodeError, ValueError):
        admitted_files = {}

    corrections: dict[bytes, list[Any]] = {}
    for row, _payload in feedback_rows:
        predecessor = row["supersedes_event_id"]
        if row["kind"] == durable.EVENT_KINDS["correction"] and predecessor is not None:
            corrections.setdefault(predecessor, []).append(row)
    withdrawals: dict[bytes, list[Any]] = {}
    for row, _payload in withdrawal_rows:
        predecessor = row["supersedes_event_id"]
        if predecessor is not None:
            withdrawals.setdefault(predecessor, []).append(row)
    for successors in (*corrections.values(), *withdrawals.values()):
        successors.sort(key=lambda item: (item["observed_at"], item["event_id"]))

    records: list[dict[str, Any]] = []
    counts = {name: 0 for name in ("current", "stale", "superseded", "withdrawn", "invalid")}
    for row, payload in feedback_rows:
        event_id = row["event_id"]
        withdrawn = withdrawals.get(event_id, [])
        superseded = corrections.get(event_id, [])
        current = _source_is_current(payload, admitted_files)
        if withdrawn:
            state = "withdrawn"
        elif superseded:
            state = "superseded"
        elif current:
            state = "current"
        else:
            state = "stale"
        counts[state] += 1
        records.append(
            {
                "event_id": event_id.hex(),
                "kind": durable.EVENT_KIND_NAMES[row["kind"]],
                "state": state,
                "invalid_reason": None,
                "judgement": payload["judgement"],
                "query_digest": payload["query_digest"],
                "query": payload["query"],
                "source": payload["source"],
                "reviewer": payload["review"]["reviewer"],
                "origin": payload["provenance"]["origin"],
                "observed_at": row["observed_at"],
                "superseded_by": superseded[0]["event_id"].hex() if superseded else None,
                "withdrawn_by": withdrawn[0]["event_id"].hex() if withdrawn else None,
                "source_current": current,
            }
        )
    counts["invalid"] = len(invalid)
    records.extend(invalid)
    records.sort(key=lambda item: (item["observed_at"], item["event_id"]))
    if not include_history:
        records = [item for item in records if item["state"] in {"current", "stale", "invalid"}]
    return {
        "schema": REPORT_SCHEMA,
        "project_id": ledger.project_id_text,
        "records": records,
        "counts": counts,
        "include_history": include_history,
        "authority": "historical_only",
        "authorizes_actions": False,
        "retrieval_influence": False,
    }


__all__ = [
    "FEEDBACK_SCHEMA",
    "WITHDRAWAL_SCHEMA",
    "REPORT_SCHEMA",
    "JUDGEMENTS",
    "ORIGINS",
    "FeedbackError",
    "normalize_query",
    "build_feedback",
    "feedback_subject",
    "validate_feedback_payload",
    "build_withdrawal",
    "validate_withdrawal_payload",
    "record_feedback",
    "correct_feedback",
    "withdraw_feedback",
    "feedback_report",
]
