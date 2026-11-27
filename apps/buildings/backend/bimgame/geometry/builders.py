"""Procedural mesh builders (pure numpy/shapely; no Blender). All units metres.

Each builder returns ``(MeshData, slots)`` where ``slots[i]`` is the material
id for face slot ``i`` (None = element default material).
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry import box as sbox
from shapely.geometry.polygon import orient

from ..bim.model import RBeam, RColumn, RDecor, RFloor, RLamp, ROpening, RRoad, RRoof, RStair, RWall
from .mesh import MeshData, _mesh, _tri_ccw, box, cylinder, extrude

DETAIL = {  # circle segments / arch segments per preset
    "low": {"seg": 8, "arch": 6},
    "medium": {"seg": 16, "arch": 12},
    "high": {"seg": 32, "arch": 24},
}
FRAME_W = 0.06  # door/window frame bar width (m)
Built = tuple[MeshData, list[str | None]]


def _frame(ax: float, ay: float, dx: float, dy: float, z0: float) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Proper rotation mapping local (x,y,z) -> (direction, up, right-normal)."""
    d = np.array([dx, dy, 0.0])
    nr = np.array([dy, -dx, 0.0])
    return np.column_stack([d, [0, 0, 1], nr]), (ax, ay, z0)


def _dir(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float]:
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    return (b[0] - a[0]) / L, (b[1] - a[1]) / L, L


# walls -------------------------------------------------------------------------
def _opening_poly(o: ROpening, arch_seg: int) -> Polygon:
    u0, u1 = o.u - o.width / 2, o.u + o.width / 2
    if o.shape == "arch" and o.height > o.width / 2:
        r = o.width / 2
        top = o.sill + o.height - r
        pts = [(u0, o.sill), (u1, o.sill), (u1, top)]
        pts += [(o.u + r * math.cos(t), top + r * math.sin(t)) for t in np.linspace(0, math.pi, arch_seg + 1)[1:-1]]
        pts += [(u0, top)]
        return Polygon(pts)
    return sbox(u0, o.sill, u1, o.sill + o.height)


def _feature_poly(f) -> Polygon | None:
    try:
        p = Polygon(f.polygon)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.area < 1e-8:
            return None
        return p
    except Exception:  # noqa: BLE001 - a broken shape must never kill the whole wall
        return None


def _to_manifold(m: MeshData):
    import manifold3d as m3d
    w = m.welded()
    return m3d.Manifold(m3d.Mesh(vert_properties=w.v.astype(np.float32), tri_verts=w.f.astype(np.uint32)))


def _from_manifold(mf, slot_depth_axis: int = 2) -> MeshData:
    mesh = mf.to_mesh()
    v = np.asarray(mesh.vert_properties, np.float64)[:, :3]
    f = np.asarray(mesh.tri_verts, np.int32)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    slot = (n[:, slot_depth_axis] / ln > 0.7).astype(np.int16)  # faces looking to +depth = right face
    return MeshData(v, f, slot).welded()


def _apply_depth_features(m: MeshData, w: RWall, outline, recess: list, relief: list) -> MeshData:
    """Boolean recesses (difference) and reliefs (union) on the extruded wall. Needs manifold3d."""
    try:
        import manifold3d  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ValueError("wall recess/relief shapes need the 'manifold3d' package (pip install manifold3d)") from exc
    t = w.thickness
    eps = min(0.02, t / 10)
    ph = float(t / 2)

    def prism(poly: Polygon, f) -> MeshData:
        d = min(f.depth, t - 2 * eps) if f.kind == "recess" else f.depth
        if f.face == "right":
            d0, d1 = (ph - d, ph + eps) if f.kind == "recess" else (ph - eps, ph + d)
        else:
            d0, d1 = (-ph - eps, -ph + d) if f.kind == "recess" else (-ph - d, -ph + eps)
        return extrude(poly, d0, d1)

    base = _to_manifold(m)
    if recess:
        cutters = [_to_manifold(prism(p, f)) for p, f in recess]
        import manifold3d as m3d
        base = base - m3d.Manifold.batch_boolean(cutters, m3d.OpType.Add)
    if relief:
        import manifold3d as m3d
        adds = [_to_manifold(prism(p, f)) for p, f in relief]
        base = base + m3d.Manifold.batch_boolean(adds, m3d.OpType.Add)
    return _from_manifold(base)


