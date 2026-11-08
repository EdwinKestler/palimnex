from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from palimnex import durable
from palimnex.feedback import (
    FEEDBACK_SCHEMA,
    FeedbackError,
    build_feedback,
    build_withdrawal,
    correct_feedback,
    feedback_report,
    feedback_subject,
    normalize_query,
    record_feedback,
    validate_feedback_payload,
    withdraw_feedback,
)
from palimnex.retrieval import retrieve_sources
from palimnex.tests.support import PROJECT_ID, write_project


class RetrievalFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source_text = "heading\nalpha answer line\nomega context line\n"
        write_project(self.root, {"docs/source.md": self.source_text})
        self.ledger = durable.MemoryLedger(
            self.root / ".private/memory.sqlite3",
            project_id=PROJECT_ID,
            project_slug="memory-fixture",
            root=self.root,
        )
        self.ledger.initialize()
        self.session_id = self.ledger.start_session("review retrieval feedback")["session_id"]

    def record(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "query": "alpha answer",
            "locator": "docs/source.md:2-2",
            "judgement": "answers",
            "reviewer": "EdwinKestler",
        }
        arguments.update(overrides)
        return record_feedback(self.ledger, self.session_id, **arguments)  # type: ignore[arg-type]

    def test_record_report_verification_digest_and_authority(self) -> None:
        receipt = self.record(note="Reviewed against the selected line.", origin="context")
        report = feedback_report(self.ledger)

        self.assertTrue(receipt["verified"])
        self.assertEqual(report["counts"], {
            "current": 1,
            "stale": 0,
            "superseded": 0,
            "withdrawn": 0,
            "invalid": 0,
        })
        record = report["records"][0]
        self.assertEqual(record["state"], "current")
        self.assertTrue(record["source_current"])
        self.assertEqual(record["origin"], "context")
        self.assertEqual(report["authority"], "historical_only")
        self.assertFalse(report["authorizes_actions"])
        self.assertFalse(report["retrieval_influence"])
        with self.ledger.connection(create=False) as connection:
            row = connection.execute(
                "SELECT payload,payload_digest FROM events WHERE event_id=?",
                (bytes.fromhex(str(receipt["event_id"])),),
            ).fetchone()
            evidence = connection.execute(
                "SELECT locally_verified FROM evidence WHERE event_id=?",
                (bytes.fromhex(str(receipt["event_id"])),),
            ).fetchone()
        payload = durable.unpack_payload(row["payload"], row["payload_digest"])
        self.assertEqual(
            receipt["payload_digest"],
            hashlib.sha256(durable.canonical_json(payload)).hexdigest(),
        )
        self.assertEqual(evidence["locally_verified"], 1)
        self.assertNotIn("alpha answer", str(receipt["subject"]))

    def test_normalization_and_payload_validation_are_self_consistent(self) -> None:
        self.assertEqual(normalize_query("  alpha\t\n answer  "), "alpha answer")
        payload = build_feedback(
            "  alpha\t answer ",
            "docs/source.md:2",
            "answers",
            "Reviewer One",
            root=self.root,
        )
        self.assertEqual(payload["query"], "alpha answer")
        self.assertEqual(payload, validate_feedback_payload(payload))
        self.assertEqual(payload["schema"], FEEDBACK_SCHEMA)
        altered = copy.deepcopy(payload)
        altered["query_digest"] = "0" * 64
        with self.assertRaises(FeedbackError) as raised:
            validate_feedback_payload(altered)
        self.assertEqual(raised.exception.reason, "query_digest_mismatch")

    def test_query_and_metadata_refusals_are_stable_and_non_echoing(self) -> None:
        query_canary = "".join(("sk", "-", "AlphaNumericSegment", "9876543210"))
        reviewer_canary = "".join(("gh", "p_", "Ab9Cd8Ef7Gh6", "Jk5Lm4No3Pq2"))
        cases = [
            ({"query": "   "}, "empty_query"),
            ({"query": "x" * 8193}, "query_byte_bound"),
            ({"query": " ".join(f"term{index}" for index in range(129))}, "query_term_bound"),
            ({"query": "alpha\x00answer"}, "query_control"),
            ({"query": query_canary}, "query_privacy_refused"),
            ({"note": ""}, "note_invalid"),
            ({"note": "n" * 1025}, "note_byte_bound"),
            ({"note": query_canary}, "note_privacy_refused"),
            ({"judgement": "maybe"}, "judgement_invalid"),
            ({"origin": "automatic"}, "origin_invalid"),
            ({"reviewer": "bad\nreviewer"}, "reviewer_invalid"),
            ({"reviewer": reviewer_canary}, "reviewer_privacy_refused"),
        ]
        for overrides, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(FeedbackError) as raised:
                self.record(**overrides)
            self.assertEqual(raised.exception.reason, reason)
            self.assertNotIn(query_canary, str(raised.exception))
            self.assertNotIn(reviewer_canary, str(raised.exception))

    def test_locator_refusals_distinguish_shape_admission_and_range(self) -> None:
        cases = [
            ("../docs/source.md:1", "locator_invalid"),
            ("docs/source.md", "locator_invalid"),
            ("docs/missing.md:1", "source_not_admitted"),
            ("palimnex/evaluation/v25.json:1", "source_not_admitted"),
            ("docs/source.md:3-2", "range_invalid"),
            ("docs/source.md:99", "range_invalid"),
        ]
        for locator, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(FeedbackError) as raised:
                self.record(locator=locator)
            self.assertEqual(raised.exception.reason, reason)

    def test_source_drift_and_restore_change_only_source_state(self) -> None:
        self.record()
        source = self.root / "docs/source.md"
        source.write_text("heading\nchanged answer line\nomega context line\n", encoding="utf-8")
        stale = feedback_report(self.ledger)
        self.assertEqual(stale["records"][0]["state"], "stale")
        self.assertFalse(stale["records"][0]["source_current"])
        source.write_text(self.source_text, encoding="utf-8")
        restored = feedback_report(self.ledger)
        self.assertEqual(restored["records"][0]["state"], "current")
        self.assertTrue(restored["records"][0]["source_current"])
        source.write_text("changed heading\nalpha answer line\nomega context line\n", encoding="utf-8")
        file_drift = feedback_report(self.ledger)
        self.assertEqual(file_drift["records"][0]["state"], "stale")
        self.assertFalse(file_drift["records"][0]["source_current"])

    def test_correction_preserves_subject_query_locator_and_history(self) -> None:
        original = self.record()
        corrected = correct_feedback(
            self.ledger,
            self.session_id,
            str(original["event_id"]),
            judgement="does_not_answer",
            reviewer="Second Reviewer",
            note="The selected line does not answer the full question.",
        )
        self.assertEqual(original["subject"], corrected["subject"])
        current = feedback_report(self.ledger)
        self.assertEqual([item["event_id"] for item in current["records"]], [corrected["event_id"]])
        history = feedback_report(self.ledger, include_history=True)
        self.assertEqual(history["counts"]["superseded"], 1)
        self.assertEqual(history["counts"]["current"], 1)
        self.assertEqual(history["records"][0]["state"], "superseded")
        self.assertEqual(history["records"][0]["superseded_by"], corrected["event_id"])
        self.assertEqual(history["records"][1]["judgement"], "does_not_answer")
        self.assertEqual(history["records"][0]["query"], history["records"][1]["query"])
        self.assertEqual(history["records"][0]["source"], history["records"][1]["source"])
        with self.assertRaises(FeedbackError) as raised:
            correct_feedback(
                self.ledger,
                self.session_id,
                str(original["event_id"]),
                judgement="answers",
                reviewer="Third Reviewer",
            )
        self.assertEqual(raised.exception.reason, "event_not_current")

    def test_withdrawal_is_retained_and_repeat_or_foreign_target_is_refused(self) -> None:
        original = self.record()
        withdrawn = withdraw_feedback(
            self.ledger,
            self.session_id,
            str(original["event_id"]),
            reviewer="Withdrawal Reviewer",
            reason="The review was entered against the wrong question.",
        )
        self.assertEqual(feedback_report(self.ledger)["records"], [])
        history = feedback_report(self.ledger, include_history=True)
        self.assertEqual(history["counts"]["withdrawn"], 1)
        self.assertEqual(history["records"][0]["state"], "withdrawn")
        self.assertEqual(history["records"][0]["withdrawn_by"], withdrawn["event_id"])
        with self.assertRaises(FeedbackError) as repeated:
            withdraw_feedback(
                self.ledger,
                self.session_id,
                str(original["event_id"]),
                reviewer="Withdrawal Reviewer",
                reason="A repeated withdrawal must fail.",
            )
        self.assertEqual(repeated.exception.reason, "event_not_current")

        foreign = self.ledger.append_event(
            self.session_id,
            "fact",
            subject="ordinary historical fact",
            payload={"schema": "example:ordinary:v1", "value": "safe"},
            retention="durable",
        )
        with self.assertRaises(FeedbackError) as non_feedback:
            withdraw_feedback(
                self.ledger,
                self.session_id,
                foreign["event_id"],
                reviewer="Withdrawal Reviewer",
                reason="This is not a feedback record.",
            )
        self.assertEqual(non_feedback.exception.reason, "event_not_feedback")

    def test_withdrawal_reason_privacy_is_refused_without_echo(self) -> None:
        reason_canary = "".join(("AK", "IA", "ABCDEFGHIJKLMNOP"))
        with self.assertRaises(FeedbackError) as raised:
            build_withdrawal("0" * 32, "Reviewer", reason_canary)
        self.assertEqual(raised.exception.reason, "reason_privacy_refused")
        self.assertNotIn(reason_canary, str(raised.exception))

    def test_other_payload_is_ignored_and_tampered_feedback_is_invalid(self) -> None:
        self.ledger.append_event(
            self.session_id,
            "outcome",
            subject="ordinary outcome",
            payload={"schema": "example:outcome:v1", "value": "complete"},
            retention="durable",
        )
        payload = build_feedback(
            "alpha answer",
            "docs/source.md:2-2",
            "answers",
            "Reviewer",
            root=self.root,
        )
        payload["unexpected"] = "tampered"
        self.ledger.append_event(
            self.session_id,
            "fact",
            subject="retrieval-feedback:" + "0" * 64,
            payload=payload,
            retention="durable",
        )
        report = feedback_report(self.ledger)
        self.assertEqual(report["counts"]["invalid"], 1)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(report["records"][0]["state"], "invalid")
        self.assertEqual(report["records"][0]["invalid_reason"], "payload_invalid")
        self.assertIsNone(report["records"][0]["query"])

    def test_report_is_deterministic_and_logical_restore_preserves_records(self) -> None:
        self.record()
        first = feedback_report(self.ledger, include_history=True)
        self.assertEqual(first, feedback_report(self.ledger, include_history=True))
        document = self.ledger.logical_document()
        feedback_events = [
            event
            for event in document["events"]
            if isinstance(event["payload"], dict)
            and event["payload"].get("schema") == FEEDBACK_SCHEMA
        ]
        self.assertEqual(len(feedback_events), 1)

        restored_root = self.root / "restored"
        restored_root.mkdir()
        write_project(restored_root, {"docs/source.md": self.source_text})
        restored = durable.MemoryLedger(
            restored_root / ".private/memory.sqlite3",
            project_id=PROJECT_ID,
            project_slug="memory-fixture",
            root=restored_root,
        )
        restored.restore_untrusted_document(
            document,
            source_logical_digest=hashlib.sha256(durable.canonical_json(document)).hexdigest(),
            authenticated=False,
        )
        self.assertEqual(first, feedback_report(restored, include_history=True))

    def test_retrieval_is_byte_identical_before_and_after_feedback(self) -> None:
        before = retrieve_sources("alpha answer", root=self.root, influence="off")
        self.record()
        after = retrieve_sources("alpha answer", root=self.root, influence="off")
        self.assertEqual(durable.canonical_json(before), durable.canonical_json(after))

    def test_feedback_subject_formula_is_stable(self) -> None:
        payload = build_feedback(
            "alpha answer",
            "docs/source.md:2-2",
            "answers",
            "Reviewer",
            root=self.root,
        )
        source = payload["source"]
        material = (
            payload["query_digest"]
            + "\0"
            + source["path"]
            + ":"
            + str(source["start_line"])
            + "-"
            + str(source["end_line"])
        )
        expected = "retrieval-feedback:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        self.assertEqual(feedback_subject(payload), expected)

    def test_real_payloads_and_report_match_public_schemas(self) -> None:
        payload = build_feedback(
            "alpha answer",
            "docs/source.md:2-2",
            "answers",
            "Reviewer",
            root=self.root,
        )
        withdrawal = build_withdrawal("0" * 32, "Reviewer", "Reviewed withdrawal reason.")
        self.record()
        report = feedback_report(self.ledger, include_history=True)
        documents = (
            ("retrieval-feedback.v1.schema.json", payload),
            ("retrieval-feedback-withdrawal.v1.schema.json", withdrawal),
            ("retrieval-feedback-report.v1.schema.json", report),
        )
        schema_root = Path(__file__).parents[1] / "schemas"
        for name, document in documents:
            with self.subTest(schema=name):
                schema = json.loads((schema_root / name).read_text(encoding="utf-8"))
                Draft202012Validator(schema).validate(document)


if __name__ == "__main__":
    unittest.main()
