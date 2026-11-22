"""نثر النباتات والصخور: مواضع حتمية (Poisson-disk بكثافة متغيرة) من أقنعة الكثافة.

كل نوع له مسافة دنيا بين النسخ (فلا تتداخل) وتناقص احتمالي بالكثافة (مناطق أكثف تحمل نسخاً أكثر).
نفس البذرة + نفس المدخلات = نفس المواضع تماماً، فيصلح الملف للمحرك والـ Blender معاً.
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

PACK = 0.65                              # كثافة تعبئة Poisson-disk التقريبية: نقاط ≈ PACK / r² لكل م² عند كثافة 1


def effective_radius(density: np.ndarray, cell_area: float, r: float, max_count: int) -> float:
    """يرفع المسافة الدنيا عند الحاجة كي لا يتجاوز العدد المتوقع الحد الأقصى (بدل قصّ الناتج فيختل التوزيع المكاني)."""
    expected = float(density.sum()) * cell_area * PACK / (r * r)
    return r if expected <= max_count else math.sqrt(PACK * float(density.sum()) * cell_area / max_count)


def poisson_points(density: np.ndarray, x0: float, y_top: float, dx: float, dy: float, r: float, seed: int, max_count: int) -> np.ndarray:
    """نقاط (x, y) بمتر؛ density بقيم 0..1 صف 0 = الشمال. يعيد مصفوفة (n,2).
    1) Poisson-disk كامل بالمسافة r فوق المنطقة الفعالة (density > 0.02) 2) تُبقى كل نقطة باحتمال = كثافتها عندها.
    (الاختبار داخل حلقة الإعادة كان يرفع الاحتمال الفعلي إلى ~1 فيُلغي أثر الكثافة؛ لذا يُفصل التناقص عن التوليد.)"""
    ny, nx = density.shape
    act = np.argwhere(density > 0.02)
    if act.size == 0:
        return np.zeros((0, 2))
    rng = np.random.default_rng(seed)
    W, H = nx * dx, ny * dy
    cs = r / math.sqrt(2.0)
    gw, gh = int(W / cs) + 3, int(H / cs) + 3
    grid = np.full((gh, gw), -1, np.int64)
    pts: List[Tuple[float, float]] = []
    active: List[int] = []

    def dens_at(x, y):
        c = int((x - x0) / dx); rr = int((y_top - y) / dy)
        return density[rr, c] if 0 <= c < nx and 0 <= rr < ny else 0.0

    cap = max_count * 6                                      # سقف التوليد قبل التناقص

    def free(x, y):
        gx, gy = int((x - x0) / cs), int((y_top - y) / cs)
        for j in range(max(gy - 2, 0), min(gy + 3, gh)):
            for i in range(max(gx - 2, 0), min(gx + 3, gw)):
                k = grid[j, i]
                if k >= 0 and (pts[k][0] - x) ** 2 + (pts[k][1] - y) ** 2 < r * r:
                    return False
        return True

    def add(x, y):
        grid[int((y_top - y) / cs), int((x - x0) / cs)] = len(pts)
        active.append(len(pts)); pts.append((x, y))

    # بذور موزّعة على المنطقة الفعالة كلها (كل بذرة تنمو في منطقتها فلا يضيع جزء منفصل من القناع)
    n_seed = int(min(len(act), max(8, math.sqrt(len(act)))))
    for k in rng.choice(len(act), n_seed, replace=False):
        rr, c = act[k]
        x, y = x0 + (c + rng.random()) * dx, y_top - (rr + rng.random()) * dy
        if len(pts) < cap and free(x, y):
            add(x, y)
    while active and len(pts) < cap:
        ai = int(rng.integers(len(active)))
        px, py = pts[active[ai]]
        ok = False
        for _ in range(24):
            a, d = rng.random() * 2 * math.pi, r * (1.0 + rng.random())
            x, y = px + d * math.cos(a), py + d * math.sin(a)
            if not (x0 <= x < x0 + W and y_top - H < y <= y_top):
                continue
            if dens_at(x, y) > 0.02 and free(x, y):
                add(x, y); ok = True
                break
        if not ok:
            active[ai] = active[-1]; active.pop()
    P = np.asarray(pts, np.float64).reshape(-1, 2)
    if len(P) == 0:
        return P
    dd = np.array([dens_at(x, y) for x, y in P])
    P = P[rng.random(len(P)) <= dd]                          # التناقص بالكثافة
    if len(P) > max_count:                                   # قصّ عشوائي غير متحيّز مكانياً
        P = P[np.sort(rng.choice(len(P), max_count, replace=False))]
    return P


def _bilinear(F: np.ndarray, x, y, x0, y_top, dx, dy):
    ny, nx = F.shape
    fx = np.clip((x - x0) / dx, 0, nx - 1.001); fy = np.clip((y_top - y) / dy, 0, ny - 1.001)
    i, j = fx.astype(int), fy.astype(int); tx, ty = fx - i, fy - j
    return (F[j, i] * (1 - tx) * (1 - ty) + F[j, i + 1] * tx * (1 - ty) + F[j + 1, i] * (1 - tx) * ty + F[j + 1, i + 1] * tx * ty)


def place(sp, layer_density: np.ndarray, Z: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> Optional[Dict[str, np.ndarray]]:
    """مواضع نوع واحد: يقيّد الكثافة بالميل والارتفاع، ثم يعيد x,y,z,yaw,scale والعمودي على السطح."""
    dx, dy = float(xs[1] - xs[0]), float(ys[0] - ys[1])
    gy, gx = np.gradient(Z.astype(np.float64), dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    d = layer_density * (slope <= sp.max_slope_deg)
    if sp.min_elev_m is not None:
        d = d * (Z >= sp.min_elev_m)
    if sp.max_elev_m is not None:
        d = d * (Z <= sp.max_elev_m)
    if float(d.max()) <= 0.02:
        return None
    r = effective_radius(d, dx * dy, sp.min_dist_m, sp.max_count)
    P = poisson_points(d, float(xs[0]), float(ys[0]), dx, dy, r, sp.seed, sp.max_count)
    if len(P) == 0:
        return None
    rng = np.random.default_rng(sp.seed + 7919)
    x, y = P[:, 0], P[:, 1]
    z = _bilinear(Z.astype(np.float64), x, y, float(xs[0]), float(ys[0]), dx, dy)
    sx = _bilinear(gx, x, y, float(xs[0]), float(ys[0]), dx, dy); sy = _bilinear(gy, x, y, float(xs[0]), float(ys[0]), dx, dy)
    n = np.stack([-sx, -sy, np.ones_like(sx)], 1); n /= np.linalg.norm(n, axis=1, keepdims=True)
    return {"x": x, "y": y, "z": z, "yaw_deg": rng.random(len(x)) * 360.0, "scale": rng.uniform(sp.scale_min, sp.scale_max, len(x)),
            "nx": n[:, 0], "ny": n[:, 1], "nz": n[:, 2], "min_dist_m": r}


def to_csv(pts: Dict[str, np.ndarray]) -> bytes:
    cols = ("x", "y", "z", "yaw_deg", "scale", "nx", "ny", "nz")
    head = ",".join(cols)
    body = "\n".join(",".join(f"{pts[c][i]:.3f}" if c in ("x", "y", "z") else f"{pts[c][i]:.4f}" for c in cols) for i in range(len(pts["x"])))
    return (head + "\n" + body + "\n").encode("utf-8")
