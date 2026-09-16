#!/usr/bin/env bash
# Owner-only Unix-socket Redis for Palimnex.
#
#   ./scripts/palimnex_redis.sh start|stop|status|reset|guard
#
# Redis, reachable only through an owner-mode Unix socket, with its dump, log and pid file under
# `.palimnex/` — a path `.gitignore` already
# excludes. It holds the compact discovery projection that `palimnex.py`
# rebuilds from the checkout; the durable ledger is SQLite, never Redis. The
# dump survives a process restart inside one machine; a fresh environment
# starts empty and the operator reindexes explicitly.
set -euo pipefail

cd "$(dirname "$0")/.."

STATE_DIR_REQUEST="${PALIMNEX_REDIS_DIR:-$PWD/.palimnex/redis}"
SOCKET_PATH_REQUEST="${PALIMNEX_REDIS_SOCKET:-}"
STATE_DIR=""
PID_FILE=""
LOG_FILE=""
DUMP_FILE="dump.rdb"
SOCKET_PATH=""

redis_bin() {
  if command -v "$1" > /dev/null 2>&1; then
    command -v "$1"
  else
    echo ""
  fi
}

REDIS_SERVER="${REDIS_SERVER_BIN:-$(redis_bin redis-server)}"
REDIS_CLI="${REDIS_CLI_BIN:-$(redis_bin redis-cli)}"
if [ -z "$REDIS_SERVER" ] || [ -z "$REDIS_CLI" ]; then
  echo "redis-server and redis-cli not found; install the distribution Redis" >&2
  echo "package, or set REDIS_SERVER_BIN and REDIS_CLI_BIN." >&2
  exit 1
fi

cli() {
  "$REDIS_CLI" -s "$SOCKET_PATH" "$@"
}

answers() {
  [ "$(cli ping 2>/dev/null || true)" = "PONG" ]
}

# Validate every existing component without following symlinks. In create mode,
# mkdir/open each component relative to an already-open parent so a concurrent
# symlink substitution cannot redirect state outside this repository's ignored
# lab directory.
secure_state_dir() {
  local mode="$1"
  python3 - "$PWD" "$STATE_DIR_REQUEST" "$mode" <<'PY'
import os
import stat
import sys


def refuse(reason: str) -> None:
    print(f"refusing Palimnex state directory: {reason}", file=sys.stderr)
    raise SystemExit(1)


repository = os.path.realpath(sys.argv[1])
requested = os.path.abspath(sys.argv[2])
mode = sys.argv[3]
lab_root = os.path.join(repository, ".palimnex")
try:
    relative = os.path.relpath(requested, lab_root)
except ValueError:
    refuse("path cannot be compared with the repository lab directory")
if relative == "." or relative == ".." or relative.startswith(".." + os.sep):
    refuse(f"{requested} is not strictly below {lab_root}")
parts = [".palimnex", *relative.split(os.sep)]
flags = os.O_RDONLY | os.O_DIRECTORY
if hasattr(os, "O_CLOEXEC"):
    flags |= os.O_CLOEXEC
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
fd = os.open(repository, flags)
try:
    for part in parts:
        if part in {"", ".", ".."}:
            refuse("path contains an unsafe component")
        try:
            child = os.open(part, flags, dir_fd=fd)
        except FileNotFoundError:
            if mode != "create":
                break
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                child = os.open(part, flags, dir_fd=fd)
            except OSError as error:
                refuse(f"cannot securely open {part}: {error.strerror}")
        except OSError as error:
            refuse(f"component {part} is a symlink or not a directory: {error.strerror}")
        info = os.fstat(child)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            os.close(child)
            refuse(f"component {part} is not an owner-controlled directory")
        if mode == "create":
            os.fchmod(child, 0o700)
        os.close(fd)
        fd = child
finally:
    os.close(fd)
print(requested)
PY
}

configure_paths() {
  local mode="$1"
  STATE_DIR="$(secure_state_dir "$mode")"
  if [ -n "$SOCKET_PATH_REQUEST" ]; then
    SOCKET_PATH="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$SOCKET_PATH_REQUEST")"
  else
    SOCKET_PATH="$STATE_DIR/redis.sock"
  fi
  PID_FILE="$STATE_DIR/redis.pid"
  LOG_FILE="$STATE_DIR/redis.log"
  guard_socket_path
}

guard_socket_path() {
  [ "$(dirname -- "$SOCKET_PATH")" = "$STATE_DIR" ] || {
    echo "refusing Redis socket outside the state directory: $SOCKET_PATH" >&2
    return 1
  }
  [ ! -L "$SOCKET_PATH" ] || {
    echo "refusing symlinked Redis socket path: $SOCKET_PATH" >&2
    return 1
  }
  if [ -e "$SOCKET_PATH" ] && [ ! -S "$SOCKET_PATH" ]; then
    echo "refusing non-socket occupant at Redis socket path: $SOCKET_PATH" >&2
    return 1
  fi
}

