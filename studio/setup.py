"""Point World Studio at Python environments you already have (nothing is downloaded or created for them).

  python -m studio.setup --show
  python -m studio.setup --app C:\\envs\\main\\Scripts\\python.exe --bpy C:\\envs\\bpy\\Scripts\\python.exe
  python -m studio.setup --app C:\\envs\\all\\Scripts\\python.exe --same      # one environment that has everything (incl. bpy)
  python -m studio.setup --bpy none                                          # forget the override, use the managed environment again
"""
from __future__ import annotations

import argparse
import json
import sys

from . import envmgr, settings


def set_env(name: str, python: str | None) -> dict:
    envs = dict(settings.load().get("envs", {}))
    if python in (None, "", "none"):
        envs.pop(name, None)
        settings.save({"envs": envs})
        return {"ok": True, "python": None, "missing": []}
    v = envmgr.verify(name, python)
    if v["ok"]:
        envs[name] = {"python": python}
        settings.save({"envs": envs})
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="studio.setup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app")
    ap.add_argument("--bpy")
    ap.add_argument("--same", action="store_true", help="use the --app interpreter for bpy too")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    if a.same and a.app:
        a.bpy = a.app
    rc = 0
    for name in ("app", "bpy"):
        val = getattr(a, name)
        if val is not None:
            v = set_env(name, val)
            print(f"{name}: {'OK' if v['ok'] else 'NOT SAVED — missing ' + ', '.join(v['missing']) + (' (' + v['error'] + ')' if v.get('error') else '')}"
                  + (f"  [{v['warning']}]" if v.get("warning") else ""))
            rc |= 0 if v["ok"] else 1
    if a.show or not (a.app or a.bpy):
        print(json.dumps({n: envmgr.verify(n) for n in ("app", "bpy")}, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
