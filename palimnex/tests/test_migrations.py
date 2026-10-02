from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def _no_apply(connection: object, ledger: object, digest: str) -> None:
    raise AssertionError("not applied in registry tests")


def _no_audit(reader: object, connection: object) -> tuple[str, str]:
    raise AssertionError("not audited in registry tests")


def step(source: str, target: str, suffix: str = ".next", label: str = "-pre-next") -> m.Migration:
    return m.Migration(source, target, suffix, label, ("an effect",), _no_apply,  # type: ignore[arg-type]
                       _no_audit)  # type: ignore[arg-type]


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
            m.validate_registry((m.Migration(self.A, self.B, ".b", "-b", (), _no_apply,  # type: ignore[arg-type]
                                             _no_audit),), readers)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "apply and audit callbacks"):
            m.validate_registry((m.Migration(self.A, self.B, ".b", "-b", ("x",), None,  # type: ignore[arg-type]
                                             _no_audit),), readers)  # type: ignore[arg-type]

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

    def test_list_and_plan_exit_codes(self) -> None:
        before = tree_state(self.root)
        code, output, _ = self.run_cli("ledger-migrate", "--list")
        self.assertEqual((code, json.loads(output)["schema"]), (0, m.LIST_SCHEMA))
        code, output, _ = self.run_cli("ledger-migrate", "--plan", "--to", TARGET,
                                       "--expected-digest", self.digest)
        self.assertEqual((code, json.loads(output)["status"]), (0, "ready"))
        code, output, _ = self.run_cli("ledger-migrate", "--plan", "--to", TARGET,
                                       "--expected-digest", "0" * 64)
        self.assertEqual((code, json.loads(output)["status"]), (2, "refused"))
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


def ledger_files(ledger: d.MemoryLedger) -> list[str]:
    """Sidecars and temporaries beside the ledger, excluding SQLite's own files."""
    ignored = {ledger.path.name, ledger.lock_path.name, f"{ledger.path.name}-wal",
               f"{ledger.path.name}-shm"}
    return sorted(p.name for p in ledger.path.parent.iterdir()
                  if p.name not in ignored and not p.is_dir())


def snapshots(ledger: d.MemoryLedger) -> list[Path]:
    directory = ledger.path.parent / d.SNAPSHOT_DIRECTORY
    return sorted(directory.glob("*.sqlite3")) if directory.is_dir() else []


class EngineFixture(LedgerFixture):
    def apply(self, digest: str | None = None, **options: object) -> dict[str, object]:
        return m.apply(self.ledger, target=TARGET, expected_digest=digest or self.digest,
                       **options)  # type: ignore[arg-type]

    def assert_migrated(self) -> None:
        found = m.inspect(self.ledger)
        self.assertEqual(found.observed, TARGET)
        self.assertTrue(found.exact, found.failures())
        self.assertEqual(found.audit, (d.LEDGER_SCHEMA, self.digest))
        self.assertEqual(self.guard.read_bytes(), TARGET.encode())
        self.assertEqual(os.stat(self.guard).st_mode & 0o777, 0o600)
        self.assertEqual(ledger_files(self.ledger), [self.guard.name])


