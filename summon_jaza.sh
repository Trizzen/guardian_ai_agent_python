#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$SCRIPT_DIR"
FRONTEND_DIR="$REPO_ROOT/frontend"
RUNTIME_DIR="$REPO_ROOT/.runtime"
BACKEND_LOG="$RUNTIME_DIR/jaza-backend.log"
FRONTEND_LOG="$RUNTIME_DIR/jaza-frontend.log"
BACKEND_PID=""
FRONTEND_PID=""

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="5001"
FRONTEND_HOST="localhost"
FRONTEND_PORT="4201"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  local install_hint="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "$command_name is required. $install_hint"
  fi
}

process_group_is_running() {
  local leader_pid="$1"
  kill -0 -- "-$leader_pid" 2>/dev/null
}

stop_process_group() {
  local leader_pid="$1"
  local process_name="$2"
  local attempt

  if [[ -z "$leader_pid" ]] || ! process_group_is_running "$leader_pid"; then
    return
  fi

  kill -TERM -- "-$leader_pid" 2>/dev/null || true

  for attempt in {1..50}; do
    if ! process_group_is_running "$leader_pid"; then
      wait "$leader_pid" 2>/dev/null || true
      return
    fi
    sleep 0.1
  done

  printf '  %s did not stop gracefully; stopping its launcher-owned process group.\n' "$process_name" >&2
  kill -KILL -- "-$leader_pid" 2>/dev/null || true
  wait "$leader_pid" 2>/dev/null || true
}

cleanup() {
  local exit_status=$?

  trap - EXIT INT TERM HUP

  if [[ -n "$FRONTEND_PID" || -n "$BACKEND_PID" ]]; then
    printf '\nTucking Jaza away...\n'
    stop_process_group "$FRONTEND_PID" "Jaza frontend"
    stop_process_group "$BACKEND_PID" "Jaza backend"
    printf 'Jaza has been tucked away.\n'
  fi

  exit "$exit_status"
}

show_log_tail() {
  local log_file="$1"

  if [[ -s "$log_file" ]]; then
    printf '%s\n' '--- recent log output ---' >&2
    tail -n 30 "$log_file" >&2
    printf '%s\n' '--- end log output ---' >&2
  fi
}

port_is_occupied() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

check_required_ports() {
  local occupied=0

  if port_is_occupied "$BACKEND_PORT"; then
    printf 'Cannot summon Jaza: backend port %s is already in use.\n' "$BACKEND_PORT" >&2
    lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >&2 || true
    occupied=1
  fi

  if port_is_occupied "$FRONTEND_PORT"; then
    printf 'Cannot summon Jaza: frontend port %s is already in use.\n' "$FRONTEND_PORT" >&2
    lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >&2 || true
    occupied=1
  fi

  if [[ "$occupied" -ne 0 ]]; then
    exit 1
  fi
}

wait_for_service() {
  local service_name="$1"
  local url="$2"
  local leader_pid="$3"
  local log_file="$4"
  local attempts="$5"
  local attempt

  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if ! process_group_is_running "$leader_pid"; then
      printf '%s failed to start.\n' "$service_name" >&2
      show_log_tail "$log_file"
      return 1
    fi

    if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi

    sleep 1
  done

  printf '%s did not become ready at %s within %s seconds.\n' \
    "$service_name" "$url" "$attempts" >&2
  show_log_tail "$log_file"
  return 1
}

printf '%s\n' '------------------------------------------'
printf '%s\n' '      JAZA SOULMINDER — SENTINEL'
printf '%s\n' '------------------------------------------'
printf '%s\n' 'Summoning local command center...'
printf 'Backend : %s\n' "$BACKEND_PORT"
printf 'Frontend: %s\n\n' "$FRONTEND_PORT"

cd "$REPO_ROOT"

if [[ -d /opt/homebrew/opt/node@20/bin ]]; then
  export PATH="/opt/homebrew/opt/node@20/bin:$PATH"
fi

require_command uv 'Install uv, then run: uv sync --dev'
require_command node 'Install Homebrew Node 20: brew install node@20'
require_command npm 'Install Homebrew Node 20: brew install node@20'
require_command curl 'curl is included with macOS and must be available on PATH.'
require_command lsof 'lsof is included with macOS and must be available on PATH.'
require_command open 'The macOS open command must be available on PATH.'

NODE_VERSION="$(node --version)"
NODE_MAJOR="${NODE_VERSION#v}"
NODE_MAJOR="${NODE_MAJOR%%.*}"
if [[ "$NODE_MAJOR" != "20" ]]; then
  fail "Node 20 is required, but $NODE_VERSION is active. Install it with: brew install node@20"
fi

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]] || \
  ! uv run --no-sync python -c 'import flask, dotenv' >/dev/null 2>&1; then
  fail 'Backend dependencies are not ready. From the repository root run: uv sync --dev'
fi

if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
  fail "Frontend package manifest not found at $FRONTEND_DIR/package.json"
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  printf '%s\n' 'Frontend dependencies not found. Installing once...'
  (cd "$FRONTEND_DIR" && npm install)
fi

check_required_ports

mkdir -p "$RUNTIME_DIR"
: >"$BACKEND_LOG"
: >"$FRONTEND_LOG"

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# Monitor mode gives each background job its own process group. That lets cleanup
# stop npm/Angular and uv/Flask descendants without touching unrelated processes.
set -m

printf '%s\n' 'Starting Jaza backend...'
(
  cd "$REPO_ROOT"
  exec uv run --no-sync python main.py --host "$BACKEND_HOST" --port "$BACKEND_PORT"
) >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

if ! wait_for_service \
  'Jaza backend' \
  "http://$BACKEND_HOST:$BACKEND_PORT/api/health" \
  "$BACKEND_PID" \
  "$BACKEND_LOG" \
  45; then
  exit 1
fi
printf 'Jaza backend ready: http://%s:%s\n' "$BACKEND_HOST" "$BACKEND_PORT"

printf '%s\n' 'Starting Jaza frontend...'
(
  cd "$FRONTEND_DIR"
  exec npm start -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
) >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
set +m

if ! wait_for_service \
  'Jaza frontend' \
  "http://$FRONTEND_HOST:$FRONTEND_PORT" \
  "$FRONTEND_PID" \
  "$FRONTEND_LOG" \
  60; then
  exit 1
fi
printf 'Jaza frontend ready: http://%s:%s\n' "$FRONTEND_HOST" "$FRONTEND_PORT"

printf '%s\n' 'Launching Jaza in the default browser...'
open "http://$FRONTEND_HOST:$FRONTEND_PORT"

printf '%s\n' '=================================================='
printf '%s\n' 'JAZA SOULMINDER IS AWAKE'
printf 'Frontend: http://%s:%s\n' "$FRONTEND_HOST" "$FRONTEND_PORT"
printf 'Backend:  http://%s:%s\n' "$BACKEND_HOST" "$BACKEND_PORT"
printf '%s\n' 'Press Ctrl+C to tuck Jaza away.'
printf '%s\n' '=================================================='

while true; do
  if ! process_group_is_running "$BACKEND_PID"; then
    printf '%s\n' 'Jaza backend stopped unexpectedly.' >&2
    show_log_tail "$BACKEND_LOG"
    exit 1
  fi

  if ! process_group_is_running "$FRONTEND_PID"; then
    printf '%s\n' 'Jaza frontend stopped unexpectedly.' >&2
    show_log_tail "$FRONTEND_LOG"
    exit 1
  fi

  sleep 1
done
