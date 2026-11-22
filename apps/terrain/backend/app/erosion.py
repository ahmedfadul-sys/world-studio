"""تعرية أسلوبية على شبكة. تُستعمل لإنتاج فرق ارتفاع ناعم وليس لمحاكاة معايَرة بمعدلات حقيقية.

وضعان: "stylized" (القديم: قدرة مجرى مع نسبة ترسيب ثابتة) و"sediment" (الجديد): نقل رواسب بالسعة على مجاري D8
(يحمل كل مجرى رواسب أعلى مجراه؛ يُعرّي حيث تزيد السعة ويرسّب حيث تقل، فيتكوّن ترسيب عند انكسار الميل)،
مراوح ركامية (الترسيب يُنشَر جانبياً بتمويه يحفظ الكتلة)، وأخاديد (خطوط تعرية باتجاه خط الانحدار).
"""
from __future__ import annotations
import math
import numpy as np
from scipy import ndimage as ndi

OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def erode(z0: np.ndarray, dx: float, dy: float, p) -> np.ndarray:
    if getattr(p, "mode", "stylized") == "sediment":
        return erode_sediment(z0, dx, dy, p)
    return _erode_stylized(z0, dx, dy, p)


def _d8(z, dx, dy):
    """مستقبِل D8 لكل خلية وميل الانحدار؛ خارج الخريطة +inf فلا تُصرَّف الحواف للخارج (تتجمع الرواسب عندها)."""
    ny, nx = z.shape
    idx = np.arange(nx * ny).reshape(ny, nx)
    zp = np.pad(z, 1, mode="constant", constant_values=np.inf)
    best, rcv = np.zeros_like(z), idx.copy()
    for oy, ox in OFFS:
        d = math.hypot(dx * ox, dy * oy)
        s = (z - zp[1 + oy:1 + oy + ny, 1 + ox:1 + ox + nx]) / d
        m = s > best
        best = np.where(m, s, best)
        rcv = np.where(m, idx + oy * nx + ox, rcv)
    return rcv.ravel(), best


def sediment_pass(z, dx, dy, rate, ke, kd):
    """تمريرة نقل رواسب واحدة. يعيد (dz، الترسيب فقط). الكتلة محفوظة: كل ما يُجرَف يُرسَّب في مكان ما (البالوعات تأخذ الباقي)."""
    ny, nx = z.shape
    n = nx * ny
    rc, best = _d8(z, dx, dy)
    zf = z.ravel()
    order = np.argsort(-zf, kind="stable").tolist()
    rl = rc.tolist()
    acc = [1.0] * n
    for i in order:
        r = rl[i]
        if r != i:
            acc[r] += acc[i]
    E = np.sqrt(np.asarray(acc).reshape(ny, nx)) * best                # سعة النقل ~ A^0.5 · S
    pos = E[E > 0]
    ref = float(np.percentile(pos, 99.5)) if pos.size else 0.0
    cap = (rate * np.minimum(E / ref, 1.5)).ravel() if ref > 0 else np.zeros(n)
    room = np.maximum(zf - zf[rc], 0.0) * 0.5                          # لا يحفر تحت المستقبِل
    cap_l, room_l = cap.tolist(), room.tolist()
    qs = [0.0] * n
    dz = [0.0] * n
    dep_l = [0.0] * n
    for i in order:
        r = rl[i]
        q = qs[i]
        if r == i:                                                     # بالوعة: ترسب كل ما وصلها
            dz[i] += q
            dep_l[i] += q
            continue
        c = cap_l[i]
        if q > c:
            d = (q - c) * kd
            dz[i] += d
            dep_l[i] += d
            q -= d
        else:
            e = min((c - q) * ke, room_l[i])
            dz[i] -= e
            q += e
        qs[r] += q
    return np.asarray(dz).reshape(ny, nx), np.asarray(dep_l).reshape(ny, nx)


def gullies(z, dx, dy, p, seed):
    """أخاديد: ضوضاء بيضاء تُسحَب (LIC مبسّط) على امتداد خط الانحدار فتتكون خطوط طولية، تُحفر على المنحدرات المتوسطة والشديدة فقط."""
    ny, nx = z.shape
    rng = np.random.default_rng(seed)
    W = ndi.gaussian_filter(rng.standard_normal((ny, nx)), max(p.gully_spacing_m / (2.0 * dx), 0.8))
    gy, gx = np.gradient(ndi.gaussian_filter(z, 1.0), dy, dx)
    mag = np.hypot(gx, gy)
    ur, uc = -gy / (mag + 1e-12) * (1.0 / dy), -gx / (mag + 1e-12) * (1.0 / dx)      # اتجاه الانحدار بوحدات الفهرس
    nrm = math.hypot(1.0 / dx, 1.0 / dy)
    ur, uc = ur / nrm, uc / nrm
    R, C = np.mgrid[0:ny, 0:nx].astype(np.float64)
    L = int(p.gully_length_cells)
    S = np.zeros_like(W)
    for k in range(-L, L + 1):
        S += ndi.map_coordinates(W, [R + k * ur, C + k * uc], order=1, mode="nearest")
    S /= (2 * L + 1)
    S = (S - S.mean()) / (S.std() + 1e-12)
    ch = np.clip((-S - 0.3) / 1.2, 0.0, 1.0)                           # القنوات = أدنى قيم السحب
    ch = ch * ch * (3 - 2 * ch)
    sl = np.degrees(np.arctan(mag))
    sm = lambda a, b, v: (lambda t: t * t * (3 - 2 * t))(np.clip((v - a) / max(b - a, 1e-6), 0.0, 1.0))
    lo, hi = p.gully_min_slope_deg, p.gully_max_slope_deg
    m = sm(lo, lo + 10.0, sl) * (1.0 - sm(hi, hi + 15.0, sl))          # تبدأ عند lo وتبلغ كامل قوتها بعد 10°، وتتلاشى فوق hi (الجروف لا تُخدَّد)
    return -p.gully_depth_m * ch * m


