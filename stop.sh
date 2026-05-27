#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime/dev"
PID_FILE="$RUNTIME_DIR/web.pid"
PORT="${PORT:-8000}"

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

stop_pid_tree() {
  local pid="$1"
  if ! is_pid_running "$pid"; then
    return 0
  fi

  local children
  children="$(pgrep -P "$pid" || true)"
  for child in $children; do
    stop_pid_tree "$child"
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

stop_port_listener() {
  local pids

  pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"
  if [[ -z "$pids" ]]; then
    return 1
  fi

  for pid in $pids; do
    stop_pid_tree "$pid"
  done

  printf 'Web listener on port %s stopped.\n' "$PORT"
  return 0
}

if [[ ! -f "$PID_FILE" ]]; then
  if stop_port_listener; then
    exit 0
  fi
  printf 'Web server is not running.\n'
  exit 0
fi

pid="$(<"$PID_FILE")"

if ! is_pid_running "$pid"; then
  rm -f "$PID_FILE"
  if stop_port_listener; then
    exit 0
  fi
  printf 'Web pid file was stale and has been removed.\n'
  exit 0
fi

stop_pid_tree "$pid"

if stop_port_listener >/dev/null 2>&1; then
  true
fi

rm -f "$PID_FILE"
printf 'Web server stopped.\n'
