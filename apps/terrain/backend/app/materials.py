"""نظام المواد: أوزان مواد لكل بكسل (Splat) من: مادة المنطقة الأساسية -> قواعد الميل/الثلج/الشاطئ -> مواد المعالم.
كل خطوة «over» (مزج فوق ما قبلها) فيبقى مجموع الأوزان = 1 عند كل بكسل. القاع/الوسط/القمة تُحسب من الارتفاع النسبي داخل المعلم."""
from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple
import numpy as np
from .noise import fbm
from .derived import derive
from .terrain import (S, RELIEF, site_sd, nearest_grid, poly_weight_grid)
from . import texlib

BUILTIN = {"grass": "#5c8a3c", "forest_floor": "#3d5a2a", "rock": "#7b7468", "snow": "#f2f5f7", "sand": "#d8c690",
           "mud": "#6b5338", "dirt": "#8b7355", "pavement": "#8a8a8a", "farmland": "#b09a4a", "gravel": "#9a9488"}


def library(project) -> Dict[str, dict]:
    lib = {k: dict(id=k, name=k, color=v, albedo=None, normal=None, roughness=None, height=None, pack=None, roughness_value=0.9, tile_m=10.0, detail_amp_m=None, detail_kind=None) for k, v in BUILTIN.items()}
    for m in project.materials:
        lib[m.id] = dict(id=m.id, name=m.name or m.id, color=m.color, albedo=m.albedo, normal=m.normal, roughness=m.roughness, height=m.height,
                         pack=texlib.resolve_pack(m.pack), roughness_value=m.roughness_value, tile_m=m.tile_m, detail_amp_m=m.detail_amp_m, detail_kind=m.detail_kind)
    return lib


def hex_rgb(c: str) -> Tuple[int, int, int]:
    try:
        return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    except Exception:
        return 128, 128, 128


def zone_density(project, eng, z, Z, xs, ys, slope, free):
    """كثافة منطقة نباتات واحدة (0..1) على الشبكة."""
    X, Y = xs[None, :], ys[:, None]
    n = (fbm(X, Y, 1.0 / 150.0, 3, z.seed + 11) + 1.0) / 2.0
    patch = (1.0 - z.patchiness) + z.patchiness * S(0.25, 0.75, n)
    ok = 1.0 - S(0.8 * z.max_slope_deg, max(z.max_slope_deg, 1e-3), slope) if z.max_slope_deg < 90 else 1.0
    if z.min_elev_m is not None:
        ok = ok * (Z >= z.min_elev_m)
    if z.max_elev_m is not None:
        ok = ok * (Z <= z.max_elev_m)
    return poly_weight_grid(z.polygon, xs, ys, z.falloff_m) * z.density * patch * ok * free


class Painter:
    def __init__(self, shape, base: str):
        self.shape = shape
        self.W: Dict[str, np.ndarray] = {base: np.ones(shape, np.float32)}

    def over(self, a, mix: Dict[str, object], win=None):
        sl = (slice(None), slice(None)) if win is None else (slice(win[0], win[1]), slice(win[2], win[3]))
        for k in self.W:
            self.W[k][sl] *= (1.0 - a)
        for m, wt in mix.items():
            if m not in self.W:
                self.W[m] = np.zeros(self.shape, np.float32)
            self.W[m][sl] += a * wt


def _fill3(low, mid, high):
    """يملأ الخانات الفارغة بأقرب مادة معرّفة."""
    if not (low or mid or high):
        return None
    return (low or mid or high, mid or low or high, high or mid or low)


