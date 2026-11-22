"""Starts every module (a FastAPI backend each) as its own process, waits until healthy, restarts it if it dies, stops them all on exit."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import envmgr, paths


@dataclass
class Module:
    id: str
    dir: Path
    manifest: dict
    port: int = 0
    proc: subprocess.Popen | None = None
    state: str = "stopped"            # stopped | starting | ready | failed
    error: str = ""
    restarts: list[float] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def title(self, lang: str) -> str:
        t = self.manifest.get("title", {})
        return t.get(lang) or t.get("en") or self.id


def load_modules(code_root: Path = paths.CODE_ROOT) -> list[Module]:
    mods = []
    for f in sorted((code_root / "apps").glob("*/module.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            mods.append(Module(id=m["id"], dir=f.parent, manifest=m))
        except (OSError, ValueError, KeyError):
            continue            # a broken manifest must not stop the other modules
    return mods


def free_port(preferred: int = 0) -> int:
    for p in ([preferred] if preferred else []) + [0]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("no free port")


def _expand(text: str, m: Module) -> str:
    out = text.replace("{port}", str(m.port)).replace("{module}", str(m.dir)).replace("{data}", str(paths.data_dir(m.id))) \
              .replace("{home}", str(paths.home())).replace("{code}", str(paths.CODE_ROOT))
    while "{env:" in out:
        a = out.index("{env:")
        b = out.index("}", a)
        out = out[:a] + str(envmgr.resolve_python(out[a + 5:b])) + out[b + 1:]
    return out.replace("{python}", str(envmgr.resolve_python(m.manifest.get("env", "app"))))


def healthy(m: Module, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(m.url.rstrip("/") + m.manifest.get("health", "/"), timeout=timeout) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001
        return False


class Supervisor:
    def __init__(self, modules: list[Module]):
        self.modules = modules
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ process control
    def _spawn(self, m: Module) -> None:
        mf = m.manifest
        m.port = free_port(mf.get("preferred_port", 0))
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        env.update({k: _expand(v, m) for k, v in mf.get("env_vars", {}).items()})
        cmd = [_expand(c, m) for c in mf["command"]]
        log = paths.logs_dir() / f"{m.id}.log"
        if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
            os.replace(log, log.with_suffix(".log.1"))
        fh = open(log, "ab")
        kw: dict = {}
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        m.state, m.error = "starting", ""
        m.proc = subprocess.Popen(cmd, cwd=m.dir / mf.get("cwd", "."), env=env, stdout=fh, stderr=subprocess.STDOUT, **kw)

    def _kill(self, m: Module) -> None:
        p = m.proc
        if not p or p.poll() is not None:
            return
        try:
            if os.name == "nt":
                p.terminate()
            else:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            p.wait(timeout=8)
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError):
            try:
                p.kill()
            except OSError:
                pass

    def start_all(self, wait_s: float = 60.0) -> None:
        for m in self.modules:
            self._spawn(m)
        t0 = time.time()
        while time.time() - t0 < wait_s and any(m.state == "starting" for m in self.modules):
            self._poll()
            time.sleep(0.25)
        self._thread = threading.Thread(target=self._watch, daemon=True, name="supervisor")
        self._thread.start()

    def _poll(self) -> None:
        for m in self.modules:
            if m.state == "starting":
                if m.proc and m.proc.poll() is not None:
                    m.state, m.error = "failed", f"exited with code {m.proc.returncode} (see logs/{m.id}.log)"
                elif healthy(m):
                    m.state = "ready"

    def _watch(self) -> None:
        while not self._stop.wait(2.0):
            self._poll()
            for m in self.modules:
                if m.state == "ready" and (m.proc is None or m.proc.poll() is not None):
                    now = time.time()
                    m.restarts = [t for t in m.restarts if now - t < 120] + [now]
                    if len(m.restarts) > 3:
                        m.state, m.error = "failed", f"crashed {len(m.restarts)} times in 2 minutes (see logs/{m.id}.log)"
                    else:
                        self._spawn(m)         # new port; the shell reads the current url from /studio/api/modules

    def restart(self, mid: str) -> bool:
        for m in self.modules:
            if m.id == mid:
                self._kill(m)
                m.restarts.clear()
                self._spawn(m)
                return True
        return False

    def stop_all(self) -> None:
        self._stop.set()
        for m in self.modules:
            self._kill(m)
            m.state = "stopped"
