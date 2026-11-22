"""The ONLY module that imports debim.

Pipeline: internal ``Project`` -> debim manifest (grid-referenced, metres) ->
``debim.schema.ProjectManifest`` -> ``debim.resolver.SpatialResolver.resolve()``
-> ``RBuilding`` (plain dataclasses in metres).

debim resolves placement of walls (+ door/window children), slabs, and
columns. Beams, stairs, roofs, decor and custom openings are normalised here
without debim: their debim schemas are not wired in this adapter (documented
in docs/01-feasibility-and-debim-report.md).

Verified against debim 1.2.0. ``SUPPORTED_RANGE`` guards against silent API
drift: other versions emit a warning and still try, but errors are reported.
"""
from __future__ import annotations

import logging
from typing import Iterable

from ..schema import OPENING_TYPES, Project
from ..utils.errors import AppError, DependencyError
from .model import (RBeam, RBuilding, RColumn, RDecor, RFeature, RFloor, ROpening, RRoof,
                    RStair, RWall)
from .modules import apply_modules

log = logging.getLogger("bimgame.debim")

SUPPORTED_RANGE = ("1.2.0", "1.2.99")
_DEFAULT_MAT = "default"


def _load_debim():
    try:
        import debim
        from debim.resolver import SpatialResolver
        from debim.schema import ProjectManifest
    except Exception as exc:  # pragma: no cover - exercised only when missing
        raise DependencyError(
            "debim is not importable", "bim.debim_adapter",
            f"{type(exc).__name__}: {exc}", "Install it in the backend venv: pip install debim==1.2.0",
        ) from exc
    return debim, ProjectManifest, SpatialResolver


def debim_version() -> str:
    return _load_debim()[0].__version__


def _ver_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".")[:3] if x.isdigit())


class _Axes:
    """Free-form coordinates -> named debim grid axes (rounded to 1 micron)."""

    def __init__(self) -> None:
        self.x: dict[float, str] = {}
        self.y: dict[float, str] = {}

    @staticmethod
    def _k(v: float) -> float:
        return round(v, 6)

    def gx(self, v: float) -> str:
        return self.x.setdefault(self._k(v), f"X{len(self.x)}")

    def gy(self, v: float) -> str:
        return self.y.setdefault(self._k(v), f"Y{len(self.y)}")

    def pt(self, p: tuple[float, float]) -> list[str]:
        return [self.gx(p[0]), self.gy(p[1])]

    def as_manifest(self) -> dict:
        return {
            "axes_x": {n: v for v, n in self.x.items()} or {"X0": 0.0},
            "axes_y": {n: v for v, n in self.y.items()} or {"Y0": 0.0},
        }


def _sc(p: tuple[float, float], k: float) -> tuple[float, float]:
    return (p[0] * k, p[1] * k)


def select_elements(project: Project, element_ids: Iterable[str] | None, levels: Iterable[str] | None):
    """Pick elements for a (partial) resolve; openings always travel with their host wall."""
    ids = set(element_ids) if element_ids is not None else None
    lv = set(levels) if levels is not None else None
    chosen = []
    for e in project.elements:
        if lv is not None and e.level_id not in lv:
            continue
        if ids is not None:
            host = getattr(e, "wall_id", None)
            if e.id not in ids and not (host and host in ids):
                continue
        chosen.append(e)
    # a selected opening needs its host wall resolved too
    have = {e.id for e in chosen}
    by_id = {e.id: e for e in project.elements}
    for e in list(chosen):
        host = getattr(e, "wall_id", None)
        if host and host not in have and host in by_id:
            chosen.append(by_id[host])
            have.add(host)
    return chosen


