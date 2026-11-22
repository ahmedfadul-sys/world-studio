"""طبقات مشتقة من الارتفاعات فقط (بلا أي معلومة أخرى): انحناء، تجويف، تراكم التدفق، رطوبة، تصنيف الميل.

كل الدوال تعمل على شبكة Z (صفوف من الشمال إلى الجنوب، متر) وبُعدا الخلية dx (شرق) وdy (جنوب)، وتعيد قيماً في 0..1 ما لم يُذكر غير ذلك.
لا تغيّر الارتفاعات؛ تُستعمل لتلوين الأرض (صخر على الحواف المحدبة، طين في المنخفضات) ولتغميق وتلميع السطح في Blender.
"""
from __future__ import annotations
import heapq
import math
from typing import Dict, List, Optional, Sequence

import cv2
import numpy as np
from scipy import ndimage as ndi

OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
FLOW_MAX_PX = 1025                       # التدفق يُحسب على شبكة لا تتجاوز هذا الضلع ثم يُكبَّر (حلقة بايثون)


def slope_deg(Z: np.ndarray, dx: float, dy: float) -> np.ndarray:
    gy, gx = np.gradient(Z.astype(np.float64), dy, dx)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def _norm_pos(v: np.ndarray, pct: float = 98.0) -> np.ndarray:
    """يقسم على النسبة المئوية للقيم الموجبة فقط ويقصّ إلى 0..1 (يتجاهل المناطق المستوية)."""
    pos = v[v > 1e-9]
    if pos.size < 16:
        return np.zeros_like(v)
    ref = float(np.percentile(pos, pct))
    return np.clip(v / ref, 0.0, 1.0) if ref > 0 else np.zeros_like(v)


def curvature(Z: np.ndarray, dx: float, dy: float, scale_m: float) -> Dict[str, np.ndarray]:
    """انحناء مُنعَّم بمقياس scale_m: convex = حواف/قمم (يتحدب للأعلى)، concave = مجاري/منخفضات.
    المقياس يمنع التقاط ضجيج الخلية الواحدة: الانحناء الحقيقي يخص شكلاً بحجم عدة أمتار فأكثر."""
    sx, sy = max(scale_m / dx, 0.7), max(scale_m / dy, 0.7)
    Zd = Z.astype(np.float64)
    zxx = ndi.gaussian_filter(Zd, (sy, sx), order=(0, 2), mode="nearest") / (dx * dx)
    zyy = ndi.gaussian_filter(Zd, (sy, sx), order=(2, 0), mode="nearest") / (dy * dy)
    lap = zxx + zyy                                         # < 0: محدب، > 0: مقعر
    return {"convex": _norm_pos(-lap), "concave": _norm_pos(lap)}


def cavity(Z: np.ndarray, dx: float, dy: float, radius_m: float) -> np.ndarray:
    """تجويف ≈ انسداد محيطي: كم الأرض المحيطة أعلى من الخلية على مقياسين (نصف القطر ونصفه). 1 = قاع ضيق عميق."""
    Zd = Z.astype(np.float64)
    out = np.zeros_like(Zd)
    for r in (radius_m, radius_m * 0.5):
        sx, sy = max(r / dx / 2.0, 0.7), max(r / dy / 2.0, 0.7)
        out += np.maximum(ndi.gaussian_filter(Zd, (sy, sx), mode="nearest") - Zd, 0.0) / (0.35 * r)
    return np.clip(out / 2.0, 0.0, 1.0)


def fill_depressions(Z: np.ndarray) -> np.ndarray:
    """ملء الحفر (Priority-Flood، 4 جيران): كل خلية تجد مساراً هابطاً إلى حافة الخريطة، فلا يعلق التدفق في حفرة."""
    ny, nx = Z.shape
    F = Z.astype(np.float64).copy()
    seen = np.zeros((ny, nx), bool)
    heap: List = []
    for r in range(ny):
        for c in (0, nx - 1):
            if not seen[r, c]:
                seen[r, c] = True
                heap.append((F[r, c], r, c))
    for c in range(nx):
        for r in (0, ny - 1):
            if not seen[r, c]:
                seen[r, c] = True
                heap.append((F[r, c], r, c))
    heapq.heapify(heap)
    eps = 1e-4
    while heap:
        z, r, c = heapq.heappop(heap)
        for rr, cc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= rr < ny and 0 <= cc < nx and not seen[rr, cc]:
                seen[rr, cc] = True
                if F[rr, cc] < z + eps:
                    F[rr, cc] = z + eps
                heapq.heappush(heap, (F[rr, cc], rr, cc))
    return F


