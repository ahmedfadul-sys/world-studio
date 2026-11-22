"""Run by installing.bat with the Python of your conda environment (world_build).
Installs ONLY what is missing (never upgrades or downgrades what is already there), checks that bpy really imports,
and tells World Studio to use this environment for both 'app' and 'bpy'. Standard library + pip only."""
from __future__ import annotations

import importlib.metadata as md
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REQ_FILES = [ROOT / "requirements" / "app.txt", ROOT / "requirements" / "window.txt"]
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*")


def parse(path: Path, seen: set | None = None) -> list[str]:
    seen = seen if seen is not None else set()
    path = path.resolve()
    if path in seen or not path.exists():
        return []
    seen.add(path)
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            out += parse((path.parent / line.split(None, 1)[1].strip()), seen)
        elif not line.startswith("-"):
            if ";" in line and "win32" in line and sys.platform != "win32":
                continue
            out.append(line.split(";", 1)[0].strip())
    return out


def dist_name(req: str) -> str:
    return NAME.match(req).group(0)


def installed(name: str):
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


def main() -> int:
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    reqs = {}
    for f in REQ_FILES:
        for r in parse(f):
            reqs.setdefault(dist_name(r).lower().replace("_", "-"), r)
    missing = [r for n, r in reqs.items() if installed(n) is None]
    print(f"{len(reqs)} packages required, {len(missing)} missing")
    if missing:
        print("Installing only the missing ones:", ", ".join(missing))
        rc = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade-strategy", "only-if-needed", *missing])
        if rc:
            print("\nERROR: pip could not install the missing packages (see above). Nothing in your environment was removed.")
            return 1
    try:
        from packaging.requirements import Requirement
        for n, r in reqs.items():
            v = installed(n)
            req = Requirement(r)
            if v and req.specifier and not req.specifier.contains(v, prereleases=True):
                print(f"  note: {n} {v} is installed but the project asks for {req.specifier} — left as is (works in most cases)")
    except Exception:  # noqa: BLE001
        pass
    # bpy must really import in this interpreter (find_spec is not enough: it needs a matching Python and numpy)
    r = subprocess.run([sys.executable, "-c", "import bpy; print(bpy.app.version_string)"], capture_output=True, text=True)
    if r.returncode:
        print("\nERROR: 'import bpy' fails in this environment:\n" + (r.stderr.strip().splitlines() or ["?"])[-1])
        print("Fix: bpy 5.x needs Python 3.11 (and numpy 1.26). Make a separate Python 3.11 environment for it and run\n"
              "  python -m studio.setup --bpy <path to its python.exe>")
        return 2
    print("bpy", r.stdout.strip(), "imports OK")
    from studio import envmgr, setup
    for name in ("app", "bpy"):
        v = setup.set_env(name, sys.executable)
        if not v["ok"]:
            print(f"ERROR: {name}: still missing {', '.join(v['missing'])}")
            return 3
    print("World Studio will use this environment (settings saved).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
