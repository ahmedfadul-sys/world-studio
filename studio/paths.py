"""Where things live. Code can be replaced by updates; the environments, data and logs never are."""
from __future__ import annotations

import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]          # folder holding studio/, shell/, apps/, VERSION


def home() -> Path:
    """User data root (persistent across updates): envs, projects, logs, downloaded versions."""
    env = os.environ.get("STUDIO_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "WorldStudio"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "WorldStudio"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "world-studio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub(*parts: str) -> Path:
    p = home().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def env_dir(name: str) -> Path:
    return home() / "env" / name


def env_python(name: str) -> Path:
    d = env_dir(name)
    return d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def logs_dir() -> Path:
    return sub("logs")


def data_dir(module_id: str) -> Path:
    return sub("data", module_id)


def read_version(root: Path = CODE_ROOT) -> str:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"
