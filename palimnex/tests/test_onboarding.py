from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from palimnex import cache_v3
from palimnex import core
from palimnex import onboarding
from palimnex.tests.fake_redis import FakeRedis
from palimnex.tests.support import write_project

REPOSITORY = Path(__file__).resolve().parents[2]


def tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


class ActionableErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_too_long_socket_path_names_the_limit_and_workaround(self) -> None:
        path = "/" + "a" * core.UNIX_SOCKET_PATH_LIMIT
        client = core.RedisClient(f"redis+unix://{path}?db=0")
        with self.assertRaisesRegex(core.RedisError, "PALIMNEX_URL") as raised:
            client.execute("PING")
        self.assertIn(f"{len(path)} bytes", str(raised.exception))
        self.assertNotIn(path, str(raised.exception))

    def test_missing_socket_points_to_the_launcher(self) -> None:
        client = core.RedisClient(f"redis+unix://{self.root}/absent.sock?db=0")
        with self.assertRaisesRegex(core.RedisError, "palimnex redis start"):
            client.execute("PING")

    def test_stale_socket_file_is_reported_as_not_running(self) -> None:
        path = self.root / "stale.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.close()
        os.chmod(path, 0o600)
        client = core.RedisClient(f"redis+unix://{path}?db=0")
        with self.assertRaisesRegex(core.RedisError, "stale socket file"):
            client.execute("PING")

    def test_cache_and_ledger_commands_require_configuration(self) -> None:
        for command in (["status"], ["ledger-status"]):
            errors = io.StringIO()
            with mock.patch.object(core, "ROOT", self.root), contextlib.redirect_stderr(errors):
                code = core.main(command)
            self.assertEqual(code, 1)
            self.assertIn("palimnex init", json.loads(errors.getvalue())["error"])

    def test_cache_built_by_another_version_names_it_and_the_fix(self) -> None:
        write_project(self.root)
        client = FakeRedis()
        cache_v3.build_index(client, self.root)
        active = client.values[f"{cache_v3.namespace(self.root)}:active-generation"]
        key = active.decode("utf-8") if isinstance(active, bytes) else str(active)
        manifest = json.loads(client.values[key])
        manifest["bundle_version"] = "2.6.0-rc.1"
        client.values[key] = json.dumps(manifest).encode("utf-8")

        status, fresh = cache_v3.status(client, self.root)
        self.assertFalse(fresh)
        self.assertEqual(status["status"], "missing_or_invalid")
        self.assertEqual(status["built_by_version"], "2.6.0-rc.1")
        self.assertIn("index --incremental", status["action"])
        with self.assertRaisesRegex(ValueError, "built by Palimnex 2.6.0-rc.1"):
            cache_v3.search(client, "cobalt orchard", 5, self.root)



