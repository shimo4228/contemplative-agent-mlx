"""scripts/run-with-mlx.sh: where the server log goes and who can read it.

The wrapper is run against a stub server and a stub agent inside a temporary
repo layout, with HOME and MOLTBOOK_HOME pointing at different temporary
directories, so a regression that writes to ``$HOME/.config/moltbook`` shows up
as a file in the wrong place instead of in the real home.
"""

from __future__ import annotations

import os
import shutil
import socket
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run-with-mlx.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("curl") is None or shutil.which("bash") is None,
    reason="needs curl and bash",
)

_FAKE_SERVER = """\
#!{python}
import http.server, json, sys

args = sys.argv[1:]
port = int(args[args.index("--port") + 1])
model = args[args.index("--model") + 1]
print("fake-mlx-server started", flush=True)


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({{"data": [{{"id": model}}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".venv" / "bin").mkdir(parents=True)
    script = repo / "scripts" / SCRIPT.name
    shutil.copy(SCRIPT, script)
    (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
    agent = repo / ".venv" / "bin" / "contemplative-agent-mlx"
    agent.write_text("#!/bin/sh\nexit 0\n")
    agent.chmod(0o755)
    home = tmp_path / "home"
    server = home / ".local" / "bin" / "mlx_lm.server"
    server.parent.mkdir(parents=True)
    server.write_text(_FAKE_SERVER.format(python=sys.executable))
    server.chmod(0o755)
    return script, home, tmp_path / "moltbook"


def _run(script: Path, home: Path, moltbook: Path | None) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "MLX_PORT": str(_free_port()),
    }
    if moltbook is not None:
        env["MOLTBOOK_HOME"] = str(moltbook)
    return subprocess.run(
        ["bash", str(script), "distill"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_log_goes_under_moltbook_home_with_owner_only_mode(tmp_path: Path) -> None:
    script, home, moltbook = _layout(tmp_path)
    result = _run(script, home, moltbook)
    assert result.returncode == 0, result.stderr
    log = moltbook / "logs" / "mlx-server.log"
    assert log.is_file()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert "fake-mlx-server started" in log.read_text()
    # Nothing leaked into the HOME-derived default location.
    assert not (home / ".config" / "moltbook").exists()


def test_default_location_is_unchanged_without_moltbook_home(tmp_path: Path) -> None:
    script, home, _ = _layout(tmp_path)
    result = _run(script, home, None)
    assert result.returncode == 0, result.stderr
    log = home / ".config" / "moltbook" / "logs" / "mlx-server.log"
    assert log.is_file()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_script_text_has_no_hardcoded_home_log() -> None:
    text = textwrap.dedent(SCRIPT.read_text())
    assert 'LOG="$HOME/.config/moltbook' not in text
    assert "MOLTBOOK_HOME" in text
