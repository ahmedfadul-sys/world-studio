"""Wall junction handling (corners, T-junctions, crosses). Works on raw project data (metres).

Rule: at each wall end, if it meets another wall (corner at its endpoint, or T
onto its interior) and the two are not collinear, extend the end by half the
other wall's thickness so the outer corner is closed. Crosses need no
extension (the solids simply overlap). Collinear continuation: no extension.
"""
from __future__ import annotations

import math

from ..schema import Project

TOL = 1e-3  # metres


def _dist_pt_seg(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L2))
    return math.hypot(p[0] - (ax + t * vx), p[1] - (ay + t * vy))


def wall_segments(project: Project) -> dict[str, tuple[str, tuple, tuple, float]]:
    k = project.units.to_meters
    return {
        e.id: (e.level_id, (e.a[0] * k, e.a[1] * k), (e.b[0] * k, e.b[1] * k), e.thickness * k)
        for e in project.elements if e.type == "wall"
    }


def _grid(segs: dict, cell: float = 2.0) -> dict[tuple, list[str]]:
    """Spatial hash of wall bounding boxes so neighbour queries are ~O(1), not O(walls)."""
    g: dict[tuple, list[str]] = {}
    for i, (lv, a, b, t) in segs.items():
        x0, x1 = sorted((a[0], b[0])); y0, y1 = sorted((a[1], b[1]))
        pad = t + TOL
        for cx in range(int((x0 - pad) // cell), int((x1 + pad) // cell) + 1):
            for cy in range(int((y0 - pad) // cell), int((y1 + pad) // cell) + 1):
                g.setdefault((lv, cx, cy), []).append(i)
    return g


def _near(grid: dict, lv: str, p: tuple, cell: float = 2.0) -> set[str]:
    return set(grid.get((lv, int(p[0] // cell), int(p[1] // cell)), ()))


def touching(project: Project) -> dict[str, set[str]]:
    """wall id -> ids of other walls touching either end (corner or T)."""
    segs = wall_segments(project)
    grid = _grid(segs)
    out: dict[str, set[str]] = {i: set() for i in segs}
    for i, (li, ai, bi, _) in segs.items():
        for p in (ai, bi):
            for j in _near(grid, li, p):
                if j != i and _dist_pt_seg(p, segs[j][1], segs[j][2]) <= TOL:
                    out[i].add(j)
                    out[j].add(i)
    return out


def extensions(project: Project) -> dict[str, tuple[float, float]]:
    """wall id -> (extension at a, extension at b) in metres."""
    segs = wall_segments(project)
    grid = _grid(segs)
    res: dict[str, tuple[float, float]] = {}
    for i, (li, ai, bi, _) in segs.items():
        di = (bi[0] - ai[0], bi[1] - ai[1])
        Li = math.hypot(*di)
        ext = []
        for p in (ai, bi):
            e = 0.0
            for j in _near(grid, li, p):
                lj, aj, bj, tj = segs[j]
                if i == j or _dist_pt_seg(p, aj, bj) > TOL:
                    continue
                dj = (bj[0] - aj[0], bj[1] - aj[1])
                Lj = math.hypot(*dj)
                sin = abs(di[0] * dj[1] - di[1] * dj[0]) / (Li * Lj)
                if sin < 1e-3:  # collinear / parallel
                    continue
                x = tj / 2
                # End-to-end corner turning <= 90 deg: exact mitre extension (t/2)*tan(turn/2) (90 deg -> t/2).
                end_j = (aj, bj)[0] if math.hypot(p[0] - aj[0], p[1] - aj[1]) <= TOL else ((bj if math.hypot(p[0] - bj[0], p[1] - bj[1]) <= TOL else None))
                if end_j is not None:
                    ui = (-di[0] / Li, -di[1] / Li) if p is bi else (di[0] / Li, di[1] / Li)
                    uo = (dj[0] / Lj, dj[1] / Lj) if end_j is aj else (-dj[0] / Lj, -dj[1] / Lj)
                    cos_phi = ui[0] * uo[0] + ui[1] * uo[1]
                    if cos_phi <= 1e-7:
                        x = tj / 2 * math.tan((math.pi - math.acos(max(-1.0, min(1.0, cos_phi)))) / 2)
                e = max(e, x)
            ext.append(e)
        res[i] = (ext[0], ext[1])
    return res
