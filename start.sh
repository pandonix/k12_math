#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime/dev"

WEB_PID_FILE="$RUNTIME_DIR/web.pid"
WEB_LOG_FILE="$RUNTIME_DIR/web.log"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
BACKEND_LOG_FILE="$RUNTIME_DIR/backend.log"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8001}"

WEB_URL="http://${HOST}:${PORT}/index.html"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}/api/health"

if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
else
  PYTHON="${PYTHON:-python3}"
fi

WEB_PID=""
BACKEND_PID=""
STARTUP_COMPLETE="0"

require_command() {
  local cmd="$1"
  local hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n%s\n' "$cmd" "$hint" >&2
    exit 1
  fi
}

require_python_runtime() {
  if ! "$PYTHON" -c "import fastapi, sqlmodel, uvicorn" >/dev/null 2>&1; then
    printf 'Python backend dependencies are missing for %s.\n' "$PYTHON" >&2
    printf 'Create/install them with:\n' >&2
    printf '  python3 -m venv .venv\n' >&2
    printf '  .venv/bin/pip install -r backend/requirements.txt\n' >&2
    exit 1
  fi
}

spawn_detached() {
  local workdir="$1"
  local log_file="$2"
  shift 2

  "$PYTHON" - "$workdir" "$log_file" "$@" <<'PY'
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
  local pid_file="$1"
  local label="$2"

  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi

  local pid
  pid="$(<"$pid_file")"
  if is_pid_running "$pid"; then
    printf '%s already running with PID %s. Use ./stop.sh first if you need to restart it.\n' "$label" "$pid" >&2
    exit 1
  fi

  rm -f "$pid_file"
}

require_free_port() {
  local port="$1"
  local label="$2"

  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    printf '%s port %s is already in use. Stop the existing process or override the port.\n' "$label" "$port" >&2
    printf 'Examples:\n' >&2
    printf '  PORT=8010 ./start.sh\n' >&2
    printf '  BACKEND_PORT=8011 ./start.sh\n' >&2
    exit 1
  fi
}

wait_for_url() {
  local url="$1"
  local pid="$2"
  local log_file="$3"
  local label="$4"

  for ((i = 1; i <= 30; i++)); do
    if curl --silent --fail --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi

    if ! is_pid_running "$pid"; then
      printf '%s exited before becoming ready. Check %s.\n' "$label" "$log_file" >&2
      return 1
    fi

    sleep 1
  done

  printf 'Timed out waiting for %s at %s. Check %s.\n' "$label" "$url" "$log_file" >&2
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
  if [[ -n "$BACKEND_PID" ]]; then
    stop_process_group "$BACKEND_PID"
  fi

  rm -f "$WEB_PID_FILE" "$BACKEND_PID_FILE"
  exit "$exit_code"
}
trap cleanup_on_error EXIT INT TERM

require_command "python3" "Install Python 3 first, then rerun ./start.sh."
require_command "lsof" "Install lsof first, or manually confirm the ports are free."
require_command "pgrep" "Install pgrep first, then rerun ./start.sh."
require_command "curl" "Install curl first, then rerun ./start.sh."
require_python_runtime

if [[ ! -f "$ROOT_DIR/index.html" ]]; then
  printf 'Missing index.html in %s\n' "$ROOT_DIR" >&2
  exit 1
fi

if [[ ! -f "$ROOT_DIR/backend/main.py" ]]; then
  printf 'Missing backend/main.py in %s\n' "$ROOT_DIR" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR"

clear_stale_pid_file "$WEB_PID_FILE" "Web server"
clear_stale_pid_file "$BACKEND_PID_FILE" "Backend server"
require_free_port "$PORT" "Web"
require_free_port "$BACKEND_PORT" "Backend"

BACKEND_PID="$(spawn_detached "$ROOT_DIR" "$BACKEND_LOG_FILE" "$PYTHON" -m uvicorn backend.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT")"
printf '%s\n' "$BACKEND_PID" > "$BACKEND_PID_FILE"
wait_for_url "$BACKEND_URL" "$BACKEND_PID" "$BACKEND_LOG_FILE" "Backend server"

WEB_PID="$(spawn_detached "$ROOT_DIR" "$WEB_LOG_FILE" python3 -m http.server "$PORT" --bind "$HOST")"
printf '%s\n' "$WEB_PID" > "$WEB_PID_FILE"
wait_for_url "$WEB_URL" "$WEB_PID" "$WEB_LOG_FILE" "Web server"

STARTUP_COMPLETE="1"

printf 'Backend started: %s\n' "$BACKEND_URL"
printf 'Web started: %s\n' "$WEB_URL"
printf 'Logs:\n'
printf '  %s\n' "$BACKEND_LOG_FILE"
printf '  %s\n' "$WEB_LOG_FILE"
printf 'Stop both with ./stop.sh\n'
