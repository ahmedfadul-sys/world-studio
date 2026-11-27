"""تصدير العالم كملف glTF ثنائي (.glb) جاهز للفتح في Blender وGodot وUnity وأي عارض 3D — بلا أي اعتماد على Blender.

المحتوى: شبكة التضاريس (مع UV وNormals)، خامة PBR واحدة «مخبوزة» من مزج خامات المواد بحسب خريطة التوزيع (Splat)،
سطح البحر والبحيرات كأسطح مائية شفافة، وعقد فارغة (Empties) للمنشآت ونقاط الاهتمام مع بياناتها في extras.

المحاور: عالم الأداة (x شرق، y شمال، z أعلى) ← glTF (X = x، Y = z، Z = -y)، الوحدة متر.
قيود معروفة: الخامة المخبوزة بدقة محدودة (texel = حجم العالم / دقة الخامة) فتُرشَّح الخامات المتكررة تلقائياً كي لا تتشوّش؛
للجودة الكاملة (خامات حقيقية بإسقاط ثلاثي المحاور، فصل الأقنعة) استعمل تصدير .blend.
"""
from __future__ import annotations

import json
import math
import os
import struct
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .materials import library, paint, hex_rgb
from .terrain import engine_for, grid_axes

MAX_GLB_RES = 2049
GAMMA = 2.2
_ALBEDO_KEYS = ("_color", "_diff", "albedo", "basecolor", "base_color")
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")


def find_albedo(mat: dict) -> Optional[str]:
    """مسار صورة اللون لمادة: المسار الصريح ثم اكتشاف داخل مجلد الحزمة (نفس قواعد import_build.py)."""
    a = mat.get("albedo")
    if a and os.path.isfile(a):
        return a
    d = mat.get("pack")
    if d and os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            stem, ext = os.path.splitext(f.lower())
            if ext in _IMG_EXT and any(k in stem for k in _ALBEDO_KEYS):
                return os.path.join(d, f)
    return None


def _prefilter(img: np.ndarray, tile_m: float, texel_m: float) -> np.ndarray:
    """يصغّر الخامة بحيث يساوي حجمها بالبكسل عدد texels التي تغطي طول تكرارها (مرشّح مساحة ≈ mipmap) فلا يحدث aliasing."""
    n = int(np.clip(round(tile_m / max(texel_m, 1e-6)), 1, max(img.shape[:2])))
    if n >= max(img.shape[:2]):
        return img
    return cv2.resize(img, (n, n), interpolation=cv2.INTER_AREA)


