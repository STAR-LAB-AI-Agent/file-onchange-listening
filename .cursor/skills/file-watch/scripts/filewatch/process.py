from __future__ import annotations

import ctypes
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_pid(pid: int) -> None:
    if not pid_alive(pid):
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return
    os.kill(pid, signal.SIGTERM)


def spawn_detached(
    argv: list[str],
    log_path: Path,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    kwargs: dict = {
        "args": argv,
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "cwd": str(cwd) if cwd else None,
        "env": env,
        "close_fds": sys.platform != "win32",
    }
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(**kwargs)
    return proc.pid


def _addr_port(local: str) -> int | None:
    text = local.strip()
    if text.startswith("[") and "]:" in text:
        try:
            return int(text.rsplit("]:", 1)[1])
        except ValueError:
            return None
    if ":" not in text:
        return None
    try:
        return int(text.rsplit(":", 1)[1])
    except ValueError:
        return None


def _listening_pids_windows(port: int) -> list[int]:
    completed = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    pids: set[int] = set()
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        proto = parts[0].upper()
        if proto not in {"TCP", "TCPV6"}:
            continue
        local = parts[1]
        if _addr_port(local) != port:
            continue
        state = parts[-2].upper() if len(parts) >= 5 else ""
        if state not in {"LISTENING", "LISTEN"} and "侦听" not in parts[-2]:
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def _listening_pids_unix(port: int) -> list[int]:
    commands = (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        ["ss", "-lptn", f"sport = :{port}"],
    )
    pids: set[int] = set()
    for argv in commands:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0 and not completed.stdout.strip():
            continue
        if argv[0] == "lsof":
            for line in completed.stdout.splitlines():
                text = line.strip()
                if text.isdigit():
                    pids.add(int(text))
            if pids:
                break
            continue
        for match in re.finditer(r"pid=(\d+)", completed.stdout):
            pids.add(int(match.group(1)))
        if pids:
            break
    return sorted(pids)


def listening_pids(port: int) -> list[int]:
    if port <= 0:
        return []
    if sys.platform == "win32":
        return _listening_pids_windows(port)
    return _listening_pids_unix(port)


def claim_listen_port(port: int, *, exclude_pid: int | None = None, timeout: float = 5.0) -> list[int]:
    """结束占用该端口的其它进程，只留下当前进程。"""
    if port <= 0:
        return []
    me = exclude_pid if exclude_pid is not None else os.getpid()
    seen: set[int] = set()
    deadline = time.monotonic() + timeout
    while True:
        others = [pid for pid in listening_pids(port) if pid != me]
        if not others:
            return sorted(seen)
        for pid in others:
            if pid in seen:
                continue
            terminate_pid(pid)
            seen.add(pid)
        if time.monotonic() >= deadline:
            leftover = [pid for pid in listening_pids(port) if pid != me]
            if leftover:
                raise OSError(f"端口 {port} 仍被进程占用：{leftover}")
            return sorted(seen)
        time.sleep(0.05)