class ApplyTests(EngineFixture):
    def test_apply_snapshots_publishes_the_guard_and_removes_the_intent(self) -> None:
        result = self.apply()
        self.assertEqual(result["schema"], m.RESULT_SCHEMA)
        self.assertEqual((result["status"], result["resumed"]), ("migrated", False))
        self.assertEqual(result["replacement_guard"], "published")
        self.assertFalse(result["authorizes_actions"])
        receipt = result["pre_migration_snapshot"]
        self.assertEqual((receipt["schema"], receipt["logical_digest"]), (d.LEDGER_SCHEMA, self.digest))
        self.assertEqual([path.name for path in snapshots(self.ledger)], [Path(receipt["path"]).name])
        self.assertTrue(Path(receipt["path"]).name.endswith("-pre-retention-v2.sqlite3"))
        self.assert_migrated()
        again = self.apply("0" * 64)
        self.assertEqual((again["status"], again["replacement_guard"]), ("already_migrated", "existing"))
        self.assertEqual(len(snapshots(self.ledger)), 1)
        with self.assertRaisesRegex(ValueError, "backward migration"):
            m.apply(self.ledger, target=d.LEDGER_SCHEMA, expected_digest=self.digest)

    def test_refusals_write_nothing(self) -> None:
        before = tree_state(self.root)
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            self.apply("0" * 64)
        same = m.apply(self.ledger, target=d.LEDGER_SCHEMA, expected_digest=self.digest)
        self.assertEqual((same["status"], same["replacement_guard"]), ("already_migrated", "unchanged"))
        with self.assertRaisesRegex(ValueError, "unknown migration target"):
            m.apply(self.ledger, target="project-memory:later:v9", expected_digest=self.digest)
        self.assertEqual(tree_state(self.root), before)
        intent = Path(str(self.ledger.path) + ".import-intent")
        intent.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "pending import"):
            self.apply()
        intent.unlink()
        self.write_guard(b"conflicting")
        with self.assertRaisesRegex(ValueError, "manual review"):
            self.apply()
        self.assertEqual(self.guard.read_bytes(), b"conflicting")
        self.assertEqual(m.inspect(self.ledger).observed, d.LEDGER_SCHEMA)

    def test_legacy_guard_states_beside_the_source(self) -> None:
        self.write_guard(TARGET.encode())
        result = self.apply()
        self.assertEqual(result["replacement_guard"], "existing")
        self.assertIn("continued after an existing replacement guard", result["recovery"])
        self.assert_migrated()

    def test_legacy_empty_guard_is_replaced_only_after_the_digest_matches(self) -> None:
        self.write_guard(b"")
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            self.apply("0" * 64)
        self.assertEqual(self.guard.read_bytes(), b"")
        result = self.apply()
        self.assertEqual(result["replacement_guard"], "replaced_empty")
        self.assert_migrated()

    def test_migrated_ledger_without_guard_is_repaired_with_the_audit_digest(self) -> None:
        self.apply()
        self.guard.unlink()
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            self.apply("0" * 64)
        self.assertFalse(self.guard.exists())
        result = self.apply()
        self.assertEqual(result["status"], "guard_repaired")
        self.assert_migrated()
        self.guard.unlink()
        self.write_guard(b"")
        with self.assertRaisesRegex(ValueError, "manual review"):
            self.apply()

    def test_intent_that_does_not_match_is_not_resumable(self) -> None:
        self.write_guard(TARGET.encode())
        intent = {
            "schema": m.INTENT_SCHEMA, "ledger": ".private/memory.sqlite3",
            "source": d.LEDGER_SCHEMA, "target": TARGET, "expected_digest": self.digest,
            "registry": "f" * 64, "snapshot": None, "phase": "prepared",
            "authority": "historical_only", "authorizes_actions": False,
        }
        path = Path(str(self.ledger.path) + m.INTENT_SUFFIX)
        path.write_bytes(d.canonical_json(intent))
        with self.assertRaisesRegex(ValueError, "different migration registry"):
            self.apply()
        self.assertEqual(self.plan()["status"], "refused")
        path.write_bytes(d.canonical_json({**intent, "registry": m.registry_identity(),
                                           "expected_digest": "e" * 64}))
        with self.assertRaisesRegex(ValueError, "different --expected-digest"):
            self.apply()
        path.write_bytes(d.canonical_json({**intent, "registry": m.registry_identity(),
                                           "phase": "target_verified"}))
        with self.assertRaisesRegex(ValueError, "still the source"):
            self.apply()
        self.assertTrue(any("still the source" in reason for reason in self.plan()["refusals"]))
        path.write_bytes(b'{"schema": "x"}')
        with self.assertRaisesRegex(ValueError, "canonical JSON|field set"):
            self.apply()
        self.assertEqual(m.inspect(self.ledger).observed, d.LEDGER_SCHEMA)

    def test_snapshot_survives_later_erasure(self) -> None:
        session = self.ledger.start_session("erasure rehearsal")["session_id"]
        self.ledger.append_event(session, "fact", subject="violet", payload={"v": "temporary"},
                                 retention="session")
        self.ledger.close_session(session, outcome="done")
        self.digest = self.ledger.status()["logical_digest"]
        receipt = self.apply()["pre_migration_snapshot"]
        migrated = r.as_retention(self.ledger)
        migrated.activate_policy({
            "schema": r.POLICY, "policy_id": "local", "version": 1, "mode": "manual",
            "clock": "tx_at", "rules": [{"retention": "session", "kinds": ["fact"],
                                         "ttl_seconds": 0}],
            "grace_after_close_seconds": 0, "plan_ttl_seconds": 3600,
        }, actor="operator", reason="erasure rehearsal")
        proposal = migrated.propose()
        self.assertEqual(len(proposal["affected"]), 1)
        applied = migrated.apply(proposal, confirm_digest=proposal["plan_digest"], key=b"k" * 32,
                                 actor="operator", reason="erasure rehearsal")
        self.assertEqual(applied["status"], "applied")
        snapshot = Path(receipt["path"])
        self.assertTrue(snapshot.is_file())
        self.assertEqual(m._verify_snapshot_file(self.ledger, snapshot, m.REGISTRY[0], self.digest)
                         ["logical_digest"], self.digest)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_git_ignore_is_required_before_any_write(self) -> None:
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        before = tree_state(self.root)
        with self.assertRaisesRegex(ValueError, "--allow-unignored-ledger"):
            self.apply()
        self.assertEqual(tree_state(self.root), before)
        self.assertEqual(self.apply(allow_unignored=True)["status"], "migrated")