def bake_albedo(project, pt, xs, ys, tex_px: int, progress: Callable[[float], None] = lambda f: None, region=None) -> Tuple[np.ndarray, dict]:
    """يمزج لون كل مادة (لون ثابت أو صورة متكررة كل tile_m متر) بوزنها عند كل texel. يعيد (RGB uint8، تقرير)."""
    w = project.world
    x0, y0, x1, y1 = region if region else (0.0, 0.0, w.size_x_m, w.size_y_m)
    Lx, Ly = x1 - x0, y1 - y0
    tw, th = (tex_px, max(2, int(round(tex_px * Ly / Lx)))) if Lx >= Ly else (max(2, int(round(tex_px * Lx / Ly))), tex_px)
    mx, my = Lx / tw, Ly / th
    lib = library(project)
    ny, nx = pt.shape
    mats = []
    report = {"textured": [], "color_only": []}
    for k in pt.W:
        m = lib.get(k) or {"id": k, "color": "#808080", "tile_m": 10.0, "albedo": None, "pack": None}
        path = find_albedo(m)
        img = cv2.imread(path, cv2.IMREAD_COLOR) if path else None
        if img is not None:
            img = _prefilter(img[:, :, ::-1], float(m.get("tile_m") or 10.0), max(mx, my))
            tex = (img.astype(np.float32) / 255.0) ** GAMMA
            report["textured"].append(k)
        else:
            tex = None
            report["color_only"].append(k)
        col = (np.asarray(hex_rgb(m.get("color") or "#808080"), np.float32) / 255.0) ** GAMMA
        mats.append((k, tex, col, float(m.get("tile_m") or 10.0)))
    out = np.empty((th, tw, 3), np.uint8)
    band = max(16, min(256, int(4_000_000 // max(tw, 1))))
    cols = x0 + (np.arange(tw, dtype=np.float64) + 0.5) * mx
    for r0 in range(0, th, band):
        r1 = min(th, r0 + band)
        Y = y1 - (np.arange(r0, r1, dtype=np.float64) + 0.5) * my
        X = np.broadcast_to(cols[None, :], (r1 - r0, tw))
        Yg = np.broadcast_to(Y[:, None], (r1 - r0, tw))
        gx = ((X - x0) / Lx * (nx - 1)).astype(np.float32)
        gy = ((y1 - Yg) / Ly * (ny - 1)).astype(np.float32)
        acc = np.zeros((r1 - r0, tw, 3), np.float32)
        tot = np.zeros((r1 - r0, tw), np.float32)
        for k, tex, col, tile in mats:
            wk = cv2.remap(pt.W[k].astype(np.float32), gx, gy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            if not wk.any():
                continue
            if tex is None:
                c = np.broadcast_to(col, acc.shape)
            else:
                h, ww = tex.shape[:2]
                u = ((X / tile) % 1.0 * ww).astype(np.float32)
                v = (((w.size_y_m - Yg) / tile) % 1.0 * h).astype(np.float32)
                c = cv2.remap(tex, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
            acc += c * wk[..., None]
            tot += wk
        acc /= np.maximum(tot, 1e-6)[..., None]
        out[r0:r1] = np.clip(acc ** (1.0 / GAMMA) * 255.0 + 0.5, 0, 255).astype(np.uint8)
        progress(r1 / th)
    return out, {"texture_px": [tw, th], "texel_m": [round(mx, 3), round(my, 3)], **report}


# ───────────────────────────── glTF ثنائي ─────────────────────────────
class _Builder:
    def __init__(self):
        self.bin = bytearray()
        self.views: List[dict] = []
        self.accessors: List[dict] = []

    def view(self, data: bytes, target: Optional[int] = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        v = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target:
            v["target"] = target
        self.bin += data
        self.views.append(v)
        return len(self.views) - 1

    def accessor(self, arr: np.ndarray, ctype: int, kind: str, target: Optional[int] = None, minmax: bool = False) -> int:
        a = {"bufferView": self.view(arr.tobytes(), target), "componentType": ctype, "count": int(arr.shape[0]), "type": kind}
        if minmax:
            a["min"], a["max"] = [float(x) for x in arr.min(0)], [float(x) for x in arr.max(0)]
        self.accessors.append(a)
        return len(self.accessors) - 1


def _grid_indices(ny: int, nx: int) -> np.ndarray:
    """مثلثان لكل خلية، ترتيب CCW كما يُرى من الأعلى (الوجه الأمامي نحو +Y)."""
    r, c = np.meshgrid(np.arange(ny - 1, dtype=np.uint32), np.arange(nx - 1, dtype=np.uint32), indexing="ij")
    i = (r * nx + c).ravel()
    return np.stack([i, i + nx, i + 1, i + 1, i + nx, i + nx + 1], axis=1).astype(np.uint32).ravel()


def _terrain_arrays(Z: np.ndarray, xs: np.ndarray, ys: np.ndarray):
    ny, nx = Z.shape
    zf = Z.astype(np.float32)
    X = np.broadcast_to(xs.astype(np.float32)[None, :], (ny, nx))
    Y = np.broadcast_to(ys.astype(np.float32)[:, None], (ny, nx))
    pos = np.stack([X, zf, -Y], axis=-1).reshape(-1, 3).astype(np.float32)
    dzdx = np.gradient(Z.astype(np.float64), xs, axis=1)
    dzdy = np.gradient(Z.astype(np.float64), ys, axis=0)               # مشتقة باتجاه الشمال (الإحداثيات تتناقص مع الصف)
    n = np.stack([-dzdx, np.ones_like(dzdx), dzdy], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    cc, rr = np.meshgrid(np.arange(nx, dtype=np.float32) / (nx - 1), np.arange(ny, dtype=np.float32) / (ny - 1))
    uv = np.stack([cc, rr], axis=-1).reshape(-1, 2).astype(np.float32)   # صف 0 = شمال = أعلى الصورة (v يُقاس من الأعلى في glTF)
    return pos, n.reshape(-1, 3).astype(np.float32), uv


def _disc(cx: float, cy: float, z: float, R: float, n: int = 48):
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([cx + R * np.cos(ang), np.full(n, z), -(cy + R * np.sin(ang))], axis=1)
    pos = np.vstack([[cx, z, -cy], ring]).astype(np.float32)
    idx = np.array([[0, 1 + (i + 1) % n, 1 + i] for i in range(n)], np.uint32)     # CCW من الأعلى
    return pos, idx.ravel()


def _in_poly(px, py, P):
    """اختبار نقطة داخل مضلع (شعاع أفقي) لمصفوفة نقاط."""
    inside = np.zeros(px.shape, bool)
    x, y = P[:, 0], P[:, 1]
    j = len(P) - 1
    for i in range(len(P)):
        cond = ((y[i] > py) != (y[j] > py)) & (px < (x[j] - x[i]) * (py - y[i]) / (y[j] - y[i] + 1e-12) + x[i])
        inside ^= cond
        j = i
    return inside


def _pack(gltf: dict, bin_: bytes) -> bytes:
    js = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    bin_ = bytes(bin_) + b"\0" * (-len(bin_) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_)
    return b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(bin_), b"BIN\0") + bin_


def build_glb(project, resolution: int = 1025, tex_px: int = 2048, jpeg_quality: int = 90,
              progress: Callable[[str, float], None] = lambda s, f: None, region=None, clip_poly=None, collision=False) -> Tuple[bytes, dict]:
    """يبني الملف. يعيد (bytes، تقرير: عدد الرؤوس/المثلثات، تقرير الخبز، الاعتمادات)."""
    from . import texlib
    resolution = int(min(max(resolution, 65), MAX_GLB_RES))
    w = project.world
    progress("الارتفاعات", 0.0)
    eng = engine_for(project, resolution)
    if region:                                               # مرحلة = مستطيل من العالم: الإحداثيات تبقى مطلقة داخل الحساب وتُزاح عند الكتابة
        rx0, ry0, rx1, ry1 = region
        gx_, gy_ = grid_axes(rx1 - rx0, ry1 - ry0, resolution)
        xs, ys = gx_ + rx0, gy_ + ry0
    else:
        rx0 = ry0 = 0.0; rx1, ry1 = w.size_x_m, w.size_y_m
        xs, ys = grid_axes(w.size_x_m, w.size_y_m, resolution)
    Z = eng.grid(xs, ys)
    progress("المواد", 0.25)
    pt, _ = paint(project, eng, Z, xs, ys)
    progress("خبز الخامة", 0.4)
    img, bake = bake_albedo(project, pt, xs, ys, tex_px, lambda f: progress("خبز الخامة", 0.4 + 0.4 * f), region=(rx0, ry0, rx1, ry1))
    ok, jpg = cv2.imencode(".jpg", img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
    if not ok:
        raise RuntimeError("فشل ترميز JPEG")
    progress("الشبكة", 0.85)
    pos, nrm, uv = _terrain_arrays(Z, xs - rx0, ys - ry0)
    idx = _grid_indices(*Z.shape)
    if clip_poly is not None and len(clip_poly) >= 3:        # مرحلة بحدود حرّة (إحداثيات العالم): تُحذف الخلايا التي مركزها خارج المضلع
        cx = (xs[:-1] + xs[1:]) / 2; cy = (ys[:-1] + ys[1:]) / 2
        CX, CY = np.meshgrid(cx, cy)
        inside = _in_poly(CX.ravel(), CY.ravel(), np.asarray(clip_poly, float))
        idx = idx.reshape(-1, 6)[inside].ravel()
        if idx.size == 0:
            raise ValueError("حدود المرحلة لا تحتوي أي خلية من التضاريس")
    b = _Builder()
    A_POS = b.accessor(pos, 5126, "VEC3", 34962, minmax=True)
    A_NRM = b.accessor(nrm, 5126, "VEC3", 34962)
    A_UV = b.accessor(uv, 5126, "VEC2", 34962)
    A_IDX = b.accessor(idx.reshape(-1, 1), 5125, "SCALAR", 34963)
    img_view = b.view(jpg.tobytes())
    meshes = [{"name": "Terrain-col" if collision else "Terrain", "primitives": [{"attributes": {"POSITION": A_POS, "NORMAL": A_NRM, "TEXCOORD_0": A_UV}, "indices": A_IDX, "material": 0}]}]
    materials = [{"name": "TF_Terrain", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 0.95}},
                 {"name": "TF_Water", "alphaMode": "BLEND", "doubleSided": True,
                  "pbrMetallicRoughness": {"baseColorFactor": [0.06, 0.25, 0.42, 0.72], "metallicFactor": 0.0, "roughnessFactor": 0.08}}]
    nodes = [{"name": "Terrain-col" if collision else "Terrain", "mesh": 0}]
    sea = w.sea_level_m
    RW, RH = rx1 - rx0, ry1 - ry0
    sq = np.array([[0, sea, 0], [RW, sea, 0], [RW, sea, -RH], [0, sea, -RH]], np.float32)
    sidx = np.array([0, 1, 2, 0, 2, 3], np.uint32)
    meshes.append({"name": "Sea", "primitives": [{"attributes": {"POSITION": b.accessor(sq, 5126, "VEC3", 34962, minmax=True)}, "indices": b.accessor(sidx.reshape(-1, 1), 5125, "SCALAR", 34963), "material": 1}]})
    nodes.append({"name": "Sea", "mesh": 1})
    lakes = [f for f in project.points if f.kind == "lake" and rx0 <= f.x_m <= rx1 and ry0 <= f.y_m <= ry1]
    if lakes:
        P, I, off = [], [], 0
        for f in lakes:
            p, i = _disc(f.x_m - rx0, f.y_m - ry0, f.high_m, f.diameter_m / 2)
            P.append(p); I.append(i + off); off += len(p)
        lp, li = np.vstack(P), np.concatenate(I).astype(np.uint32)
        meshes.append({"name": "Lakes", "primitives": [{"attributes": {"POSITION": b.accessor(lp, 5126, "VEC3", 34962, minmax=True)}, "indices": b.accessor(li.reshape(-1, 1), 5125, "SCALAR", 34963), "material": 1}]})
        nodes.append({"name": "Lakes", "mesh": len(meshes) - 1})
    rib = [r for r in eng.river_ribbons() if len(r["x"]) >= 2]
    if rib:                                                  # أنهار: شريط ماء على طول المجرى
        P, I, off = [], [], 0
        for r in rib:
            x, y, z, wd = r["x"], r["y"], r["z"], r["width"]
            if region:
                keep = (x >= rx0) & (x <= rx1) & (y >= ry0) & (y <= ry1)
                if keep.sum() < 2: continue
                x, y, z, wd = x[keep] - rx0, y[keep] - ry0, z[keep], wd[keep]
            tx, ty = np.gradient(x), np.gradient(y)
            n = np.hypot(tx, ty); n[n < 1e-9] = 1.0
            nx_, ny_ = -ty / n, tx / n
            L = np.stack([x + nx_ * wd / 2, z, -(y + ny_ * wd / 2)], axis=1)
            R = np.stack([x - nx_ * wd / 2, z, -(y - ny_ * wd / 2)], axis=1)
            m = len(x)
            P.append(np.vstack([L, R]).astype(np.float32))
            q = []
            for k in range(m - 1):
                q += [off + k, off + m + k + 1, off + m + k, off + k, off + k + 1, off + m + k + 1]   # CCW من الأعلى (المادة ثنائية الوجه على أي حال)
            I.append(np.array(q, np.uint32)); off += 2 * m
        rp, ri = np.vstack(P), np.concatenate(I).astype(np.uint32)
        meshes.append({"name": "Rivers", "primitives": [{"attributes": {"POSITION": b.accessor(rp, 5126, "VEC3", 34962, minmax=True)}, "indices": b.accessor(ri.reshape(-1, 1), 5125, "SCALAR", 34963), "material": 1}]})
        nodes.append({"name": "Rivers", "mesh": len(meshes) - 1})
    markers = []
    mrep = []
    for s in project.sites:
        if not (rx0 <= s.x_m <= rx1 and ry0 <= s.y_m <= ry1): continue
        z = float(eng.points([s.x_m], [s.y_m])[0])
        mrep.append({"type": "site", "kind": s.kind, "id": s.id, "name": s.name or s.id, "x": s.x_m - rx0, "y": s.y_m - ry0, "z": z, "radius_m": 0.0, "difficulty": 0, "wx": s.x_m, "wy": s.y_m})
        markers.append({"name": f"site_{s.id}", "translation": [s.x_m - rx0, z, -(s.y_m - ry0)], "extras": {"type": "site", "id": s.id, "kind": s.kind, "name": s.name or s.id}})
    for p in project.pois:
        if not (rx0 <= p.x_m <= rx1 and ry0 <= p.y_m <= ry1): continue
        z = float(eng.points([p.x_m], [p.y_m])[0])
        mrep.append({"type": "poi", "kind": p.kind, "id": p.id, "name": p.name or p.id, "x": p.x_m - rx0, "y": p.y_m - ry0, "z": z, "radius_m": p.radius_m, "difficulty": p.difficulty, "level_min": p.level_min, "level_max": p.level_max, "wx": p.x_m, "wy": p.y_m})
        markers.append({"name": f"poi_{p.id}", "translation": [p.x_m - rx0, z, -(p.y_m - ry0)], "extras": {"type": "poi", "id": p.id, "kind": p.kind, "name": p.name or p.id, "radius_m": p.radius_m}})
    children = list(range(len(nodes)))
    if markers:
        first = len(nodes)
        nodes += markers
        nodes.append({"name": "Markers", "children": list(range(first, first + len(markers)))})
        children.append(len(nodes) - 1)
    nodes.append({"name": project.name or "World", "children": children})
    used = texlib.records_for([texlib.resolve_pack(m.pack) for m in project.materials])
    gltf = {"asset": {"version": "2.0", "generator": "TerrainForge", "copyright": "Textures CC0 — see extras.credits" if used else "Generated by TerrainForge",
                      "extras": {"credits": texlib.credits_text(used) if used else "", "units": "meter", "axes": "glTF Y-up: X = east, Y = elevation, -Z = north",
                                 "world_size_m": [RW, RH], "region_origin_m": [rx0, ry0], "sea_level_m": sea, "z_min_m": float(Z.min()), "z_max_m": float(Z.max())}},
            "scene": 0, "scenes": [{"nodes": [len(nodes) - 1]}], "nodes": nodes, "meshes": meshes, "materials": materials,
            "textures": [{"source": 0, "sampler": 0}], "images": [{"bufferView": img_view, "mimeType": "image/jpeg"}],
            "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
            "bufferViews": b.views, "accessors": b.accessors, "buffers": [{"byteLength": len(b.bin) + (-len(b.bin) % 4)}]}
    data = _pack(gltf, bytes(b.bin))
    progress("تم", 1.0)
    return data, {"vertices": int(len(pos)), "triangles": int(len(idx) // 3), "grid": [int(Z.shape[1]), int(Z.shape[0])], "bytes": len(data), "bake": bake,
                  "markers": mrep, "textures_used": [f"{r['provider']}/{r['id']}" for r in used]}
