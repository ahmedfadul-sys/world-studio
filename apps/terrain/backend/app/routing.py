"""توجيه ذكي: مسارات الطرق (أقل تكلفة قطع/ميل) والأنهار (هبوط مستمر)، اقتراح مواقع بأقل تسوية، واقتراح مباني."""
from __future__ import annotations
import math
from typing import List, Tuple
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.signal import fftconvolve
from scipy.ndimage import binary_dilation
from .terrain import (Engine, BLOCKS_RIVER, WATERISH, CORE_RATIO, grid_axes, nearest_grid, site_ext, site_sd, S)

OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
BIG = 1e7


def build_graph(H, W, dx, dy, weight_fn):
    """رسم بياني موجّه (8 جيران). weight_fn(dr, dc, dist, src_slice, dst_slice) -> مصفوفة أوزان (≥0، BIG = ممنوع)."""
    idx = np.arange(H * W).reshape(H, W)
    rows, cols, data = [], [], []
    for dr, dc in OFFS:
        r0, r1 = max(0, -dr), H - max(0, dr)
        c0, c1 = max(0, -dc), W - max(0, dc)
        src = (slice(r0, r1), slice(c0, c1))
        dst = (slice(r0 + dr, r1 + dr), slice(c0 + dc, c1 + dc))
        d = math.hypot(dc * dx, dr * dy)
        w = weight_fn(d, src, dst)
        rows.append(idx[src].ravel()); cols.append(idx[dst].ravel()); data.append(np.broadcast_to(w, idx[src].shape).ravel())
    return csr_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(H * W, H * W))


def _snap(x, y, xs, ys):
    return int(np.argmin(np.abs(ys - y))), int(np.argmin(np.abs(xs - x)))


def _trace(pred, src, dst):
    path = [dst]
    while path[-1] != src:
        p = pred[path[-1]]
        if p < 0:
            return None
        path.append(int(p))
    return path[::-1]


def _dp(pts, tol):
    """Douglas–Peucker (تكراري)."""
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), bool); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p, q = pts[a], pts[b]
        v = q - p
        L = math.hypot(*v) or 1e-9
        d = np.abs(v[0] * (pts[a + 1:b, 1] - p[1]) - v[1] * (pts[a + 1:b, 0] - p[0])) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[a + 1 + k] = True
            stack += [(a, a + 1 + k), (a + 1 + k, b)]
    return pts[keep]


def _masks(project, eng, Z, xs, ys):
    """(ماء، بحيرات/مستنقعات، أنهار، قلوب الجبال) كمصفوفات منطقية."""
    H, W = Z.shape
    water = Z < project.world.sea_level_m
    lake = np.zeros((H, W), bool); core = np.zeros((H, W), bool); marsh = np.zeros((H, W), bool)
    X, Y = xs[None, :], ys[:, None]
    for f in project.points:
        R = f.diameter_m / 2
        dd = np.hypot(X - f.x_m, Y - f.y_m)
        if f.kind in ("lake", "crater", "sinkhole", "cave"):
            lake |= dd < R
        if f.kind == "marsh":
            marsh |= dd < R
        if f.kind in BLOCKS_RIVER:
            core |= dd < CORE_RATIO * R
    river = np.zeros((H, W), bool)
    for i, (typ, f) in enumerate(eng.stages):
        if typ == "line" and f.kind == "river":
            path = eng._path(f)
            if path is not None:
                hw = max(f.width_m, f.width_end_m or f.width_m) / 2 + 2
                river |= nearest_grid(path, xs, ys, hw)[0] < hw
    return water, lake, river, core, marsh