class PackRefusalTests(EngineFixture):
    def test_pack_paths_refuse_while_a_migration_intent_exists(self) -> None:
        from palimnex import portable
        key = bytes(range(32))
        pack = self.root / ".private/source.pmem"
        portable.export_pack(self.ledger, pack, key)
        Path(str(self.ledger.path) + m.INTENT_SUFFIX).write_text("{}", encoding="utf-8")
        for attempt in (
            lambda: portable.import_pack(self.ledger, pack, key),
            lambda: portable.import_pack(self.ledger, pack, key, activate=True, replace=True),
            lambda: portable.recover_import(self.ledger),
        ):
            with self.assertRaisesRegex(ValueError, "migration intent exists"):
                attempt()
        self.assertEqual(self.ledger.status()["logical_digest"], self.digest)


class LegacyAliasTests(EngineFixture):
    def twin(self) -> d.MemoryLedger:
        """An identical copy of the fixture ledger in a second repository."""
        temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        write_project(root)
        (root / ".private").mkdir(mode=0o700)
        source = sqlite3.connect(self.ledger.path)
        target = sqlite3.connect(root / ".private/memory.sqlite3")
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        os.chmod(root / ".private/memory.sqlite3", 0o600)
        return d.MemoryLedger(root / ".private/memory.sqlite3", project_id=PROJECT_ID,
                              project_slug="memory-fixture", root=root)

    @staticmethod
    def shape(ledger: d.MemoryLedger) -> dict[str, object]:
        connection = sqlite3.connect(ledger.path)
        try:
            objects = connection.execute(
                "SELECT type, name, sql FROM sqlite_schema ORDER BY name").fetchall()
            metadata = connection.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
            first = json.loads(connection.execute(
                "SELECT payload FROM retention_control ORDER BY sequence LIMIT 1").fetchone()[0])
        finally:
            connection.close()
        status = r.as_retention(ledger).retention_status()
        return {
            "objects": objects, "metadata": metadata,
            "migration": sorted(first), "from": first["from_schema"],
            "before": first["before_digest"],
            "marker": Path(str(ledger.path) + ".retention-v2").read_bytes(),
            "status_fields": sorted(status),
            "files": ledger_files(ledger),
        }

    def test_alias_and_generic_command_reach_the_same_target(self) -> None:
        twin = self.twin()
        self.assertEqual(twin.status()["logical_digest"], self.digest)
        legacy = r.migrate(self.ledger, expected_digest=self.digest, snapshot=True)
        generic = m.apply(twin, target=TARGET, expected_digest=self.digest)
        self.assertEqual(self.shape(self.ledger), self.shape(twin))
        self.assertEqual(legacy["migration"]["status"], "migrated")
        for receipt in (legacy["pre_migration_snapshot"], generic["pre_migration_snapshot"]):
            self.assertEqual(receipt["logical_digest"], self.digest)
            self.assertEqual(os.stat(receipt["path"]).st_mode & 0o777, 0o600)

    def test_sdk_keeps_its_default_and_warns(self) -> None:
        from palimnex.api import Palimnex
        twin = self.twin()
        client = Palimnex(self.root, writable=True)
        with self.assertWarns(DeprecationWarning):
            result = client.migrate_retention(expected_digest=self.digest)
        self.assertNotIn("pre_migration_snapshot", result)
        self.assertEqual(snapshots(self.ledger), [])
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            result = Palimnex(twin.root, writable=True).migrate_retention(
                expected_digest=self.digest, snapshot=True)
        self.assertEqual(result["pre_migration_snapshot"]["logical_digest"], self.digest)


