"""اللاعب المتوقع: مسار بين نقطة الانطلاق ومناطق الاهتمام (Tobler)، الزمن، الرؤية (مدى النظر) وتوصية مسافات LOD."""
from __future__ import annotations
import math
from typing import Dict, List
import numpy as np
from scipy.ndimage import map_coordinates, binary_dilation
from scipy.sparse.csgraph import dijkstra
from .terrain import Engine, grid_axes, nearest_grid
from .routing import build_graph, _snap, _trace, _dp, _masks, BIG

SEE_KINDS = {"landmark", "boss", "story", "dungeon", "quest", "resource", "fast_travel", "poi"}


def tobler(s):
    """معامل السرعة النسبي (1 ≈ أرض مستوية): دالة Tobler للمشي، s = ميل موقّع (صعود موجب)."""
    return np.exp(-3.5 * (np.abs(s + 0.05) - 0.05))


def _sample(Z, Lx, Ly, X, Y):
    nyC, nxC = Z.shape
    return map_coordinates(Z, [np.clip((Ly - Y) / (Ly / (nyC - 1)), 0, nyC - 1), np.clip(X / (Lx / (nxC - 1)), 0, nxC - 1)], order=1, mode="nearest")


def rays(Z, Lx, Ly, ox, oy, eye_h, radius, n_rays):
    """رؤية شعاعية: نقطة مرئية إن كانت زاوية ارتفاعها ≥ أكبر زاوية قبلها على الشعاع."""
    nyC, nxC = Z.shape
    dx = Lx / (nxC - 1)
    ns = max(2, int(radius / dx))
    d = (np.arange(1, ns + 1)) * dx
    ang = np.linspace(0, 2 * math.pi, n_rays, endpoint=False)
    X = ox + np.cos(ang)[:, None] * d[None, :]
    Y = oy + np.sin(ang)[:, None] * d[None, :]
    inside = (X >= 0) & (X <= Lx) & (Y >= 0) & (Y <= Ly)
    z = _sample(Z, Lx, Ly, X, Y)
    z0 = float(_sample(Z, Lx, Ly, np.array([ox]), np.array([oy]))[0]) + eye_h
    slope = (z - z0) / d[None, :]
    prev = np.concatenate([np.full((n_rays, 1), -np.inf), np.maximum.accumulate(slope, axis=1)[:, :-1]], axis=1)
    return X, Y, (slope >= prev - 1e-9) & inside, d


def los(Z, Lx, Ly, ox, oy, eye_h, tx, ty, t_h):
    """هل يرى المراقب نقطة (tx,ty) بارتفاع t_h فوق الأرض؟"""
    nyC, nxC = Z.shape
    dx = Lx / (nxC - 1)
    dist = math.hypot(tx - ox, ty - oy)
    if dist < dx:
        return True
    n = max(2, int(dist / dx))
    t = np.linspace(0, 1, n + 1)[1:]
    z = _sample(Z, Lx, Ly, ox + t * (tx - ox), oy + t * (ty - oy))
    z0 = float(_sample(Z, Lx, Ly, np.array([ox]), np.array([oy]))[0]) + eye_h
    d = t * dist
    top = z[-1] + t_h
    ang_t = (top - z0) / d[-1]
    return bool(np.all((z[:-1] - z0) / d[:-1] <= ang_t + 1e-9)) if n > 1 else True


def viewshed(project, x, y, height, radius, resolution=513):
    w = project.world
    eng = Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (resolution - 1))
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, resolution)
    Z = eng.grid(xs, ys)
    dx = xs[1] - xs[0]
    X, Y, vis, d = rays(Z.astype(np.float64), w.size_x_m, w.size_y_m, x, y, height, radius, int(min(2000, max(180, 2 * math.pi * radius / dx))))
    H, W = Z.shape
    mask = np.zeros((H, W), bool)
    ci = np.rint(X[vis] / dx).astype(int); rj = np.rint((w.size_y_m - Y[vis]) / (ys[0] - ys[1])).astype(int)
    ok = (ci >= 0) & (ci < W) & (rj >= 0) & (rj < H)
    mask[rj[ok], ci[ok]] = True
    mask = binary_dilation(mask, iterations=1)
    area = float(mask.sum() * dx * (ys[0] - ys[1]))
    return {"nx": W, "ny": H, "mask": (mask * 255).astype(np.uint8), "visible_area_km2": area / 1e6,
            "visible_fraction_of_disc": float(min(1.0, area / (math.pi * radius ** 2)))}


