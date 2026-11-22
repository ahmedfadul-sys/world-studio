"""أقنعة الطرق: سطح، كتف، وحافة مغبرّة غير منتظمة، بدقة الأقنعة (صف 0 = الشمال).

تُحسب بأقرب مسافة إلى محور الطريق (مع عرض وكتف أقرب نقطة منه، فتتدرج الأطراف على الطرق المتناقصة العرض) وتغطية جزئية للبكسل
فلا تختفي طرق أضيق من بكسل. مسارات الإطارات لا تُخبَز هنا (نصف متر لا يُرى بدقة 10 م/بكسل): تُرسم إجرائياً في ظل Blender
بإحداثيات الطريق بالأمتار، وتُصدَّر معاييرها (المسافة بين العجلتين وعرض الأثر) في build.json.
"""
from __future__ import annotations
from typing import Dict, List, Optional

import numpy as np
from scipy import ndimage as ndi

from .noise import fbm


def build(xs: np.ndarray, ys: np.ndarray, roads: List[dict], dust_width_m: float, seed: int = 5) -> Optional[Dict[str, np.ndarray]]:
    if not roads:
        return None
    ny, nx = len(ys), len(xs)
    x0, y_top = float(xs[0]), float(ys[0])
    dx, dy = float(xs[1] - xs[0]), float(ys[0] - ys[1])
    pix = 0.5 * (dx + dy)
    OFF = np.full((ny, nx), np.inf)                                  # مسافة موقّعة إلى حافة أقرب طريق (سالب = على السطح)
    HWm = np.zeros((ny, nx)); SHm = np.zeros((ny, nx))
    dust_reach = dust_width_m * 1.6 + pix
    for rd in roads:
        P = np.asarray([p[:2] for p in rd["polyline"]], np.float64)
        wid = np.asarray(rd["width_profile_m"], np.float64) / 2.0
        sh = float(rd.get("shoulder_m", 0.0))
        for i in range(len(P) - 1):
            a, b = P[i], P[i + 1]
            ab = b - a
            L2 = float(ab @ ab)
            if L2 < 1e-12:
                continue
            reach = max(wid[i], wid[i + 1]) + sh + dust_reach + 2 * pix
            c0 = max(int((min(a[0], b[0]) - reach - x0) / dx), 0); c1 = min(int((max(a[0], b[0]) + reach - x0) / dx) + 2, nx)
            r0 = max(int((y_top - max(a[1], b[1]) - reach) / dy), 0); r1 = min(int((y_top - min(a[1], b[1]) + reach) / dy) + 2, ny)
            if c0 >= c1 or r0 >= r1:
                continue
            X, Y = xs[None, c0:c1], ys[r0:r1, None]
            t = np.clip(((X - a[0]) * ab[0] + (Y - a[1]) * ab[1]) / L2, 0.0, 1.0)
            dist = np.hypot(X - (a[0] + t * ab[0]), Y - (a[1] + t * ab[1]))
            hw = wid[i] + (wid[i + 1] - wid[i]) * t
            off = dist - hw
            cur = OFF[r0:r1, c0:c1]
            m = off < cur
            if m.any():
                cur[m] = off[m]
                HWm[r0:r1, c0:c1][m] = hw[m]
                SHm[r0:r1, c0:c1][m] = sh
    if not np.isfinite(OFF).any():
        return None
    cov = lambda e: np.clip(0.5 - e / pix, 0.0, 1.0)                 # تغطية جزئية بالمسافة الموقّعة: مرشّح بعرض بكسل يحفظ المساحة لأي اتجاه
    dist_c = OFF + HWm                                               # مسافة إلى المحور
    tent = np.clip(1.0 - dist_c / pix, 0.0, 1.0) * np.minimum(2.0 * HWm / pix, 1.0)   # أضيق من بكسل: مرشّح مثلثي يحفظ المساحة (2·hw)
    surface = np.where(np.isfinite(OFF), np.where(2.0 * HWm < pix, tent, cov(OFF)), 0.0)
    full = np.where(np.isfinite(OFF), cov(OFF - SHm), 0.0)
    shoulder = np.clip(full - surface, 0.0, 1.0)
    X, Y = xs[None, :], ys[:, None]
    n01 = (fbm(X, Y, 1.0 / 18.0, 3, seed) + 1.0) / 2.0               # عرض الغبار يتغير على طول الطريق وليس خطاً منتظماً
    dw = np.maximum(dust_width_m * (0.45 + 1.1 * n01), 1e-3)
    dust = np.clip(1.0 - np.maximum(OFF, 0.0) / dw, 0.0, 1.0) * (1.0 - surface)
    return {"surface": surface.astype(np.float32), "shoulder": shoulder.astype(np.float32), "dust": dust.astype(np.float32)}
