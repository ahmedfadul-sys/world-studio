"""محرك الارتفاعات v3.
الترتيب: أرض المناطق (Biomes مدموجة) -> خلايا (مستويات ميل مدموجة) -> تضاريس نقطية (الأكبر أولاً)
-> سلاسل -> جروف -> أودية -> طرق -> أنهار -> قصّ حدود المناطق.
نفس الدوال تعمل على شبكة (grid) أو نقاط حرة (points) فالمقاطع تطابق الصورة."""
from __future__ import annotations
import hashlib, json, math
from types import SimpleNamespace
from typing import Dict, List, Tuple
import numpy as np
from scipy.ndimage import uniform_filter1d, map_coordinates
from scipy.interpolate import PchipInterpolator
from .noise import fbm
from .erosion import erode

POSITIVE = {"mountain", "hill", "plateau", "mesa", "volcano", "island", "atoll", "terraces", "scree", "delta"}
BLOCKS_RIVER = {"mountain", "volcano", "plateau", "mesa", "scree", "terraces"}
CORE_RATIO, RIDGE_CORE = 0.6, 0.3
RELIEF = {"hummocks", "rocky"}
WATERISH = {"lake", "basin", "crater", "sinkhole", "marsh", "cave"}
RIVER_BANK_SLOPE = 0.12      # ميل ضفاف الوادي المُسوّى حول النهر (12% ≈ 7°)
_ERO_CACHE: Dict[str, object] = {}
LABELS = {"mountain": "جبل", "hill": "تلّة", "plateau": "هضبة", "mesa": "مصطبة", "volcano": "بركان", "island": "جزيرة",
          "atoll": "أتول", "terraces": "مدرجات", "scree": "منحدر صخري", "delta": "دلتا", "crater": "فوهة", "basin": "منخفض",
          "lake": "بحيرة", "sinkhole": "حفرة انهيارية", "cave": "مدخل كهف", "marsh": "مستنقع", "dune": "كثبان",
          "river": "نهر", "road": "طريق", "valley": "وادٍ", "ridge": "سلسلة", "cliff": "جرف"}
LINE_ORDER = {"ridge": 0, "cliff": 1, "valley": 2, "road": 3, "river": 4}
_HIGH = ["hill", "mountain", "volcano", "mesa", "lake", "basin", "crater", "sinkhole", "marsh", "dune", "scree", "terraces", "cave"]
# التداخل المنطقي المسموح فقط: (المضيف -> ما يمكن أن يقع بكامله داخله). أي شيء آخر = خطأ.
NEST: Dict[str, List[str]] = {
    "plateau": _HIGH, "mesa": _HIGH,
    "mountain": ["lake", "basin", "hill", "scree", "terraces", "cave"],
    "volcano": ["lake", "hill", "scree", "cave"],
    "hill": ["lake", "sinkhole", "cave", "scree"], "terraces": ["lake", "hill"], "scree": ["cave"],
    "island": ["hill", "mountain", "lake", "volcano", "marsh", "dune", "cave"],
    "atoll": ["island", "lake", "hill", "marsh"],
    "basin": ["lake", "hill", "mountain", "mesa", "plateau", "sinkhole", "marsh", "dune", "island", "cave"],
    "crater": ["hill", "mountain", "lake", "basin", "sinkhole", "cave"],
    "lake": ["island", "hill", "mountain", "plateau", "mesa", "atoll", "volcano"],
    "sinkhole": ["lake", "cave"], "marsh": ["lake", "hill", "island"], "dune": ["lake", "marsh", "hill"],
    "delta": ["lake", "marsh", "island", "hill"], "cave": [],
}


def grid_axes(Lx: float, Ly: float, resolution: int):
    """الضلع الأطول = resolution بكسل، والأقصر بنفس مقياس الرسم. الصف 0 = الشمال (y=Ly)."""
    if Lx >= Ly:
        nx, ny = resolution, max(2, int(round(Ly / Lx * (resolution - 1))) + 1)
    else:
        ny, nx = resolution, max(2, int(round(Lx / Ly * (resolution - 1))) + 1)
    return np.linspace(0.0, Lx, nx), np.linspace(Ly, 0.0, ny)


def S(a: float, b: float, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def S01(t):
    return t * t * (3.0 - 2.0 * t)


def sample_grid(A, Lx, Ly, xs, ys):
    """أخذ عينات خطية (bilinear) من مصفوفة عالمية A (الصف 0 = الشمال) على محاور شبكة."""
    nyC, nxC = A.shape
    ci = np.clip(xs / (Lx / (nxC - 1)), 0, nxC - 1)
    i0 = np.minimum(ci.astype(int), nxC - 2); fx = (ci - i0).astype(np.float32)
    rj = np.clip((Ly - ys) / (Ly / (nyC - 1)), 0, nyC - 1)
    j0 = np.minimum(rj.astype(int), nyC - 2); fy = (rj - j0).astype(np.float32)
    T = A[:, i0] * (1 - fx)[None, :] + A[:, i0 + 1] * fx[None, :]
    return T[j0, :] * (1 - fy)[:, None] + T[j0 + 1, :] * fy[:, None]


def sample_points(A, Lx, Ly, X, Y):
    nyC, nxC = A.shape
    ci = np.clip(X / (Lx / (nxC - 1)), 0, nxC - 1)
    rj = np.clip((Ly - Y) / (Ly / (nyC - 1)), 0, nyC - 1)
    return map_coordinates(A, [rj, ci], order=1, mode="nearest").astype(np.float32)


def _iso_nonincreasing(y):
    """انحدار متساوي الاتجاه (PAVA): أقرب متتالية غير متزايدة بالمربعات الصغرى."""
    y = -np.asarray(y, float)
    vals, wts, cnt = [], [], []
    for v in y:
        vals.append(v); wts.append(1.0); cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), wts.pop(), cnt.pop()
            v1, w1, c1 = vals.pop(), wts.pop(), cnt.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2)); wts.append(w1 + w2); cnt.append(c1 + c2)
    return -np.repeat(vals, cnt)


def site_ext(s):
    return s.diameter_m / 2 if s.shape == "circle" else math.hypot(s.width_m, s.length_m) / 2


def site_sd(s, X, Y):
    """مسافة موقّعة إلى بصمة الموقع (سالب = داخل)."""
    if s.shape == "circle":
        return np.hypot(X - s.x_m, Y - s.y_m) - s.diameter_m / 2
    th = math.radians(s.rotation_deg)
    u = (X - s.x_m) * math.cos(th) + (Y - s.y_m) * math.sin(th)
    v = -(X - s.x_m) * math.sin(th) + (Y - s.y_m) * math.cos(th)
    qx, qy = np.abs(u) - s.width_m / 2, np.abs(v) - s.length_m / 2
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)


def _inside_pts(poly, X, Y):
    ins = np.zeros(len(X), bool)
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if y0 == y1:
            continue
        ins ^= ((y0 > Y) != (y1 > Y)) & (X < x0 + (x1 - x0) * (Y - y0) / (y1 - y0))
    return ins


def _ring(poly):
    P = np.asarray(poly, float)
    ring = np.vstack([P, P[:1]])
    return ring[:, 0], ring[:, 1], np.r_[0.0, np.cumsum(np.hypot(*np.diff(ring, axis=0).T))]


def poly_weight_grid(poly, xs, ys, falloff):
    """وزن داخل المضلع فقط (البصمة = المضلع بالضبط)، يتدرّج من 0 عند الحد إلى 1 بعد falloff للداخل."""
    ins = _inside(poly, xs, ys)
    if falloff <= 0:
        return ins.astype(np.float32)
    dist, _, _ = nearest_grid(_ring(poly), xs, ys, falloff)
    return np.where(ins, S(0.0, falloff, np.where(np.isinf(dist), falloff, dist)), 0.0).astype(np.float32)


def poly_weight_points(poly, X, Y, falloff):
    ins = _inside_pts(poly, X, Y)
    if falloff <= 0:
        return ins.astype(np.float32)
    d = nearest_points(_ring(poly), X, Y)[0]
    return np.where(ins, S(0.0, falloff, d), 0.0).astype(np.float32)


