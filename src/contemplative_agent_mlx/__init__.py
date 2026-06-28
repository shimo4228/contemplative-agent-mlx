"""Optional local MLX generation backend for contemplative-agent.

On Apple Silicon, installing this package and running the
``contemplative-agent-mlx`` entry point routes every generation call in
contemplative-agent (distill, insight, rules-distill, amend-constitution,
post, comment, reply, dialogue) through a local ``mlx_lm.server`` (Apple's
MLX runtime) instead of Ollama — ~1.8x faster and ~3.4 GB lighter on the
same Qwen3.5 9B weights. Embeddings continue to use the local Ollama
``nomic-embed-text`` model (mlx_lm.server has no embeddings endpoint).

Everything stays on-device: this is a local-runtime swap, not a cloud
backend, so the main repository's "no cloud, no API keys in transit"
property is preserved. The trade-off is operational, not on the network
axis — mlx_lm.server is unfit for unattended continuous use on a 16 GB host
(ADR-0067): use it for interactive / manual / short-lived runs.

The main repository's default stack (Ollama + Qwen3.5 9B) is unchanged and
this package injects through the abstract
``contemplative_agent.core.llm.LLMBackend`` Protocol — exactly mirroring the
``contemplative-agent-cloud`` add-on. If this package is not installed and no
backend is explicitly configured, the main repository runs as before.
"""

from contemplative_agent_mlx.backends.mlx import MlxLmBackend

__all__ = ["MlxLmBackend"]
__version__ = "0.1.0"
