"""Starting and stopping the external helper programs.

* USB tunnel  - forwards the iPhone's WDA ports to localhost
                (e.g. `iproxy`, `go-ios forward`, `tidevice relay`).
* WDA launch  - starts WebDriverAgent on the phone
                (e.g. `ios runwda`, `tidevice xctest`).
* UxPlay      - AirPlay mirroring receiver for the view-only wireless mode.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from imirror.config import CONFIG_PATH

LOG_DIR = CONFIG_PATH.parent / "logs"

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def split_commands(template: str, **values) -> list[list[str]]:
    """A template may hold several commands separated by `&&` or new lines."""
    commands = []
    for line in template.replace("&&", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.format(**values)
        commands.append(shlex.split(line, posix=(sys.platform != "win32")))
    # On Windows shlex keeps quotes; strip them.
    return [[arg.strip('"') for arg in cmd] for cmd in commands]


class ProcessGroup:
    def __init__(self):
        self.procs: list[subprocess.Popen] = []

    def start(self, argv: list[str], log_name: str) -> subprocess.Popen:
        """Start a hidden process; its output goes to logs/<log_name>.log."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOG_DIR / f"{log_name}.log", "w", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        finally:
            log.close()  # the child keeps its own handle
        self.procs.append(proc)
        return proc

    def any_exited(self) -> subprocess.Popen | None:
        return next((p for p in self.procs if p.poll() is not None), None)

    def stop_all(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()


def find_uxplay(configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("uxplay")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "UxPlay" / "uxplay.exe",
        Path(r"C:\msys64\ucrt64\bin\uxplay.exe"),
        Path(r"C:\msys64\mingw64\bin\uxplay.exe"),
        Path(__file__).resolve().parent.parent / "bin" / "uxplay.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def uxplay_command(exe: str, name: str) -> list[str]:
    # -n: name shown in iPhone's Screen Mirroring list; -nh: don't append hostname;
    # -vsync no: lowest latency for mirroring.
    argv = [exe, "-n", name, "-nh", "-vsync", "no"]
    if sys.platform == "win32":
        argv += ["-vs", "d3d11videosink"]
    return argv