# ───────────────────────── مسارات ─────────────────────────
def smooth_path(points, step: float):
    """Pchip بمعامل طول الوتر (بلا تجاوز). يعيد (x, y, s) أو None إن كان منحلاً."""
    P = [list(map(float, points[0]))]
    for q in points[1:]:
        if math.hypot(q[0] - P[-1][0], q[1] - P[-1][1]) > 1e-6:
            P.append([float(q[0]), float(q[1])])
    if len(P) < 2:
        return None
    P = np.asarray(P)
    chord = np.r_[0.0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
    n = int(min(max(2, chord[-1] / step + 1), 20000))
    u = np.linspace(0.0, chord[-1], n)
    if len(P) == 2:
        xy = P[0] + (P[1] - P[0]) * (u / chord[-1])[:, None]
    else:
        xy = np.c_[PchipInterpolator(chord, P[:, 0])(u), PchipInterpolator(chord, P[:, 1])(u)]
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    return xy[:, 0], xy[:, 1], s


def nearest_grid(path, xs, ys, reach):
    """(أقرب مسافة، موضع s، جهة: +1 يسار اتجاه الرسم) — نافذة صغيرة لكل مقطع."""
    px, py, s = path
    H, W = len(ys), len(xs)
    dist = np.full((H, W), np.inf, np.float32)
    sv, sg = np.zeros((H, W), np.float32), np.zeros((H, W), np.float32)
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    for k in range(len(px) - 1):
        x0, y0, x1, y1 = px[k], py[k], px[k + 1], py[k + 1]
        c0 = max(0, int(math.floor((min(x0, x1) - reach - xs[0]) / dx)))
        c1 = min(W, int(math.ceil((max(x0, x1) + reach - xs[0]) / dx)) + 1)
        r0 = max(0, int(math.floor((ys[0] - max(y0, y1) - reach) / dy)))
        r1 = min(H, int(math.ceil((ys[0] - min(y0, y1) + reach) / dy)) + 1)
        if c0 >= c1 or r0 >= r1:
            continue
        X, Y = xs[None, c0:c1], ys[r0:r1, None]
        vx, vy = x1 - x0, y1 - y0
        t = np.clip(((X - x0) * vx + (Y - y0) * vy) / max(vx * vx + vy * vy, 1e-12), 0.0, 1.0)
        d = np.hypot(X - (x0 + t * vx), Y - (y0 + t * vy)).astype(np.float32)
        m = d < dist[r0:r1, c0:c1]
        dist[r0:r1, c0:c1][m] = d[m]
        sv[r0:r1, c0:c1][m] = (s[k] + t * (s[k + 1] - s[k]))[m]
        sg[r0:r1, c0:c1][m] = np.sign(vx * (Y - y0) - vy * (X - x0))[m]
    return dist, sv, sg


def nearest_points(path, X, Y):
    px, py, s = path
    x0, y0, vx, vy = px[:-1], py[:-1], np.diff(px), np.diff(py)
    L2 = np.maximum(vx * vx + vy * vy, 1e-12)
    seg = np.diff(s)
    N = len(X)
    best, bs, bg, cols = np.full(N, np.inf), np.zeros(N), np.zeros(N), np.arange(N)
    for a in range(0, len(x0), 256):
        sl = slice(a, a + 256)
        t = np.clip(((X[None, :] - x0[sl, None]) * vx[sl, None] + (Y[None, :] - y0[sl, None]) * vy[sl, None]) / L2[sl, None], 0, 1)
        d = np.hypot(X[None, :] - (x0[sl, None] + t * vx[sl, None]), Y[None, :] - (y0[sl, None] + t * vy[sl, None]))
        k = d.argmin(0)
        dm = d[k, cols]
        b = dm < best
        best[b] = dm[b]
        bs[b] = (s[sl][k] + t[k, cols] * seg[sl][k])[b]
        cr = vx[sl][k] * (Y - y0[sl][k]) - vy[sl][k] * (X - x0[sl][k])
        bg[b] = np.sign(cr)[b]
    return best, bs, bg


def _inside(poly, xs, ys):
    """even-odd على شبكة (نوافذ صفوف لكل ضلع)."""
    ins = np.zeros((len(ys), len(xs)), bool)
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if y0 == y1:
            continue
        rows = np.nonzero((ys >= min(y0, y1)) & (ys <= max(y0, y1)))[0]
        if not len(rows):
            continue
        r0, r1 = rows[0], rows[-1] + 1
        Y = ys[r0:r1, None]
        cond = ((y0 > Y) != (y1 > Y)) & (xs[None, :] < x0 + (x1 - x0) * (Y - y0) / (y1 - y0))
        ins[r0:r1] ^= cond
    return ins


# ───────────────────────── تضاريس نقطية ─────────────────────────
def _profile_pos(f, t):
    k = f.kind
    if k == "mountain":
        return {"cone": 1.0 - t, "dome": 1.0 - t * t, "rugged": (1.0 - t) ** 1.2}[f.shape]
    if k == "hill":
        return 0.5 * (1.0 + np.cos(np.pi * t))
    inner = f.inner_ratio
    if k == "plateau":
        return 1.0 - S(inner, 1.0, t)
    if k == "mesa":
        a = inner + 0.3 * (1.0 - inner)
        return 1.0 - 0.9 * S(inner, a, t) - 0.1 * S(a, 1.0, t)
    if k == "volcano":
        c = min(max(inner, 0.05), 0.9)
        return np.where(t < c, 1.0 - f.depth_ratio * (1.0 - (t / c) ** 2), ((1.0 - t) / (1.0 - c)) ** 1.6)
    if k == "island":
        return (1.0 - t * t) ** 1.5
    if k == "atoll":
        rr = min(max(inner, 0.4), 0.9)
        return (0.88 * np.exp(-((t - rr) / 0.14) ** 2) + 0.12 * (1.0 - S(rr, 1.0, t))) * (1.0 - S(0.92, 1.0, t))
    if k == "terraces":
        n = max(2, f.steps)
        s = (1.0 - t) * n
        fl = np.floor(s)
        return np.clip((fl + S(0.6, 1.0, s - fl)) / n, 0.0, 1.0)
    return (1.0 - t) ** 0.8                      # scree
    

def _apply_point(Zw, Xw, Yw, f):
    k = f.kind
    R = f.diameter_m / 2.0
    H = f.high_m - f.low_m
    if R <= 0 or (k != "dune" and H <= 0):
        return
    dx, dy = Xw - f.x_m, Yw - f.y_m
    d = np.sqrt(dx ** 2 + dy ** 2)
    warp = np.clip(fbm(Xw, Yw, 1.0 / (0.8 * R), 3, f.seed), -1, 1)
    Reff = R * (1.0 - 0.15 * f.roughness * (0.5 + 0.5 * warp))   # البصمة لا تتجاوز الدائرة أبداً
    t = np.clip(d / Reff, 0.0, 1.0).astype(np.float32)
    if not (t < 1.0).any():
        return
    det = fbm(Xw, Yw, 1.0 / (0.15 * R), 5, f.seed + 7)
    w = S(0.0, 0.05, 1.0 - t)
    Z0 = np.asarray(Zw, dtype=np.float32)
    r = f.roughness
    if k == "dune":                                 # صفوف غير متماثلة عمودية على الرياح، تتلاشى نحو الحافة
        lam, th = f.wavelength_m, math.radians(f.direction_deg)
        u = dx * math.sin(th) + dy * math.cos(th)
        ph = (u + 0.8 * lam * fbm(Xw, Yw, 1.0 / (3 * lam), 3, f.seed + 3)) / lam
        fr = ph - np.floor(ph)
        prof = np.where(fr < 0.7, S(0.0, 0.7, fr), 1.0 - S(0.7, 1.0, fr))
        amp = f.amplitude_m * (0.65 + 0.35 * (fbm(Xw, Yw, 1.0 / (4 * lam), 2, f.seed + 9) + 1) / 2)
        Zw[...] = Z0 + S(0.0, 0.25, 1.0 - t) * amp * prof
        return
    if k == "marsh":                                # تسوية + برك غير منتظمة
        pools = S(0.15, 0.55, (fbm(Xw, Yw, 1.0 / (0.18 * R), 4, f.seed + 3) + 1) / 2)
        M = f.high_m - H * pools
        Zw[...] = Z0 + w * (M - Z0) * 0.9
        return
    if k in POSITIVE:
        p = _profile_pos(f, t)
        gain = 1.6 if (k == "mountain" and f.shape == "rugged") else (0.5 if k == "hill" else (2.0 if k == "scree" else 1.0))
        dd = (1.0 - 2.0 * np.abs(det)) if k == "scree" else det      # ركام: تفاصيل حادة (ridged)
        M = f.low_m + H * p + r * 0.18 * H * gain * 4.0 * p * (1.0 - p) * dd
        if k == "delta":                            # قنوات موزعة تتفرع نحو اتجاه المصب
            th, n, cw = math.radians(f.direction_deg), max(1, f.steps), f.wavelength_m
            carve = np.zeros_like(t)
            for i in range(n):
                tk = th + math.radians(100) * ((i + 0.5) / n - 0.5)
                along = dx * math.sin(tk) + dy * math.cos(tk)
                lat = dx * math.cos(tk) - dy * math.sin(tk)
                carve = np.maximum(carve, np.exp(-(lat / cw) ** 2) * (along > 0) * S(0.1, 0.3, t))
            M = np.maximum(M - f.amplitude_m * carve * p, f.low_m)
        Zw[...] = Z0 + w * np.maximum(M - Z0, 0.0)
        return
    if k == "crater":
        rim, fl = 0.75, f.inner_ratio
        inner = f.low_m + H * S(fl, rim, t)
        apron = Z0 + (f.high_m - Z0) * (1.0 - S(rim, 1.0, t))
        new = np.where(t <= rim, inner, apron) + r * 0.05 * H * det * 4.0 * t * (1.0 - t)
        Zw[...] = np.where(t < 1.0, new, Z0)
        return
    if k == "basin":
        M = f.low_m + H * t * t
    elif k == "lake":
        M = f.low_m + H * S(f.inner_ratio, 1.0, t)
    else:                                           # sinkhole / cave: جدران شبه رأسية
        a = min(f.inner_ratio + 0.15, 0.99)
        M = f.low_m + H * (0.85 * S(f.inner_ratio, a, t) + 0.15 * S(a, 1.0, t))
    M = M + r * 0.08 * H * det * 4.0 * t * (1.0 - t)
    Zw[...] = Z0 + w * np.minimum(M - Z0, 0.0)


def _lerp(a, b, frac):
    return a + (b - a) * frac


def poi_pad(p):
    """منطقة اهتمام مسوّاة (حلبة زعيم…) تُعامل كموقع تسوية دائري."""
    return SimpleNamespace(id=p.id, kind="poi", name=p.name or p.id, x_m=p.x_m, y_m=p.y_m, shape="circle", diameter_m=2 * p.radius_m,
                           width_m=2 * p.radius_m, length_m=2 * p.radius_m, rotation_deg=0.0, level_mode="mean", level_m=0.0,
                           level_offset_m=0.0, blend_m=p.blend_m, strength=1.0, mat_ground=None, is_poi=True, density=0.0, seed=1)


class Engine:
    def __init__(self, project, step: float = 5.0):
        self.p = project
        self.step = max(0.5, float(step))
        pts = sorted(project.points, key=lambda f: -f.diameter_m)          # المضيف أولاً ثم ما بداخله
        lines = sorted(project.lines, key=lambda f: LINE_ORDER[f.kind])
        # طبيعي (نقطية + سلاسل/جروف/أودية) -> تعرية -> تفاصيل صغيرة -> تسوية مواقع -> طرق -> أنهار
        self.stages = [("point", f) for f in pts] + [("line", f) for f in lines if f.kind in ("ridge", "cliff", "valley")]
        self._ero_idx = None
        if project.erosion.enabled:
            self._ero_idx = len(self.stages)
            self.stages.append(("erosion", None))
        self.stages += [("relief", z) for z in project.zones if z.layer in RELIEF]
        self.stages += [("pad", s) for s in project.sites] + [("pad", poi_pad(p)) for p in project.pois if p.flatten and p.radius_m > 0]
        self.stages += [("line", f) for f in lines if f.kind in ("road", "river")]
        self._ero = None
        self._inf = None
        b = project.base
        self._terms = [(b.elevation_m, b.noise_amplitude_m, b.noise_scale_m, b.octaves, project.world.seed)]
        for i, bm in enumerate(project.biomes):
            self._terms.append((bm.base_elevation_m, bm.noise_amplitude_m, bm.noise_scale_m, bm.octaves, project.world.seed + 17 * (i + 1)))
        self._paths: Dict[str, object] = {}
        self._designs: Dict[int, object] = {}
        self._W = None

    # ── المناطق ──
    @staticmethod
    def _terrain(term, X, Y):
        e, a, sc, o, seed = term
        z = np.zeros(np.broadcast(X, Y).shape, np.float32) + np.float32(e)
        if a > 0:
            z += a * fbm(X, Y, 1.0 / sc, o, seed)
        return z

    def _biome_maps(self):
        if self._W is None:
            w = self.p.world
            xsC, ysC = grid_axes(w.size_x_m, w.size_y_m, 1025)
            Ws = []
            for b in self.p.biomes:
                poly = [tuple(q) for q in b.polygon]
                # الأضلاع المنطبقة على حدود العالم لا تُحسب: لا انتقال مع «لا شيء» عند حافة العالم
                Lx, Ly = w.size_x_m, w.size_y_m
                def on_border(p, q):
                    return any(abs(p[a] - v) < 1e-6 and abs(q[a] - v) < 1e-6 for a, v in ((0, 0.0), (0, Lx), (1, 0.0), (1, Ly)))
                runs, cur = [], []
                for j in range(len(poly)):
                    p, q = poly[j], poly[(j + 1) % len(poly)]
                    if on_border(p, q):
                        if cur: runs.append(cur); cur = []
                        continue
                    cur = (cur or [p]) + [q]
                if cur: runs.append(cur)
                dist = np.full((len(ysC), len(xsC)), np.inf, np.float32)
                for run in runs:
                    ring = np.asarray(run, float)
                    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(ring, axis=0).T))]
                    dist = np.minimum(dist, nearest_grid((ring[:, 0], ring[:, 1], s), xsC, ysC, b.blend_m)[0])
                sd = np.where(_inside(poly, np.clip(xsC, 1e-6, Lx - 1e-6), np.clip(ysC, 1e-6, Ly - 1e-6)), dist, -dist)   # نقاط حدود العالم تُعدّ داخلاً
                Ws.append(S(-b.blend_m / 2, b.blend_m / 2, sd).astype(np.float32))
            self._W = (xsC, ysC, Ws)
        return self._W

    def _w_grid(self, i, xs, ys):
        xsC, ysC, Ws = self._biome_maps()
        w = self.p.world
        nxC, nyC = len(xsC), len(ysC)
        ci = np.clip(xs / (w.size_x_m / (nxC - 1)), 0, nxC - 1)
        i0 = np.minimum(ci.astype(int), nxC - 2); fx = (ci - i0).astype(np.float32)
        rj = np.clip((w.size_y_m - ys) / (w.size_y_m / (nyC - 1)), 0, nyC - 1)
        j0 = np.minimum(rj.astype(int), nyC - 2); fy = (rj - j0).astype(np.float32)
        Wm = Ws[i]
        T = Wm[:, i0] * (1 - fx)[None, :] + Wm[:, i0 + 1] * fx[None, :]
        return T[j0, :] * (1 - fy)[:, None] + T[j0 + 1, :] * fy[:, None]

    def _w_points(self, i, X, Y):
        xsC, ysC, Ws = self._biome_maps()
        w = self.p.world
        ci = np.clip(X / (w.size_x_m / (len(xsC) - 1)), 0, len(xsC) - 1)
        rj = np.clip((w.size_y_m - Y) / (w.size_y_m / (len(ysC) - 1)), 0, len(ysC) - 1)
        return map_coordinates(Ws[i], [rj, ci], order=1, mode="nearest").astype(np.float32)

    def _bbox(self, b, xs, ys):
        P = np.asarray(b.polygon, float)
        m = b.blend_m / 2 + 1e-6
        cols = np.nonzero((xs >= P[:, 0].min() - m) & (xs <= P[:, 0].max() + m))[0]
        rows = np.nonzero((ys >= P[:, 1].min() - m) & (ys <= P[:, 1].max() + m))[0]
        return (rows[0], rows[-1] + 1, cols[0], cols[-1] + 1) if len(cols) and len(rows) else None

    # ── الأرض الافتراضية: مستوية / ضوضاء بسعة / ضوضاء بنطاق ارتفاع منسجمة مع المعالم ──
    def _detail_amp(self):
        b = self.p.base
        return 0.0 if b.noise_mode == "off" else (b.noise_amplitude_m if b.noise_mode == "amplitude" else 0.1 * abs(b.noise_max_m - b.noise_min_m))

    def _influence(self):
        """خريطة تأثير عالمية [-1,1]: موجبة قرب المعالم الأعلى من منسوب العالم (جبال، سلاسل) وسالبة قرب الأخفض (وديان، بحيرات)."""
        if self._inf is None:
            w, b = self.p.world, self.p.base
            xs, ys = grid_axes(w.size_x_m, w.size_y_m, 257)
            X, Y = xs[None, :], ys[:, None]
            ref, rng = b.elevation_m, max(abs(b.noise_max_m - b.noise_min_m), 1.0)
            I = np.zeros((len(ys), len(xs)), np.float32)
            for f in self.p.points:
                if f.kind == "dune":
                    continue
                d = f.high_m if f.kind in POSITIVE else f.low_m
                sg, sig = math.tanh((d - ref) / (2 * rng)), 2.0 * f.diameter_m / 2
                cols = np.nonzero(np.abs(xs - f.x_m) <= 3 * sig)[0]; rows = np.nonzero(np.abs(ys - f.y_m) <= 3 * sig)[0]
                if len(cols) and len(rows):
                    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                    I[r0:r1, c0:c1] += sg * np.exp(-((np.hypot(X[:, c0:c1] - f.x_m, Y[r0:r1] - f.y_m) / sig) ** 2))
            for f in self.p.lines:
                if f.kind not in ("valley", "ridge"):
                    continue
                path = self._path(f)
                if path is None:
                    continue
                d = (f.floor_m - ref) if (f.kind == "valley" and f.floor_m is not None) else (-f.depth_m if f.kind == "valley" else
                    ((f.top_m - ref) if f.top_m is not None else f.depth_m))
                sig = 3.0 * f.width_m
                dist, _, _ = nearest_grid(path, xs, ys, 3 * sig)
                I += (math.tanh(d / (2 * rng)) * np.exp(-np.where(np.isfinite(dist), dist / sig, 99.0) ** 2)).astype(np.float32)
            self._inf = np.tanh(I).astype(np.float32)
        return self._inf

    def _range_field(self, n, I):
        b = self.p.base
        v = b.noise_bias * I + (1.0 - b.noise_bias * np.abs(I)) * np.clip(1.7 * n, -1, 1)
        return (b.noise_min_m + (b.noise_max_m - b.noise_min_m) * (0.5 + 0.5 * np.clip(v, -1, 1))).astype(np.float32)

    def _default_grid(self, xs, ys):
        b, w = self.p.base, self.p.world
        if b.noise_mode == "off":
            return np.full((len(ys), len(xs)), b.elevation_m, np.float32)
        if b.noise_mode == "amplitude":
            return self._terrain(self._terms[0], xs[None, :], ys[:, None])
        n = fbm(xs[None, :], ys[:, None], 1.0 / b.noise_scale_m, b.octaves, w.seed)
        return self._range_field(n, sample_grid(self._influence(), w.size_x_m, w.size_y_m, xs, ys))

    def _default_points(self, X, Y):
        b, w = self.p.base, self.p.world
        if b.noise_mode == "off":
            return np.full(np.broadcast(X, Y).shape, b.elevation_m, np.float32)
        if b.noise_mode == "amplitude":
            return self._terrain(self._terms[0], X, Y)
        return self._range_field(fbm(X, Y, 1.0 / b.noise_scale_m, b.octaves, w.seed), sample_points(self._influence(), w.size_x_m, w.size_y_m, X, Y))

    def _base_grid(self, xs, ys):
        if not self.p.biomes:
            return self._default_grid(xs, ys)
        tot = np.zeros((len(ys), len(xs)), np.float32)
        wins = []
        for i, b in enumerate(self.p.biomes):
            bb = self._bbox(b, xs, ys)
            if bb is None:
                wins.append(None); continue
            r0, r1, c0, c1 = bb
            wi = self._w_grid(i, xs[c0:c1], ys[r0:r1])
            tot[r0:r1, c0:c1] += wi
            wins.append((bb, wi))
        n0 = np.clip(1.0 - tot, 0.0, None)
        norm = n0 + tot
        Z = (n0 / norm) * self._default_grid(xs, ys)
        for i, item in enumerate(wins):
            if item:
                (r0, r1, c0, c1), wi = item
                Z[r0:r1, c0:c1] += (wi / norm[r0:r1, c0:c1]) * self._terrain(self._terms[i + 1], xs[None, c0:c1], ys[r0:r1, None])
        return Z

    def _base_points(self, X, Y):
        if not self.p.biomes:
            return self._default_points(X, Y)
        ws = [self._w_points(i, X, Y) for i in range(len(self.p.biomes))]
        tot = sum(ws)
        n0 = np.clip(1.0 - tot, 0.0, None)
        norm = n0 + tot
        Z = (n0 / norm) * self._default_points(X, Y)
        for i, wi in enumerate(ws):
            Z += (wi / norm) * self._terrain(self._terms[i + 1], X, Y)
        return Z

    def _clamp(self, Z, wfun):
        for i, b in enumerate(self.p.biomes):
            if b.clamp and (b.min_elev_m is not None or b.max_elev_m is not None):
                lo = -np.inf if b.min_elev_m is None else b.min_elev_m
                hi = np.inf if b.max_elev_m is None else b.max_elev_m
                wi = wfun(i)
                Z += wi * (np.clip(Z, lo, hi) - Z)

    # ── الخلايا: مستويات ميل مدموجة بنعومة (تقسيم وحدة: مجموع الأوزان = 1) ──
    def _cell_terms(self, c):
        w, b = self.p.world, self.p.base
        cs = w.cell_size_m
        sl, a = c.rise_m / c.run_m, math.radians(c.aspect_deg)
        return (c.col + 0.5) * cs, w.size_y_m - (c.row + 0.5) * cs, sl * math.sin(a), sl * math.cos(a)

    def _hat(self, u):
        tau = self.p.base.cell_blend
        return 1.0 - S(0.5 - tau, 0.5 + tau, np.abs(u))

    def _cell_target(self, c, Xw, Yw, cx, cy, gx, gy):
        b = self.p.base
        P = c.elevation_m + gx * (Xw - cx) + gy * (Yw - cy)
        if b.cell_detail > 0 and self._detail_amp() > 0:
            P = P + b.cell_detail * self._detail_amp() * fbm(Xw, Yw, 1.0 / b.noise_scale_m, b.octaves, self.p.world.seed + 5)
        return P

    def _cells_grid(self, Z, xs, ys):
        if not self.p.cells:
            return
        w, b = self.p.world, self.p.base
        cs = w.cell_size_m
        ext = (0.5 + b.cell_blend) * cs
        D = np.zeros_like(Z)
        for c in self.p.cells:
            cx, cy, gx, gy = self._cell_terms(c)
            cols = np.nonzero(np.abs(xs - cx) <= ext)[0]
            rows = np.nonzero(np.abs(ys - cy) <= ext)[0]
            if not (len(cols) and len(rows)):
                continue
            r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
            Xw, Yw = xs[None, c0:c1], ys[r0:r1, None]
            Om = self._hat((Xw - cx) / cs) * self._hat((Yw - cy) / cs)
            D[r0:r1, c0:c1] += (Om * (self._cell_target(c, Xw, Yw, cx, cy, gx, gy) - Z[r0:r1, c0:c1])).astype(np.float32)
        Z += D

    def _cells_points(self, Z, X, Y):
        if not self.p.cells:
            return
        cs = self.p.world.cell_size_m
        ext = (0.5 + self.p.base.cell_blend) * cs
        D = np.zeros_like(Z)
        for c in self.p.cells:
            cx, cy, gx, gy = self._cell_terms(c)
            m = (np.abs(X - cx) <= ext) & (np.abs(Y - cy) <= ext)
            if m.any():
                Om = self._hat((X[m] - cx) / cs) * self._hat((Y[m] - cy) / cs)
                D[m] += Om * (self._cell_target(c, X[m], Y[m], cx, cy, gx, gy) - Z[m])
        Z += D

    # ── مسارات وتصاميم ──
    def _path(self, f):
        if f.id not in self._paths:
            self._paths[f.id] = smooth_path(f.points, self.step)
        return self._paths[f.id]

    def _design(self, idx):
        if idx in self._designs:
            return self._designs[idx]
        f = self.stages[idx][1]
        res = None
        dstep = max(5.0, 0.5 * f.width_m)
        dp = smooth_path(f.points, dstep)
        if dp is not None:
            px, py, s = dp
            L = float(s[-1])
            st = np.linspace(0.0, L, int(np.clip(L / dstep + 1, 2, 2500)))
            sx, sy = np.interp(st, s, px), np.interp(st, s, py)
            g = self.points(sx, sy, upto=idx)
            res = getattr(self, "_design_" + f.kind)(f, st, g, L)
            res.update(s=st, ground=g, L=L, x=sx, y=sy)
        self._designs[idx] = res
        return res

    def _w(self, f, st, L, a, b):
        return _lerp(a, a if b is None else b, st / max(L, 1e-9))

    def _design_river(self, f, st, g, L):
        dep = self._w(f, st, L, f.depth_m, f.depth_end_m)
        off = np.zeros_like(st)
        for fl in f.falls:                          # شلال: يهبط القاع بمقدار الارتفاع على طول الطول المحدد
            s0 = fl.at * L
            off += fl.height_m * S(s0 - fl.length_m / 2, s0 + fl.length_m / 2, st)
        ds = L / max(len(st) - 1, 1)
        wd = max(f.width_m, f.width_end_m or f.width_m)
        gs = uniform_filter1d(g, size=min(5, len(g)), mode="nearest")
        warn = []
        if gs[-1] > gs[0] + 0.5:
            warn.append(f"النهر {f.id}: المصب أعلى من المنبع بـ {gs[-1] - gs[0]:.1f} م — بدّل الاتجاه.")
        if f.grade_mode == "regrade":
            # ضبط مناسيب الأرض: منحنى قاع هابط ناعم أقرب ما يكون للأرض (انحدار متساوي الاتجاه)، ثم تُزاح الأرض حول
            # المجرى بالفرق (قطع/ردم) بدل حفر خندق. القناة نفسها تُحفر نسبةً للأرض المُسوّاة فقط.
            k = max(3, int(round(60.0 / max(ds, 1e-6))))
            k += 1 - k % 2
            sm = uniform_filter1d(g, size=min(k, len(g)), mode="nearest")
            m = f.min_slope
            G = _iso_nonincreasing(sm + m * st) - m * st
            G = np.minimum.accumulate(uniform_filter1d(G, size=min(2 * k + 1, len(G)), mode="nearest")) - off
            delta = G - g
            bed = np.minimum.accumulate(G - dep)
            cut, fill = max(-float(delta.min()), 0.0), max(float(delta.max()), 0.0)
            if max(cut, fill) > 15:
                warn.append(f"النهر {f.id}: ضبط مناسيب الأرض يتطلب قطعاً حتى {cut:.0f} م وردماً حتى {fill:.0f} م — فكّر في تغيير المسار أو المنبع/المصب.")
            reach = wd / 2 + dep.max() * 2.5 + max(cut, fill) / RIVER_BANK_SLOPE * 1.25 + f.grade_width_m + 1.0
            return dict(kind="river", mode="regrade", bed=bed, G=G, delta=delta, warnings=warn, reach=reach)
        raw = g - dep - off
        bed = raw.copy()
        if f.enforce_descent:
            for i in range(1, len(bed)):
                bed[i] = min(raw[i], bed[i - 1] - f.min_slope * (st[i] - st[i - 1]))
        rise = gs - np.minimum.accumulate(gs)
        fix = "غيّر المسار ليتبع الانحدار أو بدّل المنبع والمصب." + (" (الأداة تحفر خندقاً ليبقى القاع هابطاً.)" if f.enforce_descent else " (فرض الانحدار معطّل فالقاع يتبع الأرض كما هي.)")
        if rise.max() > 1.0:
            ix = np.nonzero(rise > 1.0)[0]
            warn.append(f"النهر {f.id}: المسار يصعد بين {st[ix[0]]:.0f} و{st[ix[-1]]:.0f} م من المنبع (أقصى صعود {rise.max():.1f} م) والماء لا يصعد. {fix}")
        if (g - bed).max() > 3 * max(dep.max() + off.max(), 1.0) + 2:
            warn.append(f"النهر {f.id}: أقصى عمق حفر {(g - bed).max():.1f} م (أكبر بكثير من عمق القناة) بسبب فرض الانحدار.")
        return dict(kind="river", mode="carve", bed=bed, warnings=warn, reach=wd / 2 + (dep.max() + off.max()) * 2.5 + 1.0)

    def _design_road(self, f, st, g, L):
        ds = L / max(len(st) - 1, 1)
        k = max(1, int(round(30.0 / max(ds, 1e-6))))
        z = uniform_filter1d(g, size=2 * k + 1, mode="nearest").tolist()
        lim = (f.max_grade * np.diff(st)).tolist()
        n = len(z)
        for _ in range(80):
            old = list(z)
            for i in range(1, n):
                z[i] = min(max(z[i], z[i - 1] - lim[i - 1]), z[i - 1] + lim[i - 1])
            for i in range(n - 2, -1, -1):
                z[i] = min(max(z[i], z[i + 1] - lim[i]), z[i + 1] + lim[i])
            if max(abs(a - b) for a, b in zip(z, old)) < 1e-3:
                break
        z = np.asarray(z)
        warn = []
        if np.abs(z - g).max() > 6.0:
            warn.append(f"الطريق {f.id}: قطع/ردم يصل إلى {np.abs(z - g).max():.1f} م — فكّر في تغيير المسار.")
        return dict(kind="road", z=z, bed=z, warnings=warn, reach=f.width_m / 2 + f.shoulder_m + 1.0)

    def _design_valley(self, f, st, g, L):
        return dict(kind="valley", warnings=[], reach=f.width_m / 2 + 1.0)

    _design_ridge = _design_valley

    def _design_cliff(self, f, st, g, L):
        return dict(kind="cliff", warnings=[], reach=f.width_m / 2 + f.shoulder_m + 1.0)

    def design_warnings(self) -> List[str]:
        out: List[str] = []
        sea = self.p.world.sea_level_m
        for i, (typ, f) in enumerate(self.stages):
            if typ == "line":
                d = self._design(i)
                if d:
                    out += d["warnings"]
            elif typ == "pad":
                d = self._site_design(i)
                if d["level"] < sea + 0.5:
                    out.append(f"الموقع {f.id}: منسوب التسوية ({d['level']:.1f}م) عند مستوى البحر أو دونه.")
                if max(d["cut"], d["fill"]) > max(8.0, 0.12 * site_ext(f)):
                    out.append(f"الموقع {f.id}: التسوية كبيرة (قطع حتى {d['cut']:.0f} م وردم حتى {d['fill']:.0f} م) — الأرض شديدة الميل هنا، فكّر في موضع آخر.")
        return out

    def waterfalls(self):
        out = []
        for i, (typ, f) in enumerate(self.stages):
            if typ == "line" and f.kind == "river" and f.falls:
                d = self._design(i)
                for fl in f.falls:
                    s0 = fl.at * d["L"]
                    out.append(dict(river=f.id, x_m=float(np.interp(s0, d["s"], d["x"])), y_m=float(np.interp(s0, d["s"], d["y"])),
                                    height_m=fl.height_m, length_m=fl.length_m))
        return out

    def linear_info(self, maxn=300):
        out = []
        for i, (typ, f) in enumerate(self.stages):
            if typ != "line":
                continue
            d = self._design(i)
            if not d:
                continue
            ix = np.unique(np.linspace(0, len(d["s"]) - 1, min(maxn, len(d["s"]))).astype(int))
            out.append(dict(id=f.id, kind=f.kind, length_m=d["L"], s=d["s"][ix].tolist(), ground=d["ground"][ix].tolist(),
                            x=d["x"][ix].tolist(), y=d["y"][ix].tolist(), design=(d["bed"][ix].tolist() if "bed" in d else None)))
        return out

    # ── تطبيق الخطي ──
    def _carve(self, f, d, z, dist, s, side, X, Y):
        L = d["L"]
        fr = np.clip(s / max(L, 1e-9), 0, 1)
        k = f.kind
        if k == "river":
            if d["mode"] == "regrade":              # إزاحة مناسيب الأرض حول المجرى (قطع/ردم ناعم) قبل حفر القناة
                Gs = np.interp(s, d["s"], d["G"])
                off_d = np.maximum(dist - _lerp(f.width_m, f.width_end_m or f.width_m, fr) / 2, 0.0)
                # وادٍ مُسوّى: قطع للضفاف بميل ثابت حيث الأرض أعلى، وردم (جسر ترابي) حيث أخفض، فيستقر النهر في أخفض نقطة
                z2 = np.maximum(np.minimum(z, Gs + RIVER_BANK_SLOPE * off_d), Gs - RIVER_BANK_SLOPE * off_d)
                z = z + (1.0 - S(0.85 * d["reach"], d["reach"], dist)) * (z2 - z)
            bed = np.interp(s, d["s"], d["bed"])
            hw = _lerp(f.width_m, f.width_end_m or f.width_m, fr) / 2
            dp = _lerp(f.depth_m, f.depth_end_m if f.depth_end_m is not None else f.depth_m, fr)
            bank = np.maximum(dp * 2.5, 1.0) if d["mode"] == "regrade" else np.maximum(np.maximum(dp * 2.5, 1.5 * np.maximum(z - bed, 0)), 1.0)
            u = np.clip((dist - hw) / bank, 0, 1)
            return np.minimum(z, bed + np.maximum(z - bed, 0) * S01(u))
        if k == "road":
            zr = np.interp(s, d["s"], d["z"])
            u = np.clip((dist - f.width_m / 2) / max(f.shoulder_m, 1e-3), 0, 1)
            return zr + (z - zr) * S01(u)
        taper = S(0.0, max(min(f.width_m / 2, L / 2), 1e-6), np.minimum(s, L - s))
        amt = _lerp(f.depth_m, f.depth_end_m if f.depth_end_m is not None else f.depth_m, fr)
        if k == "cliff":                            # الجهة اليسرى مرتفعة: انتقال حاد ثم حافة تتلاشى
            hw = max(f.width_m / 2, 0.5)
            sd = side * dist
            return z + amt * S(-hw, hw, sd) * (1.0 - S(hw, hw + max(f.shoulder_m, 1e-3), sd)) * taper
        W = _lerp(f.width_m, f.width_end_m or f.width_m, fr)
        u = np.clip(dist / (W / 2), 0, 1)
        prof = (1 - u) if f.profile == "v" else S01(1 - u)
        if k == "valley":
            if f.floor_m is not None:                # منسوب قاع مطلق: تنخفض الأرض إليه (مثلاً 200 -> 50 = هبوط 150 م)
                return z + prof * taper * (np.minimum(f.floor_m, z) - z)
            return z - amt * prof * taper
        if f.top_m is not None:                      # منسوب قمة مطلق للسلسلة
            amt = np.maximum(f.top_m - z, 0.0)
        amt = amt * (1.0 + 0.35 * f.roughness * fbm(X, Y, 1.0 / (1.5 * f.width_m + 1.0), 3, f.seed))
        return z + amt * prof * taper

    def _apply_line_grid(self, Z, idx, xs, ys):
        f = self.stages[idx][1]
        path, d = self._path(f), self._design(idx)
        if path is None or d is None:
            return
        dist, sv, sg = nearest_grid(path, xs, ys, d["reach"])
        rr, cc = np.nonzero(dist < d["reach"])
        if len(rr):
            Z[rr, cc] = self._carve(f, d, Z[rr, cc], dist[rr, cc], sv[rr, cc], sg[rr, cc], xs[cc], ys[rr])

    def _apply_line_points(self, Z, idx, X, Y):
        f = self.stages[idx][1]
        path, d = self._path(f), self._design(idx)
        if path is None or d is None:
            return
        dist, sv, sg = nearest_points(path, X, Y)
        m = dist < d["reach"]
        if m.any():
            Z[m] = self._carve(f, d, Z[m], dist[m], sv[m], sg[m], X[m], Y[m])

    # ── التعرية / المواقع / التفاصيل ──
    def _ero_key(self):
        p = self.p
        blob = json.dumps({"w": p.world.model_dump(), "b": p.base.model_dump(), "bio": [x.model_dump() for x in p.biomes],
                           "c": [c.model_dump() for c in p.cells], "s": [f.model_dump() for _, f in self.stages[:self._ero_idx]],
                           "e": p.erosion.model_dump()}, sort_keys=True, default=str)
        return hashlib.md5(blob.encode()).hexdigest()

    def _ero_delta(self):
        """فرق التعرية العالمي (يُخزَّن مؤقتاً): يعتمد على الأرض الطبيعية فقط، فتعديل الأنهار/الطرق/المواقع لا يعيد الحساب."""
        if self._ero is None:
            key = self._ero_key()
            hit = _ERO_CACHE.get(key)
            if hit is None:
                w, e = self.p.world, self.p.erosion
                xs, ys = grid_axes(w.size_x_m, w.size_y_m, e.resolution)
                Z = self._run_grid(xs, ys, upto=self._ero_idx)
                hit = (xs, ys, (erode(Z, xs[1] - xs[0], ys[0] - ys[1], e) - Z).astype(np.float32))
                if len(_ERO_CACHE) >= 4:
                    _ERO_CACHE.pop(next(iter(_ERO_CACHE)))
                _ERO_CACHE[key] = hit
            self._ero = hit
        return self._ero[2]

    def _site_design(self, idx):
        if idx in self._designs:
            return self._designs[idx]
        s = self.stages[idx][1]
        ext = site_ext(s)
        g = np.linspace(-ext, ext, 25)
        GX, GY = np.meshgrid(g, g)
        X, Y = s.x_m + GX.ravel(), s.y_m + GY.ravel()
        m = site_sd(s, X, Y) <= 0
        if m.sum() < 3:
            m[:] = True
        Zs = self.points(X[m], Y[m], upto=idx)
        lvl = {"mean": float(Zs.mean()), "min": float(Zs.min()), "max": float(Zs.max()), "fixed": s.level_m}[s.level_mode] + s.level_offset_m
        d = dict(level=lvl, ground_min=float(Zs.min()), ground_max=float(Zs.max()), ground_mean=float(Zs.mean()),
                 cut=max(float(Zs.max()) - lvl, 0.0), fill=max(lvl - float(Zs.min()), 0.0))
        self._designs[idx] = d
        return d

    @staticmethod
    def _relief_pattern(z, X, Y):
        n = fbm(X, Y, 1.0 / z.wavelength_m, 3, z.seed)
        return n if z.layer == "hummocks" else (1.0 - 2.0 * np.abs(n))

    def _pad_grid(self, Z, idx, xs, ys):
        s, d = self.stages[idx][1], self._site_design(idx)
        ext = site_ext(s) + s.blend_m
        cols = np.nonzero(np.abs(xs - s.x_m) <= ext)[0]
        rows = np.nonzero(np.abs(ys - s.y_m) <= ext)[0]
        if not (len(cols) and len(rows)):
            return
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        w = s.strength * (1.0 - S(0.0, s.blend_m, site_sd(s, xs[None, c0:c1], ys[r0:r1, None])))
        win = Z[r0:r1, c0:c1]
        win += (w * (d["level"] - win)).astype(np.float32)

    def _pad_points(self, Z, idx, X, Y):
        s, d = self.stages[idx][1], self._site_design(idx)
        Z += (s.strength * (1.0 - S(0.0, s.blend_m, site_sd(s, X, Y)))) * (d["level"] - Z)

    def _relief_grid(self, Z, z, xs, ys):
        P = np.asarray(z.polygon, float)
        cols = np.nonzero((xs >= P[:, 0].min() - 1) & (xs <= P[:, 0].max() + 1))[0]
        rows = np.nonzero((ys >= P[:, 1].min() - 1) & (ys <= P[:, 1].max() + 1))[0]
        if not (len(cols) and len(rows)):
            return
        r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        Xw, Yw = xs[None, c0:c1], ys[r0:r1, None]
        w = poly_weight_grid(z.polygon, xs[c0:c1], ys[r0:r1], z.falloff_m)
        Z[r0:r1, c0:c1] += (w * z.density * z.amplitude_m * self._relief_pattern(z, Xw, Yw)).astype(np.float32)

    def _relief_points(self, Z, z, X, Y):
        Z += poly_weight_points(z.polygon, X, Y, z.falloff_m) * z.density * z.amplitude_m * self._relief_pattern(z, X, Y)

    def exclusion(self, xs, ys, Z):
        """1 = لا نباتات: تحت الماء، بحيرات، مواقع (مسوّاة)، طرق، مجاري أنهار."""
        ex = (Z < self.p.world.sea_level_m - 0.05).astype(np.float32)
        for i, (typ, f) in enumerate(self.stages):
            if typ == "point" and f.kind == "lake":
                R = f.diameter_m / 2
                cols = np.nonzero(np.abs(xs - f.x_m) <= R)[0]; rows = np.nonzero(np.abs(ys - f.y_m) <= R)[0]
                if len(cols) and len(rows):
                    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                    ex[r0:r1, c0:c1] = np.maximum(ex[r0:r1, c0:c1], (np.hypot(xs[None, c0:c1] - f.x_m, ys[r0:r1, None] - f.y_m) < R * 0.95).astype(np.float32))
            elif typ == "pad":
                ext = site_ext(f)
                cols = np.nonzero(np.abs(xs - f.x_m) <= ext + f.blend_m)[0]; rows = np.nonzero(np.abs(ys - f.y_m) <= ext + f.blend_m)[0]
                if len(cols) and len(rows):
                    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                    ex[r0:r1, c0:c1] = np.maximum(ex[r0:r1, c0:c1], (site_sd(f, xs[None, c0:c1], ys[r0:r1, None]) <= f.blend_m * 0.15).astype(np.float32))
            elif typ == "line" and f.kind in ("road", "river"):
                path, d = self._path(f), self._design(i)
                if path is None or d is None:
                    continue
                hw = f.width_m / 2 + (f.shoulder_m * 0.5 if f.kind == "road" else 2.0)
                dist, _, _ = nearest_grid(path, xs, ys, hw + 1)
                ex[dist < hw] = 1.0
        return ex

    # ── واجهات الحساب ──
    def _apply_grid(self, Z, i, typ, f, xs, ys):
        w = self.p.world
        if typ == "point":
            R = f.diameter_m / 2.0
            cols = np.nonzero(np.abs(xs - f.x_m) <= R)[0]
            rows = np.nonzero(np.abs(ys - f.y_m) <= R)[0]
            if len(cols) and len(rows):
                r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                _apply_point(Z[r0:r1, c0:c1], xs[None, c0:c1], ys[r0:r1, None], f)
        elif typ == "line":
            self._apply_line_grid(Z, i, xs, ys)
        elif typ == "erosion":
            Z += sample_grid(self._ero_delta(), w.size_x_m, w.size_y_m, xs, ys)
        elif typ == "relief":
            self._relief_grid(Z, f, xs, ys)
        elif typ == "pad":
            self._pad_grid(Z, i, xs, ys)

    def _run_grid(self, xs, ys, upto=None):
        Z = self._base_grid(xs, ys)
        self._cells_grid(Z, xs, ys)
        for i, (typ, f) in enumerate(self.stages if upto is None else self.stages[:upto]):
            self._apply_grid(Z, i, typ, f, xs, ys)
        return Z

    def grid(self, xs, ys):
        Z = self._run_grid(xs, ys)

        def wf(i):
            bb = self._bbox(self.p.biomes[i], xs, ys)
            full = np.zeros_like(Z)
            if bb:
                r0, r1, c0, c1 = bb
                full[r0:r1, c0:c1] = self._w_grid(i, xs[c0:c1], ys[r0:r1])
            return full
        self._clamp(Z, wf)
        return Z

    def points(self, X, Y, upto=None):
        X, Y = np.asarray(X, float), np.asarray(Y, float)
        w = self.p.world
        Z = self._base_points(X, Y)
        self._cells_points(Z, X, Y)
        for i, (typ, f) in enumerate(self.stages if upto is None else self.stages[:upto]):
            if typ == "point":
                _apply_point(Z, X, Y, f)
            elif typ == "line":
                self._apply_line_points(Z, i, X, Y)
            elif typ == "erosion":
                Z += sample_points(self._ero_delta(), w.size_x_m, w.size_y_m, X, Y)
            elif typ == "relief":
                self._relief_points(Z, f, X, Y)
            elif typ == "pad":
                self._pad_points(Z, i, X, Y)
        if upto is None:
            self._clamp(Z, lambda i: self._w_points(i, X, Y))
        return Z

    def profile(self, p0, p1, n):
        t = np.linspace(0.0, 1.0, n)
        X, Y = p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])
        return t * math.hypot(p1[0] - p0[0], p1[1] - p0[1]), self.points(X, Y)

    def biome_issues(self, Z, xs, ys):
        """حدود الارتفاع لكل منطقة (على شبكة المعاينة). يعيد (أخطاء، تحذيرات)."""
        err, warn = [], []
        for i, b in enumerate(self.p.biomes):
            if b.clamp or (b.min_elev_m is None and b.max_elev_m is None):
                continue
            m = self._w_grid(i, xs, ys) > 0.98       # قلب المنطقة فقط (منطقة الانتقال تخص الاثنتين)
            if not m.any():
                continue
            zz = np.where(m, Z, np.nan)
            if b.max_elev_m is not None and np.nanmax(zz) > b.max_elev_m + 0.5:
                r, c = np.unravel_index(np.nanargmax(zz), zz.shape)
                err.append(f"المنطقة «{b.name}»: الارتفاع {np.nanmax(zz):.1f} م عند ({xs[c]:.0f}, {ys[r]:.0f}) أعلى من حدها الأقصى {b.max_elev_m:g} م — عدّل التضاريس أو فعّل «قصّ تلقائي».")
            if b.min_elev_m is not None and np.nanmin(zz) < b.min_elev_m - 0.5:
                r, c = np.unravel_index(np.nanargmin(zz), zz.shape)
                err.append(f"المنطقة «{b.name}»: الارتفاع {np.nanmin(zz):.1f} م عند ({xs[c]:.0f}, {ys[r]:.0f}) أدنى من حدها الأدنى {b.min_elev_m:g} م — عدّل التضاريس أو فعّل «قصّ تلقائي».")
        return err, warn


