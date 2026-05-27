#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime/dev"
PID_FILE="$RUNTIME_DIR/web.pid"
LOG_FILE="$RUNTIME_DIR/web.log"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
URL="http://${HOST}:${PORT}/index.html"

WEB_PID=""
STARTUP_COMPLETE="0"

require_command() {
  local cmd="$1"
  local hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n%s\n' "$cmd" "$hint" >&2
    exit 1
  fi
}

spawn_detached() {
  local workdir="$1"
  local log_file="$2"
  shift 2

  python3 - "$workdir" "$log_file" "$@" <<'PY'
import os
import sys

workdir = sys.argv[1]
log_file = sys.argv[2]
cmd = sys.argv[3:]

pid = os.fork()
if pid > 0:
    print(pid)
    sys.exit(0)

os.setsid()
os.chdir(workdir)

devnull_fd = os.open("/dev/null", os.O_RDONLY)
log_fd = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)

os.dup2(devnull_fd, 0)
os.dup2(log_fd, 1)
os.dup2(log_fd, 2)

os.close(devnull_fd)
os.close(log_fd)

os.execvpe(cmd[0], cmd, os.environ.copy())
PY
}

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

clear_stale_pid_file() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 0
  fi

  local pid
  pid="$(<"$PID_FILE")"
  if is_pid_running "$pid"; then
    printf 'Web server already running with PID %s. Use ./stop.sh first if you need to restart it.\n' "$pid" >&2
    exit 1
  fi

  rm -f "$PID_FILE"
}

require_free_port() {
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'Port %s is already in use. Stop the existing process or override the port before running ./start.sh.\n' "$PORT" >&2
    printf 'Example: PORT=8010 ./start.sh\n' >&2
    exit 1
  fi
}

wait_for_url() {
  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi

  for ((i = 1; i <= 30; i++)); do
    if curl --silent --fail --max-time 1 "$URL" >/dev/null 2>&1; then
      return 0
    fi

    if ! is_pid_running "$WEB_PID"; then
      printf 'Web server exited before becoming ready. Check %s.\n' "$LOG_FILE" >&2
      return 1
    fi

    sleep 1
  done

  printf 'Timed out waiting for web server at %s. Check %s.\n' "$URL" "$LOG_FILE" >&2
  return 1
}

stop_process_group() {
  local pid="$1"
  if ! is_pid_running "$pid"; then
    return 0
  fi

  local children
  children="$(pgrep -P "$pid" || true)"
  for child in $children; do
    stop_process_group "$child"
  done

  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..20}; do
    if ! is_pid_running "$pid"; then
      return 0
    fi
    sleep 0.5
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
}

cleanup_on_error() {
  local exit_code=$?
  if [[ "$STARTUP_COMPLETE" == "1" ]]; then
    exit "$exit_code"
  fi

  if [[ -n "$WEB_PID" ]]; then
    stop_process_group "$WEB_PID"
  fi

  rm -f "$PID_FILE"
  exit "$exit_code"
}
trap cleanup_on_error EXIT INT TERM

require_command "python3" "Install Python 3 first, then rerun ./start.sh."
require_command "lsof" "Install lsof first, or manually confirm the port is free."
require_command "pgrep" "Install pgrep first, then rerun ./start.sh."

if [[ ! -f "$ROOT_DIR/index.html" ]]; then
  printf 'Missing index.html in %s\n' "$ROOT_DIR" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR"

clear_stale_pid_file
require_free_port

WEB_PID="$(spawn_detached "$ROOT_DIR" "$LOG_FILE" python3 -m http.server "$PORT" --bind "$HOST")"
printf '%s\n' "$WEB_PID" > "$PID_FILE"

wait_for_url

STARTUP_COMPLETE="1"

printf 'Web started: %s\n' "$URL"
printf 'Log:\n'
printf '  %s\n' "$LOG_FILE"
printf 'Stop it with ./stop.sh\n'
