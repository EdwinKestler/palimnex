"""Installation diagnosis (`doctor`) and previewed configuration setup (`init`).

`doctor` changes no configuration, cache or ledger content. When a ledger
exists it is opened exactly like `ledger-status`: under the shared lock, with
its private directory kept at mode 0700. `init` previews by default; with
`write=True` it creates `.palimnex.json` exclusively and appends missing
`.gitignore` lines. Neither creates a ledger, starts Redis, or contacts the
network.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import stat
import sys
import urllib.parse
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from . import core
from .vcs import git_ignore_state

DOCTOR_SCHEMA = "palimnex:doctor:v1"
INIT_SCHEMA = "palimnex:init:v1"
GITIGNORE_HEADER = "# Palimnex runtime state, memory packs and key files"
GITIGNORE_LINES = (".palimnex/", "*.pmem", "*.key")
CODE_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".scala",
    ".sql", ".proto", ".graphql", ".sh",
})
DOCUMENT_SUFFIXES = frozenset({".md"})
MAX_SCANNED_FILES = 50_000
MAX_PROPOSED_PATTERNS = 40

CheckStatus = Literal["ok", "info", "warn", "fail", "skip"]
InstallMode = Literal["installed", "editable", "source_checkout", "copied_bundle"]
COPY_MIGRATION = 'docs/UPGRADING.md, "Copied bundle to package"'
BUNDLE_VERSION_LINE = re.compile(rb'^BUNDLE_VERSION = "([^"\n]{1,64})"$', re.MULTILINE)
MAX_CORE_BYTES = 1 << 20
MAX_PYPROJECT_BYTES = 1 << 16


@dataclass(frozen=True)
class Check:
    id: str
    status: CheckStatus
    detail: str
    action: str | None = None


def _scan_sources(root: Path, excluded: set[str]) -> tuple[list[str], bool]:
    """List code and Markdown files outside excluded and hidden directories."""
    found: list[str] = []
    scanned = 0
    for current, directories, files in os.walk(root):
        base = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in excluded and not name.startswith(".") and not (base / name).is_symlink()
        )
        for name in sorted(files):
            scanned += 1
            if scanned > MAX_SCANNED_FILES:
                return found, True
            suffix = Path(name).suffix.lower()
            if suffix in CODE_SUFFIXES or suffix in DOCUMENT_SUFFIXES:
                found.append((base / name).relative_to(root).as_posix())
    return found, False


def _top_level(relative: str) -> str:
    parts = Path(relative).parts
    return f"{parts[0]}/" if len(parts) > 1 else "(root)"


def _describe_counts(counts: Counter[str]) -> str:
    return ", ".join(
        f"{name} ({count} file{'s' if count != 1 else ''})" for name, count in sorted(counts.items())
    )


def _url_source(root: Path, url: str) -> str:
    for name in core.redis_url_envs(root):
        if os.environ.get(name) == url:
            return f"environment variable {name}"
    if url == core.configured_redis_url(root):
        return "redis_socket_path" if url.startswith("redis+unix://") else "default loopback TCP"
    return "--url"


def _config_checks(root: Path) -> tuple[list[Check], bool]:
    if not core.config_present(root):
        return [Check("config", "fail", f"no {core.CONFIG_FILE} in the repository root",
                      "run `palimnex init` to preview one, then `palimnex init --write`")], False
    checks: list[Check] = []
    try:
        config = core.project_config(root)
        from . import cache_v3
        cache_v3.project_id(root)
        mode = cache_v3.configured_cache_mode(root)
    except (ValueError, TypeError) as exc:
        return [Check("config", "fail", str(exc), f"fix {core.CONFIG_FILE}")], False
    checks.append(Check("config", "ok", f"{core.CONFIG_FILE} is valid with a UUID project_id"))
    if not isinstance(config.get("project_slug"), str) or not config["project_slug"]:
        checks.append(Check(
            "project_slug", "warn",
            "project_slug is not set, so it defaults to the directory name; the ledger refuses "
            "to open under a different slug, for example after a clone into another directory",
            f"add \"project_slug\": \"{core.project_slug(root)}\" to {core.CONFIG_FILE}",
        ))
    else:
        checks.append(Check("project_slug", "ok", f"project_slug is {config['project_slug']!r}"))
    if mode == "on":
        checks.append(Check("cache_mode", "ok", "cache_mode is on (compact v3 cache)"))
    elif mode == "shadow":
        checks.append(Check("cache_mode", "info", "cache_mode is shadow: v2 stays authoritative "
                            "while v3 is built for comparison"))
    else:
        checks.append(Check(
            "cache_mode", "warn",
            "cache_mode is off (or missing): the legacy v2 cache stores complete source text "
            "and plaintext token lists in Redis",
            "for a new repository run `palimnex clear` while still off, then set "
            "\"cache_mode\": \"on\" and run `palimnex index --incremental`; "
            "existing v2 deployments migrate through `migration-shadow` (docs/UPGRADING.md)",
        ))
    return checks, True


def _ignore_checks(root: Path) -> list[Check]:
    try:
        ledger_path = core.durable_ledger_path(root)
    except (ValueError, TypeError) as exc:
        return [Check("git_ignore", "fail", str(exc), f"fix durable_ledger_path in {core.CONFIG_FILE}")]
    ledger_relative = ledger_path.relative_to(root).as_posix()
    state = git_ignore_state(root, ledger_relative)
    if state == "not_applicable":
        return [Check("git_ignore", "skip", "Git is unavailable or this is not a Git work tree")]
    if state == "unknown":
        return [Check("git_ignore", "warn", "Git could not report whether the ledger path is ignored",
                      f"run `git check-ignore -v {ledger_relative}`")]
    lines = " ".join(GITIGNORE_LINES)
    checks = [
        Check("git_ignore", "ok", f"Git ignores {ledger_relative}")
        if state == "ignored"
        else Check("git_ignore", "fail",
                   f"Git does not ignore {ledger_relative}; `git add -A` would commit the ledger",
                   f"add these lines to .gitignore: {lines} (or run `palimnex init --write`)")
    ]
    if git_ignore_state(root, "memory-export.pmem") == "not_ignored":
        checks.append(Check("git_ignore_packs", "warn", "Git does not ignore *.pmem memory packs",
                            f"add these lines to .gitignore: {lines}"))
    return checks


def _redis_checks(root: Path, redis_url: str, cache_ready: bool) -> list[Check]:
    from . import cache_v3
    source = _url_source(root, redis_url)
    try:
        client = core.RedisClient(redis_url, timeout=2.0)
    except core.RedisError as exc:
        return [Check("redis", "fail", f"Redis URL from {source} is invalid: {exc}")]
    if client.socket_path is not None:
        length = len(os.fsencode(client.socket_path))
        if length >= core.UNIX_SOCKET_PATH_LIMIT:
            return [Check(
                "socket_path", "fail",
                f"Redis Unix socket path (from {source}) is {length} bytes; this platform allows "
                f"at most {core.UNIX_SOCKET_PATH_LIMIT - 1}",
                "use a shorter checkout path or set PALIMNEX_URL to a short owner-only socket "
                "(docs/INSTALL.md, \"Long repository paths\")",
            )]
    try:
        client.execute("PING")
    except core.RedisError as exc:
        return [Check("redis", "warn", f"Redis (from {source}) is not reachable: {exc}",
                      "start Redis with `palimnex redis start`; ledger commands work without it")]
    checks = [Check("redis", "ok", f"Redis (from {source}) answers")]
    if not cache_ready:
        return checks
    if cache_v3.configured_cache_mode(root) == "off":
        checks.append(Check("cache", "info", "the legacy v2 cache is in use; v3 freshness not checked"))
        return checks
    try:
        report, fresh = cache_v3.status(client, root)
    except (core.RedisError, ValueError, TypeError, OSError) as exc:
        return checks + [Check("cache", "fail", f"cache status failed: {exc}")]
    if fresh:
        checks.append(Check("cache", "ok", "the v3 cache is fresh"))
    else:
        built_by = report.get("built_by_version")
        detail = (f"the v3 cache was built by Palimnex {built_by}" if built_by
                  else f"the v3 cache is {report['status']}")
        checks.append(Check("cache", "warn", detail, "run `palimnex index --incremental`"))
    if report.get("legacy_preserved"):
        checks.append(Check(
            "legacy_cache", "warn",
            "the legacy v2 cache, which holds complete source text, is still in Redis",
            "once you no longer need a v2 rollback, run `palimnex redis reset`, start Redis "
            "again and reindex (docs/UPGRADING.md)",
        ))
    return checks


def _ledger_checks(root: Path) -> list[Check]:
    from . import cache_v3, durable, retention
    try:
        path = core.durable_ledger_path(root)
    except (ValueError, TypeError) as exc:
        return [Check("ledger", "fail", str(exc))]
    if not path.is_file():
        return [Check("ledger", "info", "no ledger yet; `palimnex ledger-init` or the first "
                      "`session-start` creates it")]
    try:
        ledger = retention.open_ledger(durable.MemoryLedger(
            path, project_id=cache_v3.project_id(root), project_slug=core.project_slug(root),
            root=root,
        ))
        report = ledger.status()
    except (ValueError, TypeError, OSError) as exc:
        action = None
        if "slug" in str(exc):
            action = f"set project_slug in {core.CONFIG_FILE} to the slug the ledger was created with"
        return [Check("ledger", "fail", f"the ledger cannot be opened: {exc}", action)]
    checks = [
        Check("ledger", "ok", "the ledger is ready")
        if report.get("status") == "ready"
        else Check("ledger", "fail", f"ledger status is {report.get('status')}",
                   "run `palimnex ledger-status` for details")
    ]
    backups = path.parent / durable.SNAPSHOT_DIRECTORY
    snapshots = sorted(backups.glob("*.sqlite3")) if backups.is_dir() else []
    if snapshots:
        checks.append(Check(
            "snapshots", "info",
            f"{len(snapshots)} ledger snapshot(s) in {backups.relative_to(root).as_posix()}/; "
            "later authorized erasure does not remove them",
        ))
    if isinstance(ledger, retention.RetentionLedger):
        checks.append(Check(
            "retention", "info",
            "the retention profile is active: hot projection and `memory-import` are "
            "disabled for this ledger",
        ))
    else:
        checks.append(Check("retention", "info", "the optional retention migration has not been "
                            "applied (see docs/UPGRADING.md before running it)"))
    return checks


def _migration_checks(root: Path) -> list[Check]:
    """Unfinished or unsafe migration sidecars; reported, never repaired."""
    from . import cache_v3, durable, migrations
    try:
        ledger = durable.MemoryLedger(
            core.durable_ledger_path(root), project_id=cache_v3.project_id(root),
            project_slug=core.project_slug(root), root=root,
        )
        findings = migrations.doctor_findings(ledger)
    except (ValueError, TypeError, OSError) as exc:
        return [Check("migration", "fail", f"migration state cannot be inspected: {exc}")]
    return [Check(identifier, status, detail, action)
            for identifier, status, detail, action in findings]


def _corpus_checks(root: Path) -> list[Check]:
    try:
        included = {path.relative_to(root).as_posix() for path in core.included_files(root)}
        candidates, truncated = _scan_sources(root, core.configured_excluded_parts(root))
    except (ValueError, TypeError, OSError) as exc:
        return [Check("corpus", "fail", f"the corpus cannot be listed: {exc}")]
    indexed = Counter(_top_level(path) for path in included)
    missing = [path for path in candidates if path not in included]
    missing_code = Counter(_top_level(path) for path in missing
                           if Path(path).suffix.lower() in CODE_SUFFIXES)
    missing_documents = Counter(_top_level(path) for path in missing
                                if Path(path).suffix.lower() in DOCUMENT_SUFFIXES)
    checks = [Check("corpus", "ok" if included else "warn",
                    f"{len(included)} files indexed: {_describe_counts(indexed) or 'none'}",
                    None if included else "set include_patterns in .palimnex.json")]
    if missing_code:
        checks.append(Check("corpus_code", "warn",
                            f"code files not indexed: {_describe_counts(missing_code)}",
                            "add matching include_patterns to .palimnex.json if they should be "
                            "searchable (docs/INSTALL.md)"))
    if missing_documents:
        checks.append(Check("corpus_documents", "info",
                            f"Markdown files not indexed: {_describe_counts(missing_documents)}"))
    if truncated:
        checks.append(Check("corpus_scan", "info",
                            f"the coverage scan stopped after {MAX_SCANNED_FILES} files"))
    return checks


@dataclass(frozen=True)
class Installation:
    """How the running Palimnex was installed, from distribution metadata."""

    mode: InstallMode
    package_dir: Path
    version: str
    distribution_version: str | None = None
    distribution_dir: Path | None = None
    shadowed: bool = False


def _distribution() -> importlib.metadata.Distribution | None:
    try:
        return importlib.metadata.distribution("palimnex")
    except importlib.metadata.PackageNotFoundError:
        return None


def _editable_source(distribution: importlib.metadata.Distribution) -> Path | None:
    """The project directory of an editable install (PEP 610 `direct_url.json`)."""
    raw = distribution.read_text("direct_url.json")
    try:
        document = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(document, dict)
        or not isinstance(document.get("dir_info"), dict)
        or document["dir_info"].get("editable") is not True
        or not isinstance(document.get("url"), str)
    ):
        return None
    parsed = urllib.parse.urlparse(document["url"])
    if parsed.scheme != "file":
        return None
    return Path(urllib.parse.unquote(parsed.path)).resolve()


def _declares_palimnex(directory: Path) -> bool:
    try:
        with open(directory / "pyproject.toml", "rb") as handle:
            text = handle.read(MAX_PYPROJECT_BYTES).decode("utf-8", "replace")
    except OSError:
        return False
    return re.search(r'^name\s*=\s*"palimnex"\s*$', text, re.MULTILINE) is not None


def _copy_version(core_file: Path) -> str | None:
    """BUNDLE_VERSION of another copy, read as bounded text and never imported."""
    try:
        with open(core_file, "rb") as handle:
            match = BUNDLE_VERSION_LINE.search(handle.read(MAX_CORE_BYTES))
    except OSError:
        return None
    return match.group(1).decode("utf-8", "replace") if match else None


def installation(package_dir: Path | None = None, version: str | None = None) -> Installation:
    """Classify the running copy: installed, editable, source checkout or copied bundle.

    Only distribution metadata is trusted. `PALIMNEX_ROOT` and the presence
    of `palimnex.py` are not signals: operators set the first for installed
    commands, and the Palimnex source checkout has the second.
    """
    package = (package_dir or Path(core.__file__).parent).resolve()
    running = version or core.BUNDLE_VERSION
    fallback: InstallMode = (
        "source_checkout" if _declares_palimnex(package.parent) else "copied_bundle")
    distribution = _distribution()
    if distribution is None:
        return Installation(fallback, package, running)
    editable = _editable_source(distribution)
    if editable is not None:
        if package.parent == editable:
            return Installation("editable", package, running, distribution.version,
                                editable / "palimnex")
        return Installation(fallback, package, running, distribution.version,
                            editable / "palimnex", shadowed=True)
    installed = Path(str(distribution.locate_file("palimnex/__init__.py"))).resolve().parent
    if installed == package:
        # Build metadata (for example a leftover `palimnex.egg-info`) inside the
        # Palimnex project tree describes the checkout, not an installed wheel.
        mode: InstallMode = "source_checkout" if _declares_palimnex(package.parent) else "installed"
        return Installation(mode, package, running, distribution.version, installed)
    return Installation(fallback, package, running, distribution.version, installed, shadowed=True)


def _install_checks(root: Path, info: Installation) -> list[Check]:
    """Report the install mode, a shadowed distribution and a second copy in the root."""
    if info.mode == "installed":
        checks = [Check("install_mode", "info",
                        f"Palimnex runs from the installed package at {info.package_dir}")]
    elif info.mode == "editable":
        detail = f"Palimnex runs from an editable install of {info.package_dir.parent}"
        if info.distribution_version and info.distribution_version != info.version:
            detail += (f"; its installed metadata still says {info.distribution_version}, so "
                       "reinstall the editable package to refresh it")
        checks = [Check("install_mode", "info", detail)]
    elif info.mode == "source_checkout":
        checks = [Check("install_mode", "info",
                        f"Palimnex runs from its source checkout at {info.package_dir.parent}")]
    else:
        checks = [Check(
            "install_mode", "warn",
            f"Palimnex runs from a copied bundle at {info.package_dir}. Copying palimnex.py and "
            "palimnex/ into a repository is deprecated: it has no version or integrity check, "
            "and its instructions are removed in 3.0.0",
            f"install the package and remove the copy ({COPY_MIGRATION})",
        )]
    if info.shadowed and info.distribution_dir is not None:
        other = _copy_version(info.distribution_dir / "core.py") or info.distribution_version
        checks.append(Check(
            "install_shadowing", "warn" if other == info.version else "fail",
            f"Python imported Palimnex {info.version} from {info.package_dir}, but the installed "
            f"palimnex distribution ({other or 'unknown version'}) is at "
            f"{info.distribution_dir}; the `palimnex` command and `python3 palimnex.py` can run "
            "different copies against the same ledger",
            "keep one copy: remove the copied palimnex.py and palimnex/ from the repository, "
            f"or uninstall the package ({COPY_MIGRATION})",
        ))
    copy = root / "palimnex"
    if (copy / "core.py").is_file() and copy.resolve() != info.package_dir:
        other = _copy_version(copy / "core.py")
        checks.append(Check(
            "second_copy", "warn" if other == info.version else "fail",
            f"{copy} holds another Palimnex copy ({other or 'unknown version'}) beside this "
            f"Palimnex {info.version}; `python3 palimnex.py` and `python3 -m palimnex` run that "
            "copy, while the `palimnex` command runs this one",
            f"remove the copied palimnex.py and palimnex/ from the repository ({COPY_MIGRATION})",
        ))
    return checks


def _environment_checks() -> list[Check]:
    extras = {
        name: importlib.util.find_spec(module) is not None
        for name, module in (("crypto", "cryptography"), ("mcp", "mcp"))
    }
    available = ", ".join(name for name, present in extras.items() if present) or "none"
    return [
        Check("version", "info", f"Palimnex {core.BUNDLE_VERSION} on Python "
              f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        Check("extras", "info", f"optional extras available: {available}"),
    ]


def doctor(root: Path, *, redis_url: str) -> dict[str, Any]:
    """Run read-only installation checks; see the module docstring for the boundary."""
    checks = _environment_checks()
    checks.extend(_install_checks(root, installation()))
    config_checks, config_ok = _config_checks(root)
    checks.extend(config_checks)
    if config_ok:
        checks.extend(_ignore_checks(root))
        checks.extend(_corpus_checks(root))
        checks.extend(_redis_checks(root, redis_url, cache_ready=True))
        checks.extend(_ledger_checks(root))
        checks.extend(_migration_checks(root))
    healthy = all(check.status not in {"warn", "fail"} for check in checks)
    return {
        "schema": DOCTOR_SCHEMA,
        "status": "healthy" if healthy else "action_needed",
        "root": str(root),
        "writes": False,
        "checks": [asdict(check) for check in checks],
    }


def _slug(root: Path, requested: str | None) -> str:
    source = requested if requested is not None else root.resolve().name
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    if not slug:
        raise ValueError("cannot derive a project slug; pass --slug")
    return slug


def _glob_files(root: Path, pattern: str) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.glob(pattern) if path.is_file()}


def proposed_include_patterns(root: Path) -> tuple[list[str], bool]:
    """Default patterns that match files, plus patterns for uncovered sources."""
    candidates, truncated = _scan_sources(root, set(core.EXCLUDED_PARTS))
    patterns: list[str] = []
    covered: set[str] = set()
    for pattern in core.DEFAULT_PATTERNS:
        matched = _glob_files(root, pattern)
        if matched:
            patterns.append(pattern)
            covered |= matched
    extra: set[str] = set()
    for relative in candidates:
        if relative in covered or relative in {"README.md", "AGENTS.md"}:
            continue
        parts = Path(relative).parts
        suffix = Path(relative).suffix.lower()
        extra.add(f"{parts[0]}/**/*{suffix}" if len(parts) > 1 else f"*{suffix}")
    patterns.extend(sorted(extra))
    return patterns[:MAX_PROPOSED_PATTERNS], truncated or len(patterns) > MAX_PROPOSED_PATTERNS


def _missing_gitignore_lines(root: Path) -> list[str]:
    path = root / ".gitignore"
    if path.is_symlink():
        raise ValueError(".gitignore is a symlink; add the lines by hand")
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    present = {line.strip() for line in existing}
    return [line for line in GITIGNORE_LINES if line not in present]


def _create_exclusive(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _append_gitignore(root: Path, lines: list[str]) -> None:
    path = root / ".gitignore"
    block = GITIGNORE_HEADER + "\n" + "".join(f"{line}\n" for line in lines)
    if not path.exists():
        _create_exclusive(path, block)
        return
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError(".gitignore must be a regular file")
    text = path.read_text(encoding="utf-8")
    separator = "" if not text or text.endswith("\n") else "\n"
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(separator + ("\n" if text.strip() else "") + block)


def init(root: Path, *, write: bool, slug: str | None = None) -> dict[str, Any]:
    """Preview, or with `write=True` create, a starter configuration."""
    if core.config_present(root):
        raise ValueError(f"{core.CONFIG_FILE} already exists; `palimnex init` never overwrites it")
    patterns, truncated = proposed_include_patterns(root)
    config: dict[str, Any] = {
        "project_slug": _slug(root, slug),
        "project_id": str(uuid.uuid4()) if write else "<a new UUID is generated by --write>",
        "cache_mode": "on",
        "redis_socket_path": ".palimnex/redis/redis.sock",
        "durable_ledger_path": ".palimnex/memory.sqlite3",
        "include_patterns": patterns,
        "semantic_provider": {"mode": "disabled"},
    }
    additions = _missing_gitignore_lines(root)
    files = ([".gitignore"] if additions else []) + [core.CONFIG_FILE]
    if write:
        if additions:
            _append_gitignore(root, additions)
        _create_exclusive(root / core.CONFIG_FILE, json.dumps(config, indent=2) + "\n")
    return {
        "schema": INIT_SCHEMA,
        "mode": "written" if write else "preview",
        "written" if write else "would_write": files,
        "config": config,
        "gitignore_additions": additions,
        "include_patterns_truncated": truncated,
        "creates_ledger": False,
        "starts_redis": False,
        "next_steps": (
            ["review include_patterns in .palimnex.json", "palimnex redis start",
             "palimnex index --incremental", "palimnex validate --deep", "palimnex doctor"]
            if write else ["palimnex init --write"]
        ),
    }