def wall_mesh(w: RWall, ext_a: float, ext_b: float, detail: str = "medium") -> Built:
    """Wall solid with REAL holes: elevation outline minus openings (+ through cuts), then extruded.

    Recess/relief shapes (wall.features) are applied afterwards as 3D booleans in wall-local space."""
    dx, dy, L = _dir(w.a, w.b)
    outline: Polygon | MultiPolygon = sbox(-ext_a, 0.0, L + ext_b, w.height)
    for o in w.openings:
        outline = outline.difference(_opening_poly(o, DETAIL[detail]["arch"]))
    shapes = [(f, _feature_poly(f)) for f in w.features]
    for f, p in shapes:
        if f.kind == "cut" and p is not None:
            outline = outline.difference(p)
    solid = outline  # silhouette incl. cuts: reliefs are clipped to it
    polys = [g for g in (list(outline.geoms) if isinstance(outline, MultiPolygon) else [outline]) if not g.is_empty and g.area > 1e-9]
    m = MeshData()
    for p in polys:
        # local (x=u, y=z, z=depth) -> slot 1 on +depth (right face), slot 0 on left/sides
        m.add(extrude(p, -w.thickness / 2, w.thickness / 2, slot_top=1, slot_bottom=0, slot_side=0))
    recess = [(p, f) for f, p in shapes if f.kind == "recess" and p is not None and p.intersects(solid)]
    relief = []
    for f, p in shapes:
        if f.kind == "relief" and p is not None:
            clipped = p.intersection(solid)
            for g in (clipped.geoms if hasattr(clipped, "geoms") else [clipped]):
                if g.geom_type == "Polygon" and g.area > 1e-8:
                    relief.append((g, f))
    if (recess or relief) and not m.is_empty():
        m = _apply_depth_features(m, w, solid, recess, relief)
    R, t = _frame(w.a[0], w.a[1], dx, dy, w.z0)
    return m.transformed(R, t), [w.material, w.material_inner or w.material]


def opening_fill_mesh(w: RWall, o: ROpening, detail: str = "medium") -> Built:
    """Door leaf+frame or window frame+glass, placed inside the wall's hole."""
    if o.kind == "opening":
        return MeshData(), []
    dx, dy, _ = _dir(w.a, w.b)
    ang = math.degrees(math.atan2(dy, dx))
    nr = (dy, -dx)
    cx, cy = w.a[0] + dx * o.u, w.a[1] + dy * o.u
    z0 = w.z0 + o.sill
    depth = max(0.05, min(w.thickness, 0.25))
    fw = min(FRAME_W, o.width / 4, o.height / 4)
    m = MeshData()

    def bar(du: float, dz: float, sx: float, sz: float, sy: float = depth, d_off: float = 0.0, slot: int = 0) -> None:
        bx, by = cx + dx * du + nr[0] * d_off, cy + dy * du + nr[1] * d_off
        m.add(box(bx, by, z0 + dz, sx, sy, sz, ang, slot))

    half = o.width / 2
    bar(-half + fw / 2, 0, fw, o.height)                       # left jamb
    bar(half - fw / 2, 0, fw, o.height)                        # right jamb
    bar(0, o.height - fw, o.width - 2 * fw, fw)                # head
    if o.kind == "door":
        bar(0, 0, o.width - 2 * fw, o.height - fw, sy=0.04)    # door leaf
        return m, [o.material]
    bar(0, 0, o.width - 2 * fw, fw)                            # sill bar
    bar(0, fw, o.width - 2 * fw, o.height - 2 * fw, sy=0.01, slot=1)  # glass pane
    return m, [o.material, "mat_glass"]


# columns / beams / decor ----------------------------------------------------
def column_mesh(c: RColumn, detail: str = "medium") -> Built:
    if c.shape == "round":
        return cylinder(c.pos[0], c.pos[1], c.z0, c.width / 2, c.height, DETAIL[detail]["seg"]), [c.material]
    return box(c.pos[0], c.pos[1], c.z0, c.width, c.depth, c.height), [c.material]


def beam_mesh(b: RBeam, detail: str = "medium") -> Built:
    dx, dy, L = _dir(b.a, b.b)
    mx, my = (b.a[0] + b.b[0]) / 2, (b.a[1] + b.b[1]) / 2
    return box(mx, my, b.z_top - b.depth, L, b.width, b.depth, math.degrees(math.atan2(dy, dx))), [b.material]


