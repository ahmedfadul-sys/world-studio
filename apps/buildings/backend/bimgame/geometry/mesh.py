"""Lightweight triangle mesh (numpy) + primitives + validation.

Winding is counter-clockwise when seen from outside (right-handed, Z up).
Per-face ``slot`` indexes into ``slots`` (material ids) for multi-material parts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


@dataclass
class MeshData:
    v: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float64))
    f: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.int32))
    slot: np.ndarray = field(default_factory=lambda: np.zeros((0,), np.int16))

    @property
    def tris(self) -> int:
        return int(len(self.f))

    def is_empty(self) -> bool:
        return len(self.f) == 0

    def bbox(self) -> tuple[list[float], list[float]]:
        if len(self.v) == 0:
            return [0, 0, 0], [0, 0, 0]
        return self.v.min(0).round(6).tolist(), self.v.max(0).round(6).tolist()

    def add(self, other: "MeshData") -> "MeshData":
        if other.is_empty():
            return self
        off = len(self.v)
        self.v = np.vstack([self.v, other.v])
        self.f = np.vstack([self.f, other.f + off]).astype(np.int32)
        self.slot = np.concatenate([self.slot, other.slot]).astype(np.int16)
        return self

    def transformed(self, rot: np.ndarray | None = None, t: tuple[float, float, float] = (0, 0, 0)) -> "MeshData":
        v = self.v if rot is None else self.v @ rot.T
        return MeshData(v + np.asarray(t), self.f.copy(), self.slot.copy())

    def welded(self, tol: float = 1e-6) -> "MeshData":
        """Merge coincident vertices and drop degenerate/duplicate-index triangles."""
        if len(self.v) == 0:
            return self
        key = np.round(self.v / tol).astype(np.int64)
        _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inv = inv.reshape(-1)
        v = self.v[first]
        f = inv[self.f]
        ok = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
        return MeshData(v, f[ok].astype(np.int32), self.slot[ok])

    # persistence (float32 on disk keeps files small) -----------------------
    def save(self, path: Path, slots: list[str | None] | None = None) -> None:
        np.savez_compressed(path, v=self.v.astype(np.float32), f=self.f, slot=self.slot,
                            slots=np.array([s or "" for s in (slots or [])], dtype="U64"))

    @staticmethod
    def load(path: Path) -> tuple["MeshData", list[str | None]]:
        with np.load(path) as z:
            m = MeshData(z["v"].astype(np.float64), z["f"].astype(np.int32), z["slot"].astype(np.int16))
            return m, [s or None for s in z["slots"].tolist()]


def _mesh(v: list | np.ndarray, f: list | np.ndarray, slot: int | list | np.ndarray = 0) -> MeshData:
    v = np.asarray(v, np.float64).reshape(-1, 3)
    f = np.asarray(f, np.int32).reshape(-1, 3)
    s = np.full(len(f), slot, np.int16) if np.isscalar(slot) else np.asarray(slot, np.int16)
    return MeshData(v, f, s)


def rot_z(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float64)


# primitives ----------------------------------------------------------------
def box(cx: float, cy: float, z0: float, sx: float, sy: float, sz: float, rot_deg: float = 0.0, slot: int = 0) -> MeshData:
    """Axis box with base centre (cx,cy,z0), size (sx,sy,sz), rotated about Z."""
    x, y = sx / 2, sy / 2
    v = np.array([[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0],
                  [-x, -y, sz], [x, -y, sz], [x, y, sz], [-x, y, sz]], np.float64)
    f = [[0, 2, 1], [0, 3, 2],      # bottom (-z)
         [4, 5, 6], [4, 6, 7],      # top (+z)
         [0, 1, 5], [0, 5, 4],      # -y
         [1, 2, 6], [1, 6, 5],      # +x
         [2, 3, 7], [2, 7, 6],      # +y
         [3, 0, 4], [3, 4, 7]]      # -x
    m = _mesh(v, f, slot)
    return m.transformed(rot_z(rot_deg) if rot_deg else None, (cx, cy, z0))


def cylinder(cx: float, cy: float, z0: float, radius: float, height: float, seg: int = 16, slot: int = 0) -> MeshData:
    seg = max(3, seg)
    ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    ring = np.stack([radius * np.cos(ang), radius * np.sin(ang)], 1)
    v = np.vstack([np.c_[ring, np.zeros(seg)], np.c_[ring, np.full(seg, height)], [[0, 0, 0], [0, 0, height]]])
    bc, tc = 2 * seg, 2 * seg + 1
    f = []
    for i in range(seg):
        j = (i + 1) % seg
        f += [[i, j, seg + j], [i, seg + j, seg + i], [bc, j, i], [tc, seg + i, seg + j]]
    return _mesh(v, f, slot).transformed(None, (cx, cy, z0))


def _tri_ccw(tri: Polygon) -> list[tuple[float, float]]:
    pts = list(tri.exterior.coords)[:3]
    (x0, y0), (x1, y1), (x2, y2) = pts
    return pts if (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0) > 0 else [pts[0], pts[2], pts[1]]


def extrude(poly: Polygon, d0: float, d1: float, slot_top: int = 0, slot_bottom: int = 0, slot_side: int = 0) -> MeshData:
    """Extrude a 2D polygon (with holes) in XY from depth d0 to d1 along +Z.

    Top (+Z at d1) and bottom (d0) are triangulated with a constrained Delaunay
    triangulation; side quads follow every ring, so holes become real reveals.
    """
    if poly.is_empty or poly.area < 1e-12:
        return MeshData()
    poly = orient(poly, 1.0)  # exterior CCW, holes CW -> solid always on the left of edges
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    slots: list[int] = []

    def vid(p, d):
        verts.append([p[0], p[1], d])
        return len(verts) - 1

    tris = shapely.constrained_delaunay_triangles(poly)
    for t in tris.geoms:
        if not poly.buffer(1e-9).contains(t.representative_point()):
            continue
        a, b, c = _tri_ccw(t)
        faces.append([vid(a, d1), vid(b, d1), vid(c, d1)]); slots.append(slot_top)
        faces.append([vid(a, d0), vid(c, d0), vid(b, d0)]); slots.append(slot_bottom)
    rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
    for ring in rings:
        for p0, p1 in zip(ring[:-1], ring[1:]):
            A, B, C, D = vid(p0, d0), vid(p1, d0), vid(p1, d1), vid(p0, d1)
            faces += [[A, B, C], [A, C, D]]
            slots += [slot_side, slot_side]
    return _mesh(verts, faces, slots).welded()


# validation ------------------------------------------------------------------
def signed_volume(m: MeshData) -> float:
    if m.is_empty():
        return 0.0
    a, b, c = (m.v[m.f[:, i]] for i in range(3))
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def is_watertight(m: MeshData) -> bool:
    """True if every undirected edge is used exactly twice, once per direction."""
    w = m.welded()
    if w.is_empty():
        return False
    e = np.concatenate([w.f[:, [0, 1]], w.f[:, [1, 2]], w.f[:, [2, 0]]])
    directed = {(int(a), int(b)) for a, b in e}
    if len(directed) != len(e):
        return False  # a directed edge repeated -> overlapping/duplicated faces
    return all((b, a) in directed for a, b in directed)


def mesh_issues(m: MeshData) -> list[str]:
    out = []
    if m.is_empty():
        return ["mesh is empty"]
    if not np.isfinite(m.v).all():
        out.append("non-finite vertex coordinates")
    a, b, c = (m.v[m.f[:, i]] for i in range(3))
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    if (area < 1e-12).any():
        out.append(f"{int((area < 1e-12).sum())} degenerate triangles")
    return out