class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.client = FakeRedis()
        self.client.socket_path = None  # type: ignore[attr-defined]

    def _doctor(self) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
        with mock.patch.object(core, "RedisClient", return_value=self.client):
            report = onboarding.doctor(self.root, redis_url="redis://127.0.0.1:6379/0")
        return report, {check["id"]: check for check in report["checks"]}  # type: ignore[index]

    def _configure(self, **changes: object) -> None:
        path = self.root / ".palimnex.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        for key, value in changes.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        path.write_text(json.dumps(config), encoding="utf-8")

    def test_missing_configuration_is_the_only_failure_reported(self) -> None:
        report, checks = self._doctor()
        self.assertEqual(report["status"], "action_needed")
        self.assertEqual(checks["config"]["status"], "fail")
        self.assertIn("palimnex init", checks["config"]["action"])
        self.assertNotIn("redis", checks)

    def test_healthy_fresh_repository_and_no_content_changes(self) -> None:
        write_project(self.root)
        self._configure(cache_mode="on")
        cache_v3.build_index(self.client, self.root)
        files_before = tree_digest(self.root)
        redis_before = dict(self.client.values)
        report, checks = self._doctor()
        self.assertEqual(tree_digest(self.root), files_before)
        self.assertEqual(self.client.values, redis_before)
        self.assertFalse(report["writes"])
        self.assertEqual(checks["cache"]["status"], "ok")
        self.assertEqual(checks["cache_mode"]["status"], "ok")
        self.assertEqual(checks["git_ignore"]["status"], "skip")
        self.assertEqual(checks["ledger"]["status"], "info")
        self.assertEqual(report["status"], "healthy", report)

    def test_warns_about_off_mode_missing_slug_stale_cache_and_unindexed_code(self) -> None:
        write_project(self.root)
        self._configure(cache_mode=None, project_slug=None)
        (self.root / "app").mkdir()
        (self.root / "app/payments.py").write_text("def refund():\n    return 1\n", encoding="utf-8")
        report, checks = self._doctor()
        self.assertEqual(report["status"], "action_needed")
        self.assertEqual(checks["cache_mode"]["status"], "warn")
        self.assertEqual(checks["project_slug"]["status"], "warn")
        self.assertIn("app/ (1 file)", checks["corpus_code"]["detail"])
        self.assertEqual(checks["cache"]["status"], "info")

    def test_cache_built_by_another_version_is_named(self) -> None:
        write_project(self.root)
        self._configure(cache_mode="on")
        cache_v3.build_index(self.client, self.root)
        active = self.client.values[f"{cache_v3.namespace(self.root)}:active-generation"]
        key = active.decode("utf-8") if isinstance(active, bytes) else str(active)
        manifest = json.loads(self.client.values[key])
        manifest["bundle_version"] = "2.6.0-rc.1"
        self.client.values[key] = json.dumps(manifest).encode("utf-8")
        _, checks = self._doctor()
        self.assertEqual(checks["cache"]["status"], "warn")
        self.assertIn("2.6.0-rc.1", checks["cache"]["detail"])

    def test_existing_ledger_is_reported_ready(self) -> None:
        from palimnex.api import Palimnex
        write_project(self.root)
        self._configure(cache_mode="on")
        Palimnex(self.root, writable=True).initialize()
        _, checks = self._doctor()
        self.assertEqual(checks["ledger"]["status"], "ok")
        self.assertEqual(checks["retention"]["status"], "info")

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_unignored_ledger_path_fails_in_a_git_work_tree(self) -> None:
        write_project(self.root)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        _, checks = self._doctor()
        self.assertEqual(checks["git_ignore"]["status"], "fail")
        (self.root / ".gitignore").write_text(".private/\n*.pmem\n", encoding="utf-8")
        _, checks = self._doctor()
        self.assertEqual(checks["git_ignore"]["status"], "ok")
        self.assertNotIn("git_ignore_packs", checks)

    def test_cli_exit_codes(self) -> None:
        output = io.StringIO()
        with mock.patch.object(core, "ROOT", self.root), contextlib.redirect_stdout(output):
            code = core.main(["doctor"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["schema"], onboarding.DOCTOR_SCHEMA)


class InitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "acme-app"
        for relative in ("app/payments.py", "src/core.py", "docs/guide.md", "data/raw.py",
                         ".hidden/tool.py", "README.md"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x = 1\n" if relative.endswith(".py") else "# Title\n", encoding="utf-8")

    def test_preview_writes_nothing_and_proposes_safe_defaults(self) -> None:
        before = tree_digest(self.root)
        result = onboarding.init(self.root, write=False)
        self.assertEqual(tree_digest(self.root), before)
        self.assertEqual(result["mode"], "preview")
        config = result["config"]
        self.assertEqual(config["cache_mode"], "on")
        self.assertEqual(config["project_slug"], "acme-app")
        self.assertIn("app/**/*.py", config["include_patterns"])
        self.assertIn("src/**/*.py", config["include_patterns"])
        self.assertIn("docs/**/*.md", config["include_patterns"])
        self.assertFalse(any(p.startswith(("data/", ".hidden/")) for p in config["include_patterns"]))
        self.assertEqual(result["gitignore_additions"], list(onboarding.GITIGNORE_LINES))
        self.assertFalse(result["creates_ledger"])

    def test_write_creates_configuration_and_gitignore_once(self) -> None:
        result = onboarding.init(self.root, write=True, slug="Acme App")
        self.assertEqual(result["written"], [".gitignore", ".palimnex.json"])
        config = json.loads((self.root / ".palimnex.json").read_text(encoding="utf-8"))
        uuid.UUID(config["project_id"])
        self.assertEqual(config["project_slug"], "acme-app")
        lines = (self.root / ".gitignore").read_text(encoding="utf-8").splitlines()
        for line in onboarding.GITIGNORE_LINES:
            self.assertIn(line, lines)
        self.assertIn("app/payments.py", {p.relative_to(self.root).as_posix() for p in core.included_files(self.root)})
        self.assertFalse((self.root / ".palimnex").exists())
        with self.assertRaisesRegex(ValueError, "never overwrites"):
            onboarding.init(self.root, write=True)

    def test_existing_gitignore_keeps_content_and_gains_only_missing_lines(self) -> None:
        (self.root / ".gitignore").write_text("node_modules/\n.palimnex/", encoding="utf-8")
        onboarding.init(self.root, write=True)
        text = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("node_modules/\n.palimnex/\n"))
        self.assertEqual(text.count(".palimnex/"), 1)
        self.assertIn("*.pmem\n", text)
        self.assertIn("*.key\n", text)

    def test_symlinked_gitignore_is_refused_before_any_write(self) -> None:
        target = self.root / "elsewhere.txt"
        target.write_text("", encoding="utf-8")
        (self.root / ".gitignore").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            onboarding.init(self.root, write=True)
        self.assertFalse((self.root / ".palimnex.json").exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_cli_preview(self) -> None:
        output = io.StringIO()
        with mock.patch.object(core, "ROOT", self.root), contextlib.redirect_stdout(output):
            code = core.main(["init"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "preview")
        self.assertFalse((self.root / ".palimnex.json").exists())



@unittest.skipUnless(shutil.which("git"), "git is required")
class LedgerCommitGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_project(self.root)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def _cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "PYTHONPATH": str(REPOSITORY)}
        environment.pop("PALIMNEX_ROOT", None)
        return subprocess.run([sys.executable, "-m", "palimnex", *arguments], cwd=self.root,
                              env=environment, capture_output=True, text=True, check=False)

    def test_sdk_refuses_an_unignored_ledger_and_creates_nothing(self) -> None:
        from palimnex.api import Palimnex
        with self.assertRaisesRegex(ValueError, "Git does not ignore"):
            Palimnex(self.root, writable=True).initialize()
        self.assertFalse((self.root / ".private").exists())

    def test_cli_refuses_explicit_and_implicit_creation(self) -> None:
        for arguments in (("ledger-init",), ("session-start", "--task", "t")):
            result = self._cli(*arguments)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Git does not ignore", json.loads(result.stderr)["error"])
        self.assertFalse((self.root / ".private").exists())

    def test_explicit_override_and_ignored_path_both_create_the_ledger(self) -> None:
        result = self._cli("ledger-init", "--allow-unignored-ledger")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / ".private/memory.sqlite3").is_file())
        shutil.rmtree(self.root / ".private")
        (self.root / ".gitignore").write_text(".private/\n", encoding="utf-8")
        from palimnex.api import Palimnex
        self.assertEqual(Palimnex(self.root, writable=True).initialize()["status"], "ready")



class LedgerSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        from palimnex.api import Event, Evidence, Palimnex
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_project(self.root)
        self.client = Palimnex(self.root, writable=True)
        self.client.initialize()
        session = self.client.start_session("snapshot rehearsal")["session_id"]
        self.client.record(Event(session, "fact", "cobalt orchard", {"state": "kept"},
                                 (Evidence("docs/alpha.md:1-3"),), retention="durable"))
        self.client.close_session(session, "done")

    def _cli(self, *arguments: str) -> dict[str, object]:
        environment = {**os.environ, "PYTHONPATH": str(REPOSITORY)}
        environment.pop("PALIMNEX_ROOT", None)
        result = subprocess.run([sys.executable, "-m", "palimnex", *arguments], cwd=self.root,
                                env=environment, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_backup_is_private_self_contained_and_verified(self) -> None:
        snapshot = self.client.backup_ledger()
        path = Path(snapshot["path"])
        self.assertEqual(path.parent, self.root / ".private/backups")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertFalse(Path(str(path) + "-wal").exists())
        self.assertEqual(snapshot["logical_digest"], self.client.status()["logical_digest"])
        self.assertIn("does not remove", snapshot["note"])
        report = onboarding.doctor(self.root, redis_url="redis://127.0.0.1:6379/0")
        checks = {check["id"]: check for check in report["checks"]}
        self.assertIn("1 ledger snapshot(s)", checks["snapshots"]["detail"])
        with self.assertRaises(FileExistsError):
            self.client.backup_ledger(path)
        with self.assertRaisesRegex(ValueError, "parent directory"):
            self.client.backup_ledger(Path(self.temporary.name) / "absent" / "copy.sqlite3")

    def test_dry_run_writes_nothing_and_reports_refusal(self) -> None:
        digest = self.client.status()["logical_digest"]
        preview = self._cli("retention-migrate", "--expected-digest", digest, "--dry-run")
        self.assertFalse(preview["will_write"])
        self.assertEqual(preview["would_refuse"], [])
        self.assertTrue(any("memory-import" in effect for effect in preview["effects"]))
        wrong = self._cli("retention-migrate", "--expected-digest", "0" * 64, "--dry-run")
        self.assertEqual(wrong["would_refuse"], ["DIGEST_MISMATCH"])
        self.assertFalse((self.root / ".private/memory.sqlite3.retention-v2").exists())
        self.assertFalse((self.root / ".private/backups").exists())
        self.assertEqual(self.client.status()["logical_digest"], digest)

    def test_cli_migration_writes_a_verified_snapshot_first(self) -> None:
        digest = self.client.status()["logical_digest"]
        output = self._cli("retention-migrate", "--expected-digest", digest)
        snapshot = output["pre_migration_snapshot"]
        self.assertEqual(snapshot["logical_digest"], digest)
        self.assertEqual(snapshot["schema"], "project-memory:ledger:v1")
        self.assertTrue(Path(snapshot["path"]).name.endswith("-pre-retention-v2.sqlite3"))
        self.assertTrue((self.root / ".private/memory.sqlite3.retention-v2").exists())

    def test_sdk_snapshot_is_opt_in(self) -> None:
        digest = self.client.status()["logical_digest"]
        result = self.client.migrate_retention(expected_digest=digest)
        self.assertNotIn("pre_migration_snapshot", result)
        self.assertFalse((self.root / ".private/backups").exists())



class PackagedRedisLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pmx-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = {"project_slug": "launcher", "project_id": str(uuid.uuid4()), "cache_mode": "on",
                       "redis_socket_path": ".palimnex/redis/redis.sock"}
        (self.root / ".palimnex.json").write_text(json.dumps(self.config), encoding="utf-8")

    def _cli(self, *arguments: str, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "PYTHONPATH": str(REPOSITORY), **(extra or {})}
        environment.pop("PALIMNEX_ROOT", None)
        return subprocess.run([sys.executable, "-m", "palimnex", *arguments], cwd=self.root,
                              env=environment, capture_output=True, text=True, check=False)

    def test_packaged_launcher_is_identical_to_the_repository_script(self) -> None:
        # scripts/palimnex_redis.sh is the reviewed, indexed source; the package carries a copy.
        self.assertEqual(core.REDIS_LAUNCHER.read_bytes(),
                         (REPOSITORY / "scripts/palimnex_redis.sh").read_bytes())

    def test_status_and_guard_target_the_current_repository_without_writing(self) -> None:
        fake_cli = self.root / "fake-cli"
        fake_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_cli.chmod(0o700)
        fakes = {"REDIS_SERVER_BIN": "/bin/true", "REDIS_CLI_BIN": str(fake_cli)}
        status = self._cli("redis", "status", extra=fakes)
        self.assertEqual(status.returncode, 1)
        self.assertIn(str(self.root / ".palimnex/redis/redis.sock"), status.stdout)
        self.assertEqual(self._cli("redis", "guard", extra=fakes).returncode, 0)
        self.assertFalse((self.root / ".palimnex").exists())

    def test_start_refuses_a_too_long_socket_path_before_running_the_launcher(self) -> None:
        self.config["redis_socket_path"] = ".palimnex/" + "d" * core.UNIX_SOCKET_PATH_LIMIT + "/redis.sock"
        (self.root / ".palimnex.json").write_text(json.dumps(self.config), encoding="utf-8")
        with mock.patch.object(subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "PALIMNEX_URL"):
                core.run_redis_launcher("start", self.root)
        run.assert_not_called()

    def test_start_requires_the_client_to_use_the_launcher_socket(self) -> None:
        del self.config["redis_socket_path"]
        (self.root / ".palimnex.json").write_text(json.dumps(self.config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "redis_socket_path"):
            core.run_redis_launcher("start", self.root)

    @unittest.skipUnless(shutil.which("redis-server") and shutil.which("redis-cli"), "Redis is required")
    def test_real_start_index_and_stop(self) -> None:
        (self.root / "docs").mkdir()
        (self.root / "docs/notes.md").write_text("# Notes\n\nRetry budget is three.\n", encoding="utf-8")
        started = self._cli("redis", "start")
        self.addCleanup(self._cli, "redis", "stop")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(self._cli("index", "--incremental").returncode, 0)
        found = json.loads(self._cli("search", "retry budget").stdout)
        self.assertEqual([item["path"] for item in found["results"]], ["docs/notes.md"])
        self.assertEqual(self._cli("redis", "stop").returncode, 0)


if __name__ == "__main__":
    unittest.main()