def decor_mesh(d: RDecor, detail: str = "medium") -> Built:
    sx, sy, sz = d.size
    if d.shape == "cylinder":
        return cylinder(d.pos[0], d.pos[1], d.z0, sx / 2, sz, DETAIL[detail]["seg"]), [d.material]
    return box(d.pos[0], d.pos[1], d.z0, sx, sy, sz, d.rotation_deg), [d.material]


# floors / ceilings / balconies ---------------------------------------------
def floor_mesh(f: RFloor, detail: str = "medium") -> Built:
    poly = Polygon(f.polygon, f.holes)
    if not poly.is_valid or poly.area < 1e-6:
        raise ValueError(f"floor polygon is invalid or has zero area ({f.id})")
    return extrude(poly, f.z_top - f.thickness, f.z_top), [f.material]


# roofs -----------------------------------------------------------------------
def _poly_fan(pts: list[np.ndarray], up: bool = True) -> list[list[np.ndarray]]:
    """Fan-triangulate a planar convex polygon, oriented so its normal faces up."""
    tris = [[pts[0], pts[i], pts[i + 1]] for i in range(1, len(pts) - 1)]
    out = []
    for a, b, c in tris:
        n = np.cross(b - a, c - a)
        if np.linalg.norm(n) < 1e-12:
            continue
        out.append([a, b, c] if n[2] > 0 else [a, c, b])
    return out


def _roof_solid(surfaces, loop, z0, t, V) -> MeshData:
    """Top surfaces + flat bottom cap at z0-t + skirt along `loop` (every loop vertex keeps its own top z)."""
    verts: list[np.ndarray] = []
    faces: list[list[int]] = []

    def vid(p: np.ndarray) -> int:
        verts.append(p)
        return len(verts) - 1

    for s_ in surfaces:
        for tri in _poly_fan(s_):
            faces.append([vid(p) for p in tri])
    # bottom cap uses EVERY loop vertex so skirt edges match exactly
    cap = Polygon([(p[0], p[1]) for p in loop])
    for tri in shapely.constrained_delaunay_triangles(cap).geoms:
        a, b, c = _tri_ccw(tri)
        faces.append([vid(V(a[0], a[1], z0 - t)), vid(V(c[0], c[1], z0 - t)), vid(V(b[0], b[1], z0 - t))])
    for i, p in enumerate(loop):
        q = loop[(i + 1) % len(loop)]
        A, B, C, D = vid(V(p[0], p[1], z0 - t)), vid(V(q[0], q[1], z0 - t)), vid(q), vid(p)
        faces += [[A, B, C], [A, C, D]]
    return _mesh(np.array(verts), faces).welded()


def _radial_roof(r: RRoof, poly: Polygon, detail: str) -> MeshData:
    """Cone / pyramid / dome: rings shrink from the (overhang-offset) eave outline to an apex over the centroid."""
    V = lambda x, y, z: np.array([x, y, z], np.float64)  # noqa: E731
    big = orient(poly.buffer(r.overhang, join_style=2) if r.overhang else poly, 1.0)
    c = poly.centroid
    if not poly.contains(c):
        raise ValueError(f"roof '{r.kind}' needs a shape that contains its centre ({r.id})")
    ring = [(x, y) for x, y in big.exterior.coords[:-1]]
    cx, cy = c.x, c.y
    R = sum(math.hypot(x - cx, y - cy) for x, y in ring) / len(ring)
    z0, t = r.z_eave, r.thickness
    if r.kind == "cone":
        steps = [(1.0, 0.0), (0.0, R * math.tan(math.radians(r.pitch_deg)))]
    else:  # dome: ellipsoid cap, height = R*sin(pitch)
        n = {"low": 4, "medium": 8, "high": 14}.get(detail, 8)
        h = R * math.sin(math.radians(max(r.pitch_deg, 5.0)))
        steps = [(math.cos(math.pi / 2 * k / n), h * math.sin(math.pi / 2 * k / n)) for k in range(n + 1)]
        steps[-1] = (0.0, h)
    rings = [[V(cx + (x - cx) * sc, cy + (y - cy) * sc, z0 + dz) for x, y in ring] for sc, dz in steps]
    surfaces = []
    m = len(ring)
    for k in range(len(rings) - 1):
        for i in range(m):
            j = (i + 1) % m
            surfaces.append([rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]])
    return _roof_solid(surfaces, rings[0], z0, t, V)


