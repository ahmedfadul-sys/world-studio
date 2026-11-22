"""قرى ومبانٍ من وحدات (Kit): يضع قطعاً (بيوت، مبنى رئيسي، سور، بوابة، برج، زينة) في قطع المباني المقترحة وعلى محيط الموقع.

- البيوت تأخذ قطعة بالوزن من قطع الدور المناسب (والموقع)، وتتجه نحو أقرب طريق إن قرُب (face_road) وإلا نحو مركز الموقع كما في القطع.
- الأسوار على محيط المواقع المختارة بخطوة طول القطعة وتواجه الخارج؛ حيث يقطع طريقٌ السور توضع بوابة (إن وُجدت) أو يُترك فراغ.
- أبراج على أركان/نقاط موزعة من المحيط، وزينة (آبار، عربات...) حول القطع.
اصطلاح الاتجاه كاصطلاح قطع المباني: واجهة القطعة = محورها +X المحلي؛ yaw بالدرجات حول Z (x شرقاً، y شمالاً).
حتمي بالكامل بالبذرة.
"""
from __future__ import annotations
import math
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


def _nearest_on_roads(x: float, y: float, roads: Sequence[dict]) -> Tuple[float, Optional[Tuple[float, float]]]:
    """أقرب مسافة إلى أي طريق ونقطته (بين عينات الخط)."""
    best, pt = float("inf"), None
    for rd in roads:
        P = np.asarray([p[:2] for p in rd["polyline"]], np.float64)
        if len(P) < 2:
            continue
        A, B = P[:-1], P[1:]
        AB = B - A
        L2 = np.maximum((AB ** 2).sum(1), 1e-12)
        t = np.clip(((x - A[:, 0]) * AB[:, 0] + (y - A[:, 1]) * AB[:, 1]) / L2, 0.0, 1.0)
        Q = A + AB * t[:, None]
        d = np.hypot(Q[:, 0] - x, Q[:, 1] - y)
        k = int(d.argmin())
        if d[k] < best:
            best, pt = float(d[k]), (float(Q[k, 0]), float(Q[k, 1]))
    return best, pt


def _pick(pieces: list, rng) -> Optional[object]:
    if not pieces:
        return None
    w = np.asarray([max(p.weight, 1e-6) for p in pieces], np.float64)
    return pieces[int(rng.choice(len(pieces), p=w / w.sum()))]


