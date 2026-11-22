"""خرائط الماء من الارتفاعات وبيانات الأنهار والبحيرات: عمق، شاطئ، رغوة، واتجاه/سرعة التدفق.

كلها بدقة الأقنعة وصف 0 = الشمال. تُستعمل في Blender لظلال ماء (امتصاص بالعمق، رغوة عند الشاطئ والمنحدرات، تموّج يتبع التدفق)
وتصلح لأي محرك (قناة عمق 16 بت، شاطئ/رغوة 8 بت، تدفق RGB).
"""
from __future__ import annotations
import math
from typing import Dict, List

import cv2
import numpy as np
from scipy import ndimage as ndi

NEG = -1e9


def _smooth(a, lo, hi):
    t = np.clip((a - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _to_px(x, y, x0, y_top, dx, dy):
    return np.stack([(np.asarray(x) - x0) / dx, (y_top - np.asarray(y)) / dy], -1)


def _densify(pl, wz, wid, step):
    """يعيد أخذ العينات على الخط بخطوة ≈ بكسل مع استيفاء خطي للمنسوب والعرض (وإلا صار سطح الماء درجات على نهر منحدر)."""
    P = np.asarray([p[:2] for p in pl], np.float64)
    seg = np.hypot(*(P[1:] - P[:-1]).T)
    t = np.concatenate([[0.0], np.cumsum(seg)])
    if t[-1] < 1e-9:
        return pl, list(wz), list(wid)
    u = np.arange(0.0, t[-1], step)
    u = np.append(u, t[-1])
    xs_, ys_ = np.interp(u, t, P[:, 0]), np.interp(u, t, P[:, 1])
    return list(zip(xs_, ys_)), list(np.interp(u, t, wz)), list(np.interp(u, t, wid))


def _segment_quads(pl, widths, min_half):
    """رباعيات لكل مقطع من خط: (4 نقاط بالمتر، اتجاه الوحدة)."""
    out = []
    for i in range(len(pl) - 1):
        (x1, y1), (x2, y2) = pl[i][:2], pl[i + 1][:2]
        dxm, dym = x2 - x1, y2 - y1
        L = math.hypot(dxm, dym)
        if L < 1e-6:
            continue
        tx, ty = dxm / L, dym / L
        nx, ny = -ty, tx
        h1, h2 = max(widths[i] / 2.0, min_half), max(widths[i + 1] / 2.0, min_half)
        out.append((np.array([[x1 + nx * h1, y1 + ny * h1], [x1 - nx * h1, y1 - ny * h1], [x2 - nx * h2, y2 - ny * h2], [x2 + nx * h2, y2 + ny * h2]]), (tx, ty), i))
    return out


def build(Z: np.ndarray, xs: np.ndarray, ys: np.ndarray, sea_level: float, lakes: List[dict], rivers: List[dict], cfg) -> Dict[str, object]:
    """يعيد قاموساً: depth (م)، shore/foam (0..1)، flow (H,W,3 بين 0..1)، river (قناع)، info."""
    ny, nx = Z.shape
    x0, y_top = float(xs[0]), float(ys[0])
    dx, dy = float(xs[1] - xs[0]), float(ys[0] - ys[1])
    Zd = Z.astype(np.float64)
    L = np.full((ny, nx), sea_level, np.float64)                 # سطح الماء: البحر في كل مكان (العمق = ما تحت المنسوب)
    X, Y = xs[None, :], ys[:, None]
    for lk in lakes:
        r = lk["radius_m"] * 1.3
        inside = (np.hypot(X - lk["x"], Y - lk["y"]) <= r) & (Zd < lk["water_level_m"])
        L = np.where(inside, np.maximum(L, lk["water_level_m"]), L)
    # أنهار: ارسم كل مقطع بسطح مائه واتجاهه
    Rl = np.full((ny, nx), NEG, np.float32)
    flow = np.zeros((ny, nx, 3), np.float32)
    flow[..., 0] = flow[..., 1] = 0.5
    rmask = np.zeros((ny, nx), np.uint8)
    gy, gx = np.gradient(Zd, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    for rv in rivers:
        pl, wz, wid = _densify(rv["polyline"], rv["water_z"], rv.get("width_profile_m") or [rv["width_m"]] * len(rv["polyline"]), 0.8 * min(dx, dy))
        for quad, (tx, ty), i in _segment_quads(pl, wid, 0.75 * max(dx, dy)):
            poly = np.round(_to_px(quad[:, 0], quad[:, 1], x0, y_top, dx, dy) * 16).astype(np.int32)       # 4 بتّات كسرية: حواف أنعم
            cv2.fillConvexPoly(Rl, poly, float((wz[i] + wz[i + 1]) / 2.0), lineType=cv2.LINE_8, shift=4)
            cv2.fillConvexPoly(rmask, poly, 255, lineType=cv2.LINE_8, shift=4)
            cv2.fillConvexPoly(flow, poly, (0.5 + 0.5 * tx, 0.5 + 0.5 * ty, 0.0), lineType=cv2.LINE_8, shift=4)
    on = Rl > NEG / 2
    L = np.where(on, np.maximum(L, Rl), L)
    depth = np.maximum(L - Zd, 0.0)
    wm = depth > 0.03
    river_px = (rmask > 0) & wm
    speed = np.clip(0.25 + 0.75 * _smooth(slope, 0.5, 8.0), 0.0, 1.0) * river_px
    flow[..., 2] = speed
    flow[~river_px, 0] = 0.5
    flow[~river_px, 1] = 0.5
    # شاطئ (جهة اليابسة) ورغوة (جهة الماء + منحدرات النهر)
    if wm.any():
        d_out = ndi.distance_transform_edt(~wm, sampling=(dy, dx))
        d_in = ndi.distance_transform_edt(wm, sampling=(dy, dx))
    else:
        d_out = np.full_like(Zd, 1e9); d_in = np.zeros_like(Zd)
    shore = np.where(wm, 0.0, np.clip(1.0 - d_out / max(cfg.shore_width_m, 1e-6), 0.0, 1.0))
    foam = np.where(wm, np.clip(1.0 - d_in / max(cfg.foam_width_m, 1e-6), 0.0, 1.0), 0.0)
    rapids = _smooth(slope, cfg.rapids_slope_deg, cfg.rapids_slope_deg * 2.5) * river_px
    foam = np.clip(np.maximum(foam, rapids) * cfg.foam_amount, 0.0, 1.0)
    return {"depth": depth.astype(np.float32), "shore": shore.astype(np.float32), "foam": foam.astype(np.float32), "flow": flow,
            "river": river_px, "water_mask": wm, "level": L.astype(np.float32)}


def encode(maps: Dict[str, object], depth_max: float = None):
    """(بايتات PNG 16-بت للعمق، 8-بت للشاطئ/الرغوة، RGB للتدفق) مع أقصى عمق مستعمل في الترميز."""
    d = maps["depth"]
    dmax = float(depth_max or max(float(d.max()), 0.5))
    d16 = np.rint(np.clip(d / dmax, 0, 1) * 65535).astype(np.uint16)
    u8 = lambda a: (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)
    f = maps["flow"]
    rgb = u8(f)[..., ::-1].copy()                                # cv2 يكتب BGR
    return dmax, cv2.imencode(".png", d16)[1].tobytes(), cv2.imencode(".png", u8(maps["shore"]))[1].tobytes(), \
        cv2.imencode(".png", u8(maps["foam"]))[1].tobytes(), cv2.imencode(".png", rgb)[1].tobytes()
