"""مكتبة الخامات المفتوحة: تنزيل خامات PBR بدقة 1K من مصادر ترخيصها CC0 فقط (Poly Haven، ambientCG).

القواعد الصارمة (لا تُخفَّف):
  * الدقة 1K فقط (`RESOLUTION`).
  * لا يُقبل أصل إلا إذا كان المصدر معلناً CC0 ولم تذكر بياناته الوصفية ترخيصاً آخر.
  * كل عنوان (بما فيه إعادات التوجيه) يجب أن يكون https على مضيف ضمن القائمة المسموحة.
  * معرّفات الأصول تُفحص بنمط صارم (لا مسارات)، وأسماء الملفات تُبنى محلياً ولا تؤخذ من الخادم.
  * حدود حجم لكل ملف ولمحتوى الـ zip، والصور تُفحص بفك الترميز ويُرفض الأكبر من 2048 بكسل.
تُحفظ الخامات في كاش دائم ومعها `source.json` (المصدر، الترخيص، المؤلفون، التاريخ) لملف الشكر في التصدير.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

import cv2
import httpx
import numpy as np

RESOLUTION = "1k"
LICENSE_ID = "CC0-1.0"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
CC0_NAMES = {"cc0", "cc0-1.0", "cc0 1.0", "cc0 1.0 universal", "public domain cc0", "creative commons cc0", "cc-0"}
UA = "TerrainForge/0.2 (+https://github.com/ahmedfadul-sys/world-studio)"
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_ZIP_UNPACKED = 160 * 1024 * 1024
MAX_SIDE_PX = 2048
ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
DEFAULT_HOSTS = ("polyhaven.com", "polyhaven.org", "ambientcg.com", "struffelproductions.com", "backblazeb2.com")
MAPS = ("diff", "rough", "nor_gl", "disp")      # أسماء الملفات المحلية = ما يكتشفه import_build.py


class TexError(Exception):
    """خطأ مفهوم للمستخدم (ترخيص، شبكة، ملف غير صالح)."""


def data_root() -> Path:
    d = os.environ.get("TERRAIN_DATA_DIR")
    p = Path(d) if d else Path.home() / ".terrainforge"
    p = p / "textures"
    p.mkdir(parents=True, exist_ok=True)
    return p


def allowed_hosts() -> tuple:
    extra = os.environ.get("TERRAIN_TEXTURE_HOSTS", "")
    return DEFAULT_HOSTS + tuple(h.strip().lower() for h in extra.split(",") if h.strip())


def host_ok(url: str) -> bool:
    u = urlparse(url)
    h = (u.hostname or "").lower()
    return u.scheme == "https" and any(h == a or h.endswith("." + a) for a in allowed_hosts())


def is_cc0(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in CC0_NAMES


def check_id(asset_id: str) -> str:
    if not isinstance(asset_id, str) or not ID_RE.fullmatch(asset_id):
        raise TexError("معرّف الخامة غير صالح")
    return asset_id


def make_client() -> httpx.Client:
    """يُستبدل في الاختبارات. لا يتبع إعادة التوجيه تلقائياً: نفحص كل قفزة بأنفسنا."""
    return httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": UA}, follow_redirects=False)


def _get(client: httpx.Client, url: str, *, binary: bool = False, limit: int = MAX_FILE_BYTES):
    for _ in range(6):
        if not host_ok(url):
            raise TexError(f"مضيف غير مسموح أو غير آمن: {urlparse(url).hostname}")
        try:
            r = client.get(url)
        except httpx.HTTPError as e:
            raise TexError(f"تعذّر الاتصال بالمصدر ({type(e).__name__}). تحقق من الإنترنت.") from e
        if r.status_code in (301, 302, 303, 307, 308):
            nxt = r.headers.get("location")
            if not nxt:
                raise TexError("إعادة توجيه بلا وجهة")
            url = str(httpx.URL(url).join(nxt))
            continue
        if r.status_code == 404:
            raise TexError("الخامة غير موجودة عند المصدر")
        if r.status_code >= 400:
            raise TexError(f"المصدر رفض الطلب (HTTP {r.status_code})")
        if len(r.content) > limit:
            raise TexError("الملف أكبر من الحد المسموح")
        return r.content if binary else r.json()
    raise TexError("إعادات توجيه كثيرة")


def _check_image(data: bytes, what: str) -> None:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise TexError(f"ملف {what} ليس صورة صالحة")
    if max(img.shape[:2]) > MAX_SIDE_PX:
        raise TexError(f"ملف {what} أكبر من 1K فعلياً ({max(img.shape[:2])} بكسل) — رُفض")


def _md5_ok(data: bytes, md5: Optional[str]) -> bool:
    return not md5 or hashlib.md5(data).hexdigest().lower() == str(md5).lower()


@dataclass
class Hit:
    provider: str
    id: str
    name: str
    categories: List[str]
    thumb: Optional[str]
    page: str

    def asdict(self) -> dict:
        return dict(provider=self.provider, id=self.id, name=self.name, categories=self.categories, thumb=self.thumb, page=self.page)


# ───────────────────────────── Poly Haven ─────────────────────────────
class PolyHaven:
    id = "polyhaven"
    title = "Poly Haven"
    credit = "Textures by Poly Haven (polyhaven.com) — CC0"
    api = "https://api.polyhaven.com"
    _list_cache: Optional[tuple] = None             # (وقت، بيانات) — القائمة كبيرة ولا تتغير بسرعة

    def search(self, client, q: str, limit: int) -> List[Hit]:
        now = time.time()
        if PolyHaven._list_cache is None or now - PolyHaven._list_cache[0] > 600:
            PolyHaven._list_cache = (now, _get(client, f"{self.api}/assets?type=textures"))
        data = PolyHaven._list_cache[1]
        words = [w for w in re.split(r"[\s,]+", q.lower()) if w]
        out = []
        for aid, a in data.items():
            if not ID_RE.fullmatch(aid):
                continue
            hay = " ".join([aid, str(a.get("name", "")), " ".join(a.get("categories", []) or []), " ".join(a.get("tags", []) or [])]).lower()
            if all(w in hay for w in words):
                out.append(Hit(self.id, aid, a.get("name") or aid, list(a.get("categories", []) or []),
                               f"https://cdn.polyhaven.com/asset_img/thumbs/{quote(aid)}.png?width=256&height=256", f"https://polyhaven.com/a/{aid}"))
        out.sort(key=lambda h: (not all(w in h.id.lower() for w in words), h.id))
        return out[:limit]

    def fetch(self, client, aid: str, dest: Path) -> dict:
        info = _get(client, f"{self.api}/info/{quote(aid)}")
        lic = info.get("license") if isinstance(info, dict) else None
        if lic is not None and not is_cc0(lic):
            raise TexError(f"الترخيص المعلن ({lic}) ليس CC0 — رُفضت الخامة")
        files = _get(client, f"{self.api}/files/{quote(aid)}")
        want = {"diff": ("Diffuse", ("jpg", "png")), "rough": ("Rough", ("jpg", "png")),
                "nor_gl": ("nor_gl", ("png", "jpg")), "disp": ("Displacement", ("jpg", "png"))}
        saved = {}
        for local, (key, fmts) in want.items():
            node = (files.get(key) or {}).get(RESOLUTION) or {}
            f = next((node[x] for x in fmts if isinstance(node.get(x), dict) and node[x].get("url")), None)
            fmt = next((x for x in fmts if isinstance(node.get(x), dict) and node[x].get("url")), None)
            if not f:
                continue
            data = _get(client, f["url"], binary=True)
            if not _md5_ok(data, f.get("md5")):
                raise TexError(f"فشل التحقق من سلامة {key} (md5)")
            _check_image(data, key)
            name = f"{aid}_{local}_{RESOLUTION}.{fmt}"
            (dest / name).write_bytes(data)
            saved[local] = name
        if "diff" not in saved:
            raise TexError("لا تتوفر خريطة اللون بدقة 1K لهذه الخامة")
        authors = list((info.get("authors") or {}).keys()) if isinstance(info.get("authors"), dict) else []
        return dict(name=info.get("name") or aid, authors=authors, files=saved, source_url=f"https://polyhaven.com/a/{aid}")


# ───────────────────────────── ambientCG ─────────────────────────────
class AmbientCG:
    id = "ambientcg"
    title = "ambientCG"
    credit = "Textures by ambientCG (ambientcg.com) — CC0"
    api = "https://ambientcg.com/api/v2/full_json"
    _suffix = {"diff": ("_color",), "rough": ("_roughness",), "nor_gl": ("_normalgl",), "disp": ("_displacement",)}

    def _items(self, client, params: str) -> list:
        j = _get(client, f"{self.api}?{params}")
        return j.get("foundAssets") or []

    def search(self, client, q: str, limit: int) -> List[Hit]:
        items = self._items(client, f"type=Material&q={quote(q)}&limit={int(limit)}&include=displayData,tagData,previewData")
        out = []
        for a in items:
            aid = a.get("assetId")
            if not (isinstance(aid, str) and ID_RE.fullmatch(aid)):
                continue
            prev = a.get("previewImage") or {}
            thumb = next((v for k, v in prev.items() if isinstance(v, str) and v.startswith("https://")), None) if isinstance(prev, dict) else None
            out.append(Hit(self.id, aid, a.get("displayName") or aid, list(a.get("tags", []) or [])[:6], thumb, f"https://ambientcg.com/view?id={aid}"))
        return out

    def fetch(self, client, aid: str, dest: Path) -> dict:
        items = self._items(client, f"type=Material&id={quote(aid)}&include=downloadData,displayData")
        a = next((x for x in items if x.get("assetId") == aid), None)
        if not a:
            raise TexError("الخامة غير موجودة عند المصدر")
        lic = a.get("license") or a.get("licenseName")
        if lic is not None and not is_cc0(lic):
            raise TexError(f"الترخيص المعلن ({lic}) ليس CC0 — رُفضت الخامة")
        dls = []
        try:
            for folder in (a.get("downloadFolders") or {}).values():
                for cat in (folder.get("downloadFiletypeCategories") or {}).values():
                    dls += cat.get("downloads") or []
        except AttributeError:
            pass
        d = next((x for x in dls if str(x.get("attribute", "")).upper() == "1K-JPG" and x.get("downloadLink")), None)
        if not d:
            raise TexError("لا توجد حزمة 1K-JPG لهذه الخامة")
        blob = _get(client, d["downloadLink"], binary=True)
        try:
            zf = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as e:
            raise TexError("حزمة التنزيل ليست zip صالحة") from e
        if sum(i.file_size for i in zf.infolist()) > MAX_ZIP_UNPACKED:
            raise TexError("محتوى الحزمة أكبر من الحد المسموح")
        saved = {}
        for local, sufs in self._suffix.items():
            for info in zf.infolist():
                base = os.path.basename(info.filename)               # لا مسارات من الخادم أبداً
                stem, ext = os.path.splitext(base)
                if ext.lower() not in (".jpg", ".jpeg", ".png") or not any(stem.lower().endswith(s) for s in sufs):
                    continue
                data = zf.read(info)
                _check_image(data, base)
                name = f"{aid}_{local}_{RESOLUTION}{ext.lower()}"
                (dest / name).write_bytes(data)
                saved[local] = name
                break
        if "diff" not in saved:
            raise TexError("لم أجد خريطة اللون داخل الحزمة")
        return dict(name=a.get("displayName") or aid, authors=["ambientCG"], files=saved, source_url=f"https://ambientcg.com/view?id={aid}")


PROVIDERS: Dict[str, object] = {p.id: p for p in (PolyHaven(), AmbientCG())}
_locks: Dict[str, threading.Lock] = {}


def provider(pid: str):
    p = PROVIDERS.get(pid)
    if p is None:
        raise TexError("مصدر غير معروف (المتاح: " + ", ".join(PROVIDERS) + ")")
    return p


def search(pid: str, q: str, limit: int = 24) -> List[dict]:
    p = provider(pid)
    with make_client() as c:
        return [h.asdict() for h in p.search(c, (q or "").strip(), max(1, min(int(limit), 60)))]


def pack_dir(pid: str, aid: str) -> Path:
    provider(pid)
    return data_root() / pid / check_id(aid)


def fetch(pid: str, aid: str) -> dict:
    """ينزّل الخامة (1K) إلى الكاش إن لم تكن موجودة، ويعيد وصفها. آمن للاستدعاء المتكرر."""
    p = provider(pid)
    check_id(aid)
    dest = pack_dir(pid, aid)
    with _locks.setdefault(f"{pid}/{aid}", threading.Lock()):
        src = dest / "source.json"
        if src.is_file():
            return {**json.loads(src.read_text("utf-8")), "cached": True, "folder": str(dest)}
        tmp = dest.with_name(dest.name + ".part")
        if tmp.exists():
            for f in tmp.iterdir():
                f.unlink()
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            with make_client() as c:
                meta = p.fetch(c, aid, tmp)
            rec = {"provider": pid, "id": aid, "resolution": RESOLUTION, "license": LICENSE_ID, "license_url": LICENSE_URL,
                   "credit": p.credit, "fetched_at": time.strftime("%Y-%m-%d"), **meta}
            (tmp / "source.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), "utf-8")
            if dest.exists():
                for f in dest.iterdir():
                    f.unlink()
                dest.rmdir()
            tmp.rename(dest)
        except Exception:
            for f in tmp.iterdir():
                f.unlink()
            tmp.rmdir()
            raise
        return {**rec, "cached": False, "folder": str(dest)}


def cached() -> List[dict]:
    out = []
    for src in sorted(data_root().glob("*/*/source.json")):
        try:
            out.append({**json.loads(src.read_text("utf-8")), "folder": str(src.parent)})
        except (OSError, ValueError):
            continue
    return out


REF_RE = re.compile(r"^cc0:([a-z0-9]+)/([A-Za-z0-9_\-]{1,80})$")


def make_ref(pid: str, aid: str) -> str:
    """مرجع قابل للنقل بين الأجهزة يُحفظ في المشروع بدل المسار المحلي المطلق."""
    return f"cc0:{provider(pid).id}/{check_id(aid)}"


def resolve_pack(pack: Optional[str]) -> Optional[str]:
    """`cc0:<مصدر>/<معرّف>` ← مجلد الكاش إن كان منزَّلاً (وإلا يبقى المرجع كما هو فلا يوجد مجلد وتسقط المادة إلى لونها). غير ذلك يعود كما هو."""
    if not pack:
        return pack
    m = REF_RE.match(pack)
    if not m or m.group(1) not in PROVIDERS:
        return pack
    d = pack_dir(m.group(1), m.group(2))
    return str(d) if (d / "source.json").is_file() else pack


def ensure(refs) -> List[dict]:
    """ينزّل الخامات الناقصة لمراجع cc0: (أفضل جهد) ويعيد حالة كل مرجع."""
    out = []
    for ref in dict.fromkeys(r for r in refs if isinstance(r, str)):
        m = REF_RE.match(ref)
        if not m:
            continue
        try:
            r = fetch(m.group(1), m.group(2))
            out.append({"ref": ref, "ok": True, "cached": r.get("cached", False)})
        except TexError as e:
            out.append({"ref": ref, "ok": False, "error": str(e)})
    return out


def is_managed(path: Optional[str]) -> bool:
    """هل المسار مجلد خامة من الكاش (فقط هذه تُنسخ إلى التصدير)؟"""
    if not path:
        return False
    try:
        return Path(path).resolve().parent.parent == data_root().resolve() and (Path(path) / "source.json").is_file()
    except OSError:
        return False


def read_pack(path: str) -> dict:
    d = Path(path)
    rec = json.loads((d / "source.json").read_text("utf-8"))
    return {"record": rec, "files": {n: (d / n).read_bytes() for n in rec["files"].values() if (d / n).is_file()}}


def records_for(packs) -> List[dict]:
    """سجلات المصدر لمجلدات الخامات المُدارة (من الكاش) الواردة في packs؛ غيرها يُتجاهل."""
    out, seen = [], set()
    for p in packs:
        if is_managed(p) and str(Path(p).resolve()) not in seen:
            seen.add(str(Path(p).resolve()))
            out.append(json.loads((Path(p) / "source.json").read_text("utf-8")))
    return out


def credits_text(records: List[dict]) -> str:
    lines = ["TEXTURE CREDITS (all CC0 1.0 — " + LICENSE_URL + ")", ""]
    seen = set()
    for r in records:
        k = (r["provider"], r["id"])
        if k in seen:
            continue
        seen.add(k)
        lines.append(f"- {r.get('name', r['id'])} [{r['provider']}/{r['id']}] — {r.get('source_url', '')} — {', '.join(r.get('authors') or []) or 'n/a'}")
    provs = sorted({r["provider"] for r in records})
    lines += [""] + [PROVIDERS[p].credit for p in provs if p in PROVIDERS]
    return "\n".join(lines) + "\n"