def _outline_samples(outline: Sequence[Sequence[float]], step: float):
    """نقاط على محيط مغلق بخطوة ثابتة عبر طول القوس التراكمي: (x, y, z, ظل الاتجاه tx, ty, إشارة الاتجاه الخارجي)."""
    P = np.asarray([[p[0], p[1], p[2] if len(p) > 2 else 0.0] for p in outline], np.float64)
    if len(P) < 3:
        return []
    if np.hypot(*(P[0, :2] - P[-1, :2])) > 1e-6:
        P = np.vstack([P, P[:1]])
    seg = np.hypot(*np.diff(P[:, :2], axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    n = int(total // step)
    if n < 1:
        return []
    area = 0.5 * float(((P[:-1, 0] * P[1:, 1]) - (P[1:, 0] * P[:-1, 1])).sum())
    sign = 1.0 if area > 0 else -1.0                                 # +1: عكس عقارب الساعة، الخارج = يمين المماس
    out = []
    for k in range(n):
        s_ = (k + 0.5) * total / n                                   # توزيع منتظم يملأ المحيط كله بلا فجوة أخيرة
        x, y, z = (float(np.interp(s_, cum, P[:, c])) for c in range(3))
        i = int(np.clip(np.searchsorted(cum, s_, side="right") - 1, 0, len(seg) - 1))
        L = max(float(seg[i]), 1e-9)
        out.append((x, y, z, float((P[i + 1, 0] - P[i, 0]) / L), float((P[i + 1, 1] - P[i, 1]) / L), sign))
    return out


def plan(kit, sites: List[dict], roads: List[dict]) -> List[dict]:
    pieces = list(kit.pieces)
    rows: List[dict] = []
    if not pieces:
        return rows
    for site in sites:
        rng = np.random.default_rng(kit.seed + zlib.crc32(site["id"].encode("utf-8")))
        kind = site["kind"]
        ok = lambda p: (not p.site_kinds) or kind in p.site_kinds
        by = lambda role: [p for p in pieces if p.role == role and ok(p)]
        cx, cy = site["center"]["x"], site["center"]["y"]
        add = lambda p, x, y, z, yaw, sc=1.0: rows.append({"site": site["id"], "piece": p.id, "role": p.role, "x": round(float(x), 2), "y": round(float(y), 2),
                                                          "z": round(float(z), 2), "yaw_deg": round(float(yaw) % 360.0, 2), "scale": round(float(sc), 3)})
        # ── بيوت ──
        for lot in site.get("building_lots", []):
            p = _pick(by("main") if lot["main"] else by("house"), rng) or (_pick(by("house"), rng) if lot["main"] else None)
            if p is None:
                continue
            yaw = lot["rotation_deg"]
            if kit.face_road and roads:
                d, q = _nearest_on_roads(lot["x_m"], lot["y_m"], roads)
                if q is not None and d <= kit.road_snap_m and d > 1e-6:
                    yaw = math.degrees(math.atan2(q[1] - lot["y_m"], q[0] - lot["x_m"]))
            fit = min(1.0, lot["width_m"] / max(p.width_m, 1e-6), lot["length_m"] / max(p.length_m, 1e-6))
            add(p, lot["x_m"], lot["y_m"], lot["z_m"], yaw, fit * float(rng.uniform(0.95, 1.05)))
            props = by("prop")
            if props and kit.props_per_lot > 0:
                for _ in range(int(rng.poisson(kit.props_per_lot))):
                    a = float(rng.uniform(0, 2 * math.pi)); r = 0.5 * max(lot["width_m"], lot["length_m"]) + float(rng.uniform(1.0, 3.5))
                    pr = _pick(props, rng)
                    add(pr, lot["x_m"] + r * math.cos(a), lot["y_m"] + r * math.sin(a), lot["z_m"], float(rng.uniform(0, 360)), float(rng.uniform(0.85, 1.15)))
        # ── أسوار وبوابات وأبراج على محيط المواقع المحددة ──
        if kit.walls and kind in kit.wall_kinds and site.get("outline"):
            walls, gates, towers = by("wall"), by("gate"), by("tower")
            if walls:
                step = max(min(w.length_m for w in walls), 1.0)
                smp = _outline_samples(site["outline"], step)
                yaws = [math.degrees(math.atan2(-tx * sg, ty * sg)) for (_, _, _, tx, ty, sg) in smp]       # واجهة السور (+X) نحو الخارج
                near = [(_nearest_on_roads(x, y, roads)[0] if roads else float("inf")) <= kit.gate_width_m / 2.0 for (x, y, _, _, _, _) in smp]
                # عينات متتالية قريبة من طريق = عبور واحد: تُستبدل ببوابة واحدة في وسطه (أو فراغ إن لم توجد بوابة)
                runs, cur = [], []
                for k, flag in enumerate(near):
                    if flag:
                        cur.append(k)
                    elif cur:
                        runs.append(cur); cur = []
                if cur:
                    if runs and near[0] and runs[0][0] == 0:        # عبور يلتف حول نقطة البداية
                        runs[0] = cur + runs[0]
                    else:
                        runs.append(cur)
                gate_at = {r[len(r) // 2]: r for r in runs}
                skip = {k for r in runs for k in r}
                for k, (x, y, z, tx, ty, sg) in enumerate(smp):
                    if k in gate_at:
                        g = _pick(gates, rng)
                        if g is not None:
                            r = gate_at[k]
                            add(g, sum(smp[j][0] for j in r) / len(r), sum(smp[j][1] for j in r) / len(r), z, yaws[k])
                    elif k not in skip:
                        add(_pick(walls, rng), x, y, z, yaws[k])
            if towers:
                P = site["outline"]
                if len(P) > 3 and math.hypot(P[0][0] - P[-1][0], P[0][1] - P[-1][1]) < 1e-6:
                    P = P[:-1]                                       # أزل نقطة الإغلاق المكررة فلا يتكرر برج الركن
                n = min(len(P), 8)
                for k in range(n):
                    p0 = P[int(k * len(P) / n)]
                    add(_pick(towers, rng), p0[0], p0[1], p0[2] if len(p0) > 2 else site["level_z"], math.degrees(math.atan2(p0[1] - cy, p0[0] - cx)))
    return rows


def to_csv(rows: List[dict]) -> bytes:
    head = "site,piece,role,x,y,z,yaw_deg,scale"
    body = "\n".join(f'{r["site"]},{r["piece"]},{r["role"]},{r["x"]},{r["y"]},{r["z"]},{r["yaw_deg"]},{r["scale"]}' for r in rows)
    return (head + "\n" + body + "\n").encode("utf-8")
