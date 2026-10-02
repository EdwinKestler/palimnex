#!/usr/bin/env python3
"""Rehearse a copied-bundle upgrade from a release tag to this checkout.

All mutable state lives below one short temporary directory.  The script starts
its own socket-only Redis process and never opens the checkout's configured
cache or durable ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable
import uuid


CHECKOUT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT_SECONDS = 120
FIXED_RECALL_TIME = "4102444800000"  # 2100-01-01T00:00:00Z
DOCTOR_STATUSES = frozenset({"ok", "info", "warn", "fail", "skip"})
RETENTION_SCHEMA = "project-memory:retention-ledger:v2"


class RehearsalError(RuntimeError):
    """A rehearsal assertion or subprocess failed."""


def _run(
    command: Iterable[str],
    *,
    cwd: Path,
    expected: frozenset[int] = frozenset({0}),
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = list(command)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode not in expected:
        rendered = " ".join(argv)
        raise RehearsalError(
            f"command exited {result.returncode}, expected {sorted(expected)}: {rendered}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _json(result: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RehearsalError(f"{label} did not emit JSON: {result.stdout!r}") from exc
    if not isinstance(value, dict):
        raise RehearsalError(f"{label} did not emit a JSON object")
    return value


def _cli_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PALIMNEX_ROOT",
        "PALIMNEX_URL",
        "PROJECT_MEMORY_URL",
        "PALIMNEX_PACK_KEY_FILE",
        "PROJECT_MEMORY_PACK_KEY_FILE",
        "PYTHONPATH",
    ):
        environment.pop(name, None)
    return environment


def _cli(
    root: Path,
    *arguments: str,
    expected: frozenset[int] = frozenset({0}),
    redis_url: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = _cli_environment()
    if redis_url is not None:
        environment["PALIMNEX_URL"] = redis_url
    return _run(
        [sys.executable, str(root / "palimnex.py"), *arguments],
        cwd=root,
        expected=expected,
        environment=environment,
    )


def _cli_json(
    root: Path,
    *arguments: str,
    expected: frozenset[int] = frozenset({0}),
    redis_url: str | None = None,
) -> dict[str, Any]:
    return _json(
        _cli(root, *arguments, expected=expected, redis_url=redis_url),
        "palimnex " + " ".join(arguments),
    )


def _latest_release_tag(requested: str | None) -> str:
    if requested:
        tag = requested
    else:
        result = _run(
            ["git", "tag", "--list", "v*", "--sort=-version:refname"],
            cwd=CHECKOUT,
        )
        tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not tags:
            raise RehearsalError("no v* release tag is available")
        tag = tags[0]
    _run(
        ["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        cwd=CHECKOUT,
    )
    return tag


def _extract_old_bundle(tag: str, destination: Path) -> None:
    archive = subprocess.Popen(
        ["git", "archive", tag, "palimnex.py", "palimnex"],
        cwd=CHECKOUT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if archive.stdout is None or archive.stderr is None:
        archive.kill()
        raise RehearsalError("could not create the git archive pipeline")
    extract = subprocess.Popen(
        ["tar", "-x", "-C", str(destination)],
        stdin=archive.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    archive.stdout.close()
    try:
        extract_stdout, extract_stderr = extract.communicate(timeout=COMMAND_TIMEOUT_SECONDS)
        archive_stderr = archive.stderr.read()
        archive_returncode = archive.wait(timeout=COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        archive.kill()
        extract.kill()
        archive.wait()
        extract.wait()
        raise RehearsalError("git archive or tar extraction timed out") from exc
    if archive_returncode != 0:
        raise RehearsalError(
            f"git archive exited {archive_returncode}: {archive_stderr.decode(errors='replace')}"
        )
    if extract.returncode != 0:
        raise RehearsalError(
            f"tar exited {extract.returncode}: {extract_stderr.decode(errors='replace')}\n"
            f"stdout: {extract_stdout.decode(errors='replace')}"
        )


def _write_repository_files(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "docs" / "upgrade.md").write_text(
        "# Upgrade rehearsal\n\nThe cobalt archive remains recallable after an upgrade.\n",
        encoding="utf-8",
    )
    (root / ".gitignore").write_text(".palimnex/\n", encoding="utf-8")
    config = {
        "project_slug": "upgrade-rehearsal",
        "project_id": str(uuid.uuid4()),
        "cache_mode": "on",
        "redis_socket_path": ".palimnex/redis/redis.sock",
        "durable_ledger_path": ".palimnex/memory.sqlite3",
        "include_patterns": ["docs/**/*.md"],
        "semantic_provider": {"mode": "disabled"},
    }
    (root / ".palimnex.json").write_text(
        json.dumps(config, sort_keys=True) + "\n", encoding="utf-8"
    )
    _run(["git", "init", "-q"], cwd=root)
    _run(["git", "check-ignore", "-q", ".palimnex/memory.sqlite3"], cwd=root)


def _wait_for_redis(socket_path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RehearsalError(f"temporary redis-server exited {process.returncode}")
        if socket_path.is_socket():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    client.connect(str(socket_path))
                    client.sendall(b"*1\r\n$4\r\nPING\r\n")
                    if client.recv(64).startswith(b"+PONG"):
                        return
            except OSError:
                pass
        time.sleep(0.05)
    raise RehearsalError("temporary redis-server did not create a usable socket")


def _start_redis(root: Path) -> tuple[subprocess.Popen[bytes], Path, str]:
    executable = shutil.which("redis-server")
    if executable is None:
        raise RehearsalError("redis-server is required")
    state = root / ".palimnex" / "redis"
    state.mkdir(parents=True, mode=0o700)
    socket_path = state / "redis.sock"
    if len(os.fsencode(socket_path)) >= 108:
        raise RehearsalError(f"temporary Redis socket path is too long: {socket_path}")
    process = subprocess.Popen(
        [
            executable,
            "--port", "0",
            "--unixsocket", str(socket_path),
            "--unixsocketperm", "600",
            "--protected-mode", "yes",
            "--daemonize", "no",
            "--dir", str(state),
            "--dbfilename", "rehearsal.rdb",
            "--appendonly", "no",
            "--save", "",
        ],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_redis(socket_path, process)
        if stat.S_IMODE(socket_path.stat().st_mode) != 0o600:
            raise RehearsalError("temporary Redis socket is not owner-only")
    except BaseException:
        _stop_redis(process)
        raise
    return process, socket_path, f"redis+unix://{socket_path}?db=0"


def _stop_redis(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _replace_with_head(root: Path) -> None:
    package = root / "palimnex"
    entrypoint = root / "palimnex.py"
    shutil.rmtree(package)
    entrypoint.unlink()
    if package.exists() or entrypoint.exists():
        raise RehearsalError("old bundle was not fully removed before the upgrade")
    shutil.copy2(CHECKOUT / "palimnex.py", entrypoint)
    shutil.copytree(CHECKOUT / "palimnex", package)


def _version(root: Path) -> str:
    return _cli(root, "--version").stdout.strip()


def _recall(root: Path) -> dict[str, Any]:
    return _cli_json(
        root,
        "recall",
        "cobalt archive",
        "--known-at", FIXED_RECALL_TIME,
        "--valid-at", FIXED_RECALL_TIME,
    )


def _tree_state(root: Path) -> dict[str, tuple[str, int]]:
    state: dict[str, tuple[str, int]] = {}
    if not root.exists():
        return state
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_dir():
            state[relative] = ("directory", mode)
        elif path.is_file():
            state[relative] = (hashlib.sha256(path.read_bytes()).hexdigest(), mode)
        else:
            state[relative] = ("other", mode)
    return state


def _copy_for_retention(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(".git", ".palimnex"),
    )
    _run(["git", "init", "-q"], cwd=target)
    private = target / ".palimnex"
    private.mkdir(mode=0o700)
    source_database = sqlite3.connect(source / ".palimnex" / "memory.sqlite3")
    destination_database = sqlite3.connect(target / ".palimnex" / "memory.sqlite3")
    try:
        source_database.backup(destination_database)
    finally:
        destination_database.close()
        source_database.close()
    os.chmod(target / ".palimnex" / "memory.sqlite3", 0o600)


def _assert_doctor(report: dict[str, Any]) -> None:
    if report.get("schema") != "palimnex:doctor:v1" or report.get("writes") is not False:
        raise RehearsalError("doctor report has an invalid envelope")
    if report.get("status") not in {"healthy", "action_needed"}:
        raise RehearsalError("doctor report has an invalid status")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise RehearsalError("doctor report has no checks")
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) != {"id", "status", "detail", "action"}
            or not isinstance(check["id"], str)
            or check["status"] not in DOCTOR_STATUSES
            or not isinstance(check["detail"], str)
            or (check["action"] is not None and not isinstance(check["action"], str))
        ):
            raise RehearsalError(f"doctor emitted a malformed check: {check!r}")


def _rehearse_retention(source: Path, target: Path, redis_url: str) -> dict[str, Any]:
    _copy_for_retention(source, target)
    before_status = _cli_json(target, "ledger-status")
    expected_digest = before_status["logical_digest"]
    before = _tree_state(target / ".palimnex")
    preview = _cli_json(
        target,
        "retention-migrate",
        "--expected-digest", expected_digest,
        "--dry-run",
    )
    after = _tree_state(target / ".palimnex")
    if before != after or preview.get("will_write") is not False:
        raise RehearsalError("retention-migrate --dry-run changed temporary state")
    if preview.get("would_refuse") != [] or preview.get("logical_digest") != expected_digest:
        raise RehearsalError("retention migration dry run did not accept the expected digest")

    migration = _cli_json(
        target, "retention-migrate", "--expected-digest", expected_digest
    )
    snapshot = migration.get("pre_migration_snapshot")
    if not isinstance(snapshot, dict):
        raise RehearsalError("retention migration did not report a pre-migration snapshot")
    snapshot_path = Path(str(snapshot.get("path")))
    if (
        snapshot.get("integrity") != "ok"
        or snapshot.get("logical_digest") != expected_digest
        or snapshot.get("schema") != "project-memory:ledger:v1"
        or not snapshot_path.is_file()
        or stat.S_IMODE(snapshot_path.stat().st_mode) != 0o600
    ):
        raise RehearsalError("pre-migration snapshot was not verified against the expected digest")

    hot = _cli(
        target,
        "project-hot",
        expected=frozenset({1}),
        redis_url=redis_url,
    )
    if "adapter required" not in hot.stderr:
        raise RehearsalError("project-hot was not refused by the retention profile")

    key_path = target / ".palimnex" / "rehearsal.key"
    key_path.write_bytes(b"R" * 32)
    os.chmod(key_path, 0o600)
    imported = _cli(
        target,
        "memory-import",
        str(target / ".palimnex" / "absent.pmem"),
        "--key-file", str(key_path),
        expected=frozenset({1}),
    )
    if "retention ledger replacement requires" not in imported.stderr:
        raise RehearsalError("memory-import was not refused by the retention profile")

    doctor_result = _cli(
        target, "doctor", expected=frozenset({0, 2}), redis_url=redis_url
    )
    doctor = _json(doctor_result, "palimnex doctor after retention migration")
    _assert_doctor(doctor)
    retention_checks = [
        check for check in doctor["checks"] if check["id"] == "retention"
    ]
    if (
        not retention_checks
        or "retention profile is active" not in retention_checks[0]["detail"]
    ):
        raise RehearsalError("doctor did not report the active retention profile")
    return {
        "dry_run_unchanged": True,
        "snapshot": snapshot_path.name,
        "snapshot_digest": snapshot["logical_digest"],
        "project_hot_refused": True,
        "memory_import_refused": True,
        "doctor_exit": doctor_result.returncode,
    }


def _ledger_shape(root: Path) -> dict[str, Any]:
    """Schema objects, metadata, first migration record and guard of a migrated copy."""
    ledger = root / ".palimnex" / "memory.sqlite3"
    database = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        objects = database.execute(
            "SELECT type, name, sql FROM sqlite_schema ORDER BY name"
        ).fetchall()
        metadata = database.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
        first = json.loads(database.execute(
            "SELECT payload FROM retention_control ORDER BY sequence LIMIT 1"
        ).fetchone()[0])
    finally:
        database.close()
    return {
        "objects": objects,
        "metadata": metadata,
        "migration_fields": sorted(first),
        "from_schema": first["from_schema"],
        "before_digest": first["before_digest"],
        "guard": (root / ".palimnex" / "memory.sqlite3.retention-v2").read_bytes(),
    }


def _rehearse_generic(source: Path, target: Path, alias_target: Path) -> dict[str, Any]:
    """Migrate a second copy with `ledger-migrate` and compare it with the alias result."""
    _copy_for_retention(source, target)
    expected_digest = _cli_json(target, "ledger-status")["logical_digest"]
    before = _tree_state(target / ".palimnex")
    plan = _cli_json(
        target, "ledger-migrate", "--plan", "--to", RETENTION_SCHEMA,
        "--expected-digest", expected_digest,
    )
    if _tree_state(target / ".palimnex") != before or plan.get("will_write") is not False:
        raise RehearsalError("ledger-migrate --plan changed temporary state")
    if plan.get("status") != "ready" or plan.get("refusals") != []:
        raise RehearsalError(f"ledger-migrate --plan was not ready: {plan.get('refusals')}")
    applied = _cli_json(
        target, "ledger-migrate", "--apply", "--to", RETENTION_SCHEMA,
        "--expected-digest", expected_digest,
    )
    snapshot = applied.get("pre_migration_snapshot")
    if (
        applied.get("status") != "migrated"
        or not isinstance(snapshot, dict)
        or snapshot.get("logical_digest") != expected_digest
    ):
        raise RehearsalError("ledger-migrate --apply did not migrate with a verified snapshot")
    rerun = _cli_json(
        target, "ledger-migrate", "--apply", "--to", RETENTION_SCHEMA,
        "--expected-digest", expected_digest,
    )
    if rerun.get("status") != "already_migrated":
        raise RehearsalError("rerunning ledger-migrate --apply was not idempotent")
    leftovers = sorted(
        path.name for path in (target / ".palimnex").iterdir()
        if path.name.endswith(".migration-intent") or ".tmp-" in path.name
    )
    if leftovers:
        raise RehearsalError(f"ledger-migrate left transient files: {leftovers}")
    if _ledger_shape(target) != _ledger_shape(alias_target):
        raise RehearsalError("ledger-migrate and retention-migrate produced different ledgers")
    return {
        "plan_unchanged": True,
        "status": applied["status"],
        "rerun": rerun["status"],
        "matches_alias": True,
    }


def rehearse(tag: str) -> dict[str, Any]:
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="pmx-upg-", dir="/tmp") as temporary:
            root = Path(temporary)
            repository = root / "repo"
            retention_repository = root / "ret"
            generic_repository = root / "gen"
            repository.mkdir()
            _extract_old_bundle(tag, repository)
            _write_repository_files(repository)
            redis_process, socket_path, redis_url = _start_redis(repository)
            try:
                old_version = _version(repository)
                _cli_json(repository, "index", "--incremental")
                _cli_json(repository, "ledger-init")
                session = _cli_json(
                    repository, "session-start", "--task", "rehearse copied-bundle upgrade"
                )["session_id"]
                remembered = _cli_json(
                    repository,
                    "remember",
                    "--session", session,
                    "--kind", "fact",
                    "--subject", "cobalt archive",
                    "--payload", '{"state":"preserved across upgrade"}',
                    "--retention", "durable",
                    "--evidence", "docs/upgrade.md:3",
                )
                _cli_json(
                    repository,
                    "session-close", session,
                    "--outcome", "old release state prepared",
                    "--evidence", "docs/upgrade.md:3",
                )
                _cli_json(repository, "consolidate", session)
                old_recall = _recall(repository)
                if remembered["event_id"] not in {
                    result["event_id"] for result in old_recall.get("results", [])
                }:
                    raise RehearsalError("old release did not recall the durable fact")
                old_status = _cli_json(repository, "ledger-status")
                if old_status.get("status") != "ready":
                    raise RehearsalError("old release ledger is not ready")

                _replace_with_head(repository)
                new_version = _version(repository)
                new_status = _cli_json(repository, "ledger-status")
                if (
                    new_status.get("status") != "ready"
                    or new_status.get("counts") != old_status.get("counts")
                ):
                    raise RehearsalError("HEAD did not preserve the ready ledger and its counts")
                new_recall = _recall(repository)
                if new_recall.get("results") != old_recall.get("results"):
                    raise RehearsalError("recall results changed across the upgrade")

                if old_version != new_version:
                    status = _cli_json(repository, "status", expected=frozenset({2}))
                    if status.get("built_by_version") != old_version:
                        raise RehearsalError("stale cache status did not identify its builder")
                    search = _cli(
                        repository,
                        "search", "cobalt archive",
                        expected=frozenset({1}),
                    )
                    if f"built by Palimnex {old_version}" not in search.stderr:
                        raise RehearsalError("stale cache search did not identify its builder")

                _cli_json(repository, "index", "--incremental")
                validation = _cli_json(repository, "validate", "--deep")
                if validation.get("fresh") is not True or validation.get("validation") != "passed":
                    raise RehearsalError("HEAD cache is not fresh and deep-valid")
                doctor_result = _cli(
                    repository, "doctor", expected=frozenset({0, 2})
                )
                _assert_doctor(_json(doctor_result, "palimnex doctor"))

                retention = _rehearse_retention(
                    repository, retention_repository, redis_url
                )
                retention["generic"] = _rehearse_generic(
                    repository, generic_repository, retention_repository
                )
                return {
                    "status": "passed",
                    "from": tag,
                    "old_version": old_version,
                    "new_version": new_version,
                    "version_changed": old_version != new_version,
                    "ledger_counts": new_status["counts"],
                    "recall_results": len(new_recall["results"]),
                    "cache_fresh": True,
                    "doctor_exit": doctor_result.returncode,
                    "redis_socket_bytes": len(os.fsencode(socket_path)),
                    "retention": retention,
                    "live_state_touched": False,
                    "network_used": False,
                }
            finally:
                _stop_redis(redis_process)
    finally:
        os.umask(old_umask)


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument(
        "--from",
        dest="from_tag",
        help="release tag to rehearse (default: latest v* tag)",
    )
    parsed = arguments.parse_args()
    try:
        print(json.dumps(rehearse(_latest_release_tag(parsed.from_tag)), sort_keys=True))
        return 0
    except (
        KeyError,
        OSError,
        RehearsalError,
        sqlite3.Error,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