regular_owned_or_absent() {
  local path="$1"
  [ ! -L "$path" ] || { echo "refusing symlinked Redis state file: $path" >&2; return 1; }
  [ -e "$path" ] || return 0
  [ -f "$path" ] || { echo "refusing non-file Redis state path: $path" >&2; return 1; }
  [ "$(stat -c '%u' -- "$path")" = "$(id -u)" ] \
    || { echo "refusing Redis state file owned by another user: $path" >&2; return 1; }
  [ "$(stat -c '%h' -- "$path")" = "1" ] \
    || { echo "refusing hard-linked Redis state file: $path" >&2; return 1; }
}

read_pid_file() {
  local pid size
  [ -e "$PID_FILE" ] || return 1
  regular_owned_or_absent "$PID_FILE" || return 1
  size="$(stat -c '%s' -- "$PID_FILE")"
  [ "$size" -le 32 ] || return 1
  pid="$(tr -d '[:space:]' < "$PID_FILE")"
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  printf '%s\n' "$pid"
}

live_recorded_pid() {
  local pid
  pid="$(read_pid_file)" || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s\n' "$pid"
}

managed_pid() {
  local pid expected_exe actual_exe actual_name expected_name argv0 info_pid configured_socket
  pid="$(live_recorded_pid)" || return 1
  [ "$(stat -c '%u' -- "/proc/$pid" 2>/dev/null || true)" = "$(id -u)" ] || return 1
  expected_exe="$(realpath -e -- "$REDIS_SERVER" 2>/dev/null || true)"
  actual_exe="$(readlink -f -- "/proc/$pid/exe" 2>/dev/null || true)"
  [ -n "$expected_exe" ] && [ -n "$actual_exe" ] || return 1
  if [ "$actual_exe" != "$expected_exe" ]; then
    # Some isolated installations expose redis-server through a small wrapper
    # that sets its private library path and then execs redis-server.bin. The
    # process executable is therefore the wrapped binary, not the command path.
    # Accept only that narrow wrapper shape and bind it back to the live process
    # title; the PID, uid, Redis-reported PID and configured socket are still
    # checked below before the process is treated as launcher-owned.
    expected_name="$(basename -- "$expected_exe")"
    actual_name="$(basename -- "$actual_exe")"
    [ "$expected_name" = "redis-server" ] || return 1
    case "$actual_name" in redis-server|redis-server.bin) ;; *) return 1 ;; esac
    argv0="$(tr '\0' '\n' < "/proc/$pid/cmdline" 2>/dev/null | head -1)"
    case "$argv0" in "$actual_exe"|"$actual_exe "*) ;; *) return 1 ;; esac
  fi
  answers || return 1
  info_pid="$(cli --raw info server 2>/dev/null | awk -F: '$1 == "process_id" {gsub(/\r/, "", $2); print $2; exit}')"
  [ "$info_pid" = "$pid" ] || return 1
  configured_socket="$(cli --raw config get unixsocket 2>/dev/null | awk 'NR == 2 {gsub(/\r/, ""); print; exit}')"
  [ "$configured_socket" = "$SOCKET_PATH" ] || return 1
  printf '%s\n' "$pid"
}

remove_regular_owned() {
  local path="$1"
  regular_owned_or_absent "$path" || return 1
  if [ -e "$path" ]; then
    rm -f -- "$path"
  fi
  return 0
}

start() {
  umask 077
  configure_paths create
  regular_owned_or_absent "$PID_FILE"
  regular_owned_or_absent "$LOG_FILE"
  regular_owned_or_absent "$STATE_DIR/$DUMP_FILE"
  if answers; then
    if managed_pid > /dev/null; then
      echo "Palimnex Redis already running on owner socket $SOCKET_PATH"
    else
      echo "refusing a Redis responder not owned by this launcher: $SOCKET_PATH" >&2
      exit 1
    fi
    return 0
  fi
  if [ -e "$PID_FILE" ] || [ -L "$PID_FILE" ]; then
    if ! read_pid_file > /dev/null; then
      echo "refusing malformed or unsafe Redis PID file: $PID_FILE" >&2
      exit 1
    fi
    if live_recorded_pid > /dev/null; then
      echo "refusing live process recorded by an untrusted/reused PID file: $PID_FILE" >&2
      exit 1
    fi
  fi
  remove_regular_owned "$PID_FILE"
  if [ -e "$SOCKET_PATH" ]; then
    [ -S "$SOCKET_PATH" ] || {
      echo "refusing non-socket occupant at Redis socket path: $SOCKET_PATH" >&2
      exit 1
    }
    rm -f -- "$SOCKET_PATH"
  fi
  # Owner-only Unix socket, no TCP listener, snapshots after 60 s with one change or
  # 300 s with a hundred, and on shutdown. No append-only log: the index is
  # rebuilt from the checkout, so losing the last minute costs a reindex, not
  # data. Files are created under umask 077.
  "$REDIS_SERVER" \
    --port 0 --unixsocket "$SOCKET_PATH" --unixsocketperm 600 --protected-mode yes \
    --daemonize yes --pidfile "$PID_FILE" --logfile "$LOG_FILE" \
    --dir "$STATE_DIR" --dbfilename "$DUMP_FILE" \
    --save 60 1 300 100 --appendonly no --always-show-logo no \
    > /dev/null
  for _ in $(seq 1 60); do
    if answers && managed_pid > /dev/null; then
      echo "Palimnex Redis up on owner socket $SOCKET_PATH (state $STATE_DIR)"
      return 0
    fi
    sleep 0.5
  done
  echo "Palimnex Redis did not come up within 30s; see $LOG_FILE" >&2
  exit 1
}