def paint(project, eng, Z, xs, ys, densities: Dict[str, np.ndarray] = None, derived: Dict[str, np.ndarray] = None):
    """يعيد (Painter، slope)."""
    P = project.paint
    lib = library(project)
    ok = lambda m: m if (m and m in lib) else None
    H, W = Z.shape
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    gy, gx = np.gradient(Z.astype(np.float64), dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    pt = Painter((H, W), ok(P.default_material) or "grass")
    sea = project.world.sea_level_m
    # مناطق (Biomes)
    for i, b in enumerate(project.biomes):
        if ok(b.mat_base):
            bb = eng._bbox(b, xs, ys)
            if bb:
                r0, r1, c0, c1 = bb
                pt.over(eng._w_grid(i, xs[c0:c1], ys[r0:r1]), {b.mat_base: 1.0}, bb)
    # قواعد تلقائية
    if ok(P.slope_material):
        pt.over(S(P.slope_start_deg, max(P.slope_full_deg, P.slope_start_deg + 0.1), slope), {P.slope_material: 1.0})
    if ok(P.snow_material):
        pt.over(S(P.snow_elev_m, P.snow_elev_m + P.snow_blend_m, Z) * (1.0 - S(40.0, 55.0, slope)), {P.snow_material: 1.0})
    if ok(P.beach_material):
        pt.over(1.0 - S(sea + 0.6 * P.beach_height_m, sea + P.beach_height_m, Z), {P.beach_material: 1.0})
    # قواعد من الطبقات المشتقة: صخر على الحواف المحدبة، طين في المنخفضات، مادة رطبة حيث يتجمع الماء
    Dv = project.derived
    if Dv.enabled and any(ok(m) for m in (Dv.convex_material, Dv.hollow_material, Dv.wet_material)):
        dv = derived if derived is not None else derive(Z, dx, dy, Dv)
        if ok(Dv.hollow_material):
            pt.over(dv["curv_concave"] * (1.0 - S(15.0, 30.0, slope)) * Dv.hollow_amount, {Dv.hollow_material: 1.0})
        if ok(Dv.wet_material):
            pt.over(S(Dv.wet_threshold, min(Dv.wet_threshold + 0.2, 1.0), dv["wetness"]) * (1.0 - S(8.0, 20.0, slope)) * Dv.wet_amount, {Dv.wet_material: 1.0})
        if ok(Dv.convex_material):
            pt.over(dv["curv_convex"] * S(Dv.convex_min_slope_deg, Dv.convex_min_slope_deg + 12.0, slope) * Dv.convex_amount, {Dv.convex_material: 1.0})
    # تضاريس نقطية: تدرّج قاع/وسط/قمة حسب الارتفاع النسبي داخل المعلم
    for typ, f in eng.stages:
        if typ != "point":
            continue
        m3 = _fill3(ok(f.mat_low), ok(f.mat_mid), ok(f.mat_high))
        if not m3:
            continue
        R = f.diameter_m / 2
        cols = np.nonzero(np.abs(xs - f.x_m) <= R)[0]; rows = np.nonzero(np.abs(ys - f.y_m) <= R)[0]
        if not (len(cols) and len(rows)):
            continue
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        t = np.hypot(xs[None, c0:c1] - f.x_m, ys[r0:r1, None] - f.y_m) / R
        a = (1.0 - S(0.9, 1.0, t)) * (t < 1.0)
        if f.kind == "dune" or f.high_m <= f.low_m:
            mix = {m3[0]: 1.0}
        else:
            rel = np.clip((Z[r0:r1, c0:c1] - f.low_m) / (f.high_m - f.low_m), 0.0, 1.0)
            wl, wh = 1.0 - S(0.15, 0.45, rel), S(0.55, 0.85, rel)
            mix = {}
            for m, wt in ((m3[0], wl), (m3[1], 1.0 - wl - wh), (m3[2], wh)):
                mix[m] = mix.get(m, 0.0) + wt
        pt.over(a, mix, (r0, r1, c0, c1))
    # مناطق النباتات/التفاصيل
    for z in project.zones:
        if ok(z.mat_main):
            d = (densities or {}).get(z.id)
            if d is None:
                d = poly_weight_grid(z.polygon, xs, ys, z.falloff_m) * z.density
            pt.over(d, {z.mat_main: 1.0})
    # خطوط
    for i, (typ, f) in enumerate(eng.stages):
        if typ != "line" or not (ok(f.mat_main) or ok(f.mat_edge)):
            continue
        path, d = eng._path(f), eng._design(i)
        if path is None or d is None:
            continue
        edge = f.shoulder_m if f.kind == "road" else (max(3.0, 0.5 * f.width_m) if f.kind == "river" else 0.0)
        reach = max(f.width_m, f.width_end_m or f.width_m) / 2 + edge + 1.0
        dist, sv, _ = nearest_grid(path, xs, ys, reach)
        fr = np.clip(sv / max(d["L"], 1e-9), 0, 1)
        hw = (f.width_m + (( f.width_end_m or f.width_m) - f.width_m) * fr) / 2
        if ok(f.mat_edge) and edge > 0:
            pt.over(1.0 - S(hw, hw + edge, dist), {f.mat_edge: 1.0})
        if ok(f.mat_main):
            pt.over(1.0 - S(0.6 * hw, np.maximum(hw, 0.61 * hw + 1e-3), dist), {f.mat_main: 1.0})
    # مواقع
    for typ, s in eng.stages:
        if typ == "pad" and ok(s.mat_ground):
            ext = (s.diameter_m / 2 if s.shape == "circle" else math.hypot(s.width_m, s.length_m) / 2) + s.blend_m
            cols = np.nonzero(np.abs(xs - s.x_m) <= ext)[0]; rows = np.nonzero(np.abs(ys - s.y_m) <= ext)[0]
            if len(cols) and len(rows):
                r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                pt.over(1.0 - S(0.0, s.blend_m * 0.6, site_sd(s, xs[None, c0:c1], ys[r0:r1, None])), {s.mat_ground: 1.0}, (r0, r1, c0, c1))
    return pt, slope


def colors_rgb(project, pt: Painter) -> np.ndarray:
    lib = library(project)
    out = np.zeros(pt.shape + (3,), np.float32)
    for k, w in pt.W.items():
        out += w[..., None] * np.asarray(hex_rgb(lib[k]["color"] if k in lib else "#808080"), np.float32)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def pack_splats(project, pt: Painter, min_weight: float = 0.004) -> Tuple[List[np.ndarray], List[dict]]:
    """أقنعة توزيع: كل صورة RGBA تحمل 4 مواد (R,G,B,A). يعيد (صور BGRA لـ cv2، قائمة المواد المستعملة)."""
    lib = library(project)
    used = [k for k, w in pt.W.items() if float(w.max()) > min_weight][:16]
    imgs, info = [], []
    for si in range(0, len(used), 4):
        grp = used[si:si + 4]
        arr = np.zeros(pt.shape + (4,), np.uint8)
        for ch, k in enumerate(grp):
            arr[..., [2, 1, 0, 3][ch]] = np.clip(pt.W[k] * 255 + 0.5, 0, 255).astype(np.uint8)   # BGRA: R=قناة0
            m = lib.get(k, dict(id=k, name=k, color="#808080", albedo=None, normal=None, roughness=None, height=None, pack=None, roughness_value=0.9, tile_m=10.0, detail_amp_m=None, detail_kind=None))
            info.append(dict(m, splat=f"masks/splat_{si // 4}.png", channel="RGBA"[ch]))
        imgs.append(arr)
    return imgs, info