def flow_accumulation(Z: np.ndarray, dx: float, dy: float, fill: bool = True):
    """تراكم التدفق D8. يعيد (المساحة المغذية بالمتر المربع، الميل tanβ) بنفس شكل Z."""
    ny0, nx0 = Z.shape
    f = max(1, math.ceil(max(ny0, nx0) / FLOW_MAX_PX))
    Zw = Z.astype(np.float64)
    if f > 1:
        Zw = cv2.resize(Zw, (nx0 // f, ny0 // f), interpolation=cv2.INTER_AREA)
    ddx, ddy = dx * f, dy * f
    ny, nx = Zw.shape
    F = fill_depressions(Zw) if fill else Zw
    n = nx * ny
    idx = np.arange(n).reshape(ny, nx)
    zp = np.pad(F, 1, mode="constant", constant_values=-np.inf)      # خارج الخريطة = مصرف: الحواف تُصرّف للخارج
    best, rcv = np.zeros_like(F), idx.copy()
    for oy, ox in OFFS:
        d = math.hypot(ddx * ox, ddy * oy)
        nb = zp[1 + oy:1 + oy + ny, 1 + ox:1 + ox + nx]
        s = (F - nb) / d
        s = np.where(np.isinf(nb), 1e-6, s)                          # خلية حافة تصرّف للخارج بميل رمزي
        m = s > best
        best = np.where(m, s, best)
        rcv = np.where(m & ~np.isinf(nb), idx + oy * nx + ox, rcv)   # للخارج: تبقى مستقبِلة نفسها (نهاية المسار)
    rc = rcv.ravel().tolist()
    acc = [1.0] * n
    for i in np.argsort(-F, axis=None, kind="stable").tolist():
        r = rc[i]
        if r != i:
            acc[r] += acc[i]
    A = np.asarray(acc, np.float64).reshape(ny, nx) * (ddx * ddy)
    tanb = best
    if f > 1:
        A = cv2.resize(A, (nx0, ny0), interpolation=cv2.INTER_LINEAR)
        tanb = cv2.resize(tanb, (nx0, ny0), interpolation=cv2.INTER_LINEAR)
    return A, tanb


def flow_layers(Z: np.ndarray, dx: float, dy: float, stream_area_m2: float) -> Dict[str, np.ndarray]:
    """flow = أهمية المجرى (لوغاريتمي)، stream = مجرى فعلي (0/1 منعّم)، wetness = مؤشر الرطوبة الطبوغرافي TWI مُطبَّع."""
    A, tanb = flow_accumulation(Z, dx, dy)
    a_spec = A / max(math.hypot(dx, dy), 1e-9)                       # مساحة مغذية لكل متر من عرض الكنتور
    twi = np.log(np.maximum(a_spec, 1e-9) / np.maximum(tanb, 0.05))   # أرضية ميل 0.05 (~3°): السهل المستوي لا يُعدّ رطباً لمجرد استوائه
    lo, hi = np.percentile(twi, 50), np.percentile(twi, 99.5)        # النصف الأجف = 0، فتبرز الأراضي المغذّاة فقط
    wet = np.clip((twi - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    cell_a = dx * dy
    lg = np.log10(np.maximum(A, cell_a) / cell_a)
    flow = np.clip(lg / max(float(lg.max()), 1e-9), 0.0, 1.0)
    stream = np.clip((np.log10(np.maximum(A, 1.0)) - math.log10(max(stream_area_m2, 1.0))) / 0.35 + 0.5, 0.0, 1.0)
    return {"flow": flow, "stream": stream, "wetness": wet, "area_m2": A}


def slope_classes(slope: np.ndarray, limits_deg: Sequence[float]) -> np.ndarray:
    """فهرس الفئة: 0 أقل من أول حد، ... ، len(limits) فوق آخر حد."""
    return np.searchsorted(np.asarray(sorted(limits_deg), np.float64), slope, side="right").astype(np.uint8)


def derive(Z: np.ndarray, dx: float, dy: float, cfg) -> Dict[str, np.ndarray]:
    """كل الطبقات في قاموس. cfg: كائن إعدادات Derived (curvature_scale_m, cavity_radius_m, stream_area_m2, slope_classes_deg)."""
    sl = slope_deg(Z, dx, dy)
    out: Dict[str, np.ndarray] = {"slope_deg": sl}
    c = curvature(Z, dx, dy, cfg.curvature_scale_m)
    out["curv_convex"], out["curv_concave"] = c["convex"], c["concave"]
    out["cavity"] = cavity(Z, dx, dy, cfg.cavity_radius_m)
    out.update(flow_layers(Z, dx, dy, cfg.stream_area_m2))
    out["slope_class"] = slope_classes(sl, cfg.slope_classes_deg)
    return out


def to_u8(a: np.ndarray) -> np.ndarray:
    return (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
