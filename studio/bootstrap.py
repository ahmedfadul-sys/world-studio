"""First-run / every-run bootstrap (standard library only, runs under the installer's own Python):
make sure the two environments exist (instantly when nothing changed), then run the studio inside them and restart it after updates."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import envmgr, paths, updater

RESTART = 75


def specs(root: Path) -> list[envmgr.EnvSpec]:
    req = root / "requirements"
    return [
        envmgr.EnvSpec("app", [req / "app.txt", req / "window.txt"], base_python=sys.executable),
        envmgr.EnvSpec("bpy", [req / "bpy.txt"], base_python=sys.executable),        # bpy wheels need the exact Python minor of the runtime (3.11)
    ]


def prepare(root: Path, progress: Callable[[str], None] | None = None) -> dict[str, str]:
    """Ensure all environments; returns {name: reused|updated|created|external}."""
    out = {}
    for s in specs(root):
        if envmgr.status(s) == "external":
            v = envmgr.verify(s.name)
            if not v["ok"]:
                raise envmgr.EnvError(f"Your environment for '{s.name}' ({v['python']}) is missing: {', '.join(v['missing']) or v.get('error', '?')}.\n"
                                      f"Install them there (pip install -r requirements/{'bpy' if s.name == 'bpy' else 'app'}.txt) or run: python -m studio.setup --{s.name} none")
            out[s.name] = "external"
        else:
            out[s.name] = envmgr.ensure(s, progress)
    return out


def run_forever(progress: Callable[[str], None] | None = None) -> int:
    while True:
        root = updater.active_root()
        try:
            prepare(root, progress)
        except envmgr.EnvError as e:
            if progress:
                progress("ERROR: " + str(e).splitlines()[0])
            print(e, file=sys.stderr)
            return 2
        py = envmgr.resolve_python("app")
        env = {**os.environ, "PYTHONPATH": str(root), "PYTHONIOENCODING": "utf-8"}
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        code = subprocess.call([str(py), "-m", "studio.run"], cwd=root, env=env, **kw)
        if code != RESTART:
            return code


def main() -> int:
    return run_forever(lambda s: print(s, flush=True))


if __name__ == "__main__":
    sys.exit(main())
