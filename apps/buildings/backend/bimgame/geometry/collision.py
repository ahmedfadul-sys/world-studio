"""Analytic collision decomposition for walls.

A single box over a wall with a door would block the doorway in game. Instead
the wall's solid region is decomposed into non-overlapping boxes that leave
every opening open (arch openings use their bounding rectangle, i.e. the
collision is slightly conservative there).
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from ..bim.model import RWall

MIN = 1e-3


def wall_boxes(w: RWall, ext_a: float, ext_b: float) -> list[list[float]]:
    """-> list of [cx, cy, z0, sx, sy, sz, rot_deg] (world, metres)."""
    dx, dy = w.b[0] - w.a[0], w.b[1] - w.a[1]
    L = math.hypot(dx, dy)
    ux, uy = dx / L, dy / L
    lo, hi = -ext_a, L + ext_b
    openings = list(w.openings)
    for f in w.features:  # through-cuts keep the doorway-like gap open (notches at the top edge stay solid)
        if f.kind != "cut":
            continue
        us = [p[0] for p in f.polygon]; vs = [p[1] for p in f.polygon]
        v0, v1 = max(0.0, min(vs)), min(w.height, max(vs))
        if v1 - v0 < MIN or max(vs) >= w.height - MIN:
            continue
        openings.append(SimpleNamespace(u=(min(us) + max(us)) / 2, width=max(us) - min(us), sill=v0, height=v1 - v0))
    cuts = {lo, hi}
    for o in openings:
        for v in (o.u - o.width / 2, o.u + o.width / 2):
            cuts.add(min(max(v, lo), hi))
    xs = sorted(cuts)

    pieces: list[list[float]] = []  # [u0, u1, za, zb]
    for u0, u1 in zip(xs[:-1], xs[1:]):
        if u1 - u0 < MIN:
            continue
        mid = (u0 + u1) / 2
        blocked = sorted((o.sill, min(o.sill + o.height, w.height)) for o in openings
                         if o.u - o.width / 2 <= mid <= o.u + o.width / 2)
        z = 0.0
        free: list[tuple[float, float]] = []
        for a, b in blocked:
            if a > z + MIN:
                free.append((z, a))
            z = max(z, b)
        if w.height > z + MIN:
            free.append((z, w.height))
        for za, zb in free:
            if pieces and abs(pieces[-1][1] - u0) < 1e-9 and abs(pieces[-1][2] - za) < 1e-9 and abs(pieces[-1][3] - zb) < 1e-9:
                pieces[-1][1] = u1
            else:
                pieces.append([u0, u1, za, zb])

    rot = math.degrees(math.atan2(dy, dx))
    out = []
    for u0, u1, za, zb in pieces:
        c = (u0 + u1) / 2
        out.append([w.a[0] + ux * c, w.a[1] + uy * c, w.z0 + za, u1 - u0, w.thickness, zb - za, rot])
    return out