def _barrel_roof(r: RRoof, poly: Polygon, detail: str) -> MeshData:
    """Half-cylinder vault over the bounding rectangle, running along ridge_axis."""
    V = lambda x, y, z: np.array([x, y, z], np.float64)  # noqa: E731
    minx, miny, maxx, maxy = poly.bounds
    minx, miny, maxx, maxy = minx - r.overhang, miny - r.overhang, maxx + r.overhang, maxy + r.overhang
    if r.ridge_axis == "x":
        Lr, W, rot = maxx - minx, maxy - miny, 0.0
    else:
        Lr, W, rot = maxy - miny, maxx - minx, 90.0
    z0, t = r.z_eave, r.thickness
    h = (W / 2) * math.sin(math.radians(max(r.pitch_deg, 5.0)))
    n = {"low": 6, "medium": 12, "high": 24}.get(detail, 12)
    prof = [(-W / 2 * math.cos(math.pi * j / n), h * math.sin(math.pi * j / n)) for j in range(n + 1)]
    L = [V(-Lr / 2, y, z0 + z) for y, z in prof]
    R = [V(Lr / 2, y, z0 + z) for y, z in prof]
    surfaces = [[L[j], R[j], R[j + 1], L[j + 1]] for j in range(n)]
    loop = [L[0], R[0]] + R[1:] + L[::-1][:-1]
    m = _roof_solid(surfaces, loop, z0, t, V)
    Rm = np.array([[math.cos(math.radians(rot)), -math.sin(math.radians(rot)), 0],
                   [math.sin(math.radians(rot)), math.cos(math.radians(rot)), 0], [0, 0, 1]])
    return m.transformed(Rm, ((minx + maxx) / 2, (miny + maxy) / 2, 0.0))


def roof_mesh(r: RRoof, detail: str = "medium") -> Built:
    poly = Polygon(r.polygon)
    if not poly.is_valid or poly.area < 1e-6:
        raise ValueError(f"roof polygon is invalid or has zero area ({r.id})")
    if r.kind == "flat":
        big = poly.buffer(r.overhang, join_style=2) if r.overhang else poly
        return extrude(big, r.z_eave, r.z_eave + r.thickness), [r.material]
    if r.kind in ("cone", "dome"):
        return _radial_roof(r, poly, detail), [r.material]
    if r.kind == "barrel":
        return _barrel_roof(r, poly, detail), [r.material]

    minx, miny, maxx, maxy = poly.bounds
    minx, miny, maxx, maxy = minx - r.overhang, miny - r.overhang, maxx + r.overhang, maxy + r.overhang
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    if r.ridge_axis == "x":
        Lr, W, rot = maxx - minx, maxy - miny, 0.0
    else:
        Lr, W, rot = maxy - miny, maxx - minx, 90.0
    tan = math.tan(math.radians(r.pitch_deg))
    z0, t = r.z_eave, r.thickness
    V = lambda x, y, z: np.array([x, y, z], np.float64)  # noqa: E731
    E1, E2, F2, F1 = V(-Lr / 2, -W / 2, z0), V(Lr / 2, -W / 2, z0), V(Lr / 2, W / 2, z0), V(-Lr / 2, W / 2, z0)

    if r.kind == "shed":
        rise = W * tan
        F1[2] = F2[2] = z0 + rise
        surfaces, loop = [[E1, E2, F2, F1]], [E1, E2, F2, F1]
    elif r.kind == "gable":
        zr = z0 + (W / 2) * tan
        R1, R2 = V(-Lr / 2, 0, zr), V(Lr / 2, 0, zr)
        surfaces = [[E1, E2, R2, R1], [R1, R2, F2, F1]]
        loop = [E1, E2, R2, F2, F1, R1]
    else:  # hip
        zr = z0 + (min(W, Lr) / 2) * tan
        hr = max(0.0, (Lr - W) / 2)
        Ra, Rb = V(-hr, 0, zr), V(hr, 0, zr)
        if Lr < W:  # tall-narrow footprint: ridge runs the other way; keep it simple and valid
            hr2 = (W - Lr) / 2
            Ra, Rb = V(0, -hr2, zr), V(0, hr2, zr)
            surfaces = [[E1, E2, Ra], [E2, F2, Rb, Ra], [F2, F1, Rb], [F1, E1, Ra, Rb]]
        else:
            surfaces = [[E1, E2, Rb, Ra], [E2, F2, Rb], [F2, F1, Ra, Rb], [F1, E1, Ra]]
        loop = [E1, E2, F2, F1]

    verts: list[np.ndarray] = []
    faces: list[list[int]] = []

    def vid(p: np.ndarray) -> int:
        verts.append(p)
        return len(verts) - 1

    for s in surfaces:
        for tri in _poly_fan(s):
            faces.append([vid(p) for p in tri])
    # bottom cap uses EVERY loop vertex (ridge ends included) so skirt edges match exactly
    cap = Polygon([(p[0], p[1]) for p in loop])
    for tri in shapely.constrained_delaunay_triangles(cap).geoms:
        a, b, c = _tri_ccw(tri)
        faces.append([vid(V(a[0], a[1], z0 - t)), vid(V(c[0], c[1], z0 - t)), vid(V(b[0], b[1], z0 - t))])
    for i, p in enumerate(loop):
        q = loop[(i + 1) % len(loop)]
        A, B, C, D = vid(V(p[0], p[1], z0 - t)), vid(V(q[0], q[1], z0 - t)), vid(q), vid(p)
        faces += [[A, B, C], [A, C, D]]
    m = _mesh(np.array(verts), faces).welded()
    R = np.array([[math.cos(math.radians(rot)), -math.sin(math.radians(rot)), 0],
                  [math.sin(math.radians(rot)), math.cos(math.radians(rot)), 0], [0, 0, 1]])
    return m.transformed(R, (cx, cy, 0.0)), [r.material]


