# contemplative-agent-mlx

> **Status: Frozen as of contemplative-agent v2.13.0 (kit static PASS 2026-10-24).** Revisit when the ADR-0067 reversal thresholds (mlx-lm #615/#884, #854/#883) are met. Run `pip-audit` on the dependencies before using it. (Decision D-P1-11-2 = A, owner, 2026-10-24.)


Optional **local MLX generation backend** for
[contemplative-agent](https://github.com/shimo4228/contemplative-agent), an
autonomous agent on a local LLM that posts on Moltbook (a social network where
only AI agents post) and proposes changes to its own prompts for a person to
approve. On Apple Silicon, installing this package and running the
`contemplative-agent-mlx` entry point routes generation through a local
`mlx_lm.server` (Apple's MLX runtime) instead of Ollama. Embeddings continue
to use local `nomic-embed-text` via Ollama. It is an add-on: it extends the
core agent without modifying or replacing it, and the core's default Ollama
path stays as it is. It is for people who run contemplative-agent on an Apple
Silicon Mac and want faster, lighter generation in interactive runs they are
watching.

Generation stays on-device: by default, each generation request (the prompt
in, the completion back) goes only to a server on localhost. What the agent
later posts to Moltbook with `run` is a separate step, described under
[Run](#run). Prompts reach another machine only if you list its host in
`OLLAMA_TRUSTED_HOSTS` (the core's setting for trusted LAN hosts) and point
`MLX_BASE_URL` at it. Unlike
[contemplative-agent-cloud](https://github.com/shimo4228/contemplative-agent-cloud),
this is a **local-runtime swap, not a cloud backend**, so the main
repository's local-only property (no cloud LLM, no LLM API key) is preserved.
In the author's benchmark on an M1 Mac with 16 GB, measured in June 2026
([ADR-0064](https://github.com/shimo4228/contemplative-agent/blob/main/docs/adr/0064-mlx-generation-backend.md),
with the raw measurements linked there), `mlx_lm.server` generated about
**1.8× faster and used ~3.4 GB less memory** than Ollama serving the same
Qwen3.5 9B model (the control; MLX 4-bit against GGUF Q4_K_M, so not
byte-identical). That model is no longer the production one: the core has run
on `gemma4:e4b` since 2026-06-28 (ADR-0069), and running through MLX changes
the generation model, so the figures do not transfer to the core's current
default.

Other work by the author is listed under [More from the author](#more-from-the-author).

## ⚠️ Unfit for unattended / continuous use on 16 GB

This add-on is for **interactive, manual, short-lived** runs. On a 16 GB
Apple Silicon host, `mlx_lm.server` is **not reliable for the unattended
scheduled agent**. The main repository's production schedule deliberately
runs on Ollama for exactly this reason (its decision record
[ADR-0067](https://github.com/shimo4228/contemplative-agent/blob/main/docs/adr/0067-keep-ollama-for-unattended-production.md)).
The failure modes observed under sustained load are summarized in the folded
section at the end of this README.

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
| LLM prompt egress | None by default | **None** by default (on-device runtime swap) |

If this package is not installed and no backend is explicitly configured,
the main repository runs exactly as before.

## Requirements

- **Apple Silicon Mac** (M1 or newer). The add-on targets Apple Silicon: its
  scripts, the Metal memory behavior recorded in ADR-0067 and every figure in this README
  come from an M1 Mac with 16 GB, where the server held about 5.2 GB resident.
- Python 3.11 or later and `uv` (the scripts launch the server with `uvx`).
- The main repository
  ([contemplative-agent](https://github.com/shimo4228/contemplative-agent))
  installed in the same virtual environment.
- Ollama running locally for embeddings (`nomic-embed-text` on
  `localhost:11434`).
- `mlx-lm` available to launch the server. `mlx-lm` is **not** a Python
  dependency of this package (the backend only speaks HTTP); the scripts run
  it via `uvx --from mlx-lm`. If you `uv tool install mlx-lm` once,
  `scripts/run-with-mlx.sh` uses that binary instead; `scripts/serve-mlx.sh`
  always runs `uvx`.
- Network access on the first server start: `mlx_lm.server` downloads the
  weights of `MLX_MODEL` (several GB; see Configure) from Hugging Face once
  and reuses the cached copy afterwards.

No LLM API key is involved. The agent still needs its own Moltbook API key to
post (`run`); the core README's `register` step creates and saves it.

## Install

Neither this package nor contemplative-agent is on PyPI, so clone both side by
side and install them into one virtual environment (this package requires
`contemplative-agent>=2.10.0`, the core release that ships the conformance
kit for backends like this one):

```bash
git clone https://github.com/shimo4228/contemplative-agent.git
git clone https://github.com/shimo4228/contemplative-agent-mlx.git
cd contemplative-agent-mlx
uv venv .venv && source .venv/bin/activate
uv pip install -e ../contemplative-agent -e .
ollama pull nomic-embed-text
```

Keep the virtual environment at `.venv` inside this repository:
`scripts/run-with-mlx.sh` looks for `.venv/bin/contemplative-agent-mlx` there.
If you have not run the core agent before, its README covers `init`,
registering on Moltbook and the autonomy levels.

## Configure

```bash
# Served model id, read by the scripts and the CLI. The default is the build the benchmark above measured, not the core's production model
export MLX_MODEL=mlx-community/Qwen3.5-9B-4bit

# Port the bundled scripts start the server on (default: 8080)
export MLX_PORT=8080

# Server origin the CLI connects to when you start the server yourself (default: http://localhost:8080)
export MLX_BASE_URL=http://localhost:8080
```

All three are optional. With `scripts/run-with-mlx.sh`, only `MLX_PORT` sets
the address: the wrapper exports `MLX_BASE_URL=http://localhost:$MLX_PORT`
for the agent and ignores yours. In the manual route, `scripts/serve-mlx.sh`
uses `MLX_PORT` and `MLX_MODEL` (or its positional `[PORT] [MODEL]`
arguments) and `contemplative-agent-mlx` reads `MLX_BASE_URL`, so keep the two
on the same port. In programmatic use, the `base_url` you pass to
`MlxLmBackend` governs.

## Run

### Easiest: the lifecycle wrapper

`scripts/run-with-mlx.sh` starts `mlx_lm.server`, waits for it to be healthy,
runs the agent through `contemplative-agent-mlx`, then stops the server on
exit (idle memory returns to ~0). The server log goes to
`$MOLTBOOK_HOME/logs/mlx-server.log` (`~/.config/moltbook/logs/` when unset),
created owner-only (mode 0600).

To see it work without a Moltbook account, run the core's two-agent dialogue
demo through the wrapper. Nothing goes to Moltbook; the two agents talk
through local pipes, and the terminal prints each turn in the format the core
README's demo shows:

```bash
MOLTBOOK_HOME=/tmp/ca-a contemplative-agent-mlx init
MOLTBOOK_HOME=/tmp/ca-b contemplative-agent-mlx init --template stoic
scripts/run-with-mlx.sh dialogue /tmp/ca-a /tmp/ca-b --seed "Is it ever right to change your own values?" --turns 2
```

With a registered agent, `run` posts publicly under its Moltbook account
(`--auto` drops the per-post confirmation), and `distill` turns recent
episode logs into patterns locally:

```bash
scripts/run-with-mlx.sh -v --auto run --session 60
scripts/run-with-mlx.sh distill --days 1
```

### Manual: server + CLI separately

```bash
# Terminal 1: start the MLX server (foreground)
scripts/serve-mlx.sh            # defaults: port 8080, MLX_MODEL's default

# Terminal 2: run any subcommand, swapping the binary name
contemplative-agent-mlx init
contemplative-agent-mlx distill --days 3
contemplative-agent-mlx run --session 60
contemplative-agent-mlx dialogue ~/dialogue/a ~/dialogue/b --seed "..." --turns 10
```

Any `contemplative-agent` subcommand works. Swap the command name from
`contemplative-agent` to `contemplative-agent-mlx`. All generation routes
through the local MLX server; Ollama is still contacted for embeddings.

`run` also needs Ollama for its feed relevance check: that check always asks
an Ollama model (`DECISION_MODEL`, unset = `OLLAMA_MODEL`, default
`gemma4:e4b`), never the MLX server. With `DECISION_MODEL=` empty, `run`
engages with no posts. Under this wrapper the judging model is loaded and
unloaded once per batch (about 7 s for gemma, an accepted cost: ADR-0112
addendum of 2026-10-24 in the core).

## Thinking is OFF

The backend runs with `enable_thinking=False` (production default). Native
thinking via `mlx_lm.server`'s OpenAI `/v1` endpoint is broken upstream
(mlx-lm [#1352](https://github.com/ml-explore/mlx-lm/issues/1352) /
[#337](https://github.com/lmstudio-ai/mlx-engine/issues/337)): the server's
reasoning-separation layer can leave `content` empty and run to
`finish_reason=length`. The `think` flag is still forwarded through the
Protocol for parity, but thinking-on against the server endpoint is not
recommended.

## Programmatic use

```python
from contemplative_agent.core.llm import configure
from contemplative_agent_mlx import MlxLmBackend

configure(backend=MlxLmBackend(
    base_url="http://localhost:8080",
    model="<the model id your mlx_lm.server serves>",
))

# From this point on, every `contemplative_agent.core.llm.generate()` call
# runs through the local mlx_lm.server, whichever subcommand or adapter
# triggered it. Reset with `reset_llm_config()`.
```

## Verified against the core

Verified against contemplative-agent main `v2.13.0-41-gaec9d8a` (conformance
kit level static) on 2026-10-24. This is the core's release gate output
(`scripts/check-sibling-backends.sh`), pasted as printed; refresh it at each
release:

```
[sibling] ok contemplative_agent_mlx.backends.mlx:MlxLmBackend sha=eb76250 main=v2.13.0-41-gaec9d8a level=static kit=2
```

## More from the author

- **[contemplative-agent](https://github.com/shimo4228/contemplative-agent)**: the core agent these add-ons extend, a long-running experiment in which an agent on a local LLM posts on its own and proposes changes to its own constitution, identity and skills (never its weights), with a person approving each change.
- **[contemplative-agent-cloud](https://github.com/shimo4228/contemplative-agent-cloud)**: the other optional generation backend, which routes the agent's generation to Claude or OpenAI APIs while embeddings stay local; prompts leave the machine and a paid API key is needed.
- **[tiny-lm-lab](https://github.com/shimo4228/tiny-lm-lab)**: a char-level GPT written by hand on MLX primitives and trained on the author's own articles, for a look at MLX below the server (in Japanese).
- **[shimo4228](https://github.com/shimo4228/shimo4228)**: the author's hub, with Contemplative Agent next to the author's other long-running projects and their DOIs.

## License

MIT. See [LICENSE](LICENSE).

<details>
<summary>For tools and AI assistants</summary>

contemplative-agent-mlx is an optional Python add-on for the contemplative-agent autonomous agent that routes the agent's text generation to a local `mlx_lm.server` (Apple's MLX runtime) on Apple Silicon instead of Ollama, while embeddings stay on local Ollama (`nomic-embed-text`), for people who want faster, lighter generation in interactive runs they are watching. It does not replace or modify the core agent: it implements the core's `contemplative_agent.core.llm.LLMBackend` Protocol (defined in `contemplative_agent/core/llm/backend.py`: a `model` property, a `context_window` property and `generate(prompt, system, num_predict, format, *, temperature, think) -> Optional[BackendResult]`) as `MlxLmBackend`, and injects itself with `configure(backend=...)` before handing control to the core CLI.

It exists because MLX was faster on the author's 16 GB M1 but proved unreliable for the unattended schedule. The core first carried an MLX backend, then kept production on Ollama (ADR-0067: under sustained load, memory exhaustion tripped the circuit breaker and the retry loop spun) and moved the MLX backend out into this sibling repository (ADR-0070), so the core's only in-tree generation path is Ollama. ADR-0067 also found that truncated generations (`finish_reason=length`) were noise rather than specific to MLX, so the decision rests on the circuit cascade. By default no LLM prompt leaves the machine (the backend reaches another host only if the user lists it in `OLLAMA_TRUSTED_HOSTS` and points `MLX_BASE_URL` at it, a check made by the same SSRF guard, `validate_trusted_url`, that the core's Ollama path uses), so the core's local-only property holds; the trade-off is operational.

ADR-0067 records four failure modes on the 16 GB host under sustained load, where every request carries the same system prefix of roughly 7.5k to 7.6k tokens. OOM to circuit cascade: under memory pressure a generation fails, and repeated failures trip the core's circuit breaker (after 5 consecutive failures it stops sending requests for 120 s) while the loop keeps spinning. Prefill cliff: prefill is the model reading the prompt before its first output token; one request of that size (~7.5k tokens as counted in `mlx-server.log`) prefilled in ~72 s and later took tens of minutes in the same process. Prompt-cache churn: the bundled scripts start the server with `--prompt-cache-size 2` to bound cache memory, so the server keeps at most two cached prompts; as the reply, comment, score and internal-note prompts rotate behind the shared prefix, they push out the cached entries that held it, and most generations pay a full cold prefill. Wired-memory thrash: MLX's Metal (wired, non-pageable) memory coexists worse with other apps than Ollama's pageable GGUF mmap, despite a smaller resident size.

Canonical facts: MIT license; Python 3.11 or later, built with hatchling; depends only on `contemplative-agent>=2.10.0` (the release that ships the core's backend conformance kit); `mlx-lm` is deliberately not a Python dependency, because the backend only speaks HTTP to a server started by `scripts/serve-mlx.sh` or `scripts/run-with-mlx.sh` through `uvx --from mlx-lm`. Frozen as of contemplative-agent v2.13.0 (kit static PASS 2026-10-24); revisit when the ADR-0067 reversal thresholds are met. Neither package is on PyPI, so both are installed from source into one `.venv` inside this repository. Requirements: an Apple Silicon Mac, uv, Ollama on `localhost:11434` for embeddings, and a one-time download of the model weights from Hugging Face; no LLM API key (the agent's own Moltbook API key comes from the core's `register` step). Configuration: `MLX_BASE_URL` (default `http://localhost:8080`, restricted to localhost or `OLLAMA_TRUSTED_HOSTS`; the lifecycle wrapper sets it from `MLX_PORT`), `MLX_PORT` (default `8080`, read by the scripts) and `MLX_MODEL` (default: see Configure). The backend declares a 32,768-token context window, bounded by memory on the 16 GB host (the agent's shared system prefix is about 7.6k tokens of it), and runs with thinking off (in-process `mlx_lm.generate` terminates correctly with thinking on, but using it would re-add the `mlx-lm` dependency, against the HTTP-only design). Status: for interactive, manual, short-lived runs only, not for unattended continuous use on 16 GB.

Example: `scripts/run-with-mlx.sh distill --days 1` starts `mlx_lm.server` with `--prompt-cache-size 2`, waits for `/health`, checks that the server serves the expected model id, runs `contemplative-agent-mlx distill --days 1`, and stops the server on exit. In the core's ADR-0064 benchmark (M1, 16 GB, the Ollama control on the same model, June 2026, thinking off), `mlx_lm.server` generated 12.1 to 12.7 tokens per second against Ollama's 6.8 to 7.0, with 5.2 GB resident memory against 8.6 GB. Conformance with the core's contract was last checked on 2026-10-24 (see "Verified against the core") with `python -m contemplative_agent.testing --backend contemplative_agent_mlx.backends.mlx:MlxLmBackend --kwarg base_url=http://localhost:8080 --kwarg model=conformance-probe` (static level, ok).

Links: [llms.txt](llms.txt) is the machine-readable summary. The parent project is [contemplative-agent](https://github.com/shimo4228/contemplative-agent), concept DOI [10.5281/zenodo.19212118](https://doi.org/10.5281/zenodo.19212118); cite that DOI for the framework. The decisions behind this package are the core's [ADR-0064](https://github.com/shimo4228/contemplative-agent/blob/main/docs/adr/0064-mlx-generation-backend.md), [ADR-0067](https://github.com/shimo4228/contemplative-agent/blob/main/docs/adr/0067-keep-ollama-for-unattended-production.md) and [ADR-0070](https://github.com/shimo4228/contemplative-agent/blob/main/docs/adr/0070-retire-mlx-to-sibling-repo-and-remove-docker.md). Sibling add-ons: [contemplative-agent-cloud](https://github.com/shimo4228/contemplative-agent-cloud) (Claude or OpenAI generation) and [contemplative-agent-otel](https://github.com/shimo4228/contemplative-agent-otel) (offline audit-log to OpenTelemetry converter).

</details>
