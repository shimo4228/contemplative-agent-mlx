"""Tests for the contemplative-agent-mlx CLI wrapper."""

from __future__ import annotations

import sys
import types

import pytest


def test_build_backend_defaults(monkeypatch):
    monkeypatch.delenv("MLX_BASE_URL", raising=False)
    monkeypatch.delenv("MLX_MODEL", raising=False)

    from contemplative_agent_mlx.cli import (
        _DEFAULT_BASE_URL,
        _DEFAULT_MODEL,
        _build_backend,
    )
    from contemplative_agent_mlx.backends.mlx import MlxLmBackend

    backend = _build_backend()
    assert isinstance(backend, MlxLmBackend)
    assert backend.base_url == _DEFAULT_BASE_URL
    assert backend.model == _DEFAULT_MODEL


def test_build_backend_env_override(monkeypatch):
    monkeypatch.setenv("MLX_BASE_URL", "http://localhost:9090")
    monkeypatch.setenv("MLX_MODEL", "mlx-community/some-other-4bit")

    from contemplative_agent_mlx.cli import _build_backend

    backend = _build_backend()
    assert backend.base_url == "http://localhost:9090"
    assert backend.model == "mlx-community/some-other-4bit"


def test_build_backend_untrusted_url_fails_fast(monkeypatch):
    """A misconfigured external MLX_BASE_URL is rejected at construction
    (CLI startup), not deferred to the first generate() call."""
    monkeypatch.delenv("OLLAMA_TRUSTED_HOSTS", raising=False)
    monkeypatch.setenv("MLX_BASE_URL", "http://evil.com:8080")

    from contemplative_agent_mlx.cli import _build_backend

    with pytest.raises(ValueError, match="trusted host"):
        _build_backend()


def test_main_sets_peer_module_env(monkeypatch):
    """main() must set CONTEMPLATIVE_DIALOGUE_PEER_MODULE so the main CLI
    re-enters this wrapper when spawning dialogue peers."""
    monkeypatch.delenv("MLX_BASE_URL", raising=False)
    monkeypatch.delenv("MLX_MODEL", raising=False)
    monkeypatch.delenv("CONTEMPLATIVE_DIALOGUE_PEER_MODULE", raising=False)
    # main() reassigns sys.argv; snapshot so monkeypatch restores it on teardown.
    monkeypatch.setattr(sys, "argv", sys.argv[:])

    fake_cli_module = types.ModuleType("contemplative_agent.cli")
    fake_cli_module.main = lambda: None
    monkeypatch.setitem(sys.modules, "contemplative_agent.cli", fake_cli_module)

    from contemplative_agent_mlx.cli import main

    main(argv=["distill"])

    import os as _os
    assert (
        _os.environ["CONTEMPLATIVE_DIALOGUE_PEER_MODULE"]
        == "contemplative_agent_mlx.cli"
    )

    from contemplative_agent.core import llm as _llm_module
    _llm_module.reset_llm_config()


def test_main_injects_backend(monkeypatch):
    monkeypatch.delenv("MLX_BASE_URL", raising=False)
    monkeypatch.delenv("MLX_MODEL", raising=False)
    # main() reassigns sys.argv; snapshot so monkeypatch restores it on teardown.
    monkeypatch.setattr(sys, "argv", sys.argv[:])

    called = {"hit": False}

    def fake_main():
        called["hit"] = True

    fake_cli_module = types.ModuleType("contemplative_agent.cli")
    fake_cli_module.main = fake_main
    monkeypatch.setitem(sys.modules, "contemplative_agent.cli", fake_cli_module)

    captured: dict = {}

    from contemplative_agent.core import llm as _llm_module

    orig_configure = _llm_module.configure

    def fake_configure(**kwargs):
        captured.update(kwargs)
        return orig_configure(**kwargs)

    monkeypatch.setattr("contemplative_agent_mlx.cli.configure", fake_configure)

    from contemplative_agent_mlx.cli import main
    from contemplative_agent_mlx.backends.mlx import MlxLmBackend

    main(argv=["distill", "--days", "1"])

    assert called["hit"]
    assert isinstance(captured.get("backend"), MlxLmBackend)
    _llm_module.reset_llm_config()