# stairs ----------------------------------------------------------------------
def _spiral_stair(s: RStair, detail: str) -> Built:
    """سلّم لولبي: كل درجة قطاع حلقي صلب من الأرض حتى ارتفاعها + عمود مركزي."""
    n = max(1, s.steps)
    r_in = max(0.0, s.inner_radius)
    r_out = r_in + s.width
    sgn = -1.0 if s.clockwise else 1.0
    dth = math.radians(s.turn_deg) / n
    a0 = math.radians(s.angle_deg)
    k = max(1, DETAIL[detail]["seg"] // 8)      # عدد أقسام القوس لكل درجة
    m = MeshData()
    for i in range(n):
        ang = [a0 + sgn * (i + j / k) * dth for j in range(k + 1)]
        outer = [(r_out * math.cos(a), r_out * math.sin(a)) for a in ang]
        inner = [(r_in * math.cos(a), r_in * math.sin(a)) for a in reversed(ang)] if r_in > 1e-6 else [(0.0, 0.0)]
        poly = Polygon(outer + inner)
        if not poly.is_valid:
            poly = poly.buffer(0)
        m.add(extrude(poly, 0.0, (i + 1) * s.rise))
    if r_in > 0.02:
        m.add(cylinder(0.0, 0.0, 0.0, r_in, n * s.rise + 1.0, DETAIL[detail]["seg"]))
    return m.transformed(None, (s.start[0], s.start[1], s.z0)), [s.material]


def stair_mesh(s: RStair, detail: str = "medium") -> Built:
    """One watertight solid: the step silhouette extruded across the stair width."""
    if s.kind == "spiral":
        return _spiral_stair(s, detail)
    pts = [(0.0, 0.0)]
    for i in range(s.steps):
        pts += [(i * s.run, (i + 1) * s.rise), ((i + 1) * s.run, (i + 1) * s.rise)]
    pts += [(s.steps * s.run, 0.0)]
    m = extrude(Polygon(pts), -s.width / 2, s.width / 2)
    ang = math.radians(s.angle_deg)
    R, t = _frame(s.start[0], s.start[1], math.cos(ang), math.sin(ang), s.z0)
    return m.transformed(R, t), [s.material]


# roads / street lamps ---------------------------------------------------------
def _clean_ring(coords) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for x, y in coords:
        q = (round(float(x), 6), round(float(y), 6))
        if not out or q != out[-1]:
            out.append(q)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _clean_poly(poly: Polygon) -> list[Polygon]:
    """تقريب الإحداثيات إلى 1 ميكرون وحذف النقاط المتتالية المتطابقة: buffer على خط مائل يترك رؤوساً تبعد 1e-15 فتنتج مثلثات منحلّة (خطأ «الأبعاد»)."""
    ext = _clean_ring(poly.exterior.coords)
    if len(ext) < 3:
        return []
    holes = [h for h in (_clean_ring(r.coords) for r in poly.interiors) if len(h) >= 3]
    q = Polygon(ext, holes)
    if not q.is_valid:
        q = q.buffer(0)
    return [g for g in getattr(q, "geoms", [q]) if isinstance(g, Polygon) and g.area > 1e-6]


def road_mesh(r: RRoad, detail: str = "medium") -> Built:
    """الطريق (slot 0) + الرصيفان (slot 1) المرتفعان بمقدار `curb`؛ المسار متعدد الخطوط يُعرَّض بحواف قائمة."""
    pts: list[tuple[float, float]] = []
    for p in r.path:
        if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
            pts.append((p[0], p[1]))
    if len(pts) < 2:
        raise ValueError(f"road has fewer than 2 distinct points ({r.id})")
    line = shapely.LineString(pts)
    kw = dict(cap_style="flat", join_style="mitre", mitre_limit=3.0)
    body = line.buffer(r.width / 2, **kw)
    if body.is_empty:
        raise ValueError(f"road polygon is empty ({r.id})")
    m = MeshData()

    def _safe_extrude(q: Polygon, z0: float, z1: float, *slots: int) -> None:
        try:
            m.add(extrude(q, z0, z1, *slots))
        except shapely.errors.GEOSException:                  # طريق يتقاطع مع نفسه كثيراً: نبسّط الشكل قليلاً ثم نعيد المحاولة
            for g in _clean_poly(q.simplify(0.02)):
                m.add(extrude(g, z0, z1, *slots))

    for poly in getattr(body, "geoms", [body]):
        for q in _clean_poly(poly):
            _safe_extrude(q, r.z0, r.z0 + r.thickness)
    if r.sidewalk > 1e-6:
        walk = line.buffer(r.width / 2 + r.sidewalk, **kw).difference(body)
        for poly in getattr(walk, "geoms", [walk]):
            if isinstance(poly, Polygon):
                for q in _clean_poly(poly):
                    _safe_extrude(q, r.z0, r.z0 + r.thickness + r.curb, 1, 1, 1)
    if not m.is_empty():                                         # أي مثلث بمساحة صفر (تقاطعات ذاتية) يُحذف بدل أن يُفشل البناء
        a, b, c = (m.v[m.f[:, i]] for i in range(3))
        keep = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2 >= 1e-12
        m.f, m.slot = m.f[keep], m.slot[keep]
    return m, [r.material, r.sidewalk_material]


def lamp_light(l: RLamp) -> dict:
    ang = math.radians(l.arm_deg)
    return {"pos": [l.pos[0] + math.cos(ang) * l.arm, l.pos[1] + math.sin(ang) * l.arm, l.z0 + l.height - 0.15],
            "color": l.color, "intensity": l.intensity, "range": l.range}


def lamp_mesh(l: RLamp, detail: str = "medium") -> Built:
    seg = DETAIL[detail]["seg"]
    m = cylinder(l.pos[0], l.pos[1], l.z0, l.pole_radius * 1.8, 0.25, seg)            # قاعدة
    m.add(cylinder(l.pos[0], l.pos[1], l.z0 + 0.25, l.pole_radius, l.height - 0.25, seg))
    ang = math.radians(l.arm_deg)
    hx, hy = l.pos[0], l.pos[1]
    if l.arm > 1e-6:
        mx, my = l.pos[0] + math.cos(ang) * l.arm / 2, l.pos[1] + math.sin(ang) * l.arm / 2
        m.add(box(mx, my, l.z0 + l.height - 0.08, l.arm, l.pole_radius * 1.4, l.pole_radius * 1.4, l.arm_deg))
        hx, hy = l.pos[0] + math.cos(ang) * l.arm, l.pos[1] + math.sin(ang) * l.arm
    head = box(hx, hy, l.z0 + l.height - 0.22, 0.34, 0.2, 0.22, l.arm_deg, slot=1)
    m.add(head)
    return m, [l.material, "mat_lamp_head"]