def resolve(project: Project, element_ids: Iterable[str] | None = None, levels: Iterable[str] | None = None) -> RBuilding:
    """Resolve (a subset of) the project through debim into metre-based dataclasses."""
    debim, ProjectManifest, SpatialResolver = _load_debim()
    ver = debim.__version__
    if not (_ver_tuple(SUPPORTED_RANGE[0]) <= _ver_tuple(ver) <= _ver_tuple(SUPPORTED_RANGE[1])):
        log.warning("debim %s is outside the verified range %s", ver, SUPPORTED_RANGE)

    proj = apply_modules(project)
    k = proj.units.to_meters
    chosen = select_elements(proj, element_ids, levels)
    lvl = {lv.id: lv for lv in proj.levels}
    axes = _Axes()
    mat_ids = {m.id for m in proj.materials}

    def mat(m: str | None) -> str:
        return m if m in mat_ids else _DEFAULT_MAT

    walls = {e.id: e for e in chosen if e.type == "wall"}
    kids: dict[str, list] = {}
    for e in chosen:
        if e.type in ("door", "window"):
            kids.setdefault(e.wall_id, []).append(e)  # type: ignore[union-attr]

    elements: list[dict] = []
    for w in walls.values():
        a, b = _sc(w.a, k), _sc(w.b, k)  # type: ignore[union-attr]
        h = (w.height if w.height else lvl[w.level_id].height) * k  # type: ignore[union-attr]
        children = []
        for c in kids.get(w.id, []):
            children.append({
                "class": "IfcDoor" if c.type == "door" else "IfcWindow",
                "tag": c.id, "material": mat(c.material),
                "offset_distance": c.offset * k, "sill_height": c.sill * k,
                "dimensions": {"width": c.width * k, "height": c.height * k},
            })
        elements.append({
            "class": "IfcWall", "tag": w.id, "material": mat(w.material),
            "thickness": w.thickness * k, "height": h,  # type: ignore[union-attr]
            "placement": {"from_grid": axes.pt(a), "to_grid": axes.pt(b), "storey": w.level_id},
            "children": children,
        })
    for e in chosen:
        if e.type == "floor":
            elements.append({
                "class": "IfcSlab", "tag": e.id, "material": mat(e.material), "thickness": e.thickness * k,
                "placement": {
                    "boundary": [axes.pt(_sc(p, k)) for p in e.polygon], "storey": e.level_id,
                    "offset_z": e.z_offset * k,
                    **({"voids": [[axes.pt(_sc(p, k)) for p in loop] for loop in e.holes]} if e.holes else {}),
                },
            })
        elif e.type == "column":
            c_h = (e.height if e.height else lvl[e.level_id].height) * k
            profile = ({"shape": "BOX", "width": e.width * k, "depth": e.depth * k} if e.shape == "box"
                       else {"shape": "CIRCULAR", "diameter": e.width * k})
            elements.append({
                "class": "IfcColumn", "tag": e.id, "material": mat(e.material), "profile": profile,
                "placement": {"grid": axes.pt(_sc(e.pos, k)), "base_storey": e.level_id, "height": c_h},
            })

    manifest = {
        "project": {"id": proj.id, "name": proj.name},
        "spatial_structure": {"storeys": [
            {"id": lv.id, "name": lv.name, "elevation": lv.elevation * k, "height": lv.height * k}
            for lv in proj.levels]},
        "grids": axes.as_manifest(),
        "materials": [{"id": m.id, "name": m.name, "category": "generic", "unit_cost_ref": "n/a"}
                      for m in proj.materials]
                     + [{"id": _DEFAULT_MAT, "name": "Default", "category": "generic", "unit_cost_ref": "n/a"}],
        "elements": elements,
    }

    try:
        resolved = SpatialResolver(ProjectManifest.model_validate(manifest)).resolve()
    except Exception as exc:
        raise AppError(
            "debim could not resolve the building", "bim.debim_adapter.resolve",
            f"{type(exc).__name__}: {str(exc)[:400]}",
            "Check wall endpoints, opening offsets/sizes and level references; run POST /api/geometry/validate",
            status=422,
        ) from exc

    return _to_building(resolved, chosen, proj, lvl, k, ver)


def _to_building(resolved, chosen, proj: Project, lvl, k: float, ver: str) -> RBuilding:
    out = RBuilding(debim_version=ver)
    src = {e.id: e for e in chosen}

    for rw in resolved.walls:
        w = src[rw.tag]
        ow = RWall(
            id=w.id, level_id=w.level_id, a=rw.start_point[:2], b=rw.end_point[:2], z0=rw.start_point[2],
            thickness=rw.thickness, height=rw.height, material=w.material,
            material_inner=w.material_inner or w.material,
        )
        for f in w.features:
            ow.features.append(RFeature(f.id, f.kind, [(x * k, y * k) for x, y in f.polygon], f.depth * k, f.face))
        for c in rw.children:
            s = src[c.tag]
            ow.openings.append(ROpening(id=c.tag, kind=s.type, u=c.offset_distance, width=c.width,
                                        height=c.height, sill=c.sill_height, material=s.material))
            out.resolved_via_debim += 1
        # custom openings are not debim children: carry them over directly
        for e in chosen:
            if e.type == "opening" and e.wall_id == w.id:
                ow.openings.append(ROpening(id=e.id, kind="opening", u=e.offset * k, width=e.width * k,
                                            height=e.height * k, sill=e.sill * k, shape=e.shape, material=e.material))
        ow.openings.sort(key=lambda o: o.u)
        out.walls.append(ow)
        out.resolved_via_debim += 1

    for rs in resolved.slabs:
        e = src[rs.tag]
        out.floors.append(RFloor(
            id=e.id, level_id=e.level_id, kind=e.kind, polygon=[p[:2] for p in rs.polygon],
            holes=[[p[:2] for p in loop] for loop in (rs.voids or [])], z_top=rs.polygon[0][2],
            thickness=rs.thickness, material=e.material))
        out.resolved_via_debim += 1

    for rc in resolved.columns:
        e = src[rc.tag]
        out.columns.append(RColumn(
            id=e.id, level_id=e.level_id, pos=rc.start_point[:2], z0=rc.start_point[2], height=rc.height,
            shape=e.shape, width=e.width * k, depth=e.depth * k, material=e.material))
        out.resolved_via_debim += 1

    for e in chosen:
        z0 = lvl[e.level_id].elevation * k
        if e.type == "beam":
            top = (e.top if e.top is not None else lvl[e.level_id].height) * k
            out.beams.append(RBeam(e.id, e.level_id, _sc(e.a, k), _sc(e.b, k), z0 + top, e.width * k, e.depth * k, e.material))
        elif e.type == "roof":
            out.roofs.append(RRoof(
                id=e.id, level_id=e.level_id, kind=e.kind, polygon=[_sc(p, k) for p in e.polygon],
                z_eave=z0 + lvl[e.level_id].height * k, pitch_deg=0.0 if e.kind == "flat" else e.pitch_deg,
                overhang=e.overhang * k, thickness=e.thickness * k, ridge_axis=e.ridge_axis, material=e.material))
        elif e.type == "stair":
            out.stairs.append(RStair(e.id, e.level_id, _sc(e.start, k), e.angle_deg, z0 + e.z_offset * k, e.width * k,
                                     e.steps, e.rise * k, e.run * k, e.material))
        elif e.type == "decor":
            out.decor.append(RDecor(e.id, e.level_id, _sc(e.pos, k), z0 + e.z * k,
                                    tuple(s * k for s in e.size), e.shape, e.rotation_deg, e.material))  # type: ignore[arg-type]
    return out
