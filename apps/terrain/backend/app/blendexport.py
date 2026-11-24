"""تصدير العالم كملف .blend: يبني ملفات التصدير المعتادة (الصور والأكواد تبقى كما هي) ثم يشغّل Blender لينشئ المشهد ويحفظه.

يحتاج Blender: إمّا بايثون فيه bpy (`TERRAIN_BLENDER_PYTHON`، تضبطه المنصة على بيئة bpy) أو برنامج Blender نفسه (`TERRAIN_BLENDER_CMD`).
العملية تُشغَّل منفصلة (لا تُحمَّل bpy في خادم الـAPI أبداً) مع مهلة وقتل مجموعة العمليات وحفظ سجلّها.
"""
from __future__ import annotations

import io
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

_SCRIPT = Path(__file__).resolve().parents[2] / "blender" / "export_blend.py"
_CHECK: dict = {"t": 0.0, "v": None}


class BlendError(Exception):
    pass


def _command() -> Optional[list]:
    exe = os.environ.get("TERRAIN_BLENDER_CMD")
    if exe:
        return [exe, "-b", "--factory-startup", "-P", str(_SCRIPT), "--"]
    py = os.environ.get("TERRAIN_BLENDER_PYTHON")
    return [py, str(_SCRIPT)] if py else None


def availability(force: bool = False) -> dict:
    """{available, reason}. يفحص فعلاً أن Blender/bpy يعمل (مخزّن 60 ثانية)."""
    if not force and _CHECK["v"] is not None and time.time() - _CHECK["t"] < 60:
        return _CHECK["v"]
    cmd = _command()
    if not cmd:
        v = {"available": False, "reason": "Blender غير مضبوط: ثبّت بيئة bpy من إعدادات المنصة أو اضبط TERRAIN_BLENDER_PYTHON / TERRAIN_BLENDER_CMD."}
    elif not (shutil.which(cmd[0]) or Path(cmd[0]).exists()):
        v = {"available": False, "reason": f"لم أجد Blender/بايثون عند: {cmd[0]}"}
    else:
        try:
            probe = [cmd[0], "-b", "--factory-startup", "--python-expr", "import bpy;print('TF_OK')"] if os.environ.get("TERRAIN_BLENDER_CMD") else [cmd[0], "-c", "import bpy;print('TF_OK')"]
            r = subprocess.run(probe, capture_output=True, text=True, timeout=90)
            ok = "TF_OK" in r.stdout
            v = {"available": ok, "reason": "" if ok else "تعذّر تشغيل Blender: " + (r.stderr or r.stdout)[-300:]}
        except (OSError, subprocess.SubprocessError) as e:
            v = {"available": False, "reason": f"تعذّر تشغيل Blender: {e}"}
    _CHECK.update(t=time.time(), v=v)
    return v


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover
        pass


def export_blend(zip_bytes: bytes, out_path: str, timeout_s: Optional[int] = None, cancel: Optional[threading.Event] = None,
                 on_state: Callable[[str], None] = lambda s: None) -> dict:
    """يفك zip التصدير في مجلد مؤقت ويشغّل Blender لإنتاج out_path. يعيد {seconds, size, log_tail}."""
    cmd = _command()
    if not cmd:
        raise BlendError(availability()["reason"])
    timeout_s = timeout_s or int(os.environ.get("TERRAIN_BLENDER_TIMEOUT", "1800"))
    with tempfile.TemporaryDirectory(prefix="tf_blend_") as work:
        on_state("تجهيز الملفات")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(work)
        build = Path(work) / "build.json"
        if not build.is_file() or not (Path(work) / "import_build.py").is_file():
            raise BlendError("حزمة التصدير ناقصة (build.json أو import_build.py)")
        log = Path(work) / "blender.log"
        tmp_out = Path(work) / "out.blend"
        on_state("Blender يبني المشهد")
        t0 = time.time()
        with open(log, "wb") as lf:
            try:
                proc = subprocess.Popen([*cmd, str(build), str(tmp_out)], stdout=lf, stderr=subprocess.STDOUT, start_new_session=True, cwd=work)
            except OSError as e:
                raise BlendError(f"تعذّر تشغيل Blender: {e}") from e
            while proc.poll() is None:
                if cancel is not None and cancel.is_set():
                    _kill(proc); raise BlendError("أُلغي التصدير")
                if time.time() - t0 > timeout_s:
                    _kill(proc); raise BlendError(f"انتهت مهلة Blender ({timeout_s} ث). قلّل دقة التصدير أو حجم العالم.")
                time.sleep(0.2)
        tail = log.read_text("utf-8", "replace")[-1500:]
        if proc.returncode != 0 or not tmp_out.is_file() or tmp_out.stat().st_size < 100:
            raise BlendError(f"فشل Blender (رمز {proc.returncode}). آخر السجل:\n{tail}")
        shutil.move(str(tmp_out), out_path)
        return {"seconds": round(time.time() - t0, 1), "size": os.path.getsize(out_path), "log_tail": tail}
