"""Persistent virtual environments, created once and only touched when their requirements change.

An environment is described by (name, base python, requirement files). A stamp file stores the SHA-256 of the
requirement texts + base python version; when it matches the environment is reused instantly, when it differs
`pip install -r` runs (pip only installs the difference) and the stamp is rewritten after success.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import paths, settings

Progress = Callable[[str], None]


class EnvError(RuntimeError):
    pass


@dataclass
class EnvSpec:
    name: str
    requirements: list[Path] = field(default_factory=list)
    base_python: str = sys.executable           # interpreter used to create the venv (must match what packages need, e.g. 3.11 for bpy)
    pip_args: list[str] = field(default_factory=list)


def _base_version(python: str) -> str:
    try:
        out = subprocess.run([python, "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"], capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"


def fingerprint(spec: EnvSpec) -> str:
    h = hashlib.sha256()
    h.update(_base_version(spec.base_python).rsplit(".", 1)[0].encode())       # major.minor only: a patch release must not rebuild
    for r in spec.requirements:
        h.update(r.name.encode())
        h.update(r.read_bytes() if r.exists() else b"<missing>")
    h.update(" ".join(spec.pip_args).encode())
    return h.hexdigest()


def _stamp(name: str) -> Path:
    return paths.env_dir(name) / ".studio-stamp.json"


def resolve_python(name: str) -> Path:
    """Interpreter of environment `name`: the user's own (override) when configured, else the managed one."""
    o = settings.python_override(name)
    return Path(o) if o else paths.env_python(name)


def status(spec: EnvSpec) -> str:
    """'ready' | 'stale' (exists, requirements changed) | 'missing' | 'external' (user's own environment, never touched)."""
    if settings.python_override(spec.name):
        return "external"
    py = paths.env_python(spec.name)
    if not py.exists():
        return "missing"
    try:
        st = json.loads(_stamp(spec.name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "stale"
    return "ready" if st.get("fingerprint") == fingerprint(spec) else "stale"


def _run(cmd: list[str], progress: Progress | None, what: str) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail = (tail + [line])[-25:]
        if progress and (line.startswith(("Collecting", "Downloading", "Installing", "Successfully", "Building"))):
            progress(line[:110])
    if proc.wait() != 0:
        raise EnvError(f"{what} failed (exit {proc.returncode}):\n" + "\n".join(tail))


def ensure(spec: EnvSpec, progress: Progress | None = None) -> str:
    """Make the environment match its spec. Returns 'reused' | 'updated' | 'created'."""
    s = status(spec)
    if s in ("ready", "external"):
        return "reused"
    py = paths.env_python(spec.name)
    created = False
    if s == "missing":
        if progress:
            progress(f"Creating environment '{spec.name}'…")
        paths.env_dir(spec.name).parent.mkdir(parents=True, exist_ok=True)
        _run([spec.base_python, "-m", "venv", str(paths.env_dir(spec.name))], progress, "venv creation")
        created = True
    for r in spec.requirements:
        if not r.exists():
            raise EnvError(f"requirements file not found: {r}")
        if progress:
            progress(f"Installing {r.name} into '{spec.name}'…")
        _run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(r), *spec.pip_args], progress, f"pip install -r {r.name}")
    _stamp(spec.name).write_text(json.dumps({"fingerprint": fingerprint(spec), "python": _base_version(spec.base_python)}), encoding="utf-8")
    return "created" if created else "updated"


REQUIRED = {
    "app": ["fastapi", "uvicorn", "pydantic", "numpy", "scipy", "cv2", "shapely", "debim", "psutil", "manifold3d"],
    "bpy": ["bpy"],
}


def verify(name: str, python: str | Path | None = None) -> dict:
    """Check that an interpreter has what environment `name` needs (find_spec only: fast, nothing heavy is imported).
    -> {'ok', 'python', 'version', 'missing': [...], 'error'?}"""
    py = str(python or resolve_python(name))
    if not Path(py).exists():
        return {"ok": False, "python": py, "version": None, "missing": list(REQUIRED[name]), "error": "interpreter not found"}
    code = ("import sys, importlib.util as u, json; need = json.loads(sys.argv[1]);"
            "print(json.dumps({'version': '%d.%d.%d' % sys.version_info[:3], 'missing': [m for m in need if u.find_spec(m) is None]}))")
    try:
        out = subprocess.run([py, "-c", code, json.dumps(REQUIRED[name])], capture_output=True, text=True, timeout=60)
        r = json.loads(out.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        return {"ok": False, "python": py, "version": None, "missing": list(REQUIRED[name]), "error": f"cannot run it: {e}"}
    res = {"ok": not r["missing"], "python": py, **r}
    if name == "bpy" and r["version"] and not r["version"].startswith(("3.11", "3.12", "3.13")):
        res["warning"] = "bpy wheels target Python 3.11 (Blender 4.x/5.x)"
    return res