def route(project, kind, points, resolution=257, max_grade=0.08):
    w = project.world
    eng = Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (resolution - 1))
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, resolution)
    Z = eng.grid(xs, ys)
    H, W = Z.shape
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    water, lake, river, core, marsh = _masks(project, eng, Z, xs, ys)
    gy, gx = np.gradient(Z.astype(np.float64), dy, dx)
    gm = np.hypot(gx, gy)
    Zd = Z.astype(np.float64)
    if kind == "road":
        block = (water | lake) * BIG
        extra = np.where(river, 40.0 * dx, 0.0) + marsh * 2.0 * dx                       # عبور نهر/مستنقع مكلف
        def wf(d, src, dst):
            s = np.abs(Zd[dst] - Zd[src]) / d
            fac = 1.0 + (s / max_grade) ** 2 + 2.0 * 0.5 * (gm[src] + gm[dst])             # ميل + خشونة (تقدير للقطع/الردم)
            fac = np.where(s > 0.6, fac * 50, fac)
            return d * fac + 0.5 * (extra[src] + extra[dst]) + np.maximum(block[src], block[dst])
    else:
        block = core * BIG
        def wf(d, src, dst):
            up = np.maximum(Zd[dst] - Zd[src], 0.0) / d
            return d * (1.0 + (up / 0.01) ** 2) + np.maximum(block[src], block[dst])
    G = build_graph(H, W, dx, dy, wf)
    pts = [tuple(p) for p in points]
    legs = []
    notes = []
    if kind == "river" and len(pts) == 1:
        r0, c0 = _snap(pts[0][0], pts[0][1], xs, ys)
        src = r0 * W + c0
        dist, pred = dijkstra(G, directed=True, indices=src, return_predecessors=True)
        zf = Zd.ravel()
        cand = np.nonzero((zf <= project.world.sea_level_m + 0.5) & (dist < BIG))[0]
        mouth = "sea"
        if not len(cand):
            edge = np.zeros((H, W), bool); edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
            cand = np.nonzero(edge.ravel() & (zf < zf[src] - 2) & (dist < BIG))[0]
            mouth = "edge"
        if not len(cand):
            ok = np.nonzero(dist < BIG)[0]
            cand = ok[[int(np.argmin(zf[ok]))]] if len(ok) else []
            mouth = "lowest"
        if not len(cand):
            raise ValueError("لا يوجد مسار ممكن من هذا المنبع")
        dst = int(cand[int(np.argmin(dist[cand]))])
        notes.append({"sea": "المصب: البحر", "edge": "المصب: حافة العالم (أخفض من المنبع)", "lowest": "لا بحر ولا مخرج: المصب أخفض نقطة يمكن بلوغها"}[mouth])
        legs.append(_trace(pred, src, dst))
    else:
        if len(pts) < 2:
            raise ValueError("المسار يحتاج نقطتين على الأقل")
        for a, b in zip(pts[:-1], pts[1:]):
            r0, c0 = _snap(a[0], a[1], xs, ys); r1, c1 = _snap(b[0], b[1], xs, ys)
            src, dst = r0 * W + c0, r1 * W + c1
            dist, pred = dijkstra(G, directed=True, indices=src, return_predecessors=True)
            if dist[dst] >= BIG:
                raise ValueError("لا يوجد مسار ممكن بين النقطتين (ماء أو قلب جبل يسدّ الطريق)")
            legs.append(_trace(pred, src, dst))
    nodes = [n for i, leg in enumerate(legs) for n in (leg if i == 0 else leg[1:])]
    rr, cc = np.divmod(np.asarray(nodes), W)
    P = np.c_[xs[cc], ys[rr]]
    z = Zd[rr, cc]
    seg = np.hypot(*np.diff(P, axis=0).T)
    slope = np.abs(np.diff(z)) / np.maximum(seg, 1e-9)
    simp = _dp(P, 1.3 * max(dx, dy))
    if kind == "road":
        simp[0], simp[-1] = pts[0], pts[-1]
    elif len(pts) >= 2:
        simp[0], simp[-1] = pts[0], pts[-1]
    else:
        simp[0] = pts[0]
    return {"points": [[round(float(x), 1), round(float(y), 1)] for x, y in simp], "length_m": float(seg.sum()),
            "max_grade": float(slope.max()) if len(slope) else 0.0, "mean_grade": float(slope.mean()) if len(slope) else 0.0,
            "climb_m": float(np.maximum(np.diff(z), 0).sum()), "descent_m": float(np.maximum(-np.diff(z), 0).sum()),
            "notes": notes + ([f"أقصى ميل {slope.max() * 100:.1f}% يتجاوز الحد {max_grade * 100:.0f}%"] if kind == "road" and len(slope) and slope.max() > max_grade * 1.05 else [])}