def erode_sediment(z0, dx, dy, p):
    z = z0.astype(np.float64).copy()
    rate = p.max_depth_m / max(p.iterations, 1)
    sigma = max(p.fan_spread_m / (2.0 * dx), 0.0) if p.fans else 0.0
    for _ in range(p.iterations):
        dz, dep = sediment_pass(z, dx, dy, rate, p.erodibility, p.deposition_rate)
        if sigma > 0.4:                                                # مراوح: يُنشَر الترسيب جانبياً (التمويه يحفظ المجموع) بدل أن يبقى خطاً ضيقاً
            dz = dz - dep + ndi.gaussian_filter(dep, sigma, mode="reflect")   # reflect: يحفظ المجموع عند حافة الخريطة
        z += dz
        if p.smooth > 0:
            zp2 = np.pad(z, 1, mode="edge")
            z += p.smooth * 0.1 * (zp2[:-2, 1:-1] + zp2[2:, 1:-1] + zp2[1:-1, :-2] + zp2[1:-1, 2:] - 4 * z)
    if p.thermal:
        z = _thermal(z, dx, dy, p)
    if p.gullies and p.gully_depth_m > 0:
        z = z + gullies(z, dx, dy, p, p.seed)
    return z


def _thermal(z, dx, dy, p):
    ny, nx = z.shape
    dists = [math.hypot(dx * ox, dy * oy) for oy, ox in OFFS]
    T = [math.tan(math.radians(p.talus_deg)) * d for d in dists]
    for _ in range(max(1, p.iterations)):
        zp = np.pad(z, 1, mode="constant", constant_values=np.inf)
        gain = np.zeros_like(z)
        for (oy, ox), t in zip(OFFS, T):
            ex = 0.1 * np.maximum(z - zp[1 + oy:1 + oy + ny, 1 + ox:1 + ox + nx] - t, 0.0)
            z -= ex
            gain += np.roll(np.roll(ex, oy, axis=0), ox, axis=1)
        z += gain
    return z


def _erode_stylized(z0: np.ndarray, dx: float, dy: float, p) -> np.ndarray:
    z = z0.astype(np.float64).copy()
    ny, nx = z.shape
    n = nx * ny
    idx = np.arange(n).reshape(ny, nx)
    dists = [math.hypot(dx * ox, dy * oy) for oy, ox in OFFS]
    rate = p.max_depth_m / max(p.iterations, 1)
    for _ in range(p.iterations):
        # أقرب منحدر D8 (خارج الحدود = +inf فلا يُختار؛ الحواف لا تصرّف للخارج)
        zp = np.pad(z, 1, mode="constant", constant_values=np.inf)
        best, rcv = np.zeros_like(z), idx.copy()
        for (oy, ox), d in zip(OFFS, dists):
            nb = zp[1 + oy:1 + oy + ny, 1 + ox:1 + ox + nx]
            s = (z - nb) / d
            m = s > best
            best = np.where(m, s, best)
            rcv = np.where(m, idx + oy * nx + ox, rcv)
        # تراكم التدفق بترتيب الارتفاع (المستقبِل أخفض دائماً)
        rc = rcv.ravel().tolist()
        acc = [1.0] * n
        for i in np.argsort(-z, axis=None, kind="stable").tolist():
            r = rc[i]
            if r != i:
                acc[r] += acc[i]
        E = np.sqrt(np.asarray(acc).reshape(ny, nx)) * best           # قدرة المجرى ~ A^0.5 · S
        pos = E[E > 0]
        if pos.size and rate > 0:
            ref = float(np.percentile(pos, 99.5))
            if ref > 0:
                ero = rate * np.minimum(E / ref, 1.5)
                zr = z.ravel()[rcv.ravel()].reshape(ny, nx)
                ero = np.minimum(ero, np.maximum(z - zr, 0.0) * 0.5)  # لا يتجاوز نصف الفرق مع المستقبِل
                z -= ero
                z += np.bincount(rcv.ravel(), weights=(ero * p.deposition).ravel(), minlength=n).reshape(ny, nx)
        if p.smooth > 0:
            zp2 = np.pad(z, 1, mode="edge")
            z += p.smooth * 0.1 * (zp2[:-2, 1:-1] + zp2[2:, 1:-1] + zp2[1:-1, :-2] + zp2[1:-1, 2:] - 4 * z)
    if p.thermal:                                                      # انهيار الركام فوق زاوية الاستقرار
        T = [math.tan(math.radians(p.talus_deg)) * d for d in dists]
        for _ in range(max(1, p.iterations)):
            zp = np.pad(z, 1, mode="constant", constant_values=np.inf)
            gain = np.zeros_like(z)
            for (oy, ox), t in zip(OFFS, T):
                ex = 0.1 * np.maximum(z - zp[1 + oy:1 + oy + ny, 1 + ox:1 + ox + nx] - t, 0.0)
                z -= ex
                gain += np.roll(np.roll(ex, oy, axis=0), ox, axis=1)   # ex=0 عند الحدود فلا التفاف
            z += gain
    return z