stop() {
  local pid
  configure_paths inspect
  if pid="$(managed_pid)"; then
    # Persist the index before exit so the next start needs no reindex.
    cli shutdown save > /dev/null 2>&1 || kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 60); do
      if ! kill -0 "$pid" 2>/dev/null; then
        remove_regular_owned "$PID_FILE"
        [ ! -e "$SOCKET_PATH" ] || rm -f -- "$SOCKET_PATH"
        echo "Palimnex Redis stopped (dump kept in $STATE_DIR)"
        return 0
      fi
      sleep 0.5
    done
    echo "Palimnex Redis did not stop within 30s" >&2
    exit 1
  fi
  if [ -e "$PID_FILE" ] || [ -L "$PID_FILE" ]; then
    if ! read_pid_file > /dev/null; then
      echo "refusing malformed or unsafe Redis PID file: $PID_FILE" >&2
      return 1
    fi
    if live_recorded_pid > /dev/null; then
      echo "refusing live process recorded by an untrusted/reused PID file: $PID_FILE" >&2
      return 1
    fi
  fi
  if answers; then
    echo "refusing to manage a Redis responder not owned by this launcher: $SOCKET_PATH" >&2
    return 1
  fi
  remove_regular_owned "$PID_FILE"
  if [ -e "$SOCKET_PATH" ]; then
    [ -S "$SOCKET_PATH" ] || {
      echo "refusing non-socket occupant at Redis socket path: $SOCKET_PATH" >&2
      return 1
    }
    rm -f -- "$SOCKET_PATH"
  fi
  echo "Palimnex Redis was not running on $SOCKET_PATH"
}

status() {
  local pid keys
  configure_paths inspect
  if answers; then
    if pid="$(managed_pid)"; then
      echo "Palimnex Redis: up on owner socket $SOCKET_PATH, pid $pid, state $STATE_DIR"
    else
      echo "Palimnex Redis: untrusted responder on $SOCKET_PATH (not launcher-owned)" >&2
      return 1
    fi
    keys="$(cli dbsize 2>/dev/null | tr -dc '0-9')"
    echo "keys:     ${keys:-unknown}"
    if [ -f "$STATE_DIR/$DUMP_FILE" ]; then
      echo "dump:     $(stat -c '%s bytes, saved %y' "$STATE_DIR/$DUMP_FILE" | cut -d. -f1)"
    fi
    return 0
  fi
  echo "Palimnex Redis not running on owner socket $SOCKET_PATH"
  return 1
}

reset() {
  local candidate removed=0
  configure_paths inspect
  # Refuse every currently visible deletion target before stopping the managed
  # process. A guard failure must not have the side effect of taking Redis down.
  regular_owned_or_absent "$LOG_FILE"
  regular_owned_or_absent "$STATE_DIR/$DUMP_FILE"
  shopt -s nullglob
  for candidate in "$STATE_DIR"/temp-*.rdb; do
    regular_owned_or_absent "$candidate"
  done
  shopt -u nullglob
  stop || return 1
  for candidate in "$LOG_FILE" "$STATE_DIR/$DUMP_FILE"; do
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
      remove_regular_owned "$candidate"
      removed=$((removed + 1))
    fi
  done
  shopt -s nullglob
  for candidate in "$STATE_DIR"/temp-*.rdb; do
    remove_regular_owned "$candidate"
    removed=$((removed + 1))
  done
  shopt -u nullglob
  echo "cleared $removed Redis projection file(s) under $STATE_DIR; durable ledger preserved"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  reset) reset ;;
  guard) configure_paths inspect && echo "state directory and socket are safe" ;;
  *) echo "usage: $0 start|stop|status|reset|guard" >&2; exit 2 ;;
esac
