"""Source of WorldStudio.exe (built by installing.bat with PyInstaller, no console window).
It only starts World Studio with the conda environment recorded in WorldStudio.json next to the exe."""
import json
import os
import subprocess
import sys
import ctypes
from pathlib import Path

here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
try:
    cfg = json.loads((here / "WorldStudio.json").read_text(encoding="utf-8"))
    prefix, root = Path(cfg["prefix"]), Path(cfg["root"])
    pyw = prefix / "pythonw.exe"
    launcher = root / "launcher" / "launcher.py"
    if not pyw.exists() or not launcher.exists():
        raise FileNotFoundError(f"{pyw if not pyw.exists() else launcher} not found")
except Exception as e:  # noqa: BLE001
    ctypes.windll.user32.MessageBoxW(0, f"World Studio cannot start:\n{e}\n\nRun installing.bat again.", "World Studio", 0x10)
    sys.exit(1)

env = dict(os.environ)
# what 'conda activate' would add: needed for the DLLs of numpy/scipy/ssl/tk in a conda environment
extra = [prefix, prefix / "Library" / "mingw-w64" / "bin", prefix / "Library" / "usr" / "bin", prefix / "Library" / "bin", prefix / "Scripts"]
env["PATH"] = os.pathsep.join(str(p) for p in extra) + os.pathsep + env.get("PATH", "")
env["CONDA_PREFIX"] = str(prefix)
subprocess.Popen([str(pyw), str(launcher)], cwd=str(root), env=env, creationflags=0x08000000 | 0x00000008)   # no window, detached