class ApplyCommandTests(EngineFixture):
    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        environment = {**os.environ, "PYTHONPATH": str(REPOSITORY)}
        environment.pop("PALIMNEX_ROOT", None)
        result = subprocess.run([sys.executable, "-m", "palimnex", *arguments], cwd=self.root,
                                env=environment, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, result.stderr

    def test_apply_command(self) -> None:
        code, output, errors = self.run_cli("ledger-migrate", "--apply", "--to", TARGET,
                                            "--expected-digest", self.digest)
        self.assertEqual(code, 0, errors)
        result = json.loads(output)
        self.assertEqual((result["schema"], result["status"]), (m.RESULT_SCHEMA, "migrated"))
        self.assertEqual(result["ledger_status"]["schema"], TARGET)
        self.assert_migrated()
        code, _, errors = self.run_cli("ledger-migrate", "--apply", "--to", d.LEDGER_SCHEMA,
                                       "--expected-digest", self.digest)
        self.assertEqual(code, 1)
        self.assertIn("backward migration", json.loads(errors)["error"])

    def test_no_snapshot_alias_is_deprecated(self) -> None:
        code, output, errors = self.run_cli("retention-migrate", "--expected-digest", self.digest,
                                            "--no-snapshot")
        self.assertEqual(code, 0, errors)
        self.assertIn("deprecated", errors)
        result = json.loads(output)
        self.assertEqual(result["deprecations"], [r.NO_SNAPSHOT_DEPRECATION])
        self.assertNotIn("pre_migration_snapshot", result)
        self.assert_migrated()


CHILD = """
import os, sys
from pathlib import Path
from palimnex import durable as d, migrations as m
root, boundary, digest, project = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
name, _, nth = boundary.partition("#")
reached = {"count": 0}
def interrupt(current):
    if current == name:
        reached["count"] += 1
        if reached["count"] == int(nth or 1):
            os._exit(17)
m._boundary = interrupt
ledger = d.MemoryLedger(root / ".private/memory.sqlite3", project_id=project,
                        project_slug="memory-fixture", root=root)
m.apply(ledger, target="project-memory:retention-ledger:v2", expected_digest=digest)
os._exit(0)
"""

BOUNDARIES = (
    "guard-temporary-written", "guard-linked", "guard-published",
    "intent-temporary-written", "intent-linked", "intent-created",
    "snapshot-verified", "intent-temporary-written#2", "intent-snapshot-recorded",
    "transaction-applied", "committed", "target-verified",
    "intent-temporary-written#3", "intent-verified-recorded", "intent-removed",
)


class CrashMatrixTests(EngineFixture):
    def interrupt(self, boundary: str) -> None:
        environment = {**os.environ, "PYTHONPATH": str(REPOSITORY)}
        result = subprocess.run(
            [sys.executable, "-c", CHILD, str(self.root), boundary, self.digest, PROJECT_ID],
            env=environment, capture_output=True, text=True, check=False, timeout=120,
        )
        self.assertEqual(result.returncode, 17, f"{boundary} not reached: {result.stderr}")

    def assert_exact_source_or_target(self) -> None:
        found = m.inspect(self.ledger)
        self.assertIn(found.observed, {d.LEDGER_SCHEMA, TARGET})
        self.assertTrue(found.exact, found.failures())

    def test_every_boundary_is_recoverable_by_rerunning_apply(self) -> None:
        for boundary in BOUNDARIES:
            with self.subTest(boundary=boundary):
                self.setUp()
                self.interrupt(boundary)
                self.assert_exact_source_or_target()
                self.assertEqual(self.plan()["status"] in {"resumable", "already_migrated",
                                                           "ready"}, True)
                if m.inspect(self.ledger).observed == TARGET and m._present(
                        Path(str(self.ledger.path) + m.INTENT_SUFFIX)):
                    with self.assertRaisesRegex(ValueError, "not resumable|DIGEST_MISMATCH"):
                        self.apply("e" * 64)
                elif m.inspect(self.ledger).observed == d.LEDGER_SCHEMA:
                    with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
                        self.apply("e" * 64)
                result = self.apply()
                self.assertIn(result["status"], {"migrated", "already_migrated"})
                self.assert_migrated()
                self.assertEqual(len(snapshots(self.ledger)), 1, boundary)
                self.assertEqual(self.apply()["status"], "already_migrated")

    def test_incomplete_snapshot_is_quarantined_and_rewritten(self) -> None:
        self.interrupt("intent-created")
        intent = m.read_intent(self.ledger)
        assert intent is not None
        partial = self.root / intent["snapshot"]["path"]
        partial.write_bytes(b"SQLite format 3\x00 partial")
        os.chmod(partial, 0o600)
        result = self.apply()
        self.assertTrue(any("quarantined" in note for note in result["recovery"]))
        self.assert_migrated()
        self.assertEqual(len(snapshots(self.ledger)), 1)
        self.assertEqual(len(list(partial.parent.glob("*.quarantined-*"))), 1)

    def test_exceptions_before_and_after_commit(self) -> None:
        def fail_at(name: str) -> object:
            def hook(current: str) -> None:
                if current == name:
                    raise RuntimeError(f"injected at {name}")
            return hook
        for boundary, observed in (("transaction-applied", d.LEDGER_SCHEMA),
                                   ("target-verified", TARGET)):
            with self.subTest(boundary=boundary):
                self.setUp()
                with mock.patch.object(m, "_boundary", fail_at(boundary)):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        self.apply()
                self.assertEqual(m.inspect(self.ledger).observed, observed)
                self.assertTrue(m._present(Path(str(self.ledger.path) + m.INTENT_SUFFIX)))
                self.assertTrue(self.apply()["resumed"])
                self.assert_migrated()


if __name__ == "__main__":
    unittest.main()
