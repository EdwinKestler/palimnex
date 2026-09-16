"""Versioned capture candidates and disposable extractive memory capsules.

No model judgment, approval replay, schema migration, or automatic execution.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import cache_v3, core, durable
from .retrieval import budget_items, retrieve_sources
from .security import read_bounded_file, scan_text

CAPTURE_SCHEMA = "project-memory:capture:v1"
CLAIM_SCHEMA = "project-memory:claim:v1"


def source_quote(root: Path, locator: str) -> str:
    match = re.fullmatch(r"([^:]+):(\d+)(?:-(\d+))?", locator)
    if not match:
        raise ValueError("source quote needs path:start-end")
    relative, first, last = match.groups()
    if relative not in {p.relative_to(root).as_posix() for p in core.included_files(root)}:
        raise ValueError("source quote is outside the admitted corpus")
    raw = read_bounded_file(root, relative, max_bytes=cache_v3.MAX_SOURCE_BYTES)
    text = raw.decode("utf-8")
    if scan_text(text):
        raise ValueError("source quote rejected by privacy policy")
    lines = text.splitlines()
    start, end = int(first), int(last or first)
    if not 1 <= start <= end <= len(lines):
        raise ValueError("source quote range is outside file")
    return "\n".join(lines[start-1:end])


def claim_support(event: dict[str, Any], root: Path) -> str:
    """Exact quotation support is deliberately narrower than factual truth."""
    if event.get("imported") or event.get("claimed_trust") != "observed":
        return "not_assessed"
    if event.get("source_integrity") != "current":
        return "not_assessed"
    payload = event.get("payload")
    if not isinstance(payload, dict) or set(payload) != {"schema", "claim", "support"} or payload["schema"] != CLAIM_SCHEMA:
        return "not_assessed"
    support = payload["support"]
    if not isinstance(support, dict) or set(support) != {"kind", "locator"} or support["kind"] != "exact_quote":
        return "not_assessed"
    locator = support["locator"]
    if not isinstance(locator, str) or not isinstance(payload["claim"], str) or not payload["claim"].strip():
        return "not_assessed"
    evidence = [e for e in event.get("evidence", []) if e["locator"] == locator and e["kind"] == durable.EVIDENCE_KINDS["source"]]
    if not evidence:
        return "not_assessed"
    try:
        quote = source_quote(root, locator)
        digest = hashlib.sha256(quote.encode()).hexdigest()
        return "exact_source_quote" if quote == payload["claim"] and all(e["content_digest"] == digest for e in evidence) else "not_assessed"
    except (ValueError, UnicodeError, OSError):
        return "not_assessed"


def is_capture(payload: Any) -> bool:
    """Payload schema names are untrusted data, not proof of envelope validity."""
    fields = {"schema", "project_id", "session_id", "specification", "evidence",
              "corpus_fingerprint", "checkout_id", "source_integrity", "claim_support",
              "authority", "authorizes_actions", "scanner_policy_digest", "candidate_digest"}
    if not isinstance(payload, dict) or set(payload) != fields or payload.get("schema") != CAPTURE_SCHEMA:
        return False
    spec = payload.get("specification")
    if not isinstance(spec, dict) or not isinstance(spec.get("scope"), str) or spec["scope"] not in {"checkout", "repository"}:
        return False
    for name, length in (("project_id", 32), ("session_id", 32), ("corpus_fingerprint", 64), ("checkout_id", 64), ("scanner_policy_digest", 64), ("candidate_digest", 64)):
        if not isinstance(payload[name], str) or re.fullmatch("[0-9a-f]{" + str(length) + "}", payload[name]) is None:
            return False
    if payload["authority"] != "historical_only" or payload["authorizes_actions"] is not False:
        return False
    value = dict(payload)
    digest = value.pop("candidate_digest")
    return hashlib.sha256(durable.canonical_json(value)).hexdigest() == digest


def capture_candidate(ledger: durable.MemoryLedger, session_id: str, specification: dict[str, Any]) -> dict[str, Any]:
    allowed = {"subject", "outcome", "decision", "failure", "attribution", "next_step", "evidence", "scope", "sensitivity"}
    required = {"subject", "outcome", "evidence"}
    if not isinstance(specification, dict) or set(specification) - allowed or not required <= set(specification):
        raise ValueError("capture specification has missing or unknown fields")
    spec = {"scope": "checkout", "sensitivity": "internal", "attribution": "unknown", **specification}
    for field in ("subject", "outcome", "decision", "failure", "next_step"):
        if field in spec and (not isinstance(spec[field], str) or not spec[field].strip() or len(spec[field].encode()) > 8192):
            raise ValueError(f"capture {field} must be nonempty and at most 8192 bytes")
    if not isinstance(spec["scope"], str) or not isinstance(spec["sensitivity"], str) or spec["scope"] not in {"checkout", "repository"} or spec["sensitivity"] not in {"public", "internal", "restricted"}:
        raise ValueError("unsupported capture scope or sensitivity")
    if not isinstance(spec["attribution"], str) or spec["attribution"] not in {"plan", "execution", "environment", "mixed", "unknown"}:
        raise ValueError("unsupported failure attribution")
    locators = spec["evidence"]
    if not isinstance(locators, list) or not 1 <= len(locators) <= 16 or any(not isinstance(s, str) for s in locators):
        raise ValueError("capture requires 1 to 16 source evidence locators")
    durable.pack_payload(spec)  # canonical, finite, bounded and privacy scanned
    snapshot = cache_v3.source_snapshot(ledger.root)
    evidence = []
    for locator in sorted(set(locators)):
        quote = source_quote(ledger.root, locator)
        evidence.append({"kind": "source", "locator": locator, "content_digest": hashlib.sha256(quote.encode()).hexdigest()})
    with ledger.connection(create=False) as connection:
        sid = durable._id_bytes(session_id, "session_id")
        session = connection.execute("SELECT status FROM sessions WHERE session_id=? AND project_id=?", (sid, ledger.project_id)).fetchone()
        if session is None:
            raise ValueError("capture session does not exist")
    candidate = {"schema": CAPTURE_SCHEMA, "project_id": ledger.project_id.hex(), "session_id": session_id,
                 "specification": spec, "evidence": evidence,
                 "corpus_fingerprint": snapshot.fingerprint,
                 "checkout_id": hashlib.sha256(str(ledger.root.resolve()).encode()).hexdigest(),
                 "source_integrity": "current", "claim_support": "not_assessed",
                 "scanner_policy_digest": durable.policy_digest(),
                 "authority": "historical_only", "authorizes_actions": False}
    candidate["candidate_digest"] = hashlib.sha256(durable.canonical_json(candidate)).hexdigest()
    return candidate


def _capture_receipt(connection: Any, ledger: durable.MemoryLedger, sid: bytes, eid: bytes,
                     candidate: dict[str, Any]) -> bool:
    row = connection.execute("SELECT * FROM events WHERE event_id=?", (eid,)).fetchone()
    if row is None:
        return False
    session = connection.execute("SELECT status FROM sessions WHERE session_id=? AND project_id=?", (sid, ledger.project_id)).fetchone()
    closes = connection.execute("SELECT * FROM events WHERE session_id=? AND kind=?", (sid, durable.EVENT_KINDS["session_closed"])).fetchall()
    valid = (row["project_id"] == ledger.project_id and row["session_id"] == sid
             and row["kind"] == durable.EVENT_KINDS["outcome"] and row["import_batch_id"] is None
             and row["claimed_trust"] == durable.CLAIMED_TRUST["observed"]
             and durable.unpack_payload(row["payload"], row["payload_digest"]) == candidate
             and session is not None and session["status"] == 2 and len(closes) == 1)
    if valid:
        close = closes[0]
        valid = (close["import_batch_id"] is None and close["claimed_trust"] == durable.CLAIMED_TRUST["observed"]
                 and close["sequence"] == row["sequence"] + 1 and close["observed_at"] == row["observed_at"]
                 and durable.unpack_payload(close["payload"], close["payload_digest"]) == {"outcome": candidate["specification"]["outcome"]})
    if not valid:
        raise ValueError("capture identity collision: no matching completed local capture")
    return True


def apply_capture(ledger: durable.MemoryLedger, candidate: dict[str, Any]) -> dict[str, Any]:
    """Record outcome and close session in one transaction; exact retry is idempotent."""
    if not is_capture(candidate):
        raise ValueError("invalid capture candidate or digest mismatch")
    supplied = dict(candidate)
    digest = supplied.pop("candidate_digest", None)
    if digest != hashlib.sha256(durable.canonical_json(supplied)).hexdigest():
        raise ValueError("capture candidate digest mismatch")
    if candidate["project_id"] != ledger.project_id.hex():
        raise ValueError("capture project mismatch")
    sid = durable._id_bytes(candidate["session_id"], "session_id")
    eid = hashlib.sha256(b"capture-v1\0" + sid + bytes.fromhex(digest)).digest()[:16]
    # An acknowledged exact retry needs no new source validation or state changes.
    with ledger.connection(create=False) as connection:
        if _capture_receipt(connection, ledger, sid, eid, candidate):
            return {"status": "already_captured", "event_id": eid.hex(), "session_id": sid.hex(),
                    "authority": "historical_only", "authorizes_actions": False}
    refreshed = capture_candidate(ledger, candidate["session_id"], candidate["specification"])
    if refreshed != candidate:
        raise ValueError("capture source or policy context changed; preview again")
    spec = candidate["specification"]
    with ledger.connection(create=False, write=True) as connection:
        if _capture_receipt(connection, ledger, sid, eid, candidate):
            return {"status": "already_captured", "event_id": eid.hex(), "session_id": sid.hex(),
                    "authority": "historical_only", "authorizes_actions": False}
        timestamp = ledger._next_session_observed_at(connection, sid, durable.now_ms())
        evidence = [ledger._prepare_evidence(item) for item in candidate["evidence"]]
        ledger._align_verified_evidence(evidence, timestamp)
        event = ledger._append_event_tx(connection, sid, "outcome", subject=spec["subject"], payload=candidate,
                                        evidence_rows=evidence, sensitivity=spec["sensitivity"], retention="durable",
                                        observed_at=timestamp, valid_from=timestamp, event_id=eid)
        ledger._append_event_tx(connection, sid, "session_closed", subject=f"session:{sid.hex()}",
                                payload={"outcome": spec["outcome"]}, evidence_rows=[], sensitivity=spec["sensitivity"],
                                retention="durable", observed_at=timestamp, valid_from=timestamp)
        connection.execute("UPDATE sessions SET status=2,ended_at=? WHERE session_id=?", (timestamp, sid))
    return {"status": "captured", "event_id": event["event_id"], "session_id": sid.hex(),
            "claim_support": "not_assessed", "authority": "historical_only", "authorizes_actions": False,
            "projection": "pending; use project-hot"}


def current_eligible(event: dict[str, Any], fingerprint: str, checkout: str) -> bool:
    if event["imported"] or event["claimed_trust"] != "observed":
        return False
    payload = event["payload"]
    if isinstance(payload, dict) and payload.get("schema") == CAPTURE_SCHEMA:
        if not is_capture(payload):
            return False
        if payload["specification"]["scope"] == "checkout":
            return payload["corpus_fingerprint"] == fingerprint and payload["checkout_id"] == checkout
    return True


def assemble_context(query: str, *, root: Path = core.ROOT, ledger: durable.MemoryLedger | None = None,
                     client: Any = None, byte_budget: int = 16384, limit: int = 8,
                     session_id: str | None = None, max_sensitivity: str = "internal",
                     include_graph: bool = True) -> dict[str, Any]:
    budget_items([], byte_budget)
    sources = retrieve_sources(query, root=root, client=client, limit=limit,
                               byte_budget=byte_budget, include_graph=include_graph)
    history = []
    state = "missing"
    truncated = False
    if ledger is not None and ledger.path.exists():
        recalled = ledger.recall(query, limit=100, max_sensitivity=max_sensitivity,
                                 session_id=session_id, visibility="current",
                                 result_filter=lambda e: current_eligible(e, sources["corpus_fingerprint"], sources["checkout_id"]))
        state = "consulted"
        truncated = recalled["candidate_scan_truncated"]
        for event in recalled["results"]:
            payload = event["payload"]
            if event["imported"] or event["claimed_trust"] != "observed":
                continue
            if is_capture(payload):
                if payload["specification"]["scope"] == "checkout" and (
                    payload["corpus_fingerprint"] != sources["corpus_fingerprint"]
                    or payload["checkout_id"] != sources["checkout_id"]):
                    continue
            history.append({"type": "historical_event", **event})
    source_items = [{"type": "source", **item} for item in sources["results"]]
    # Interleave channels; one long history record cannot consume the whole budget.
    combined = []
    for i in range(max(len(source_items), len(history))):
        for group in (source_items, history):
            if i < len(group):
                combined.append(group[i])
    selected, _ = budget_items(combined, byte_budget)
    selected = selected[:limit]
    _, used = budget_items(selected, byte_budget)
    return {"schema": "project-memory:context:v1", "query": query, "items": selected,
            "items_bytes": used, "byte_budget": byte_budget, "budget_unit": "serialized_utf8_bytes",
            "ledger_status": state, "cache_consulted": sources["cache_consulted"],
            "retrieval_mode": sources["retrieval_mode"], "scan_scope": sources["scan_scope"],
            "corpus_fingerprint": sources["corpus_fingerprint"], "checkout_id": sources["checkout_id"],
            "candidate_scan_truncated": truncated,
            "abstained": not selected, "omitted_count": len(combined)-len(selected),
            "authority": "evidence_and_historical_context", "authorizes_actions": False}


def build_capsule(query: str, *, ledger: durable.MemoryLedger, byte_budget: int = 8192,
                  max_sensitivity: str = "internal", session_id: str | None = None) -> dict[str, Any]:
    """Extract exact source quotations; never synthesize unsupported event claims."""
    if not cache_v3._bounded_query_tokens(query, "capsule query"):
        raise ValueError("capsule query must contain a lexical term")
    snapshot = cache_v3.source_snapshot(ledger.root)
    checkout = hashlib.sha256(str(ledger.root.resolve()).encode()).hexdigest()
    recalled = ledger.recall(query, limit=100, max_sensitivity=max_sensitivity,
                             session_id=session_id, visibility="current",
                             result_filter=lambda e: current_eligible(e, snapshot.fingerprint, checkout) and e["source_integrity"] == "current")
    items = []
    omitted_evidence = 0
    for event in recalled["results"]:
        if event["imported"] or event["claimed_trust"] != "observed" or event["source_integrity"] != "current":
            continue
        payload = event["payload"]
        if is_capture(payload):
            if payload["specification"]["scope"] == "checkout" and (payload["corpus_fingerprint"] != snapshot.fingerprint or payload["checkout_id"] != checkout):
                continue
        for evidence in event["evidence"]:
            if evidence["kind"] != durable.EVIDENCE_KINDS["source"]:
                continue
            try:
                text = source_quote(ledger.root, evidence["locator"])
            except (ValueError, UnicodeError, OSError):
                omitted_evidence += 1
                continue
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest != evidence["content_digest"]:
                omitted_evidence += 1
                continue
            items.append({"text": text, "pointer": evidence["locator"], "content_digest": digest,
                          "parent_event_id": event["event_id"], "parent_record_digest": event["record_digest"],
                          "contradicts": event["contradicts"], "sensitivity": event["sensitivity"],
                          "support": "source_quote_only", "event_claim_support": event["claim_support"]})
    selected, used = budget_items(items, byte_budget)
    return {"schema": "project-memory:capsule:v1", "query": query, "items": selected,
            "items_bytes": used, "byte_budget": byte_budget, "omitted_count": len(items)-len(selected), "omitted_evidence": omitted_evidence,
            "candidate_scan_truncated": recalled["candidate_scan_truncated"],
            "derivation": "extractive_source_quotes", "persisted": False,
            "authority": "historical_only", "authorizes_actions": False}
