#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime/dev"

WEB_PID_FILE="$RUNTIME_DIR/web.pid"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"

PORT="${PORT:-8000}"
BACKEND_PORT="${BACKEND_PORT:-8001}"

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
  local port="$1"
  local label="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
  if [[ -z "$pids" ]]; then
    return 1
  fi

  for pid in $pids; do
    stop_pid_tree "$pid"
  done

  printf '%s listener on port %s stopped.\n' "$label" "$port"
  return 0
}

stop_from_pid_file() {
  local pid_file="$1"
  local port="$2"
  local label="$3"

  if [[ ! -f "$pid_file" ]]; then
    if stop_port_listener "$port" "$label"; then
      return 0
    fi
    printf '%s is not running.\n' "$label"
    return 0
  fi

  local pid
  pid="$(<"$pid_file")"

  if is_pid_running "$pid"; then
    stop_pid_tree "$pid"
  else
    printf '%s pid file was stale and has been removed.\n' "$label"
  fi

  rm -f "$pid_file"

  if stop_port_listener "$port" "$label" >/dev/null 2>&1; then
    true
  fi

  printf '%s stopped.\n' "$label"
}

stop_from_pid_file "$BACKEND_PID_FILE" "$BACKEND_PORT" "Backend server"
stop_from_pid_file "$WEB_PID_FILE" "$PORT" "Web server"