def simulate(project, resolution=513):
    w, pl = project.world, project.player
    starts = [p for p in project.pois if p.kind == "player_start"]
    if not starts:
        raise ValueError("أضف نقطة انطلاق للاعب (POI من نوع «نقطة انطلاق»)")
    eng = Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (resolution - 1))
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, resolution)
    Z = eng.grid(xs, ys).astype(np.float64)
    H, W = Z.shape
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    water, lake, river, core, marsh = _masks(project, eng, Z, xs, ys)
    smax = math.tan(math.radians(pl.max_slope_deg))
    slow = np.where(river, 3.0, 1.0) * np.where(marsh, 2.0, 1.0)
    wet = (water | lake)

    def wf(d, src, dst):
        s = (Z[dst] - Z[src]) / d
        f = np.clip(tobler(s), 0.05, 1.4)
        t = d / (pl.speed_mps * f) * 0.5 * (slow[src] + slow[dst])
        t = np.where(np.abs(s) > smax, BIG, t)
        wetp = np.maximum(wet[src], wet[dst])
        return np.where(wetp, (t * 4 if pl.can_swim else BIG), t)
    G = build_graph(H, W, dx, dy, wf)
    ordered = sorted([p for p in project.pois if p.order > 0 and p.kind != "player_start"], key=lambda p: p.order)
    stops = [starts[0]] + ordered
    legs, warnings, nodes_all = [], [], []
    walked = 0.0
    for a, b in zip(stops[:-1], stops[1:]):
        r0, c0 = _snap(a.x_m, a.y_m, xs, ys); r1, c1 = _snap(b.x_m, b.y_m, xs, ys)
        src, dst = r0 * W + c0, r1 * W + c1
        dist, pred = dijkstra(G, directed=True, indices=src, return_predecessors=True)
        if dist[dst] >= BIG:
            warnings.append(f"لا يمكن للاعب الوصول من «{a.name or a.id}» إلى «{b.name or b.id}» (ماء أو منحدر شديد). عدّل التضاريس أو أضف جسراً/طريقاً.")
            legs.append({"from": a.id, "to": b.id, "reachable": False})
            continue
        path = _trace(pred, src, dst)
        rr, cc = np.divmod(np.asarray(path), W)
        P = np.c_[xs[cc], ys[rr]]
        z = Z[rr, cc]
        seg = np.hypot(*np.diff(P, axis=0).T)
        dz = np.diff(z)
        sl = np.abs(dz) / np.maximum(seg, 1e-9)
        legs.append({"from": a.id, "to": b.id, "reachable": True, "distance_m": float(seg.sum()), "walk_s": float(dist[dst]),
                     "climb_m": float(np.maximum(dz, 0).sum()), "descent_m": float(np.maximum(-dz, 0).sum()),
                     "max_slope_deg": float(math.degrees(math.atan(sl.max()))) if len(sl) else 0.0, "start_distance_m": walked,
                     "points": [[round(float(x), 1), round(float(y), 1)] for x, y in _dp(P, 1.0 * dx)]})
        walked += float(seg.sum())
        nodes_all.append((P, z, seg))
    total_walk = sum(l.get("walk_s", 0.0) for l in legs)
    dwell = sum(p.dwell_min * 60 for p in stops[1:])
    # مقطع طولي كامل
    D, ZZ = [], []
    off = 0.0
    marks = []
    for (P, z, seg), leg in zip(nodes_all, [l for l in legs if l.get("reachable")]):
        cum = off + np.r_[0.0, np.cumsum(seg)]
        step = max(1, len(cum) // 400)
        D += cum[::step].tolist(); ZZ += z[::step].tolist()
        off = float(cum[-1])
    for p in stops:
        r, c = _snap(p.x_m, p.y_m, xs, ys)
        marks.append({"id": p.id, "name": p.name or p.id, "kind": p.kind, "difficulty": p.difficulty, "level_min": p.level_min, "level_max": p.level_max,
                      "z": float(Z[r, c])})
    # الرؤية على طول المسار
    view = {"observers": 0, "bands_m": None, "pois_seen": []}
    if nodes_all:
        Pall = np.vstack([n[0] for n in nodes_all])
        cum = np.r_[0.0, np.cumsum(np.hypot(*np.diff(Pall, axis=0).T))]
        total = float(cum[-1])
        n_obs = int(min(60, max(2, total / 150)))
        ds = np.linspace(0, total, n_obs)
        ox, oy = np.interp(ds, cum, Pall[:, 0]), np.interp(ds, cum, Pall[:, 1])
        far = []
        for x0, y0 in zip(ox, oy):
            X, Y, vis, d = rays(Z, w.size_x_m, w.size_y_m, x0, y0, pl.eye_height_m, pl.view_distance_m, 120)
            far.append(np.where(vis, d[None, :], 0.0).max(axis=1))
        far = np.concatenate(far)
        bands = np.percentile(far, [25, 50, 75, 90]).tolist()
        seen = []
        for p in project.pois:
            if p.kind == "player_start" or p.kind not in SEE_KINDS:
                continue
            zt = float(_sample(Z, w.size_x_m, w.size_y_m, np.array([p.x_m]), np.array([p.y_m]))[0])
            first = None
            for dd, x0, y0 in zip(ds, ox, oy):
                dist = math.hypot(p.x_m - x0, p.y_m - y0)
                if dist <= pl.view_distance_m and los(Z, w.size_x_m, w.size_y_m, x0, y0, pl.eye_height_m, p.x_m, p.y_m, p.landmark_height_m + 2.0):
                    first = (float(dd), dist); break
            seen.append({"id": p.id, "name": p.name or p.id, "kind": p.kind, "first_seen_at_m": first[0] if first else None,
                         "first_seen_distance_m": first[1] if first else None, "ever_seen": first is not None})
        view = {"observers": int(n_obs), "bands_m": [round(b, 1) for b in bands], "mean_far_m": round(float(far.mean()), 1), "pois_seen": seen}
        for sdict in seen:
            if not sdict["ever_seen"] and sdict["kind"] in ("landmark", "boss", "story"):
                warnings.append(f"«{sdict['name']}» لا يُرى من أي نقطة على مسار اللاعب المتوقع.")
    return {"legs": legs, "totals": {"distance_m": walked, "walk_s": total_walk, "dwell_s": dwell, "total_s": total_walk + dwell,
                                     "climb_m": sum(l.get("climb_m", 0) for l in legs), "descent_m": sum(l.get("descent_m", 0) for l in legs),
                                     "max_slope_deg": max([l.get("max_slope_deg", 0) for l in legs] or [0])},
            "profile": {"distance_m": D, "z": ZZ}, "stops": marks, "view": view, "warnings": warnings,
            "suggested_lod_distances_m": ([round(v, 0) for v in view["bands_m"]] if view.get("bands_m") else None)}
