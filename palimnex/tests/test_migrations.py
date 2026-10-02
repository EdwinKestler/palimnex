from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from palimnex import durable as d
from palimnex import migrations as m
from palimnex import onboarding
from palimnex import retention as r
from palimnex.tests.support import PROJECT_ID, write_project

REPOSITORY = Path(__file__).resolve().parents[2]
TARGET = r.SCHEMA


def tree_state(root: Path) -> dict[str, tuple[str, int, int]]:
    """Name, mode, and file content digest and mtime of every entry below `root`.

    Directory mtimes are left out: SQLite creates and removes its -wal and
    -shm files whenever a connection opens and closes the ledger.
    """
    state: dict[str, tuple[str, int, int]] = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if path.is_file() and not path.is_symlink():
            entry = (hashlib.sha256(path.read_bytes()).hexdigest(), metadata.st_mode,
                     metadata.st_mtime_ns)
        else:
            entry = ("", metadata.st_mode, 0)
        state[path.relative_to(root).as_posix()] = entry
    return state


def step(source: str, target: str, suffix: str = ".next", label: str = "-pre-next") -> m.Migration:
    return m.Migration(source, target, suffix, label, ("an effect",))


class RegistryTests(unittest.TestCase):
    A, B, C = "project-memory:a:v1", "project-memory:b:v1", "project-memory:c:v1"

    def readers(self, *names: str) -> dict[str, m.Reader]:
        return {name: m._plain_reader for name in names}

    def test_shipped_registry_is_one_retention_edge(self) -> None:
        self.assertEqual(m.schema_chain(), [d.LEDGER_SCHEMA, TARGET])
        self.assertEqual(m.REGISTRY[0].marker_suffix, ".retention-v2")
        self.assertEqual(m.REGISTRY[0].marker_bytes, TARGET.encode())
        self.assertEqual(m.REGISTRY[0].effects, r.MIGRATION_EFFECTS)

    def test_rejects_malformed_registries(self) -> None:
        readers = self.readers(self.A, self.B, self.C)
        cases = {
            "empty": ((), readers),
            "ambiguous successor": (
                (step(self.A, self.B), step(self.A, self.C, ".other", "-other")), readers),
            "gap": ((step(self.A, self.B), step(self.C, self.A, ".other", "-other")), readers),
            "cycle": ((step(self.A, self.B), step(self.B, self.A, ".other", "-other")), readers),
            "differ from its source": ((step(self.A, self.A),), readers),
            "versioned identifier": ((step(self.A, "project-memory:b"),), readers),
            "no exact reader": ((step(self.A, self.B),), self.readers(self.A)),
            "unsafe or reused": ((step(self.A, self.B, ".import-intent"),), readers),
            "snapshot label": ((step(self.A, self.B, label="../x"),), readers),
        }
        for message, (entries, chosen) in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                m.validate_registry(entries, chosen)
        with self.assertRaisesRegex(ValueError, "unsafe or reused"):
            m.validate_registry((step(self.A, self.B), step(self.B, self.C)), readers)
        with self.assertRaisesRegex(ValueError, "declare its effects"):
            m.validate_registry((m.Migration(self.A, self.B, ".b", "-b", ()),), readers)

    def test_resolves_only_the_adjacent_step(self) -> None:
        registry = m.validate_registry(
            (step(self.A, self.B, ".b", "-b"), step(self.B, self.C, ".c", "-c")),
            self.readers(self.A, self.B, self.C),
        )
        self.assertEqual(m.resolve_step(self.A, self.B, registry), registry[0])
        self.assertIsNone(m.resolve_step(self.B, self.B, registry))
        with self.assertRaisesRegex(ValueError, f"next with `--to {self.B}`"):
            m.resolve_step(self.A, self.C, registry)
        with self.assertRaisesRegex(ValueError, "backward migration"):
            m.resolve_step(self.C, self.A, registry)
        with self.assertRaisesRegex(ValueError, "unknown ledger schema"):
            m.resolve_step("project-memory:z:v1", self.B, registry)
        with self.assertRaisesRegex(ValueError, "unknown migration target"):
            m.resolve_step(self.A, "project-memory:z:v1", registry)


class LedgerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        write_project(self.root)
        self.ledger = d.MemoryLedger(self.root / ".private/memory.sqlite3", project_id=PROJECT_ID,
                                     project_slug="memory-fixture", root=self.root)
        session = self.ledger.start_session("migration rehearsal")["session_id"]
        self.ledger.append_event(session, "fact", subject="cobalt orchard",
                                 payload={"state": "kept"}, retention="durable")
        self.ledger.close_session(session, outcome="done")
        self.digest = self.ledger.status()["logical_digest"]
        self.guard = Path(str(self.ledger.path) + ".retention-v2")

    def plan(self, digest: str | None = None, **options: object) -> dict[str, object]:
        return m.plan(self.ledger, target=TARGET, expected_digest=digest or self.digest,
                      **options)  # type: ignore[arg-type]

    def migrate(self) -> None:
        r.migrate(self.ledger, expected_digest=self.digest)

    def write_guard(self, content: bytes) -> None:
        descriptor = os.open(self.guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, content)
        finally:
            os.close(descriptor)


class PlanTests(LedgerFixture):
    def test_ready_plan_names_the_step_and_writes_nothing(self) -> None:
        before = tree_state(self.root)
        result = self.plan()
        self.assertEqual(tree_state(self.root), before)
        self.assertEqual(result["schema"], m.PLAN_SCHEMA)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["refusals"], [])
        self.assertFalse(result["will_write"])
        self.assertFalse(result["authorizes_actions"])
        self.assertEqual(result["authority"], "historical_only")
        self.assertEqual(result["step"], {"source": d.LEDGER_SCHEMA, "target": TARGET})
        self.assertEqual(result["effects"], list(r.MIGRATION_EFFECTS))
        self.assertEqual(result["replacement_guard"],
                         {"path": ".private/memory.sqlite3.retention-v2", "state": "absent"})
        self.assertEqual(result["snapshot"]["policy"], "required")
        self.assertEqual(result["snapshot"]["note"], d.SNAPSHOT_ERASURE_NOTE)
        self.assertTrue(result["expected_digest_matches"])

    def test_refusals(self) -> None:
        wrong = self.plan("0" * 64)
        self.assertEqual((wrong["status"], wrong["refusals"]), ("refused", ["DIGEST_MISMATCH"]))
        intent = Path(str(self.ledger.path) + ".import-intent")
        intent.write_text("{}", encoding="utf-8")
        self.assertIn("pending import blocks ledger migration", self.plan()["refusals"])
        intent.unlink()
        Path(str(self.ledger.path) + ".migration-intent").write_text("{}", encoding="utf-8")
        result = self.plan()
        self.assertEqual(result["preconditions"]["migration_intent"], "present")
        self.assertTrue(any("migration intent" in reason for reason in result["refusals"]))

    def test_corrupt_source_and_wrong_project_are_refused(self) -> None:
        other = d.MemoryLedger(self.ledger.path, project_id="00000000-0000-4000-8000-000000000001",
                               project_slug="memory-fixture", root=self.root)
        result = m.plan(other, target=TARGET, expected_digest=self.digest)
        self.assertEqual(result["status"], "refused")
        self.assertNotEqual(result["preconditions"]["structure"], "ok")
        with self.ledger.connection(create=False, write=True, require_semantic=False) as connection:
            connection.execute(
                "UPDATE events SET record_digest=randomblob(32) "
                "WHERE event_id=(SELECT event_id FROM events ORDER BY event_id LIMIT 1)"
            )
        result = self.plan()
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["preconditions"]["structure"], "ok")
        self.assertNotEqual(result["preconditions"]["semantics"], "ok")

    def test_missing_ledger_is_refused_without_creating_anything(self) -> None:
        shutil.rmtree(self.root / ".private")
        before = tree_state(self.root)
        result = self.plan()
        self.assertEqual(result["refusals"], ["durable ledger is missing"])
        self.assertEqual(tree_state(self.root), before)
        self.assertEqual(m.listing(self.ledger)["ledger_present"], False)
        self.assertEqual(tree_state(self.root), before)

    def test_existing_guards_beside_the_source(self) -> None:
        self.write_guard(TARGET.encode())
        result = self.plan()
        self.assertEqual(result["status"], "resumable")
        self.assertEqual(result["replacement_guard"]["state"], "exact")
        self.guard.unlink()
        self.write_guard(b"")
        result = self.plan()
        self.assertEqual(result["status"], "resumable")
        self.assertIn("legacy interrupted", result["recovery"])
        self.assertEqual(self.plan("0" * 64)["status"], "refused")
        self.guard.unlink()
        self.write_guard(b"project-memory:something-else:v9")
        self.assertEqual(self.plan()["replacement_guard"]["state"], "invalid")
        self.assertEqual(self.plan()["status"], "refused")
        self.guard.unlink()
        self.guard.symlink_to(self.ledger.path)
        self.assertEqual(self.plan()["replacement_guard"]["state"], "unsafe")
        self.assertEqual(self.plan()["status"], "refused")

    def test_migrated_ledger_reports_completion_or_guard_repair(self) -> None:
        self.migrate()
        result = self.plan()
        self.assertEqual(result["status"], "already_migrated")
        self.assertTrue(result["expected_digest_matches"])
        self.assertEqual(result["audit_before_digest"], self.digest)
        self.guard.unlink()
        result = self.plan()
        self.assertEqual(result["status"], "guard_repair_required")
        self.assertIn("guard repair", result["recovery"])
        self.assertEqual(self.plan("0" * 64)["refusals"], ["DIGEST_MISMATCH"])
        self.write_guard(b"")
        self.assertEqual(self.plan()["status"], "refused")
        backward = m.plan(self.ledger, target=d.LEDGER_SCHEMA, expected_digest=self.digest)
        self.assertTrue(any("backward" in reason for reason in backward["refusals"]))

    def test_listing_reports_the_standing_of_each_step(self) -> None:
        listed = m.listing(self.ledger)
        self.assertEqual(listed["schema"], m.LIST_SCHEMA)
        self.assertEqual(listed["chain"], [d.LEDGER_SCHEMA, TARGET])
        self.assertEqual([entry["standing"] for entry in listed["migrations"]], ["next"])
        self.migrate()
        self.assertEqual([e["standing"] for e in m.listing(self.ledger)["migrations"]], ["applied"])

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_git_ignore_state_of_intent_and_snapshot_paths(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        result = self.plan()
        self.assertEqual(result["preconditions"]["git_ignore"],
                         {"intent": "not_ignored", "snapshot": "not_ignored"})
        self.assertTrue(any("--allow-unignored-ledger" in reason for reason in result["refusals"]))
        self.assertEqual(self.plan(allow_unignored=True)["status"], "ready")
        (self.root / ".gitignore").write_text(".private/\n", encoding="utf-8")
        result = self.plan()
        self.assertEqual(result["preconditions"]["git_ignore"],
                         {"intent": "ignored", "snapshot": "ignored"})
        self.assertEqual(result["status"], "ready")


class CommandTests(LedgerFixture):
    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        environment = {**os.environ, "PYTHONPATH": str(REPOSITORY)}
        environment.pop("PALIMNEX_ROOT", None)
        result = subprocess.run([sys.executable, "-m", "palimnex", *arguments], cwd=self.root,
                                env=environment, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, result.stderr

    def test_list_plan_and_apply_exit_codes(self) -> None:
        before = tree_state(self.root)
        code, output, _ = self.run_cli("ledger-migrate", "--list")
        self.assertEqual((code, json.loads(output)["schema"]), (0, m.LIST_SCHEMA))
        code, output, _ = self.run_cli("ledger-migrate", "--plan", "--to", TARGET,
                                       "--expected-digest", self.digest)
        self.assertEqual((code, json.loads(output)["status"]), (0, "ready"))
        code, output, _ = self.run_cli("ledger-migrate", "--plan", "--to", TARGET,
                                       "--expected-digest", "0" * 64)
        self.assertEqual((code, json.loads(output)["status"]), (2, "refused"))
        code, _, errors = self.run_cli("ledger-migrate", "--apply", "--to", TARGET,
                                       "--expected-digest", self.digest)
        self.assertEqual(code, 2)
        self.assertIn("retention-migrate", json.loads(errors)["error"])
        code, _, errors = self.run_cli("ledger-migrate", "--plan")
        self.assertEqual(code, 1)
        self.assertIn("--expected-digest", json.loads(errors)["error"])
        self.assertEqual(tree_state(self.root), before)
        self.assertEqual(self.ledger.status()["schema"], d.LEDGER_SCHEMA)

    def test_retention_dry_run_keeps_its_fields(self) -> None:
        code, output, _ = self.run_cli("retention-migrate", "--expected-digest", self.digest,
                                       "--dry-run")
        self.assertEqual(code, 0)
        self.assertLessEqual({
            "mode", "will_write", "already_migrated", "current_schema", "target_schema",
            "logical_digest", "expected_digest_matches", "would_refuse", "snapshot", "effects",
        }, set(json.loads(output)))


class DoctorMigrationTests(LedgerFixture):
    def findings(self) -> dict[str, dict[str, object]]:
        before = tree_state(self.root)
        report = onboarding.doctor(self.root, redis_url="redis://127.0.0.1:1/0")
        self.assertEqual(tree_state(self.root), before)
        return {check["id"]: check for check in report["checks"]
                if check["id"] in {"replacement_guard", "migration_intent", "migration"}}

    def test_clean_source_and_completed_migration_report_nothing(self) -> None:
        self.assertEqual(self.findings(), {})
        self.migrate()
        self.assertEqual(self.findings(), {})

    def test_unfinished_and_unsafe_states(self) -> None:
        self.write_guard(TARGET.encode())
        found = self.findings()["replacement_guard"]
        self.assertEqual(found["status"], "warn")
        self.assertIn("resumable", found["detail"])
        self.assertIn("ledger-migrate --plan", found["action"])
        self.guard.unlink()
        self.write_guard(b"")
        found = self.findings()["replacement_guard"]
        self.assertEqual(found["status"], "warn")
        self.assertIn("empty", found["detail"])
        self.guard.unlink()
        self.write_guard(b"conflicting")
        self.assertEqual(self.findings()["replacement_guard"]["status"], "fail")
        self.guard.unlink()
        Path(str(self.ledger.path) + ".migration-intent").write_text("{}", encoding="utf-8")
        found = self.findings()["migration_intent"]
        self.assertEqual(found["status"], "warn")
        self.assertIn("never delete the intent", found["action"])

    def test_migrated_ledger_without_guard_and_guard_without_ledger(self) -> None:
        self.migrate()
        self.guard.unlink()
        found = self.findings()["replacement_guard"]
        self.assertEqual(found["status"], "warn")
        self.assertIn("missing", found["detail"])
        self.write_guard(TARGET.encode())
        for name in ("memory.sqlite3", "memory.sqlite3-wal", "memory.sqlite3-shm"):
            with contextlib.suppress(FileNotFoundError):
                (self.root / ".private" / name).unlink()
        found = self.findings()["replacement_guard"]
        self.assertEqual(found["status"], "fail")
        self.assertIn("ledger is missing", found["detail"])


if __name__ == "__main__":
    unittest.main()
