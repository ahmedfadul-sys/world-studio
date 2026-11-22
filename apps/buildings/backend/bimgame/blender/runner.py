"""Run a Blender script as a separate, supervised subprocess.

Guarantees: process-group kill on timeout / memory limit / cancel, no zombie
left behind, job temp dir always removed, stdout+stderr go to a log file (not
memory) and its tail is attached to errors.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from ..config import Settings
from ..utils.errors import BuildError, DependencyError

log = logging.getLogger("bimgame.blender")


@dataclass
class RunResult:
    report: dict
    peak_rss_mb: float
    seconds: float
    log_tail: str


def _tree_rss(pid: int) -> float:
    try:
        p = psutil.Process(pid)
        procs = [p, *p.children(recursive=True)]
        return sum(x.memory_info().rss for x in procs if x.is_running()) / 2**20
    except psutil.Error:
        return 0.0


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()


def check_blender(settings: Settings) -> dict:
    """Dependency check: can the configured interpreter/binary start Blender?"""
    cmd = settings.blender_cmd or settings.blender_python
    if not (shutil.which(cmd) or Path(cmd).exists()):
        return {"ok": False, "command": cmd, "error": "executable not found"}
    code = "import bpy,sys;print(bpy.app.version_string)"
    try:
        if settings.blender_cmd:
            r = subprocess.run([cmd, "-b", "--factory-startup", "--python-expr", "import bpy;print('V='+bpy.app.version_string)"],
                               capture_output=True, text=True, timeout=60)
            line = next((l for l in r.stdout.splitlines() if l.startswith("V=")), "")
            return {"ok": bool(line), "command": cmd, "version": line[2:]}
        r = subprocess.run([cmd, "-c", code], capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "command": cmd, "version": r.stdout.strip(), "error": r.stderr[-300:] if r.returncode else ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "command": cmd, "error": str(exc)}


def run_blender(settings: Settings, script: str, job: dict, tmp_root: Path,
                cancel: threading.Event | None = None, timeout_s: int | None = None) -> RunResult:
    timeout_s = timeout_s or settings.blender_timeout_s
    tmp_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="blender_job_", dir=tmp_root))
    result_path, job_path, log_path = work / "result.json", work / "job.json", work / "worker.log"
    job = {**job, "result_path": str(result_path)}
    job_path.write_text(json.dumps(job))
    cmd = settings.blender_command(script, str(job_path))
    exe = cmd[0]
    if not (shutil.which(exe) or Path(exe).exists()):
        shutil.rmtree(work, ignore_errors=True)
        raise DependencyError("Blender is not available", "blender.runner", f"'{exe}' not found",
                              "Install Blender 4.2+ and set BIM_BLENDER_CMD, or create .venv-blender with `pip install bpy` and set BIM_BLENDER_PYTHON")
    t0 = time.perf_counter()
    peak = 0.0
    proc = None
    try:
        with open(log_path, "wb") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
            log.info("blender started pid=%s script=%s", proc.pid, script)
            while proc.poll() is None:
                peak = max(peak, _tree_rss(proc.pid))
                if cancel is not None and cancel.is_set():
                    _kill_group(proc)
                    raise BuildError("Build cancelled", "blender.runner", "cancel requested", "Start a new build", status=499)
                if time.perf_counter() - t0 > timeout_s:
                    _kill_group(proc)
                    raise BuildError("Blender timed out", "blender.runner", f"no result within {timeout_s}s",
                                     "Use a lower poly preset, build fewer levels, or raise BIM_BLENDER_TIMEOUT", status=504)
                if peak > settings.blender_max_rss_mb:
                    _kill_group(proc)
                    raise BuildError("Blender exceeded the memory limit", "blender.runner",
                                     f"{peak:.0f} MB > {settings.blender_max_rss_mb} MB",
                                     "Build one level at a time, use the low preset, or raise BIM_BLENDER_MAX_RSS_MB", status=507)
                time.sleep(0.05)
        tail = log_path.read_text(errors="replace")[-1500:]
        if proc.returncode != 0 or not result_path.exists():
            detail = ""
            if result_path.exists():
                try:
                    detail = json.loads(result_path.read_text()).get("error", {}).get("what", "")
                except ValueError:
                    pass
            raise BuildError("Blender worker failed", "blender.worker", detail or f"exit code {proc.returncode}",
                             f"See log tail: {tail[-300:]}", status=500)
        rep = json.loads(result_path.read_text())
        if not rep.get("ok"):
            raise BuildError("Blender worker reported failure", "blender.worker", rep.get("error", {}).get("what", "unknown"), "Check the project and retry")
        return RunResult(rep, peak, time.perf_counter() - t0, tail)
    finally:
        if proc is not None and proc.poll() is None:
            _kill_group(proc)  # never leave a Blender process behind
        shutil.rmtree(work, ignore_errors=True)
