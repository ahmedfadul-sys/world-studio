"""حفظ الملفات المُصدَّرة في مكان يختاره المستخدم.

الواجهة تعمل داخل نافذة مدمجة لا تُظهر تنزيلات المتصفح، فكان الملف ينزل بصمت ولا يجده المستخدم.
الخادم يعمل على جهاز المستخدم نفسه، لذا يفتح نافذة «حفظ باسم» أصلية ثم يكتب الملف في المسار المختار.
لا يكتب الخادم إلا في مسار اختاره المستخدم بنفسه من النافذة (رمز لمرة واحدة)، فلا تستطيع صفحة أخرى الكتابة في أي مكان.
"""
from __future__ import annotations
import os, re, threading, uuid
from pathlib import Path

_GRANTS: dict[str, Path] = {}
_LOCK = threading.Lock()
FALLBACK_DIR = Path.home() / "Downloads" / "WorldStudio"


def safe_name(name: str) -> str:
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .") or "file"
    return n[:120]


def _dialog(name: str, ext: str) -> str | None:
    """يعيد المسار المختار، أو "" إذا ألغى المستخدم، أو None إذا تعذّر فتح النافذة."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.asksaveasfilename(parent=root, title="حفظ الملف", initialfile=name,
                                         defaultextension=ext, initialdir=str(Path.home() / "Downloads") if (Path.home() / "Downloads").is_dir() else str(Path.home()))
        root.destroy()
        return p or ""
    except Exception:  # noqa: BLE001
        return None


def pick(name: str) -> dict:
    name = safe_name(name)
    ext = Path(name).suffix
    chosen = _dialog(name, ext)
    if chosen == "":
        return {"cancelled": True}
    if chosen is None:                                   # لا توجد نافذة: مجلد ثابت وواضح
        FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        target = FALLBACK_DIR / name
        i = 1
        while target.exists():
            target = FALLBACK_DIR / f"{Path(name).stem}_{i}{ext}"; i += 1
        chosen = str(target)
    tok = uuid.uuid4().hex
    with _LOCK:
        _GRANTS[tok] = Path(chosen)
    return {"token": tok, "path": chosen}


def write(token: str, data: bytes) -> Path:
    with _LOCK:
        p = _GRANTS.pop(token, None)
    if p is None:
        raise KeyError("رمز الحفظ غير صالح أو مستعمل")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p
