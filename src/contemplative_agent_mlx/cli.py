"""CLI wrapper that injects the local MLX generation backend before
delegating to the main ``contemplative-agent`` CLI.

Running ``contemplative-agent-mlx <subcommand>`` is the opt-in: every
generation call routes through a local ``mlx_lm.server`` (Apple Silicon MLX
runtime) instead of Ollama. Embeddings stay on local Ollama. This is a
local-runtime swap — nothing leaves the machine — so it mirrors the
``contemplative-agent-cloud`` injection shape without that add-on's
cloud-egress trade-off.

Configuration (environment variables, with defaults):

- ``MLX_BASE_URL`` — mlx_lm.server origin (default ``http://localhost:8080``)
- ``MLX_MODEL`` — served model id (default ``mlx-community/Qwen3.5-9B-4bit``)

This wrapper only points the backend at an *already-running* mlx_lm.server;
it never launches one. ``scripts/run-with-mlx.sh`` owns the server lifecycle
(start → wait for health → run this CLI → stop the server on exit).

Peer subprocesses spawned by ``contemplative-agent dialogue`` are re-routed
through this same wrapper by setting ``CONTEMPLATIVE_DIALOGUE_PEER_MODULE``,
so each peer also injects the MLX backend; the main repository's
``_spawn_dialogue_peer`` respects that env var.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from contemplative_agent.core.llm import LLMBackend, configure

from contemplative_agent_mlx.backends.mlx import MlxLmBackend

_DEFAULT_BASE_URL = "http://localhost:8080"
_DEFAULT_MODEL = "mlx-community/Qwen3.5-9B-4bit"


def _build_backend() -> LLMBackend:
    """Construct the MLX backend from env (``MLX_BASE_URL`` / ``MLX_MODEL``).

    Construction validates ``MLX_BASE_URL`` against the localhost /
    ``OLLAMA_TRUSTED_HOSTS`` allowlist (SSRF guard) and rejects a non-positive
    context window — a misconfiguration fails fast here, at CLI startup,
    rather than tripping the circuit breaker on the first ``generate()``.
    """
    return MlxLmBackend(
        base_url=os.environ.get("MLX_BASE_URL", _DEFAULT_BASE_URL),
        model=os.environ.get("MLX_MODEL", _DEFAULT_MODEL),
    )


def main(argv: Optional[list[str]] = None) -> None:
    # Peer subprocesses spawned by the main CLI's dialogue handler should
    # route through this wrapper so each peer also injects the MLX backend
    # (they all share the one local mlx_lm.server).
    os.environ["CONTEMPLATIVE_DIALOGUE_PEER_MODULE"] = "contemplative_agent_mlx.cli"

    backend = _build_backend()
    configure(backend=backend)

    # Delegate everything else to the main CLI, which picks up the backend
    # via the module-level state in core/llm.py.
    from contemplative_agent.cli import main as _main

    if argv is not None:
        sys.argv = ["contemplative-agent", *argv]
    _main()


if __name__ == "__main__":
    main()
