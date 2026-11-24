"""Dirty-element system: per-element mesh files on disk + fingerprint manifest.

Only elements whose fingerprint changed are resolved (through debim) and
rebuilt; unchanged meshes stay on disk untouched. Dependencies are folded into
fingerprints: a wall depends on its openings and on walls touching it; an
opening on its host wall; everything on its level.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..bim import debim_adapter
from ..bim.modules import apply_modules
from ..schema import OPENING_TYPES, Project
from ..utils.errors import BuildError
from . import builders as B
from .collision import wall_boxes
from .junctions import extensions, touching
from .mesh import MeshData, mesh_issues

GEOM_TYPES = ("wall", "door", "window", "opening", "column", "beam", "floor", "roof", "stair", "decor", "road", "lamp")
MANIFEST = "manifest.json"


def _h(*parts: object) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fingerprints(p: Project, detail: str) -> dict[str, str]:
    """Fingerprint for every mesh-producing element (after module defaults)."""
    p = apply_modules(p)
    lv = {x.id: x.model_dump() for x in p.levels}
    els = {e.id: e for e in p.elements}
    kids: dict[str, list[str]] = {}
    for e in p.elements:
        if e.type in OPENING_TYPES:
            kids.setdefault(e.wall_id, []).append(e.id)  # type: ignore[union-attr]
    touch = touching(p)
    ext = extensions(p)
    out: dict[str, str] = {}
    base = (p.units.name, detail)
    for e in p.elements:
        if e.type not in GEOM_TYPES:
            continue
        own = e.model_dump(exclude={"name", "props"})
        if e.type == "wall":
            deps = [els[i].model_dump(exclude={"name", "props"}) for i in sorted(kids.get(e.id, []))]
            deps += [els[i].model_dump(include={"a", "b", "thickness"}) for i in sorted(touch.get(e.id, []))]
            out[e.id] = _h(base, own, lv[e.level_id], deps, ext.get(e.id))
        elif e.type in OPENING_TYPES:
            host = els[e.wall_id]  # type: ignore[union-attr]
            out[e.id] = _h(base, own, lv[e.level_id], host.model_dump(include={"a", "b", "thickness", "height"}))
        else:
            out[e.id] = _h(base, own, lv[e.level_id])
    return out


def affected_by(p: Project, changed: set[str]) -> set[str]:
    """Elements whose geometry must be refreshed when ``changed`` are modified."""
    res = set(changed)
    touch = touching(p)
    for e in p.elements:
        if e.id not in changed:
            continue
        if e.type in OPENING_TYPES:
            res.add(e.wall_id)  # type: ignore[union-attr]
        if e.type == "wall":
            res |= touch.get(e.id, set())
            res |= {o.id for o in p.elements if o.type in OPENING_TYPES and o.wall_id == e.id}  # type: ignore[union-attr]
    return res


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "part"


@dataclass
class BuildStats:
    rebuilt: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    triangles: int = 0
    seconds: float = 0.0
    debim_version: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"rebuilt": len(self.rebuilt), "cached": len(self.cached), "removed": len(self.removed),
                "rebuilt_ids": self.rebuilt, "triangles": self.triangles, "seconds": round(self.seconds, 3),
                "debim_version": self.debim_version, "warnings": self.warnings}


def load_manifest(gdir: Path) -> dict:
    f = gdir / MANIFEST
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            pass
    return {"parts": {}}


def _write_manifest(gdir: Path, man: dict) -> None:
    tmp = gdir / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(man, indent=1))
    os.replace(tmp, gdir / MANIFEST)


def build_geometry(p: Project, gdir: Path, detail: str = "medium", force: bool = False,
                   levels: set[str] | None = None) -> BuildStats:
    """Generate/refresh per-element meshes in ``gdir``. Returns what changed."""
    t0 = time.perf_counter()
    gdir.mkdir(parents=True, exist_ok=True)
    pe = apply_modules(p)
    fps = fingerprints(pe, detail)
    man = load_manifest(gdir)
    parts: dict = man.get("parts", {})
    st = BuildStats()

    in_scope = {e.id for e in pe.elements if e.id in fps and (levels is None or e.level_id in levels)}
    dirty = {i for i in in_scope
             if force or i not in parts or parts[i].get("hash") != fps[i] or not (gdir / parts[i]["file"]).exists()}
    for gone in [i for i in parts if i not in fps]:
        try:
            (gdir / parts[gone]["file"]).unlink(missing_ok=True)
        except OSError:
            pass
        parts.pop(gone)
        st.removed.append(gone)

    if dirty:
        bld = debim_adapter.resolve(pe, element_ids=dirty)
        st.debim_version = bld.debim_version
        ext = extensions(pe)
        by_id = {e.id: e for e in pe.elements}
        walls = {w.id: w for w in bld.walls}

        def emit(eid: str, kind: str, level_id: str, res: B.Built, extra: dict | None = None) -> None:
            mesh, slots = res
            mesh = mesh.welded()
            issues = mesh_issues(mesh)
            if issues:
                raise BuildError(f"Generated mesh for {kind} '{eid}' is invalid", "geometry.build",
                                 "; ".join(issues), "Check the element's dimensions and position")
            fname = f"{_safe(eid)}.npz"
            mesh.save(gdir / fname, slots)
            e = by_id[eid]
            parts[eid] = {"hash": fps[eid], "file": fname, "type": kind, "level": level_id, "slots": slots,
                          "tris": mesh.tris, "bbox": mesh.bbox(), "name": _safe(e.name or f"{kind}_{eid}"),
                          **(extra or {})}
            st.rebuilt.append(eid)

        try:
            for w in bld.walls:
                if w.id in dirty:
                    ea, eb = ext.get(w.id, (0.0, 0.0))
                    emit(w.id, "wall", w.level_id, B.wall_mesh(w, ea, eb, detail),
                         {"coll_boxes": wall_boxes(w, ea, eb)})
                for o in w.openings:
                    if o.id in dirty and o.kind != "opening":
                        emit(o.id, o.kind, w.level_id, B.opening_fill_mesh(w, o, detail))
                    elif o.id in dirty:  # custom opening: hole only, but track it so it is not "dirty" forever
                        parts[o.id] = {"hash": fps[o.id], "file": "", "type": "opening", "level": w.level_id,
                                       "slots": [], "tris": 0, "bbox": [[0] * 3, [0] * 3], "name": o.id}
                        st.rebuilt.append(o.id)
            for c in bld.columns:
                if c.id in dirty:
                    emit(c.id, "column", c.level_id, B.column_mesh(c, detail))
            for b in bld.beams:
                if b.id in dirty:
                    emit(b.id, "beam", b.level_id, B.beam_mesh(b, detail))
            for f in bld.floors:
                if f.id in dirty:
                    emit(f.id, "floor", f.level_id, B.floor_mesh(f, detail), {"has_holes": bool(f.holes)})
            for r in bld.roofs:
                if r.id in dirty:
                    emit(r.id, "roof", r.level_id, B.roof_mesh(r, detail))
            for s in bld.stairs:
                if s.id in dirty:
                    emit(s.id, "stair", s.level_id, B.stair_mesh(s, detail))
            for d in bld.decor:
                if d.id in dirty:
                    emit(d.id, "decor", d.level_id, B.decor_mesh(d, detail))
            for rd in bld.roads:
                if rd.id in dirty:
                    emit(rd.id, "road", rd.level_id, B.road_mesh(rd, detail))
            for lp in bld.lamps:
                if lp.id in dirty:
                    emit(lp.id, "lamp", lp.level_id, B.lamp_mesh(lp, detail), {"light": B.lamp_light(lp)} if lp.light else None)
        except ValueError as exc:
            raise BuildError("Geometry generation failed", "geometry.build", str(exc),
                             "Fix the element reported above and rebuild") from exc
        finally:
            del bld, walls  # release resolved objects promptly

    st.cached = sorted(in_scope - dirty)
    man["parts"] = parts
    man["detail"] = detail
    _write_manifest(gdir, man)
    st.triangles = sum(v["tris"] for v in parts.values())
    st.seconds = time.perf_counter() - t0
    return st
