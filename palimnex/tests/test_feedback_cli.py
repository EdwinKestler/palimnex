"""Owner-run feedback commands (ontology Phase 5), against a temporary project and ledger only."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from palimnex import core, durable
from palimnex._offline_fixtures import PROJECT_ID, write_project


class _NoRedis:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise OSError("redis is not available in this test")


class FeedbackCliTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_project(self.root, {"docs/source.md": "heading\nalpha answer line\nomega context line\n"})
        self.ledger = durable.MemoryLedger(
            self.root / ".private/memory.sqlite3", project_id=PROJECT_ID,
            project_slug="feedback-cli", root=self.root,
        )
        self.ledger.initialize()
        self.session = self.ledger.start_session("feedback cli")["session_id"]
        for patcher in (
            mock.patch.object(core, "ROOT", self.root),
            mock.patch.object(core, "config_present", return_value=True),
            mock.patch.object(durable, "MemoryLedger", return_value=self.ledger),
            mock.patch.object(core, "RedisClient", _NoRedis),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, *argv: str) -> tuple[int, Any, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = core.main(list(argv))
        out = stdout.getvalue()
        return code, (json.loads(out) if out else None), stderr.getvalue()

    def record(self, judgement: str = "answers") -> dict[str, Any]:
        code, output, err = self.run_cli(
            "feedback-record", "--session", self.session, "--query", "alpha   answer",
            "--locator", "docs/source.md:2-2", "--judgement", judgement, "--reviewer", "EdwinKestler",
        )
        self.assertEqual(code, 0, err)
        return output

    def report(self, *extra: str) -> dict[str, Any]:
        code, output, err = self.run_cli("feedback-report", *extra)
        self.assertEqual(code, 0, err)
        return output

    def test_record_then_report_current_and_non_authorizing(self) -> None:
        output = self.record()
        self.assertTrue(output["verified"])
        self.assertFalse(output["authorizes_actions"])
        self.assertFalse(output["retrieval_influence"])
        self.assertEqual(output["projection"]["status"], "pending")
        self.assertTrue(output["projection"]["durable_operation_committed"])
        report = self.report()
        self.assertEqual(report["schema"], "palimnex:retrieval-feedback-report:v1")
        self.assertEqual(report["counts"]["current"], 1)
        self.assertEqual(report["records"][0]["query"], "alpha answer")
        self.assertEqual(report["authority"], "historical_only")
        self.assertFalse(report["retrieval_influence"])

    def test_correct_and_withdraw_keep_history(self) -> None:
        first = self.record()
        code, corrected, err = self.run_cli(
            "feedback-correct", "--session", self.session, "--event", first["event_id"],
            "--judgement", "does_not_answer", "--reviewer", "EdwinKestler", "--note", "wrong range",
        )
        self.assertEqual(code, 0, err)
        code, withdrawn, err = self.run_cli(
            "feedback-withdraw", "--session", self.session, "--event", corrected["event_id"],
            "--reviewer", "EdwinKestler", "--reason", "query no longer relevant",
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.report()["records"], [])
        history = self.report("--include-history")
        states = {item["event_id"]: item["state"] for item in history["records"]}
        self.assertEqual(states[first["event_id"]], "superseded")
        self.assertEqual(states[corrected["event_id"]], "withdrawn")
        self.assertEqual(history["counts"]["withdrawn"], 1)
        self.assertEqual(history["counts"]["superseded"], 1)

    def test_refusal_exits_one_without_echoing_the_canary(self) -> None:
        canary = "".join(("AK", "IA", "Q7Z3", "K9M2", "P4R8", "T6V1"))
        code, output, err = self.run_cli(
            "feedback-record", "--session", self.session, "--query", f"where {canary} lives",
            "--locator", "docs/source.md:2-2", "--judgement", "answers", "--reviewer", "EdwinKestler",
        )
        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertNotIn(canary, err)
        self.assertEqual(self.report()["counts"]["current"], 0)

    def test_report_is_read_only(self) -> None:
        self.record()
        before = self.ledger.status()["counts"]
        self.report("--include-history")
        self.assertEqual(self.ledger.status()["counts"], before)

    def test_context_and_capsule_never_include_feedback(self) -> None:
        from palimnex import experience
        self.ledger.append_event(
            self.session, "fact", subject="alpha answer reminder",
            payload={"text": "alpha answer lives in the source document"},
            evidence=[{"kind": "source", "locator": "docs/source.md:2-2"}], retention="durable",
        )

        def outputs() -> tuple[bytes, bytes]:
            context = experience.assemble_context("alpha answer", root=self.root, ledger=self.ledger)
            capsule = experience.build_capsule("alpha answer", ledger=self.ledger)
            return durable.canonical_json(context), durable.canonical_json(capsule)

        before_context, before_capsule = outputs()
        self.assertIn(b"alpha answer lives in the source document", before_context)
        first = self.record()
        code, corrected, err = self.run_cli(
            "feedback-correct", "--session", self.session, "--event", first["event_id"],
            "--judgement", "does_not_answer", "--reviewer", "EdwinKestler",
        )
        self.assertEqual(code, 0, err)
        code, _, err = self.run_cli(
            "feedback-withdraw", "--session", self.session, "--event", corrected["event_id"],
            "--reviewer", "EdwinKestler", "--reason", "checking context isolation",
        )
        self.assertEqual(code, 0, err)
        self.record("answers")
        after_context, after_capsule = outputs()
        self.assertEqual(after_context, before_context)
        self.assertEqual(after_capsule, before_capsule)
        self.assertNotIn(b"palimnex:retrieval-feedback", after_context + after_capsule)
        recalled = self.ledger.recall("alpha answer", include_history=True)
        self.assertTrue(any(isinstance(item["payload"], dict)
                            and item["payload"].get("schema") == "palimnex:retrieval-feedback:v1"
                            for item in recalled["results"]))

    def test_parser_rejects_unknown_judgement(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            core.parser().parse_args([
                "feedback-record", "--session", self.session, "--query", "q", "--locator", "docs/source.md:2",
                "--judgement", "maybe", "--reviewer", "EdwinKestler",
            ])


if __name__ == "__main__":
    unittest.main()
