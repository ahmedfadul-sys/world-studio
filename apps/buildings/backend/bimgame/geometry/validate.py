"""Basic input-geometry validation (before debim/geometry work)."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from shapely.geometry import Polygon

from ..schema import Project

MIN_WALL_M = 0.05
MIN_LINTEL_M = 0.05


@dataclass
class Issue:
    level: str  # error | warning
    element_id: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def validate_project(p: Project) -> list[Issue]:
    k = p.units.to_meters
    out: list[Issue] = []
    lv = {x.id: x for x in p.levels}
    walls = {e.id: e for e in p.elements if e.type == "wall"}
    by_wall: dict[str, list] = {}
    for e in p.elements:
        if e.type in ("door", "window", "opening"):
            by_wall.setdefault(e.wall_id, []).append(e)  # type: ignore[union-attr]

    for w in walls.values():
        L = math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])  # type: ignore[union-attr]
        if L * k < MIN_WALL_M:
            out.append(Issue("error", w.id, f"wall is shorter than {MIN_WALL_M} m"))
        H = (w.height or lv[w.level_id].height)  # type: ignore[union-attr]
        ops = sorted(by_wall.get(w.id, []), key=lambda o: o.offset)
        prev_end = -math.inf
        for o in ops:
            lo, hi = o.offset - o.width / 2, o.offset + o.width / 2
            if lo < -1e-9 or hi > L + 1e-9:
                out.append(Issue("error", o.id, f"{o.type} extends beyond its wall (needs 0..{L:.3f}, spans {lo:.3f}..{hi:.3f})"))
            if o.sill + o.height > H - MIN_LINTEL_M / k:
                out.append(Issue("error", o.id, f"{o.type} leaves less than {MIN_LINTEL_M} m above it (top {o.sill + o.height:.3f} vs wall height {H:.3f})"))
            if lo < prev_end - 1e-9:
                out.append(Issue("error", o.id, f"{o.type} overlaps the previous opening on wall {w.id}"))
            prev_end = max(prev_end, hi)

    for e in p.elements:
        if e.type in ("floor", "roof", "room"):
            poly = Polygon(e.polygon)  # type: ignore[union-attr]
            if not poly.is_valid:
                out.append(Issue("error", e.id, "polygon is self-intersecting"))
            elif poly.area <= 0:
                out.append(Issue("error", e.id, "polygon has zero area"))
            if e.type == "floor":
                for i, hole in enumerate(e.holes):  # type: ignore[union-attr]
                    if not poly.contains(Polygon(hole)):
                        out.append(Issue("error", e.id, f"hole {i} is not fully inside the floor polygon"))
        if e.type == "beam" and e.a == e.b:  # type: ignore[union-attr]
            out.append(Issue("error", e.id, "beam start and end are identical"))
        if e.type == "stair":
            total = e.steps * e.rise  # type: ignore[union-attr]
            if total > lv[e.level_id].height * 1.5:
                out.append(Issue("warning", e.id, f"stair rises {total:.2f} which is far above the level height {lv[e.level_id].height}"))
    return out
