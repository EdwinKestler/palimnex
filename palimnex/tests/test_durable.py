from __future__ import annotations

import contextlib
import hashlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from palimnex import core, durable
from palimnex.durable import MemoryLedger, _eligible_supersessor_exists_sql
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import PROJECT_ID


class DurableMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "evidence.md").write_text(
            "first evidence line\nsecond evidence line\n", encoding="utf-8"
        )
        self.ledger = MemoryLedger(
            self.root / ".private/memory.sqlite3",
            project_id=PROJECT_ID,
            project_slug="memory-fixture",
            root=self.root,
        )
        self.ledger.initialize()

    @staticmethod
    def _different_digest(value: bytes) -> bytes:
        return bytes([value[0] ^ 1]) + value[1:]

    def test_known_at_and_valid_at_are_independent_temporal_axes(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=500):
            session = self.ledger.start_session("temporal recall", session_id="10" * 16)
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            original = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="deployment endpoint",
                payload={"deployment endpoint": "old"},
                valid_from=1_000,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=3_000):
            correction = self.ledger.append_event(
                session["session_id"],
                "correction",
                subject="deployment endpoint",
                payload={"deployment endpoint": "corrected"},
                supersedes=original["event_id"],
                valid_from=2_000,
            )

        before_known = self.ledger.recall(
            "deployment endpoint", known_at=1_500, valid_at=2_500
        )
        self.assertEqual(before_known["results"][0]["event_id"], original["event_id"])
        before_effective = self.ledger.recall(
            "deployment endpoint", known_at=3_500, valid_at=1_500
        )
        self.assertEqual(before_effective["results"][0]["event_id"], original["event_id"])
        current = self.ledger.recall(
            "deployment endpoint", known_at=3_500, valid_at=2_500
        )
        self.assertEqual(current["results"][0]["event_id"], correction["event_id"])
        history = self.ledger.recall(
            "deployment endpoint", known_at=3_500, valid_at=2_500, include_history=True
        )
        self.assertEqual(
            {item["event_id"] for item in history["results"]},
            {original["event_id"], correction["event_id"]},
        )

    def test_local_api_and_cli_do_not_accept_observation_backdating(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            session = self.ledger.start_session("local observation clock boundary")
        before = self.ledger.status()["counts"].copy()
        with self.assertRaisesRegex(TypeError, "observed_at"):
            self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="caller supplied observation time",
                payload={"state": "must not be inserted"},
                observed_at=1,
            )
        self.assertEqual(self.ledger.status()["counts"], before)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            core.parser().parse_args(
                [
                    "remember",
                    "--session",
                    session["session_id"],
                    "--kind",
                    "fact",
                    "--subject",
                    "caller supplied observation time",
                    "--payload",
                    "{}",
                    "--observed-at",
                    "1",
                ]
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments: --observed-at 1", stderr.getvalue())

        with mock.patch("palimnex.durable.now_ms", return_value=2_000):
            stamped = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="system stamped observation time",
                payload={"state": "inserted"},
                valid_from=1_500,
            )
        self.assertEqual(stamped["observed_at"], 2_000)
        self.assertEqual(stamped["valid_from"], 1_500)

    def test_session_clock_rollback_clamps_append_and_close_history(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            session = self.ledger.start_session("session clock rollback")
        with mock.patch("palimnex.durable.now_ms", return_value=2_000):
            appended = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="nondecreasing session history",
                payload={"state": "appended"},
            )
        with mock.patch("palimnex.durable.now_ms", return_value=1_500):
            closed = self.ledger.close_session(
                session["session_id"], outcome="clock moved backwards"
            )

        self.assertEqual(appended["observed_at"], 2_000)
        self.assertEqual(closed["event"]["observed_at"], 2_000)
        self.assertEqual(closed["event"]["valid_from"], 2_000)
        with self.ledger.connection(create=False) as connection:
            row = connection.execute(
                "SELECT ended_at FROM sessions WHERE session_id=?",
                (bytes.fromhex(session["session_id"]),),
            ).fetchone()
            observed = [
                item[0]
                for item in connection.execute(
                    "SELECT observed_at FROM events WHERE session_id=? ORDER BY sequence",
                    (bytes.fromhex(session["session_id"]),),
                )
            ]
        self.assertEqual(row["ended_at"], 2_000)
        self.assertEqual(observed, sorted(observed))
        self.assertEqual(self.ledger.status()["status"], "ready")

    def test_evidence_and_initial_verification_clamp_to_event_observation(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            session = self.ledger.start_session("evidence clock rollback")
        with mock.patch(
            "palimnex.durable.now_ms", side_effect=[2_000, 1_500, 1_400]
        ):
            event = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="evidence timestamp boundary",
                payload={"state": "verified"},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            )

        self.assertEqual(event["observed_at"], 2_000)
        with self.ledger.connection(create=False) as connection:
            evidence_at = connection.execute(
                "SELECT verified_at FROM evidence WHERE event_id=?",
                (bytes.fromhex(event["event_id"]),),
            ).fetchone()[0]
            verified_at = connection.execute(
                "SELECT verified_at FROM verifications WHERE event_id=?",
                (bytes.fromhex(event["event_id"]),),
            ).fetchone()[0]
            attempt = connection.execute(
                "SELECT attempt_sequence,checked_at FROM verification_attempts "
                "WHERE event_id=?",
                (bytes.fromhex(event["event_id"]),),
            ).fetchone()
        self.assertEqual(evidence_at, 2_000)
        self.assertEqual(verified_at, 2_000)
        self.assertEqual(tuple(attempt), (1, 2_000))
        self.assertEqual(self.ledger.status()["status"], "ready")

    def test_same_millisecond_attempts_use_sequence_not_random_id_order(self) -> None:
        original_evidence = self.root.joinpath("evidence.md").read_text(encoding="utf-8")
        cases = (
            ("verified-then-stale", False, b"\x10" * 16, b"\xf0" * 16),
            ("stale-then-verified", True, b"\xf0" * 16, b"\x10" * 16),
        )
        for name, final_verified, older_id, newer_id in cases:
            with self.subTest(name=name):
                self.root.joinpath("evidence.md").write_text(
                    original_evidence, encoding="utf-8"
                )
                ledger = MemoryLedger(
                    self.root / ".private" / f"attempt-order-{name}.sqlite3",
                    project_id=PROJECT_ID,
                    project_slug="memory-fixture",
                    root=self.root,
                )
                with mock.patch("palimnex.durable.now_ms", return_value=1_000):
                    session = ledger.start_session(f"attempt order {name}")
                with mock.patch("palimnex.durable.now_ms", return_value=2_000):
                    event = ledger.append_event(
                        session["session_id"],
                        "fact",
                        subject=f"same millisecond {name}",
                        payload={"state": "initial"},
                        evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                    )

                if final_verified:
                    self.root.joinpath("evidence.md").write_text(
                        "changed evidence\n", encoding="utf-8"
                    )
                with mock.patch(
                    "palimnex.durable._new_id", return_value=older_id
                ), mock.patch("palimnex.durable.now_ms", return_value=3_000):
                    first = ledger.reverify(event["event_id"])

                if final_verified:
                    self.root.joinpath("evidence.md").write_text(
                        original_evidence, encoding="utf-8"
                    )
                else:
                    self.root.joinpath("evidence.md").write_text(
                        "changed evidence\n", encoding="utf-8"
                    )
                with mock.patch(
                    "palimnex.durable._new_id", return_value=newer_id
                ), mock.patch("palimnex.durable.now_ms", return_value=3_000):
                    second = ledger.reverify(event["event_id"])

                self.assertNotEqual(first["verified"], second["verified"])
                self.assertEqual(second["verified"], final_verified)
                with ledger.connection(create=False) as connection:
                    attempts = connection.execute(
                        "SELECT attempt_id,attempt_sequence,checked_at,outcome "
                        "FROM verification_attempts WHERE event_id=? "
                        "ORDER BY attempt_sequence",
                        (bytes.fromhex(event["event_id"]),),
                    ).fetchall()
                self.assertEqual(
                    [row["attempt_sequence"] for row in attempts], [1, 2, 3]
                )
                self.assertEqual(
                    [row["checked_at"] for row in attempts[-2:]], [3_000, 3_000]
                )
                self.assertEqual(attempts[-2]["attempt_id"], older_id)
                self.assertEqual(attempts[-1]["attempt_id"], newer_id)
                recalled = ledger.recall(
                    f"same millisecond {name}", known_at=3_000, valid_at=3_000
                )["results"]
                if final_verified:
                    current = next(
                        item for item in recalled if item["event_id"] == event["event_id"]
                    )
                    self.assertEqual(current["trust"], "verified")
                else:
                    self.assertNotIn(
                        event["event_id"], {item["event_id"] for item in recalled}
                    )
                self.assertEqual(ledger.status()["status"], "ready")

    def test_reverify_clock_rollback_keeps_attempt_history_nondecreasing(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            session = self.ledger.start_session("reverify clock rollback")
        with mock.patch("palimnex.durable.now_ms", return_value=4_000):
            event = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="reverify rollback boundary",
                payload={"state": "initial"},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            )
        original_evidence = self.root.joinpath("evidence.md").read_text(encoding="utf-8")
        self.root.joinpath("evidence.md").write_text(
            "changed evidence\n", encoding="utf-8"
        )
        with mock.patch("palimnex.durable.now_ms", return_value=3_000):
            stale = self.ledger.reverify(event["event_id"])
        self.root.joinpath("evidence.md").write_text(
            original_evidence, encoding="utf-8"
        )
        with mock.patch("palimnex.durable.now_ms", return_value=2_000):
            verified = self.ledger.reverify(event["event_id"])

        self.assertEqual(stale["checked_at"], 4_000)
        self.assertEqual(verified["verified_at"], 4_000)
        with self.ledger.connection(create=False) as connection:
            attempts = connection.execute(
                "SELECT attempt_sequence,checked_at FROM verification_attempts "
                "WHERE event_id=? ORDER BY attempt_sequence",
                (bytes.fromhex(event["event_id"]),),
            ).fetchall()
        self.assertEqual(
            [(row["attempt_sequence"], row["checked_at"]) for row in attempts],
            [(1, 4_000), (2, 4_000), (3, 4_000)],
        )
        self.assertEqual(self.ledger.status()["status"], "ready")

    def test_attempt_ordinal_or_nonmonotonic_time_tamper_is_corrupt(self) -> None:
        for name in ("ordinal-gap", "time-regression"):
            with self.subTest(name=name):
                ledger = MemoryLedger(
                    self.root / ".private" / f"attempt-tamper-{name}.sqlite3",
                    project_id=PROJECT_ID,
                    project_slug="memory-fixture",
                    root=self.root,
                )
                with mock.patch("palimnex.durable.now_ms", return_value=1_000):
                    session = ledger.start_session(f"attempt tamper {name}")
                with mock.patch(
                    "palimnex.durable.now_ms",
                    side_effect=[2_000, 2_500, 3_000],
                ):
                    event = ledger.append_event(
                        session["session_id"],
                        "fact",
                        subject=f"attempt tamper {name}",
                        payload={"state": "verified"},
                        evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                    )
                with mock.patch("palimnex.durable.now_ms", return_value=4_000):
                    ledger.reverify(event["event_id"])
                with ledger.connection(create=False, write=True) as connection:
                    if name == "ordinal-gap":
                        connection.execute(
                            "UPDATE verification_attempts SET attempt_sequence=3 "
                            "WHERE event_id=? AND attempt_sequence=2",
                            (bytes.fromhex(event["event_id"]),),
                        )
                    else:
                        connection.execute(
                            "UPDATE verification_attempts SET checked_at=2500 "
                            "WHERE event_id=? AND attempt_sequence=2",
                            (bytes.fromhex(event["event_id"]),),
                        )
                        connection.execute(
                            "UPDATE verifications SET verified_at=2500 WHERE event_id=?",
                            (bytes.fromhex(event["event_id"]),),
                        )
                        connection.execute(
                            "UPDATE evidence SET verified_at=2500 WHERE event_id=?",
                            (bytes.fromhex(event["event_id"]),),
                        )

                status = ledger.status()
                self.assertEqual(status["status"], "corrupt")
                self.assertTrue(
                    any(
                        "verification attempt order" in error
                        for error in status["semantic_errors"]
                    ),
                    status,
                )
                with self.assertRaisesRegex(
                    ValueError, "semantic validation|attempt order"
                ):
                    ledger.recall(f"attempt tamper {name}")

    def test_append_is_atomic_when_graph_write_fails(self) -> None:
        session = self.ledger.start_session("atomic transaction")
        before = self.ledger.status()["counts"].copy()
        with mock.patch.object(
            self.ledger, "_write_event_graph", side_effect=RuntimeError("injected crash")
        ):
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                self.ledger.append_event(
                    session["session_id"],
                    "decision",
                    subject="atomic rollback",
                    payload={"result": "must disappear"},
                    evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                )
        after = self.ledger.status()["counts"]
        self.assertEqual(after, before)
        self.assertEqual(self.ledger.recall("must disappear")["results"], [])

    def test_subject_only_provider_credential_is_rejected_without_any_leak(self) -> None:
        session = self.ledger.start_session("subject privacy admission")
        canary = "".join(("gh", "p_", "A7b9" * 6))
        canary_bytes = canary.encode("utf-8")
        tables = ("events", "evidence", "nodes", "edges", "projection_outbox")

        def table_counts() -> dict[str, int]:
            with self.ledger.connection(create=False) as connection:
                return {
                    table: connection.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                    for table in tables
                }

        before = table_counts()
        before_status = self.ledger.status()["counts"]
        with self.assertRaisesRegex(
            ValueError, "subject rejected by privacy policy: github-token@1"
        ):
            self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=canary,
                payload={"result": "must not be stored"},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            )

        self.assertEqual(table_counts(), before)
        self.assertEqual(self.ledger.status()["counts"], before_status)
        ledger_material = b"".join(
            path.read_bytes()
            for path in (
                self.ledger.path,
                Path(str(self.ledger.path) + "-wal"),
                Path(str(self.ledger.path) + "-shm"),
            )
            if path.exists()
        )
        self.assertNotIn(canary_bytes, ledger_material)

        client = FakeRedis()
        projected = self.ledger.project_outbox(client, "fixture:subject-privacy")
        self.assertEqual(projected["remaining"], 0)
        self.assertNotIn(canary_bytes, client.all_stored_bytes())

    def test_nested_sensitive_json_is_rejected_before_any_durable_write(self) -> None:
        session = self.ledger.start_session("nested privacy admission")
        canary = "".join(("Z7mQ2vN9", "kP4rT8xW", "3cH6sL1y", "B5dF"))
        canary_bytes = canary.encode("utf-8")
        tables = ("events", "event_terms", "evidence", "nodes", "edges", "projection_outbox")

        def table_counts() -> dict[str, int]:
            with self.ledger.connection(create=False) as connection:
                return {
                    table: connection.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                    for table in tables
                }

        before = table_counts()
        before_status = self.ledger.status()["counts"]
        payload = {
            "outer": {
                "services": [
                    {"configuration": {"api_key": canary}},
                ]
            }
        }
        with self.assertRaisesRegex(ValueError, "content privacy policy") as raised:
            self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="nested credential admission",
                payload=payload,
            )

        self.assertNotIn(canary, str(raised.exception))
        self.assertEqual(table_counts(), before)
        self.assertEqual(self.ledger.status()["counts"], before_status)
        ledger_material = b"".join(
            path.read_bytes()
            for path in (
                self.ledger.path,
                Path(str(self.ledger.path) + "-wal"),
                Path(str(self.ledger.path) + "-shm"),
            )
            if path.exists()
        )
        self.assertNotIn(canary_bytes, ledger_material)

    def test_session_start_close_and_workflow_failures_roll_back_whole_operations(self) -> None:
        before = self.ledger.status()["counts"].copy()
        with mock.patch.object(
            self.ledger, "_append_event_tx", side_effect=RuntimeError("start crash")
        ):
            with self.assertRaisesRegex(RuntimeError, "start crash"):
                self.ledger.start_session("must not leave an orphan session")
        self.assertEqual(self.ledger.status()["counts"], before)

        session = self.ledger.start_session("transaction boundaries")
        before_close = self.ledger.status()["counts"].copy()
        original_append = self.ledger._append_event_tx

        def append_then_crash(*args, **kwargs):
            original_append(*args, **kwargs)
            raise RuntimeError("operation crash")

        with mock.patch.object(self.ledger, "_append_event_tx", side_effect=append_then_crash):
            with self.assertRaisesRegex(RuntimeError, "operation crash"):
                self.ledger.close_session(session["session_id"], outcome="must roll back")
        self.assertEqual(self.ledger.status()["counts"], before_close)
        self.ledger.append_event(
            session["session_id"], "fact", subject="still open", payload="yes"
        )

        before_workflow = self.ledger.status()["counts"].copy()
        with mock.patch.object(self.ledger, "_append_event_tx", side_effect=append_then_crash):
            with self.assertRaisesRegex(RuntimeError, "operation crash"):
                self.ledger.put_workflow(
                    session["session_id"],
                    "crashing workflow",
                    {
                        "version": 1,
                        "steps": [
                            {
                                "id": "inspect",
                                "action": "read status",
                                "preconditions": "source exists",
                                "expected": "status returned",
                                "rollback": "none required",
                                "side_effect": "read",
                            }
                        ],
                    },
                    evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                )
        self.assertEqual(self.ledger.status()["counts"], before_workflow)

    def test_verified_closed_session_can_promote_but_never_authorize(self) -> None:
        session = self.ledger.start_session("promotion boundary")
        event = self.ledger.append_event(
            session["session_id"],
            "decision",
            subject="local proof",
            payload={"local proof": "verified historical guidance"},
            evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            retention="durable",
        )
        self.assertTrue(event["verified"])
        self.assertFalse(event["authorizes_actions"])
        self.ledger.close_session(session["session_id"], outcome="done")
        promotion = self.ledger.consolidate(session["session_id"])
        self.assertEqual(promotion["promoted"], [event["event_id"]])
        result = self.ledger.recall("verified historical guidance", promoted_only=True)
        self.assertEqual(result["results"][0]["trust"], "verified")
        self.assertEqual(result["results"][0]["authority"], "historical_only")
        self.assertFalse(result["results"][0]["authorizes_actions"])

    def test_promotion_visibility_and_flag_are_as_of_known_at(self) -> None:
        subject = "heliotropepromotionclock"
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            session = self.ledger.start_session("promotion time boundary")
        with mock.patch("palimnex.durable.now_ms", return_value=1_100):
            event = self.ledger.append_event(
                session["session_id"],
                "decision",
                subject=subject,
                payload={"state": "candidate"},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                retention="durable",
            )
        with mock.patch("palimnex.durable.now_ms", return_value=1_200):
            self.ledger.close_session(session["session_id"], outcome="candidate closed")
        with mock.patch("palimnex.durable.now_ms", return_value=2_000):
            promoted = self.ledger.consolidate(session["session_id"])
        self.assertEqual(promoted["promoted"], [event["event_id"]])

        before = self.ledger.recall(
            subject, known_at=1_999, valid_at=2_500
        )["results"]
        self.assertEqual([item["event_id"] for item in before], [event["event_id"]])
        self.assertFalse(before[0]["promoted"])
        self.assertEqual(
            self.ledger.recall(
                subject,
                known_at=1_999,
                valid_at=2_500,
                promoted_only=True,
            )["results"],
            [],
        )
        for known_at in (2_000, 2_001):
            with self.subTest(known_at=known_at):
                ordinary = self.ledger.recall(
                    subject, known_at=known_at, valid_at=2_500
                )["results"]
                self.assertEqual(
                    [item["event_id"] for item in ordinary], [event["event_id"]]
                )
                self.assertTrue(ordinary[0]["promoted"])
                promoted_only = self.ledger.recall(
                    subject,
                    known_at=known_at,
                    valid_at=2_500,
                    promoted_only=True,
                )["results"]
                self.assertEqual(
                    [item["event_id"] for item in promoted_only], [event["event_id"]]
                )

    def test_untrusted_successor_cannot_hide_or_block_verified_predecessor(self) -> None:
        session = self.ledger.start_session("trust poison boundary")
        subject = "shared trust poison state"
        predecessor = self.ledger.append_event(
            session["session_id"],
            "decision",
            subject=subject,
            payload={"state": "locally verified predecessor"},
            evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            retention="durable",
        )
        poison = self.ledger.append_event(
            session["session_id"],
            "correction",
            subject=subject,
            payload={"state": "untrusted successor"},
            supersedes=predecessor["event_id"],
            trust="untrusted",
            retention="durable",
        )
        self.ledger.close_session(session["session_id"], outcome="trust boundary closed")

        trusted_current = self.ledger.recall(subject)["results"]
        self.assertIn(
            predecessor["event_id"], {item["event_id"] for item in trusted_current}
        )
        self.assertNotIn(poison["event_id"], {item["event_id"] for item in trusted_current})

        untrusted_current = self.ledger.recall(
            subject, include_untrusted=True
        )["results"]
        self.assertIn(poison["event_id"], {item["event_id"] for item in untrusted_current})
        self.assertNotIn(
            predecessor["event_id"], {item["event_id"] for item in untrusted_current}
        )

        consolidation = self.ledger.consolidate(session["session_id"])
        self.assertIn(predecessor["event_id"], consolidation["promoted"])
        self.assertNotIn(poison["event_id"], consolidation["promoted"])
        self.assertEqual(self.ledger.status()["status"], "ready")

        promoted_current = self.ledger.recall(
            subject, promoted_only=True
        )["results"]
        self.assertEqual(
            {item["event_id"] for item in promoted_current},
            {predecessor["event_id"]},
        )

    def test_promoted_only_supersession_requires_verified_and_promoted_successor(self) -> None:
        session = self.ledger.start_session("eligible promoted successor")
        subject = "eligible successor predicate"
        predecessor = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject=subject,
            payload={"state": "predecessor"},
            evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            retention="durable",
        )
        successor = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject=subject,
            payload={"state": "eligible successor"},
            supersedes=predecessor["event_id"],
            evidence=[{"kind": "source", "locator": "evidence.md:2"}],
            retention="durable",
        )
        self.ledger.close_session(session["session_id"], outcome="successor closed")
        predicate = _eligible_supersessor_exists_sql(
            "e.event_id", include_untrusted=False, promoted_only=True
        )
        with self.ledger.connection(create=False) as connection:
            before = connection.execute(
                f"SELECT {predicate} FROM events e WHERE e.event_id=?",
                (bytes.fromhex(predecessor["event_id"]),),
            ).fetchone()[0]
        self.assertEqual(before, 0, "verification alone must not suppress promoted recall")

        consolidation = self.ledger.consolidate(session["session_id"])
        self.assertEqual(consolidation["promoted"], [successor["event_id"]])
        with self.ledger.connection(create=False) as connection:
            after = connection.execute(
                f"SELECT {predicate} FROM events e WHERE e.event_id=?",
                (bytes.fromhex(predecessor["event_id"]),),
            ).fetchone()[0]
        self.assertEqual(after, 1)
        promoted = self.ledger.recall(subject, promoted_only=True)["results"]
        self.assertEqual(
            {item["event_id"] for item in promoted}, {successor["event_id"]}
        )

    def test_cross_session_promotions_remain_valid_as_history_advances(self) -> None:
        subject = "cross session promotion history"
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            first_session = self.ledger.start_session("promote predecessor")
        with mock.patch("palimnex.durable.now_ms", return_value=1_100):
            predecessor = self.ledger.append_event(
                first_session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "first"},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                retention="durable",
            )
        with mock.patch("palimnex.durable.now_ms", return_value=1_200):
            self.ledger.close_session(first_session["session_id"], outcome="first closed")
        with mock.patch("palimnex.durable.now_ms", return_value=1_300):
            self.assertEqual(
                self.ledger.consolidate(first_session["session_id"])["promoted"],
                [predecessor["event_id"]],
            )

        with mock.patch("palimnex.durable.now_ms", return_value=2_000):
            second_session = self.ledger.start_session("promote successor later")
        with mock.patch("palimnex.durable.now_ms", return_value=2_100):
            successor = self.ledger.append_event(
                second_session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "second"},
                supersedes=predecessor["event_id"],
                evidence=[{"kind": "source", "locator": "evidence.md:2"}],
                retention="durable",
            )
        with mock.patch("palimnex.durable.now_ms", return_value=2_200):
            self.ledger.close_session(second_session["session_id"], outcome="second closed")

        self.assertEqual(self.ledger.status()["status"], "ready")
        before_successor_promotion = self.ledger.recall(
            subject, known_at=3_000, valid_at=3_000, promoted_only=True
        )["results"]
        self.assertEqual(
            {item["event_id"] for item in before_successor_promotion},
            {predecessor["event_id"]},
        )

        with mock.patch("palimnex.durable.now_ms", return_value=2_300):
            self.assertEqual(
                self.ledger.consolidate(second_session["session_id"])["promoted"],
                [successor["event_id"]],
            )
        self.assertEqual(self.ledger.status()["status"], "ready")
        after_successor_promotion = self.ledger.recall(
            subject, known_at=3_000, valid_at=3_000, promoted_only=True
        )["results"]
        self.assertEqual(
            {item["event_id"] for item in after_successor_promotion},
            {successor["event_id"]},
        )
        retrospective = self.ledger.recall(
            subject, known_at=2_299, valid_at=3_000, promoted_only=True
        )["results"]
        self.assertEqual(
            {item["event_id"] for item in retrospective},
            {predecessor["event_id"]},
            "a future promotion must not suppress the predecessor retrospectively",
        )
        at_successor_promotion = self.ledger.recall(
            subject, known_at=2_300, valid_at=3_000, promoted_only=True
        )["results"]
        self.assertEqual(
            {item["event_id"] for item in at_successor_promotion},
            {successor["event_id"]},
        )
        historical = self.ledger.recall(
            subject,
            known_at=2_299,
            valid_at=3_000,
            include_history=True,
        )["results"]
        promoted_flags = {item["event_id"]: item["promoted"] for item in historical}
        self.assertTrue(promoted_flags[predecessor["event_id"]])
        self.assertFalse(promoted_flags[successor["event_id"]])

    def test_future_effective_successor_does_not_veto_early_consolidation(self) -> None:
        subject = "future effective promotion history"
        with mock.patch("palimnex.durable.now_ms", return_value=3_000):
            session = self.ledger.start_session("future successor")
        with mock.patch("palimnex.durable.now_ms", return_value=3_100):
            predecessor = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "effective now"},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                retention="durable",
                valid_from=3_100,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=3_150):
            successor = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "effective later"},
                supersedes=predecessor["event_id"],
                evidence=[{"kind": "source", "locator": "evidence.md:2"}],
                retention="durable",
                valid_from=5_000,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=3_200):
            self.ledger.close_session(session["session_id"], outcome="future fact recorded")

        with mock.patch("palimnex.durable.now_ms", return_value=4_000):
            early = self.ledger.consolidate(session["session_id"])
        self.assertIn(predecessor["event_id"], early["promoted"])
        self.assertNotIn(successor["event_id"], early["promoted"])
        self.assertEqual(
            {
                item["event_id"]
                for item in self.ledger.recall(
                    subject,
                    known_at=4_000,
                    valid_at=4_000,
                    promoted_only=True,
                )["results"]
            },
            {predecessor["event_id"]},
        )

        with mock.patch("palimnex.durable.now_ms", return_value=6_000):
            later = self.ledger.consolidate(session["session_id"])
        self.assertEqual(later["promoted"], [successor["event_id"]])
        self.assertEqual(self.ledger.status()["status"], "ready")

    def test_changed_source_evidence_cannot_reverify_or_power_current_recall(self) -> None:
        session = self.ledger.start_session("source evidence freshness")
        subject = "source backed durable fact"
        event = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject=subject,
            payload={"state": "verified against source"},
            evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            retention="durable",
        )
        self.ledger.close_session(session["session_id"], outcome="verified source closed")
        self.assertEqual(
            self.ledger.consolidate(session["session_id"])["promoted"],
            [event["event_id"]],
        )
        self.assertIn(
            event["event_id"],
            {item["event_id"] for item in self.ledger.recall(subject)["results"]},
        )

        evidence_path = self.root / "evidence.md"
        evidence_path.write_text(
            "edited evidence line\nsecond evidence line\n", encoding="utf-8"
        )
        self.assertNotIn(
            event["event_id"],
            {item["event_id"] for item in self.ledger.recall(subject)["results"]},
        )
        self.assertNotIn(
            event["event_id"],
            {
                item["event_id"]
                for item in self.ledger.recall(subject, promoted_only=True)["results"]
            },
        )
        self.assertIn(
            event["event_id"],
            {
                item["event_id"]
                for item in self.ledger.recall(subject, include_history=True)["results"]
            },
        )

        stale = self.ledger.reverify(event["event_id"])
        self.assertFalse(stale["verified"])
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["reason"], "changed")
        self.assertTrue(stale["invalidated_previous_verification"])
        self.assertTrue(stale["invalidated_promotion"])
        self.assertNotIn(
            event["event_id"],
            {item["event_id"] for item in self.ledger.recall(subject)["results"]},
        )

    def test_non_durable_retention_cannot_be_consolidated(self) -> None:
        session = self.ledger.start_session("retention promotion boundary")
        events = [
            self.ledger.append_event(
                session["session_id"],
                "decision",
                subject=f"{retention} historical fact",
                payload={"retention": retention},
                evidence=[{"kind": "source", "locator": "evidence.md:1"}],
                retention=retention,
            )
            for retention in ("volatile", "session")
        ]
        self.assertTrue(all(event["verified"] for event in events))
        self.ledger.close_session(session["session_id"], outcome="done")

        promotion = self.ledger.consolidate(session["session_id"])

        self.assertEqual(promotion["promoted"], [])
        for retention, event in zip(("volatile", "session"), events, strict=True):
            query = f"{retention} historical fact"
            self.assertIn(
                event["event_id"],
                {item["event_id"] for item in self.ledger.recall(query)["results"]},
            )
            self.assertEqual(
                self.ledger.recall(query, promoted_only=True)["results"],
                [],
            )

    def test_hot_projection_is_bounded_metadata_not_event_payload(self) -> None:
        session = self.ledger.start_session("hot projection")
        marker = "payload must stay in sqlite authority"
        event = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject="projection boundary",
            payload={"detail": marker},
        )
        client = FakeRedis()
        projected = self.ledger.project_outbox(client, "fixture:hot", limit=100)
        effective_namespace = projected["hot_namespace"]
        self.assertEqual(
            effective_namespace,
            self.ledger.hot_projection_namespace("fixture:hot"),
        )
        self.assertIn(event["event_id"], projected["delivered"])
        self.assertEqual(projected["delivered_count"], projected["appended_count"])
        self.assertEqual(projected["deduplicated_count"], 0)
        self.assertNotIn(marker.encode(), client.all_stored_bytes())
        stream = client.streams[f"{effective_namespace}:events"]
        self.assertEqual(set(stream[-1]), {
            "event", "session", "kind", "subject", "observed", "supersedes",
            "contradicts", "trust", "sensitivity", "digest",
        })

    def test_hot_projection_can_be_exactly_rebuilt_after_redis_loss(self) -> None:
        session = self.ledger.start_session("hot cache rebuild")
        subject = "rebuild relation subject"
        payload_marker = "durable payload must never enter hot redis"
        original = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject=subject,
            payload={"detail": payload_marker, "state": "original"},
        )
        replacement = self.ledger.append_event(
            session["session_id"],
            "correction",
            subject=subject,
            payload={"detail": payload_marker, "state": "replacement"},
            supersedes=original["event_id"],
        )
        contradiction = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject=subject,
            payload={"detail": payload_marker, "state": "opposed"},
            contradicts=replacement["event_id"],
        )
        client = FakeRedis()
        namespace = "fixture:hot-rebuild"
        first = self.ledger.project_outbox(client, namespace, limit=100)
        effective_namespace = first["hot_namespace"]
        self.assertEqual(
            effective_namespace, self.ledger.hot_projection_namespace(namespace)
        )
        self.assertEqual(first["remaining"], 0)
        self.assertEqual(first["delivered_count"], first["appended_count"])
        self.assertEqual(first["deduplicated_count"], 0)

        # A rebuild request while Redis still has its exactly-once markers
        # acknowledges every eligible SQLite row without appending again.
        original_stream = list(client.streams[f"{effective_namespace}:events"])
        retained_reset = self.ledger.reset_hot_projection()
        retained_batches = []
        while True:
            batch = self.ledger.project_outbox(
                client, namespace, limit=2, force=True
            )
            retained_batches.append(batch)
            self.assertEqual(batch["hot_namespace"], effective_namespace)
            if batch["remaining"] == 0:
                break
            self.assertLess(
                len(retained_batches), 20, "deduplicating rebuild did not converge"
            )
        self.assertEqual(
            sum(batch["delivered_count"] for batch in retained_batches),
            retained_reset["eligible"],
        )
        self.assertEqual(
            sum(batch["appended_count"] for batch in retained_batches), 0
        )
        self.assertEqual(
            sum(batch["deduplicated_count"] for batch in retained_batches),
            retained_reset["eligible"],
        )
        self.assertEqual(
            client.streams[f"{effective_namespace}:events"], original_stream
        )

        client.values.clear()
        client.hashes.clear()
        client.streams.clear()
        client.stream_ids.clear()
        client.stream_counters.clear()
        client.expiries.clear()
        reset = self.ledger.reset_hot_projection()
        self.assertEqual(reset["reset"], reset["eligible"])

        batches = []
        while True:
            batch = self.ledger.project_outbox(
                client, namespace, limit=2, force=True
            )
            batches.append(batch)
            self.assertEqual(batch["hot_namespace"], effective_namespace)
            if batch["remaining"] == 0:
                break
            self.assertLess(len(batches), 20, "bounded rebuild did not converge")

        self.assertTrue(all(batch["forced"] for batch in batches))
        self.assertTrue(all(batch["delivered_count"] <= 2 for batch in batches))
        self.assertEqual(sum(batch["delivered_count"] for batch in batches), reset["eligible"])
        self.assertEqual(sum(batch["appended_count"] for batch in batches), reset["eligible"])
        self.assertEqual(sum(batch["deduplicated_count"] for batch in batches), 0)
        self.assertEqual(batches[-1]["remaining"], 0)
        self.assertNotIn(payload_marker.encode(), client.all_stored_bytes())
        expected_fields = {
            "event", "session", "kind", "subject", "observed", "supersedes",
            "contradicts", "trust", "sensitivity", "digest",
        }
        self.assertTrue(client.streams[f"{effective_namespace}:events"])
        self.assertTrue(
            all(
                set(record) == expected_fields
                for record in client.streams[f"{effective_namespace}:events"]
            )
        )

        subject_digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        self.assertIsNone(
            client.execute("GET", f"{effective_namespace}:active:{subject_digest}")
        )
        self.assertEqual(
            client.execute(
                "GET", f"{effective_namespace}:latest-projected:{subject_digest}"
            ),
            contradiction["event_id"].encode(),
        )
        self.assertEqual(
            client.execute(
                "GET", f"{effective_namespace}:superseded-by:{original['event_id']}"
            ),
            replacement["event_id"].encode(),
        )
        self.assertEqual(
            client.execute(
                "GET",
                f"{effective_namespace}:contradicted-by:{replacement['event_id']}",
            ),
            contradiction["event_id"].encode(),
        )

    def test_hot_projection_retry_after_receipt_expiry_and_sqlite_ack_failure_does_not_duplicate(self) -> None:
        self.ledger.start_session("projection crash window")
        client = FakeRedis()
        namespace = "fixture:hot-crash"
        effective_namespace = self.ledger.hot_projection_namespace(namespace)
        original_open = self.ledger._open

        class FailAcknowledgement:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, statement, *parameters):
                if "UPDATE projection_outbox SET delivered_at" in statement:
                    raise RuntimeError("injected SQLite acknowledgement failure")
                return self.connection.execute(statement, *parameters)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def open_with_failed_ack(*, create: bool):
            return FailAcknowledgement(original_open(create=create))

        with mock.patch.object(self.ledger, "_open", side_effect=open_with_failed_ack):
            with self.assertRaisesRegex(RuntimeError, "acknowledgement failure"):
                self.ledger.project_outbox(client, namespace, limit=1)

        stream_key = f"{effective_namespace}:events"
        self.assertEqual(len(client.streams[stream_key]), 1)
        with self.ledger.connection(create=False) as connection:
            row = connection.execute(
                "SELECT e.event_id,o.attempted_at,o.delivered_at "
                "FROM projection_outbox o JOIN events e ON e.event_id=o.event_id "
                "ORDER BY o.outbox_id LIMIT 1"
            ).fetchone()
        self.assertIsNotNone(row["attempted_at"])
        self.assertIsNone(row["delivered_at"])
        receipt_key = f"{effective_namespace}:event:{row['event_id'].hex()}"
        self.assertIsNotNone(client.execute("GET", receipt_key))
        client.values.pop(receipt_key)
        client.expiries.pop(receipt_key, None)

        retry = self.ledger.project_outbox(client, namespace, limit=1)
        self.assertEqual(retry["delivered_count"], 1)
        self.assertEqual(retry["appended_count"], 0)
        self.assertEqual(retry["deduplicated_count"], 1)
        self.assertEqual(retry["hot_namespace"], effective_namespace)
        self.assertEqual(len(client.streams[stream_key]), 1)
        self.assertIsNotNone(client.execute("GET", receipt_key))

    def test_hot_projection_refuses_poisoned_receipts_until_clean_rebuild(self) -> None:
        refusing_variants = (
            "marker-only",
            "wrong-receipt-digest",
            "mismatched-stream-record",
            "duplicate-stream-record",
        )
        for name in refusing_variants:
            with self.subTest(name=name):
                ledger = MemoryLedger(
                    self.root / ".private" / f"projection-poison-{name}.sqlite3",
                    project_id=PROJECT_ID,
                    project_slug="memory-fixture",
                    root=self.root,
                )
                ledger.initialize()
                session = ledger.start_session(f"projection poison {name}")
                event_id = session["event"]["event_id"]
                namespace = f"fixture:projection-poison:{name}"
                effective_namespace = ledger.hot_projection_namespace(namespace)
                stream_key = f"{effective_namespace}:events"
                receipt_key = f"{effective_namespace}:event:{event_id}"
                client = FakeRedis()

                if name == "marker-only":
                    client.execute("SET", receipt_key, "1")
                else:
                    initial = ledger.project_outbox(client, namespace, limit=1)
                    self.assertEqual(initial["appended_count"], 1)
                    self.assertEqual(initial["hot_namespace"], effective_namespace)
                    ledger.reset_hot_projection()
                    receipt = client.values[receipt_key]
                    stream_id, digest = receipt.split(b"|", 1)
                    if name == "wrong-receipt-digest":
                        client.values[receipt_key] = stream_id + b"|" + b"0" * 64
                    elif name == "mismatched-stream-record":
                        client.streams[stream_key][0]["event"] = b"f" * 32
                    else:
                        client.values.pop(receipt_key)
                        client.expiries.pop(receipt_key, None)
                        client.streams[stream_key].append(
                            dict(client.streams[stream_key][0])
                        )
                        client.stream_ids[stream_key].append(b"999999-0")

                with self.assertRaisesRegex(
                    ValueError, "receipt is stale or differs"
                ):
                    ledger.project_outbox(client, namespace, limit=1, force=True)
                self.assertEqual(ledger.status()["projection_pending"], 1)
                with ledger.connection(create=False) as connection:
                    delivered_at = connection.execute(
                        "SELECT delivered_at FROM projection_outbox o "
                        "JOIN events e ON e.event_id=o.event_id "
                        "WHERE e.event_id=?",
                        (bytes.fromhex(event_id),),
                    ).fetchone()[0]
                self.assertIsNone(delivered_at)

                client.values.clear()
                client.hashes.clear()
                client.streams.clear()
                client.stream_ids.clear()
                client.stream_counters.clear()
                client.expiries.clear()
                repaired = ledger.project_outbox(client, namespace, limit=1, force=True)
                self.assertEqual(repaired["hot_namespace"], effective_namespace)
                self.assertEqual(repaired["delivered_count"], 1)
                self.assertEqual(repaired["appended_count"], 1)
                self.assertEqual(repaired["deduplicated_count"], 0)
                self.assertEqual(repaired["remaining"], 0)
                recent = ledger.hot_events(client, namespace, limit=1)["results"]
                self.assertEqual([item["event_id"] for item in recent], [event_id])

    def test_hot_projection_repairs_a_wrong_receipt_id_or_absent_stream_record(self) -> None:
        for name in ("wrong-receipt-id", "absent-stream-record"):
            with self.subTest(name=name):
                ledger = MemoryLedger(
                    self.root / ".private" / f"projection-repair-{name}.sqlite3",
                    project_id=PROJECT_ID,
                    project_slug="memory-fixture",
                    root=self.root,
                )
                ledger.initialize()
                session = ledger.start_session(f"projection repair {name}")
                event_id = session["event"]["event_id"]
                namespace = f"fixture:projection-repair:{name}"
                initial = ledger.project_outbox(client := FakeRedis(), namespace, limit=1)
                effective_namespace = initial["hot_namespace"]
                stream_key = f"{effective_namespace}:events"
                receipt_key = f"{effective_namespace}:event:{event_id}"
                self.assertEqual(initial["appended_count"], 1)
                ledger.reset_hot_projection()
                _, digest = client.values[receipt_key].split(b"|", 1)
                if name == "wrong-receipt-id":
                    client.values[receipt_key] = b"999999-0|" + digest
                    expected_appended = 0
                    expected_deduplicated = 1
                else:
                    client.streams[stream_key].clear()
                    client.stream_ids[stream_key].clear()
                    expected_appended = 1
                    expected_deduplicated = 0

                repaired = ledger.project_outbox(client, namespace, limit=1, force=True)
                self.assertEqual(repaired["hot_namespace"], effective_namespace)
                self.assertEqual(repaired["appended_count"], expected_appended)
                self.assertEqual(repaired["deduplicated_count"], expected_deduplicated)
                self.assertEqual(repaired["remaining"], 0)
                self.assertEqual(len(client.streams[stream_key]), 1)
                receipt_id, receipt_digest = client.values[receipt_key].split(b"|", 1)
                self.assertEqual(receipt_id, client.stream_ids[stream_key][0])
                self.assertEqual(receipt_digest, digest)

    def test_hot_event_consumer_groups_sessions_newest_first_without_payloads(self) -> None:
        first_session = self.ledger.start_session("first hot consumer session")
        first_event = self.ledger.append_event(
            first_session["session_id"],
            "fact",
            subject="first hot event",
            payload={"private_detail": "first payload stays in sqlite"},
        )
        second_session = self.ledger.start_session("second hot consumer session")
        second_event = self.ledger.append_event(
            second_session["session_id"],
            "fact",
            subject="second hot event",
            payload={"private_detail": "second payload stays in sqlite"},
        )
        client = FakeRedis()
        namespace = "fixture:hot-consumer"
        projected = self.ledger.project_outbox(client, namespace, limit=100)
        self.assertEqual(projected["remaining"], 0)

        recent = self.ledger.hot_events(client, namespace, limit=100)
        self.assertEqual(recent["results"][0]["event_id"], second_event["event_id"])
        self.assertFalse(recent["payloads_included"])
        self.assertEqual(recent["payload_authority"], "sqlite")
        for item in recent["results"]:
            self.assertNotIn("payload", item)
            self.assertEqual(item["authority"], "historical_only")
            self.assertFalse(item["authorizes_actions"])

        grouped = self.ledger.hot_events(
            client,
            namespace,
            session_id=first_session["session_id"],
            limit=100,
        )
        self.assertTrue(grouped["results"])
        self.assertTrue(
            all(
                item["session_id"] == first_session["session_id"]
                for item in grouped["results"]
            )
        )
        self.assertIn(
            first_event["event_id"], {item["event_id"] for item in grouped["results"]}
        )
        self.assertNotIn(
            second_event["event_id"], {item["event_id"] for item in grouped["results"]}
        )
        limited = self.ledger.hot_events(client, namespace, limit=1)
        self.assertEqual(
            [item["event_id"] for item in limited["results"]],
            [second_event["event_id"]],
        )
        self.assertNotIn(b"payload stays in sqlite", client.all_stored_bytes())

    def test_hot_event_consumer_refuses_malformed_stream_records(self) -> None:
        session = self.ledger.start_session("malformed hot stream")
        self.ledger.append_event(
            session["session_id"], "fact", subject="valid hot record", payload="sqlite"
        )
        client = FakeRedis()
        namespace = "fixture:hot-malformed"
        projected = self.ledger.project_outbox(client, namespace)
        effective_namespace = projected["hot_namespace"]
        valid = client.execute(
            "XREVRANGE",
            f"{effective_namespace}:events",
            "+",
            "-",
            "COUNT",
            str(durable.HOT_STREAM_MAXLEN),
        )
        invalid_typed = [[valid[0][0], list(valid[0][1])]]
        invalid_typed[0][1][-1] = b"not-a-record-digest"
        variants = (
            {"not": "a list"},
            [[b"1-0", [b"event", b"too-few-fields"]]],
            invalid_typed,
            [None] * (durable.HOT_STREAM_MAXLEN + 1),
        )
        for response in variants:
            with self.subTest(response_type=type(response).__name__), mock.patch.object(
                client, "execute", return_value=response
            ):
                with self.assertRaisesRegex(ValueError, "malformed|invalid|unexpected"):
                    self.ledger.hot_events(client, namespace)

    def test_hot_event_consumer_verifies_entire_batch_before_limit(self) -> None:
        first_session = self.ledger.start_session("authoritative hot first")
        self.ledger.append_event(
            first_session["session_id"],
            "fact",
            subject="authoritative hot first event",
            payload="sqlite one",
        )
        second_session = self.ledger.start_session("authoritative hot second")
        self.ledger.append_event(
            second_session["session_id"],
            "fact",
            subject="authoritative hot second event",
            payload="sqlite two",
        )
        namespace = "fixture:hot-authoritative"
        projected = FakeRedis()
        projection = self.ledger.project_outbox(projected, namespace)
        stream_key = f"{projection['hot_namespace']}:events"
        authoritative = [dict(record) for record in projected.streams[stream_key]]

        def unknown(records: list[dict[str, bytes]]) -> None:
            records[0]["event"] = b"0" * 32

        def duplicate(records: list[dict[str, bytes]]) -> None:
            records.insert(0, dict(records[-1]))

        def forged_session(records: list[dict[str, bytes]]) -> None:
            records[0]["session"] = second_session["session_id"].encode("ascii")

        def forged_kind(records: list[dict[str, bytes]]) -> None:
            records[0]["kind"] = b"7" if records[0]["kind"] != b"7" else b"3"

        def forged_subject(records: list[dict[str, bytes]]) -> None:
            records[0]["subject"] = b"0" * 64

        def forged_observed(records: list[dict[str, bytes]]) -> None:
            records[0]["observed"] = str(int(records[0]["observed"]) + 1).encode()

        def forged_supersedes(records: list[dict[str, bytes]]) -> None:
            records[0]["supersedes"] = b"0" * 32

        def forged_contradicts(records: list[dict[str, bytes]]) -> None:
            records[0]["contradicts"] = b"0" * 32

        def forged_trust(records: list[dict[str, bytes]]) -> None:
            records[0]["trust"] = b"0" if records[0]["trust"] != b"0" else b"1"

        def forged_sensitivity(records: list[dict[str, bytes]]) -> None:
            records[0]["sensitivity"] = (
                b"2" if records[0]["sensitivity"] != b"2" else b"1"
            )

        def stale_digest(records: list[dict[str, bytes]]) -> None:
            records[0]["digest"] = b"0" * 64

        for name, mutate in (
            ("unknown", unknown),
            ("duplicate", duplicate),
            ("session", forged_session),
            ("kind", forged_kind),
            ("subject", forged_subject),
            ("observed", forged_observed),
            ("supersedes", forged_supersedes),
            ("contradicts", forged_contradicts),
            ("trust", forged_trust),
            ("sensitivity", forged_sensitivity),
            ("stale", stale_digest),
        ):
            with self.subTest(name=name):
                client = FakeRedis()
                client.streams[stream_key] = [dict(record) for record in authoritative]
                mutate(client.streams[stream_key])
                with self.assertRaisesRegex(
                    ValueError,
                    "authoritative|duplicate|unknown|mismatch|stale|forged|differ",
                ):
                    self.ledger.hot_events(client, namespace, limit=1)

    def test_hot_event_consumer_verifies_rows_before_session_filtering(self) -> None:
        first_session = self.ledger.start_session("filtered hot first")
        self.ledger.append_event(
            first_session["session_id"], "fact", subject="filtered first", payload="one"
        )
        second_session = self.ledger.start_session("filtered hot second")
        self.ledger.append_event(
            second_session["session_id"], "fact", subject="filtered second", payload="two"
        )
        client = FakeRedis()
        namespace = "fixture:hot-filter-authority"
        projection = self.ledger.project_outbox(client, namespace)
        stream_key = f"{projection['hot_namespace']}:events"
        client.streams[stream_key][0]["event"] = b"f" * 32

        with self.assertRaisesRegex(
            ValueError, "authoritative|unknown|mismatch|stale|differ"
        ):
            self.ledger.hot_events(
                client,
                namespace,
                session_id=second_session["session_id"],
                limit=100,
            )

    def test_latest_subject_pointer_is_delivery_metadata_not_current_truth(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=100):
            session = self.ledger.start_session("active pointer semantics")
        subject = "active pointer subject"
        with mock.patch("palimnex.durable.now_ms", return_value=400):
            current = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "current"},
                valid_from=400,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=500):
            contradiction = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "contradiction"},
                contradicts=current["event_id"],
                valid_from=500,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=600):
            untrusted = self.ledger.append_event(
                session["session_id"],
                "correction",
                subject=subject,
                payload={"state": "untrusted correction"},
                supersedes=current["event_id"],
                trust="untrusted",
                valid_from=600,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=300):
            backdated = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "backdated"},
                valid_from=300,
            )
        client = FakeRedis()
        namespace = "fixture:active-pointer"
        projection = self.ledger.project_outbox(client, namespace)
        effective_namespace = projection["hot_namespace"]
        subject_digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        active_key = f"{effective_namespace}:active:{subject_digest}"
        latest_key = f"{effective_namespace}:latest-projected:{subject_digest}"
        self.assertIsNone(client.execute("GET", active_key))
        self.assertEqual(
            client.execute("GET", latest_key), backdated["event_id"].encode()
        )
        projected = self.ledger.hot_events(client, namespace)
        self.assertEqual(projected["payload_authority"], "sqlite")
        self.assertTrue(
            all(item["authority"] == "historical_only" for item in projected["results"])
        )
        self.assertTrue(
            all(not item["authorizes_actions"] for item in projected["results"])
        )

        with mock.patch("palimnex.durable.now_ms", return_value=700):
            trusted_successor = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject=subject,
                payload={"state": "trusted successor"},
                supersedes=current["event_id"],
                valid_from=700,
            )
        projected_successor = self.ledger.project_outbox(client, namespace)
        self.assertEqual(projected_successor["hot_namespace"], effective_namespace)
        self.assertEqual(
            client.execute("GET", latest_key), trusted_successor["event_id"].encode()
        )
        self.assertIsNone(client.execute("GET", active_key))

    def test_contradiction_is_additive_and_does_not_hide_either_event(self) -> None:
        with mock.patch("palimnex.durable.now_ms", return_value=500):
            session = self.ledger.start_session("contradiction history")
        with mock.patch("palimnex.durable.now_ms", return_value=1_000):
            original = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="network scope statement",
                payload={"network scope statement": "first observation"},
                valid_from=1_000,
            )
        with mock.patch("palimnex.durable.now_ms", return_value=2_000):
            opposed = self.ledger.append_event(
                session["session_id"],
                "fact",
                subject="network scope statement",
                payload={"network scope statement": "conflicting observation"},
                contradicts=original["event_id"],
                valid_from=2_000,
            )
        recalled = self.ledger.recall(
            "network scope statement", known_at=3_000, valid_at=3_000
        )["results"]
        self.assertEqual(
            {item["event_id"] for item in recalled},
            {original["event_id"], opposed["event_id"]},
        )
        contradiction = next(item for item in recalled if item["event_id"] == opposed["event_id"])
        self.assertEqual(contradiction["contradicts"], original["event_id"])

    @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "requires Linux procfs")
    def test_repeated_operations_leave_no_ledger_file_descriptors_open(self) -> None:
        session = self.ledger.start_session("descriptor closure")
        self.ledger.append_event(
            session["session_id"], "fact", subject="descriptor fact", payload="closed"
        )
        for _ in range(30):
            self.ledger.status()
            self.ledger.recall("descriptor fact")
        ledger_path = str(self.ledger.path)
        open_targets = []
        for descriptor in Path("/proc/self/fd").iterdir():
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if ledger_path in target:
                open_targets.append(target)
        self.assertEqual(open_targets, [])

    def test_workflow_name_and_step_digest_tampering_marks_ledger_corrupt(self) -> None:
        session = self.ledger.start_session("workflow integrity")
        workflow = self.ledger.put_workflow(
            session["session_id"],
            "verified recovery",
            {
                "version": 1,
                "steps": [
                    {
                        "id": "inspect",
                        "action": "read status",
                        "preconditions": "source exists",
                        "expected": "status returned",
                        "rollback": "none required",
                        "side_effect": "read",
                    }
                ],
            },
            evidence=[{"kind": "source", "locator": "evidence.md:1"}],
        )
        workflow_id = bytes.fromhex(workflow["workflow_id"])
        self.assertEqual(self.ledger.status()["status"], "ready")

        for table, column in (
            ("workflows", "name_digest"),
            ("workflow_steps", "step_id_digest"),
        ):
            with self.subTest(table=table, column=column):
                with self.ledger.connection(
                    create=False, write=True, require_semantic=False
                ) as connection:
                    original = connection.execute(
                        f"SELECT {column} FROM {table} WHERE workflow_id=?",
                        (workflow_id,),
                    ).fetchone()[0]
                    connection.execute(
                        f"UPDATE {table} SET {column}=? WHERE workflow_id=?",
                        (self._different_digest(original), workflow_id),
                    )
                status = self.ledger.status()
                self.assertEqual(status["status"], "corrupt")
                self.assertEqual(status["integrity"], "ok")
                self.assertEqual(status["foreign_key_errors"], 0)
                self.assertIn(
                    "workflow specification failed validation",
                    status["semantic_errors"],
                )
                with self.ledger.connection(
                    create=False, write=True, require_semantic=False
                ) as connection:
                    connection.execute(
                        f"UPDATE {table} SET {column}=? WHERE workflow_id=?",
                        (original, workflow_id),
                    )
                self.assertEqual(self.ledger.status()["status"], "ready")

    def test_event_record_digest_tampering_marks_ledger_corrupt(self) -> None:
        session = self.ledger.start_session("event integrity")
        event = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject="digest protected event",
            payload={"result": "stable"},
        )
        with self.ledger.connection(
            create=False, write=True, require_semantic=False
        ) as connection:
            original = connection.execute(
                "SELECT record_digest FROM events WHERE event_id=?",
                (bytes.fromhex(event["event_id"]),),
            ).fetchone()[0]
            connection.execute(
                "UPDATE events SET record_digest=? WHERE event_id=?",
                (self._different_digest(original), bytes.fromhex(event["event_id"])),
            )

        status = self.ledger.status()

        self.assertEqual(status["status"], "corrupt")
        self.assertEqual(status["integrity"], "ok")
        self.assertEqual(status["foreign_key_errors"], 0)
        self.assertIn("event record digest failed validation", status["semantic_errors"])
        with self.assertRaisesRegex(ValueError, "failed semantic validation"):
            self.ledger.recall("digest protected event")

    def test_event_term_deletion_and_addition_mark_ledger_corrupt(self) -> None:
        session = self.ledger.start_session("retrieval term integrity")
        event = self.ledger.append_event(
            session["session_id"],
            "fact",
            subject="cobalt orchard retrieval",
            payload={"state": "stable"},
        )
        event_id = bytes.fromhex(event["event_id"])
        with self.ledger.connection(create=False) as connection:
            original_terms = [
                row["term_digest"]
                for row in connection.execute(
                    "SELECT term_digest FROM event_terms WHERE event_id=? ORDER BY term_digest",
                    (event_id,),
                )
            ]
        self.assertGreaterEqual(len(original_terms), 2)
        added = b"\xff" * 16
        self.assertNotIn(added, original_terms)

        mutations = {
            "deletion": (
                "DELETE FROM event_terms WHERE event_id=? AND term_digest=?",
                (event_id, original_terms[0]),
                "INSERT INTO event_terms(event_id,term_digest) VALUES(?,?)",
                (event_id, original_terms[0]),
            ),
            "addition": (
                "INSERT INTO event_terms(event_id,term_digest) VALUES(?,?)",
                (event_id, added),
                "DELETE FROM event_terms WHERE event_id=? AND term_digest=?",
                (event_id, added),
            ),
        }
        for name, (mutate_sql, mutate_args, restore_sql, restore_args) in mutations.items():
            with self.subTest(name=name):
                with self.ledger.connection(
                    create=False, write=True, require_semantic=False
                ) as connection:
                    connection.execute(mutate_sql, mutate_args)
                status = self.ledger.status()
                self.assertEqual(status["status"], "corrupt")
                self.assertIn(
                    "event retrieval term set failed validation",
                    status["semantic_errors"],
                )
                with self.assertRaisesRegex(ValueError, "failed semantic validation"):
                    self.ledger.recall("cobalt orchard retrieval")
                with self.ledger.connection(
                    create=False, write=True, require_semantic=False
                ) as connection:
                    connection.execute(restore_sql, restore_args)
                self.assertEqual(self.ledger.status()["status"], "ready")

    def test_metadata_identity_and_codec_tampering_fail_closed(self) -> None:
        cases = {
            "project_slug": (
                b"different-project-slug",
                "project slug does not match",
            ),
            "payload_codec": (
                b"unsupported-payload-codec",
                "payload codec is unsupported",
            ),
        }
        for key, (replacement, message) in cases.items():
            with self.subTest(key=key):
                ledger = MemoryLedger(
                    self.root / ".private" / f"tampered-{key}.sqlite3",
                    project_id=PROJECT_ID,
                    project_slug="memory-fixture",
                    root=self.root,
                )
                ledger.initialize()
                raw = ledger._open(create=False)
                try:
                    raw.execute(
                        "UPDATE metadata SET value=? WHERE key=?",
                        (replacement, key),
                    )
                    raw.commit()
                finally:
                    raw.close()

                raw = ledger._open(create=False)
                try:
                    with self.assertRaisesRegex(ValueError, message):
                        ledger._require_schema(raw)
                finally:
                    raw.close()
                with self.assertRaisesRegex(ValueError, message):
                    ledger.status()
                with self.assertRaisesRegex(ValueError, message):
                    with ledger.connection(create=False):
                        self.fail("tampered ledger was opened")

    def test_invalid_promotion_tampering_marks_ledger_corrupt(self) -> None:
        session = self.ledger.start_session("promotion integrity")
        event = self.ledger.append_event(
            session["session_id"],
            "decision",
            subject="verified promotion target",
            payload={"result": "locally verified"},
            evidence=[{"kind": "source", "locator": "evidence.md:1"}],
            retention="durable",
        )
        self.ledger.close_session(session["session_id"], outcome="done")
        self.assertEqual(self.ledger.consolidate(session["session_id"])["promoted"], [event["event_id"]])
        self.assertEqual(self.ledger.status()["status"], "ready")
        with self.ledger.connection(
            create=False, write=True, require_semantic=False
        ) as connection:
            original = connection.execute(
                "SELECT policy_digest FROM promotions WHERE event_id=?",
                (bytes.fromhex(event["event_id"]),),
            ).fetchone()[0]
            connection.execute(
                "UPDATE promotions SET policy_digest=? WHERE event_id=?",
                (self._different_digest(original), bytes.fromhex(event["event_id"])),
            )

        status = self.ledger.status()

        self.assertEqual(status["status"], "corrupt")
        self.assertEqual(status["integrity"], "ok")
        self.assertEqual(status["foreign_key_errors"], 0)
        self.assertIn(
            "promotion is not evidence-verified, active, and policy-bound",
            status["semantic_errors"],
        )


if __name__ == "__main__":
    unittest.main()
