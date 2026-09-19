from __future__ import annotations

import socket
import subprocess
import sys
import time
from filewatch.process import claim_listen_port, listening_pids, pid_alive
from filewatch.web import create_server, replace_serve_on_port


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _listen(port: int) -> subprocess.Popen:
    script = (
        "import socket, time\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {port}))\n"
        "s.listen(1)\n"
        "time.sleep(30)\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_listening(port: int, pid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pid in listening_pids(port):
            return
        if not pid_alive(pid):
            raise AssertionError(f"listener {pid} exited before binding {port}")
        time.sleep(0.05)
    raise AssertionError(f"pid {pid} did not listen on {port}")


def test_claim_listen_port_keeps_latest() -> None:
    port = _free_port()
    first = _listen(port)
    try:
        _wait_listening(port, first.pid)
        replaced = claim_listen_port(port)
        assert first.pid in replaced
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and pid_alive(first.pid):
            time.sleep(0.05)
        assert first.pid not in listening_pids(port)
        second = _listen(port)
        try:
            _wait_listening(port, second.pid)
            assert second.pid in listening_pids(port)
        finally:
            second.terminate()
            second.wait(timeout=5)
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=5)


def test_create_server_replaces_same_port(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    port = _free_port()
    occupant = _listen(port)
    try:
        _wait_listening(port, occupant.pid)
        httpd = create_server("127.0.0.1", port)
        try:
            assert occupant.pid in httpd.replaced_pids
            assert httpd.server_address[1] == port
            assert replace_serve_on_port(port) == []
        finally:
            httpd.server_close()
    finally:
        if occupant.poll() is None:
            occupant.terminate()
            occupant.wait(timeout=5)
