# contemplative-agent-mlx

Optional **local MLX generation backend** for
[contemplative-agent](https://github.com/shimo4228/contemplative-agent).
On Apple Silicon, installing this package and running the
`contemplative-agent-mlx` entry point routes generation through a local
`mlx_lm.server` (Apple's MLX runtime) instead of Ollama — about **1.8× faster
and ~3.4 GB lighter** on the same Qwen3.5 9B weights. Embeddings continue to
use local `nomic-embed-text` via Ollama.

Everything stays on-device. Unlike
[contemplative-agent-cloud](https://github.com/shimo4228/contemplative-agent-cloud),
this is a **local-runtime swap, not a cloud backend** — the main repository's
"No cloud. No API keys in transit" property is preserved. Both add-ons inject
through the same abstract `contemplative_agent.core.llm.LLMBackend` Protocol;
the main repository is not modified.

## ⚠️ Unfit for unattended / continuous use on 16 GB

This add-on is for **interactive, manual, short-lived** runs. On a 16 GB
Apple Silicon host, `mlx_lm.server` is **not reliable for the unattended
scheduled agent** — the main repository's production schedule deliberately
runs on Ollama for exactly this reason
([ADR-0067](https://github.com/shimo4228/contemplative-agent/blob/main/docs/adr/0067-keep-ollama-for-unattended-production.md)).
Observed failure modes under sustained load with a ~7.6k-token system prompt:

- **EOS runaway** — generation occasionally fails to emit a stop token and
  runs to `num_predict` (`finish_reason=length`), even with `top_p`/`top_k`
  sent.
- **OOM → circuit cascade** — under memory pressure a generation fails;
  repeated failures trip the circuit breaker while the loop keeps spinning.
- **Prefill cliff** — the same ~7.5k prompt that prefilled in ~72 s can
  later take tens of minutes in the same process.
- **Prompt-cache churn** — with `--prompt-cache-size 2`, smaller prompts can
  evict the shared system prefix, forcing full re-prefill.
- **Wired-memory thrash** — MLX's Metal (wired, non-pageable) memory coexists
  worse with other apps than Ollama's pageable GGUF mmap, despite a smaller
  resident size.

For continuous, unattended operation, run the main repository on Ollama. Use
this add-on for hands-on experiments, A/B comparisons, and one-off runs where
you are watching it.

## What changes when this is installed

| | Default (main repo only) | With `contemplative-agent-mlx` |
|---|---|---|
| Generation | Local Ollama | Local `mlx_lm.server` (Apple MLX runtime) |
| Embedding | Local Ollama + `nomic-embed-text` | **Unchanged** (still local Ollama) |
| Episode log, knowledge, identity | `$MOLTBOOK_HOME` (0600 perms) | **Unchanged** |
| Prompt-injection boundary | `wrap_untrusted_content()` | **Unchanged** |
| Output sanitization | `_sanitize_output()` | **Unchanged** |
| Circuit breaker | 5 failures → 120 s cooldown | **Unchanged** |
| Network surface | `moltbook.com` + `localhost` | **Unchanged** (second *local* port) |
| Data egress | None | **None** (on-device runtime swap) |

The main repository is **not modified** when you install this add-on. Its
code never learns about MLX — this package injects a backend implementation
through the `LLMBackend` Protocol. If this package is not installed and no
backend is explicitly configured, the main repository runs exactly as before.

## Security posture

This add-on **does not relax** the main repository's "No cloud, no API keys
in transit" property: generation stays on the local machine, just served by a
different local runtime on a second `localhost` port. The MLX backend reuses
the same SSRF guard (`validate_trusted_url`) as the Ollama path, so
`MLX_BASE_URL` is restricted to localhost / `OLLAMA_TRUSTED_HOSTS`; output
passes through the same `_sanitize_output()` forbidden-pattern filter and is
stored in `$MOLTBOOK_HOME` the same way.

The trade-off here is **operational, not on the network axis** — see the
unattended-use caveat above.

## Requirements

- **Apple Silicon Mac** (M1 or newer). MLX is Apple-Metal only; this add-on is
  not useful on other platforms.
- The main repository
  ([contemplative-agent](https://github.com/shimo4228/contemplative-agent))
  installed in the same virtual environment.
- Ollama running locally for embeddings (`nomic-embed-text` on
  `localhost:11434`).
- `mlx-lm` available to launch the server. `mlx-lm` is **not** a Python
  dependency of this package (the backend only speaks HTTP); the scripts run
  it via `uvx --from mlx-lm`, or you can `uv tool install mlx-lm` once.

## Install

```bash
git clone https://github.com/shimo4228/contemplative-agent-mlx
cd contemplative-agent-mlx
uv venv .venv && source .venv/bin/activate
uv pip install -e .
# Install the main repository into the same venv (path or PyPI):
uv pip install -e ../contemplative-agent
```

Installing this package declares `contemplative-agent>=2.0` as a dependency;
when developing locally, install the main repository from your checkout as
shown above.

## Configure

```bash
# mlx_lm.server origin (default: http://localhost:8080)
export MLX_BASE_URL=http://localhost:8080

# Served model id (default: mlx-community/Qwen3.5-9B-4bit)
export MLX_MODEL=mlx-community/Qwen3.5-9B-4bit
```

Both are optional — the defaults match the bundled scripts.

## Run

### Easiest: the lifecycle wrapper

`scripts/run-with-mlx.sh` starts `mlx_lm.server`, waits for it to be healthy,
runs the agent through `contemplative-agent-mlx`, then stops the server on
exit (idle memory returns to ~0):

```bash
scripts/run-with-mlx.sh -v --auto run --session 60
scripts/run-with-mlx.sh distill --days 1
```

### Manual: server + CLI separately

```bash
# Terminal 1 — start the MLX server (foreground)
scripts/serve-mlx.sh            # defaults: port 8080, Qwen3.5-9B-4bit

# Terminal 2 — run any subcommand, swapping the binary name
contemplative-agent-mlx init
contemplative-agent-mlx distill --days 3
contemplative-agent-mlx run --session 60
contemplative-agent-mlx dialogue ~/dialogue/a ~/dialogue/b --seed "..." --turns 10
```

Any `contemplative-agent` subcommand works — just swap the command name from
`contemplative-agent` to `contemplative-agent-mlx`. All generation routes
through the local MLX server; Ollama is still contacted for embeddings.

## Thinking is OFF

The backend runs with `enable_thinking=False` (production default). Native
thinking via `mlx_lm.server`'s OpenAI `/v1` endpoint is broken upstream
(mlx-lm [#1352](https://github.com/ml-explore/mlx-lm/issues/1352) /
[#337](https://github.com/lmstudio-ai/mlx-engine/issues/337)): the server's
reasoning-separation layer can leave `content` empty and run to
`finish_reason=length`. The `think` flag is still forwarded through the
Protocol for parity, but thinking-on against the server endpoint is not
recommended. (In-process `mlx_lm.generate` terminates correctly, but using it
would re-add the `mlx-lm` dependency, against this package's HTTP-only design.)

## Programmatic use

```python
from contemplative_agent.core.llm import configure
from contemplative_agent_mlx import MlxLmBackend

configure(backend=MlxLmBackend(
    base_url="http://localhost:8080",
    model="mlx-community/Qwen3.5-9B-4bit",
))

# From this point on, every `contemplative_agent.core.llm.generate()` call —
# no matter which subcommand or adapter triggered it — runs through the local
# mlx_lm.server. Reset with `reset_llm_config()`.
```

## Relationship to the main repository

The main repository exposes a single abstract hook:

```python
# contemplative_agent/core/llm.py
class LLMBackend(Protocol):
    @property
    def model(self) -> str: ...
    @property
    def context_window(self) -> int: ...
    def generate(self, prompt, system, num_predict, format, *, temperature, think) -> Optional[BackendResult]: ...
```

This package provides one concrete implementation of that Protocol —
`MlxLmBackend` — against a local `mlx_lm.server`. The Protocol itself has no
knowledge of MLX; it carries the
[cloud add-on](https://github.com/shimo4228/contemplative-agent-cloud) the
same way. The main repository's default behavior (`backend=None`) is the
built-in Ollama HTTP path, unchanged from before this add-on existed.

## License

MIT. See [LICENSE](LICENSE).
