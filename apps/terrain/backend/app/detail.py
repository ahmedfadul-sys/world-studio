"""تفاصيل ارتفاع دقيقة (≤ 1 م/بكسل) تُضاف عند تصدير المربعات، بحسب المادة والميل.

كل الحقول دوال خالصة لإحداثيات العالم المطلقة (x, y) فتتطابق قيم بكسل الحافة المشترك بين مربعين متجاورين تماماً (لا شقوق).
الميل وقناع الاستثناء يُحسبان على شبكة موسّعة بهامش ثم تُقصّ، فلا يختلف فرق الارتفاع عند الحافة بين المربعين.
المواد تأتي من أوزان التلوين العالمية (دقة الأقنعة) بعد أخذ عينة ثنائية الخطية، فتتدرج السعة بسلاسة بين المواد.
"""
from __future__ import annotations
import math
from typing import Dict, Tuple

import numpy as np

from .noise import fbm

KINDS = ("soil", "rock", "sand", "gravel")
# سعة (م) ونوع افتراضيان للمواد المدمجة؛ مادة المستخدم بلا قيمة تأخذ نوعها من هنا أو 'soil' بسعة صغيرة
DEFAULTS: Dict[str, Tuple[str, float]] = {
    "grass": ("soil", 0.12), "forest_floor": ("soil", 0.15), "rock": ("rock", 0.8), "snow": ("soil", 0.10), "sand": ("sand", 0.10),
    "mud": ("soil", 0.08), "dirt": ("soil", 0.12), "pavement": ("soil", 0.0), "farmland": ("soil", 0.10), "gravel": ("gravel", 0.25),
}
PAD = 2                                                      # خلايا هامش لحساب الميل


def _smooth(a, lo, hi):
    t = np.clip((a - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def field(kind: str, X: np.ndarray, Y: np.ndarray, wavelength_m: float, mpp: float, seed: int) -> np.ndarray:
    """حقل تفاصيل في نحو [-1,1] بطول موجة أعظمي wavelength_m؛ الأقصر من مترين لكل بكسل يُهمَل (تعرّج لا معنى له)."""
    f0 = 1.0 / max(wavelength_m, 2.0 * mpp)
    octs = int(np.clip(math.floor(math.log2(max(wavelength_m, 2.0 * mpp) / (2.0 * max(mpp, 0.05)))), 1, 5))
    base = fbm(X, Y, f0, octs, seed)
    if kind == "rock":                                       # حواف حادة وكتل: ridged + تدريج
        r = 1.0 - np.abs(base)
        return (np.round(r * r * 6.0) / 6.0) * 2.0 - 1.0 + 0.35 * fbm(X, Y, f0 * 4.0, 2, seed + 5)
    if kind == "gravel":                                     # حصى: تردد أعلى وقمم متفرقة
        return np.abs(fbm(X, Y, f0 * 2.0, octs, seed + 9)) * 2.0 - 1.0
    if kind == "sand":                                       # تموجات رياح: موجات مُعوَّجة بضوضاء
        warp = fbm(X, Y, f0 * 0.5, 2, seed + 3) * wavelength_m * 0.6
        return np.sin((X * 0.8 + Y * 0.6 + warp) * (2.0 * math.pi / max(wavelength_m * 0.6, 2.0 * mpp)))
    return base                                              # soil: تموّج ناعم


def padded_axes(xs: np.ndarray, ys: np.ndarray, pad: int = PAD):
    sx, sy = xs[1] - xs[0], ys[1] - ys[0]                    # sy سالب (الشمال أولاً)
    return (np.r_[xs[0] - sx * np.arange(pad, 0, -1), xs, xs[-1] + sx * np.arange(1, pad + 1)],
            np.r_[ys[0] - sy * np.arange(pad, 0, -1), ys, ys[-1] + sy * np.arange(1, pad + 1)])


def _bilinear_grid(F: np.ndarray, xs: np.ndarray, ys: np.ndarray, gx0: float, gy_top: float, gdx: float, gdy: float) -> np.ndarray:
    """عيّنة ثنائية الخطية من شبكة عالمية F (صف 0 = شمال) عند محاور المربع."""
    ny, nx = F.shape
    fx = np.clip((xs - gx0) / gdx, 0, nx - 1.001)[None, :]
    fy = np.clip((gy_top - ys) / gdy, 0, ny - 1.001)[:, None]
    i, j = fx.astype(int), fy.astype(int)
    tx, ty = fx - i, fy - j
    return (F[j, i] * (1 - tx) * (1 - ty) + F[j, i + 1] * tx * (1 - ty) + F[j + 1, i] * (1 - tx) * ty + F[j + 1, i + 1] * tx * ty)


class DetailContext:
    """يُجهَّز مرة واحدة لكل تصدير: أوزان المواد العالمية والإعدادات."""

    def __init__(self, project, weights: Dict[str, np.ndarray], gxs: np.ndarray, gys: np.ndarray, lib: Dict[str, dict]):
        self.p, self.cfg = project, project.detail
        self.gx0, self.gy_top = float(gxs[0]), float(gys[0])
        self.gdx, self.gdy = float(gxs[1] - gxs[0]), float(gys[0] - gys[1])
        self.W = weights
        self.prof: Dict[str, Tuple[str, float]] = {}
        for mid, m in lib.items():
            kind, amp = DEFAULTS.get(mid, ("soil", 0.12))
            if m.get("detail_kind"):
                kind = m["detail_kind"]
            if m.get("detail_amp_m") is not None:
                amp = float(m["detail_amp_m"])
            if mid in weights and amp > 0:
                self.prof[mid] = (kind, amp)

    def apply(self, eng, Zp: np.ndarray, xp: np.ndarray, yp: np.ndarray, mpp: float) -> np.ndarray:
        """Zp على المحاور الموسّعة؛ يعيد الارتفاع بعد التفاصيل بشكل المحاور الأصلية (مقصوصاً)."""
        cfg = self.cfg
        sx, sy = abs(xp[1] - xp[0]), abs(yp[1] - yp[0])
        gy, gx = np.gradient(Zp.astype(np.float64), sy, sx)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        free = 1.0 - eng.exclusion(xp, yp, Zp)                # الطرق والمواقع تبقى مستوية
        X, Y = xp[None, :], yp[:, None]
        fields: Dict[Tuple[str, int], np.ndarray] = {}
        dZ = np.zeros_like(Zp, dtype=np.float64)
        for k, (mid, (kind, amp)) in enumerate(self.prof.items()):
            w = _bilinear_grid(self.W[mid], xp, yp, self.gx0, self.gy_top, self.gdx, self.gdy)
            if float(w.max()) < 0.01:
                continue
            key = (kind, 0)
            if key not in fields:
                fields[key] = field(kind, X, Y, cfg.wavelength_max_m, mpp, cfg.seed + 17 * KINDS.index(kind))
            a = amp * (1.0 + (cfg.slope_gain * _smooth(slope, 10.0, 45.0) if kind in ("rock", "gravel") else 0.0))
            dZ += w * a * fields[key]
        out = Zp + dZ * free
        return out[PAD:-PAD, PAD:-PAD]
