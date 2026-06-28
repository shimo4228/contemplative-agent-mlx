#!/bin/bash
# On-demand mlx_lm.server lifecycle for the MLX generation backend.
#
# Wraps a contemplative-agent-mlx generation command: start mlx_lm.server,
# wait for /health, run the agent through THIS repo's `contemplative-agent-mlx`
# entry point (which injects the MLX backend via configure(backend=...)), then
# kill the server via `trap EXIT` so the server's lifetime matches the job's.
# Idle memory stays ~0 (server unloaded between jobs), which is why on-demand
# beats a resident KeepAlive server on a 16 GB host — see the main repo's
# ADR-0065. Embeddings stay on Ollama (a separate always-on daemon); this
# wrapper manages only the mlx server.
#
# Note: there is no LLM_BACKEND env var — backend selection is which binary you
# run. This script runs `contemplative-agent-mlx`; the plain `contemplative-agent`
# binary keeps the default Ollama path.
#
# Usage:
#   run-with-mlx.sh <contemplative-agent args...>
#   e.g. run-with-mlx.sh -v --auto run --session 60
#        run-with-mlx.sh distill --days 1
set -euo pipefail

PORT="${MLX_PORT:-8080}"
MODEL="${MLX_MODEL:-mlx-community/Qwen3.5-9B-4bit}"

if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "run-with-mlx: invalid PORT: $PORT" >&2
  exit 1
fi

SERVER="$HOME/.local/bin/mlx_lm.server"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
AGENT="$REPO_ROOT/.venv/bin/contemplative-agent-mlx"
PYTHON="$REPO_ROOT/.venv/bin/python"
LOG="$HOME/.config/moltbook/logs/mlx-server.log"
STARTED_MLX=

mkdir -p "$(dirname "$LOG")"

if [ ! -x "$AGENT" ]; then
  echo "run-with-mlx: executable not found: $AGENT" >&2
  exit 1
fi
if [ ! -x "$PYTHON" ]; then
  echo "run-with-mlx: executable not found: $PYTHON" >&2
  exit 1
fi

health_ready() {
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1
}

served_models() {
  curl -sf "http://127.0.0.1:$PORT/v1/models" | "$PYTHON" -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(1)
for item in data.get("data", []):
    if isinstance(item, dict) and isinstance(item.get("id"), str):
        print(item["id"])
'
}

require_served_model() {
  local models
  if ! models="$(served_models)"; then
    echo "run-with-mlx: failed to query served models on :$PORT" >&2
    return 1
  fi
  if ! printf '%s\n' "$models" | grep -Fx -- "$MODEL" >/dev/null; then
    echo "run-with-mlx: mlx_lm.server on :$PORT serves unexpected model(s):" >&2
    printf '%s\n' "$models" >&2
    echo "run-with-mlx: expected: $MODEL" >&2
    return 1
  fi
}

if health_ready; then
  # A server is already listening. Reuse it only if it is the exact requested
  # model; otherwise fail instead of silently attaching to stale/wrong state.
  require_served_model
else
  # Resolve how to launch the server: a globally-installed binary if present
  # (`uv tool install mlx-lm`), otherwise the no-install `uvx --from mlx-lm`
  # path that serve-mlx.sh uses and the README documents as the easiest setup.
  if [ -x "$SERVER" ]; then
    server_cmd=("$SERVER")
  elif command -v uvx >/dev/null 2>&1; then
    server_cmd=(uvx --from mlx-lm mlx_lm.server)
  else
    echo "run-with-mlx: no mlx_lm.server found — install it ('uv tool install mlx-lm') or install uv for the uvx path" >&2
    exit 1
  fi

  # --prompt-cache-size 2: cap retained KV caches. Default holds up to ~10
  # distinct prompt KV caches; at this agent's ~7.6k-token system prompt that
  # is ~2 GB of cache ON TOP of the ~5.2 GB weights, pushing a 16 GB host into
  # compression + swap (the model footprint then exceeds the ADR-0064 cold
  # benchmark). A single autonomous agent reuses one system-prompt prefix, so
  # 2 caches preserve the prefix-reuse speedup while bounding cache to ~0.4 GB.
  "${server_cmd[@]}" --model "$MODEL" --host 127.0.0.1 --port "$PORT" \
    --prompt-cache-size 2 \
    --chat-template-args '{"enable_thinking": false}' >>"$LOG" 2>&1 &
  MLX_PID=$!
  STARTED_MLX=1
  # Kill only the server this wrapper started. Do NOT `exec` the agent below,
  # or this trap won't fire.
  trap 'if [ -n "$STARTED_MLX" ]; then kill "$MLX_PID" 2>/dev/null || true; fi' EXIT

  # Wait for the model to load (cold M1 load ~12s; cap at 60s). If it never comes
  # up, skip this cycle — the next scheduled job retries. We deliberately do NOT
  # fall back to Ollama generation: running this wrapper is the operator's explicit
  # choice of the MLX backend, and a silent fallback would mask a broken server.
  ready=
  for _ in $(seq 1 60); do
    if health_ready; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ -z "$ready" ]; then
    echo "run-with-mlx: mlx_lm.server health timeout on :$PORT — skipping cycle" >&2
    exit 1
  fi

  require_served_model
fi

# Point the backend at the local server and pin the same served model id, then
# run the MLX entry point (it injects MlxLmBackend via configure(backend=...)).
export MLX_BASE_URL="http://localhost:$PORT"
export MLX_MODEL="$MODEL"
"$AGENT" "$@"