def engine_for(project, resolution: int) -> Engine:
    w = project.world
    return Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (resolution - 1))


def _poly_area(P):
    x, y = np.asarray(P, float).T
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def validate(project, engine: Engine, Z=None, xs=None, ys=None) -> Tuple[List[str], List[str]]:
    """(أخطاء تمنع التصدير، تحذيرات). Z اختياري: لفحص حدود المناطق (وإلا يُحسب بدقة 513)."""
    err: List[str] = []
    warn: List[str] = []
    w = project.world
    P = project.points
    for i, a in enumerate(P):
        for b in P[i + 1:]:
            d, ra, rb = math.hypot(a.x_m - b.x_m, a.y_m - b.y_m), a.diameter_m / 2, b.diameter_m / 2
            if d >= ra + rb - 1e-6:
                continue
            if d + rb <= ra + 1e-6:
                host, child = a, b
            elif d + ra <= rb + 1e-6:
                host, child = b, a
            else:
                err.append(f"تداخل جزئي بين {a.id} ({LABELS[a.kind]}) و{b.id} ({LABELS[b.kind]}): المسافة بين المركزين {d:.0f} م. يُسمح فقط بالتلامس أو بأن يقع أحدهما بكامله داخل الآخر عندما يكون ذلك منطقياً.")
                continue
            if child.kind not in NEST.get(host.kind, []):
                err.append(f"تداخل غير منطقي: {child.id} ({LABELS[child.kind]}) داخل {host.id} ({LABELS[host.kind]}).")
    for a in P:
        pos = a.kind in POSITIVE
        if a.kind != "dune" and a.high_m <= a.low_m:
            warn.append(f"{a.id}: القيمة العليا ({a.high_m:g}م) ليست أعلى من السفلى ({a.low_m:g}م) — سيُتجاهل.")
        if not (0 <= a.x_m <= w.size_x_m and 0 <= a.y_m <= w.size_y_m):
            warn.append(f"{a.id}: المركز خارج حدود العالم.")
        elif (a.x_m - a.diameter_m / 2 < 0 or a.x_m + a.diameter_m / 2 > w.size_x_m or
              a.y_m - a.diameter_m / 2 < 0 or a.y_m + a.diameter_m / 2 > w.size_y_m):
            warn.append(f"{a.id}: البصمة تتجاوز حدود العالم (ستُقصّ).")
        if pos and a.low_m < project.base.elevation_m - project.base.noise_amplitude_m and a.high_m > a.low_m and not project.biomes:
            warn.append(f"{a.id}: أدنى نقطة ({a.low_m:g}م) أقل من الأرض المحيطة (~{project.base.elevation_m:g}م) — ستبدو البصمة المرئية أصغر من القطر.")
        if a.diameter_m < w.cell_size_m:
            warn.append(f"{a.id}: القطر أصغر من خلية الشبكة ({w.cell_size_m:g}م).")
    nc, nr = math.ceil(w.size_x_m / w.cell_size_m), math.ceil(w.size_y_m / w.cell_size_m)
    out_cells = [c for c in project.cells if c.col >= nc or c.row >= nr]
    if out_cells:
        warn.append(f"{len(out_cells)} خلية معدّلة خارج الشبكة الحالية ({nc}×{nr}) وسيتم تجاهلها.")
    if (w.size_x_m % w.chunk_size_m) or (w.size_y_m % w.chunk_size_m):
        warn.append(f"حجم العالم لا يقبل القسمة على المنطقة المحمّلة ({w.chunk_size_m:g}م): المربعات الأخيرة ستمتد خارج العالم.")
    coarse = max(w.size_x_m, w.size_y_m) / 1024
    for b in project.biomes:
        if _poly_area(b.polygon) < 1.0:
            err.append(f"المنطقة «{b.name}»: المضلع منحل (مساحة صفر).")
        if b.blend_m < 3 * coarse:
            warn.append(f"المنطقة «{b.name}»: عرض الانتقال ({b.blend_m:g}م) أقل من 3 بكسل خريطة المناطق ({3 * coarse:.0f}م) — قد تظهر حافة مسننة.")
    ridges = [(f, engine._path(f)) for f in project.lines if f.kind == "ridge"]
    for r in (f for f in project.lines if f.kind == "river"):
        path = engine._path(r)
        if path is None:
            continue
        px, py = path[0], path[1]
        for m in P:
            if m.kind in BLOCKS_RIVER and (np.hypot(px - m.x_m, py - m.y_m) < CORE_RATIO * m.diameter_m / 2).any():
                err.append(f"النهر {r.id} يمر داخل قلب {m.id} ({LABELS[m.kind]}) — الأنهار لا تخترق الجبال؛ يمكنها أن تنبع من السفح أو تمر بجانبه.")
        for rf, rp in ridges:
            if rp is not None and (nearest_points(rp, px, py)[0] < RIDGE_CORE * rf.width_m / 2).any():
                err.append(f"النهر {r.id} يقطع قلب السلسلة {rf.id}.")
    for f in project.lines:
        if engine._path(f) is None:
            err.append(f"{f.id}: المسار يحتاج نقطتين مختلفتين على الأقل.")
    S_ = project.sites
    for i, a in enumerate(S_):
        for b in S_[i + 1:]:
            if math.hypot(a.x_m - b.x_m, a.y_m - b.y_m) < site_ext(a) + site_ext(b) - 1e-6:
                err.append(f"تداخل موقعين: {a.id} ({a.name or a.kind}) و{b.id} ({b.name or b.kind}).")
        for m in P:
            if m.kind in WATERISH and math.hypot(a.x_m - m.x_m, a.y_m - m.y_m) < m.diameter_m / 2:
                err.append(f"الموقع {a.id} يقع داخل {LABELS[m.kind]} {m.id} — لا يمكن تسوية الأرض هناك.")
        for r in (f for f in project.lines if f.kind == "river"):
            path = engine._path(r)
            if path is not None and nearest_points(path, np.array([a.x_m]), np.array([a.y_m]))[0][0] < site_ext(a) + r.width_m / 2:
                warn.append(f"النهر {r.id} يمر عبر الموقع {a.id} أو يلامسه — ستُسوّى الأرض فوق المجرى.")
    for z in project.zones:
        if _poly_area(z.polygon) < 1.0:
            err.append(f"المنطقة النباتية «{z.name}»: المضلع منحل (مساحة صفر).")
    pois = project.pois
    starts = [p for p in pois if p.kind == "player_start"]
    if pois and not starts:
        warn.append("لا توجد نقطة انطلاق للاعب (POI من نوع «نقطة انطلاق») — لن تعمل محاكاة اللاعب المتوقع.")
    if len(starts) > 1:
        warn.append(f"{len(starts)} نقاط انطلاق: تُستعمل الأولى ({starts[0].name or starts[0].id}) في المحاكاة.")
    orders = [p.order for p in pois if p.order > 0]
    if len(orders) != len(set(orders)):
        warn.append("أرقام ترتيب المرور مكررة بين مناطق الاهتمام — سيُحدَّد الترتيب بين المتساوين عشوائياً.")
    for p in pois:
        z = float(engine.points([p.x_m], [p.y_m])[0])
        if z < w.sea_level_m:
            warn.append(f"«{p.name or p.id}» تحت مستوى البحر ({z:.1f}م).")
        if p.kind in ("boss", "story") and p.radius_m > 0 and not p.flatten:
            g = np.linspace(-p.radius_m, p.radius_m, 9)
            GX, GY = np.meshgrid(g, g)
            m = GX ** 2 + GY ** 2 <= p.radius_m ** 2
            zz = engine.points(p.x_m + GX[m], p.y_m + GY[m])
            if float(zz.max() - zz.min()) > 0.1 * p.radius_m:
                warn.append(f"«{p.name or p.id}»: الأرض غير مستوية (فرق {zz.max() - zz.min():.0f} م) — فعّل «تسوية الأرض» لحلبة مناسبة.")
    if any(b.max_elev_m is not None or b.min_elev_m is not None for b in project.biomes):
        if Z is None:
            e2 = engine_for(project, 513)
            xs, ys = grid_axes(w.size_x_m, w.size_y_m, 513)
            Z = e2.grid(xs, ys)
            e, wn = e2.biome_issues(Z, xs, ys)
        else:
            e, wn = engine.biome_issues(Z, xs, ys)
        err += e; warn += wn
    warn += engine.design_warnings()
    return err, warn