def suggest_sites(project, kind, diameter_m, count=5, resolution=513):
    """أفضل مواقع بأقل تسوية: انحراف معياري للارتفاع داخل القرص (تقريب سريع بالالتفاف) ثم قياس القطع/الردم الفعلي."""
    w = project.world
    eng = Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (resolution - 1))
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, resolution)
    Z = eng.grid(xs, ys).astype(np.float64)
    H, W = Z.shape
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    R = diameter_m / 2
    rc = max(2, int(round(R / dx)))
    yy, xx = np.mgrid[-rc:rc + 1, -rc:rc + 1]
    ker = ((xx * dx) ** 2 + (yy * dy) ** 2 <= R * R).astype(np.float64)
    n = ker.sum()
    m1 = fftconvolve(Z, ker, mode="same") / n
    m2 = fftconvolve(Z * Z, ker, mode="same") / n
    std = np.sqrt(np.maximum(m2 - m1 * m1, 0))
    water, lake, river, core, marsh = _masks(project, eng, Z, xs, ys)
    bad = water | lake | core | marsh
    for s in project.sites:                                         # بعيداً عن المواقع القائمة
        bad |= np.hypot(xs[None, :] - s.x_m, ys[:, None] - s.y_m) < site_ext(s) + R
    for f in project.points:
        if f.kind in WATERISH:
            bad |= np.hypot(xs[None, :] - f.x_m, ys[:, None] - f.y_m) < f.diameter_m / 2 + R * 0.5
    badc = fftconvolve(bad.astype(np.float64), ker, mode="same") > 0.5
    score = std + 8.0 * (fftconvolve(river.astype(np.float64), ker, mode="same") > 0.5)           # النهر يُفضَّل تجنبه
    score = np.where(badc, np.inf, score)
    score[:rc, :] = score[-rc:, :] = np.inf; score[:, :rc] = score[:, -rc:] = np.inf               # هامش حدود العالم
    out, sc = [], score.copy()
    for _ in range(count):
        k = int(np.argmin(sc))
        if not np.isfinite(sc.ravel()[k]):
            break
        r, c = divmod(k, W)
        cx, cy = float(xs[c]), float(ys[r])
        g = np.linspace(-R, R, 31)
        GX, GY = np.meshgrid(g, g)
        m = GX ** 2 + GY ** 2 <= R * R
        Zs = eng.points(cx + GX[m], cy + GY[m])
        lvl = float(Zs.mean())
        area = math.pi * R * R / m.sum()
        out.append({"x_m": round(cx, 1), "y_m": round(cy, 1), "level_m": round(lvl, 2), "rms_m": round(float(std[r, c]), 2),
                    "cut_m3": round(float(np.maximum(Zs - lvl, 0).sum() * area), 0), "fill_m3": round(float(np.maximum(lvl - Zs, 0).sum() * area), 0),
                    "max_cut_m": round(float(max(Zs.max() - lvl, 0)), 2), "max_fill_m": round(float(max(lvl - Zs.min(), 0)), 2)})
        rr0, rr1, cc0, cc1 = max(0, r - 2 * rc), min(H, r + 2 * rc + 1), max(0, c - 2 * rc), min(W, c + 2 * rc + 1)
        sc[rr0:rr1, cc0:cc1] = np.inf                                # تباعد: 2R
    return out


LOT_TABLE = {"village": (10, 8, 20), "town": (12, 10, 26), "city": (16, 12, 34), "castle": (24, 24, 60), "ruins": (8, 8, 30),
             "farm": (14, 10, 35), "industrial": (30, 20, 50), "power_plant": (40, 25, 70), "mine": (20, 15, 60),
             "camp": (5, 4, 14), "tower": (8, 8, 40), "temple": (18, 14, 50)}


def lots_for_site(site, level_z=0.0):
    """اقتراح أماكن مبانٍ داخل بصمة الموقع المسوّاة: رمي أقراص (Poisson-disk) حتمي بـ seed، موجَّهة نحو المركز."""
    w, l, sp = LOT_TABLE.get(site.kind, (10, 8, 24))
    rng = np.random.default_rng(site.seed + 977)
    margin = max(w, l) / 2 + 2
    ext = site_ext(site)
    spacing = sp / math.sqrt(max(site.density, 0.05))
    lots = []
    if site.kind in ("castle", "temple", "tower"):                       # مبنى رئيسي في المركز
        lots.append((site.x_m, site.y_m))
    for _ in range(6000):
        if len(lots) >= 400:
            break
        x, y = site.x_m + rng.uniform(-ext, ext), site.y_m + rng.uniform(-ext, ext)
        if site_sd(site, np.array(x), np.array(y)) > -margin:
            continue
        if all(math.hypot(x - a, y - b) >= spacing for a, b in lots):
            lots.append((x, y))
    out = []
    for i, (x, y) in enumerate(lots):
        main = i == 0 and site.kind in ("castle", "temple", "tower")
        rot = site.rotation_deg if site.shape == "rect" else math.degrees(math.atan2(site.y_m - y, site.x_m - x)) + float(rng.normal(0, 8))
        out.append({"x_m": round(float(x), 1), "y_m": round(float(y), 1), "width_m": w * (1.6 if main else 1.0), "length_m": l * (1.6 if main else 1.0),
                    "rotation_deg": round(float(rot), 1), "z_m": round(float(level_z), 2), "main": main})
    return out
