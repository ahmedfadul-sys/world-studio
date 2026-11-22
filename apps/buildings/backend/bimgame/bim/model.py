"""Resolved building model consumed by the geometry layer. All lengths in METRES.

Independent of Blender and of debim's classes (the adapter fills it in).
"""
from __future__ import annotations

from dataclasses import dataclass, field

P2 = tuple[float, float]


@dataclass
class ROpening:
    id: str
    kind: str  # door | window | opening
    u: float  # distance from wall start to opening centre (m)
    width: float
    height: float
    sill: float
    shape: str = "rect"
    material: str | None = None


@dataclass
class RFeature:
    id: str
    kind: str                      # cut | recess | relief
    polygon: list[P2]              # wall-local (u, v) in metres
    depth: float
    face: str                      # left | right


@dataclass
class RWall:
    id: str
    level_id: str
    a: P2
    b: P2
    z0: float
    thickness: float
    height: float
    material: str | None
    material_inner: str | None
    openings: list[ROpening] = field(default_factory=list)
    features: list[RFeature] = field(default_factory=list)


@dataclass
class RColumn:
    id: str
    level_id: str
    pos: P2
    z0: float
    height: float
    shape: str
    width: float
    depth: float
    material: str | None


@dataclass
class RBeam:
    id: str
    level_id: str
    a: P2
    b: P2
    z_top: float
    width: float
    depth: float
    material: str | None


@dataclass
class RFloor:
    id: str
    level_id: str
    kind: str
    polygon: list[P2]
    holes: list[list[P2]]
    z_top: float
    thickness: float
    material: str | None


@dataclass
class RRoof:
    id: str
    level_id: str
    kind: str
    polygon: list[P2]
    z_eave: float
    pitch_deg: float
    overhang: float
    thickness: float
    ridge_axis: str
    material: str | None


@dataclass
class RStair:
    id: str
    level_id: str
    start: P2
    angle_deg: float
    z0: float
    width: float
    steps: int
    rise: float
    run: float
    material: str | None


@dataclass
class RDecor:
    id: str
    level_id: str
    pos: P2
    z0: float
    size: tuple[float, float, float]
    shape: str
    rotation_deg: float
    material: str | None


@dataclass
class RBuilding:
    walls: list[RWall] = field(default_factory=list)
    columns: list[RColumn] = field(default_factory=list)
    beams: list[RBeam] = field(default_factory=list)
    floors: list[RFloor] = field(default_factory=list)
    roofs: list[RRoof] = field(default_factory=list)
    stairs: list[RStair] = field(default_factory=list)
    decor: list[RDecor] = field(default_factory=list)
    debim_version: str = ""
    resolved_via_debim: int = 0  # number of elements whose placement debim resolved

    def count(self) -> int:
        return sum(len(x) for x in (self.walls, self.columns, self.beams, self.floors, self.roofs, self.stairs, self.decor))
