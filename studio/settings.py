"""User settings (settings.json in the data home): language and optional existing Python environments to reuse."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import paths

DEFAULTS = {"lang": "ar", "envs": {}, "auto_update": True, "last_update_check": 0}


def _file() -> Path:
    return paths.home() / "settings.json"


def load() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {**DEFAULTS, **d}


def save(patch: dict) -> dict:
    d = {**load(), **patch}
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _file())
    return d


def python_override(name: str) -> str | None:
    """Reuse an environment the user already has: STUDIO_PYTHON_<NAME> or settings.json → envs.<name>.python."""
    v = os.environ.get(f"STUDIO_PYTHON_{name.upper()}") or (load().get("envs", {}).get(name) or {}).get("python")
    return v if v and Path(v).exists() else None
