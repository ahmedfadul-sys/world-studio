"""Internal, Blender-independent project schema (Pydantic v2).

This is the single source of truth for a project. Coordinates are in
*project units* (see ``Units``); the debim adapter converts to metres.
"""
from __future__ import annotations

import re

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

Point = tuple[float, float]


def new_id(prefix: str = "e") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Units(BaseModel):
    """Configurable unit system. ``to_meters`` converts project units to metres."""

    name: Literal["m", "cm", "mm", "ft", "in"] = "m"

    @property
    def to_meters(self) -> float:
        return {"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "in": 0.0254}[self.name]

    @property
    def default_snap(self) -> float:
        """Default snap step, expressed in project units (0.1 m equivalent)."""
        return {"m": 0.1, "cm": 10.0, "mm": 100.0, "ft": 0.25, "in": 4.0}[self.name]


class EditorSettings(BaseModel):
    grid_size: float | None = Field(default=None, gt=0)
    snap_size: float | None = Field(default=None, gt=0)
    snap_enabled: bool = True
    show_dimensions: bool = True


class Level(BaseModel):
    id: str = Field(default_factory=lambda: new_id("lvl"))
    name: str
    elevation: float = 0.0
    height: float = Field(default=3.0, gt=0)


LAB_PRESETS = ("brick", "concrete", "plaster", "wood", "tile", "marble", "stone", "metal", "asphalt")


class MaterialLab(BaseModel):
    """Parameters of a procedural material made in the Material Lab (kept so it can be tweaked and regenerated)."""
    model_config = ConfigDict(extra="forbid")

    preset: Literal["brick", "concrete", "plaster", "wood", "tile", "marble", "stone", "metal", "asphalt"] = "brick"
    color1: str = Field(default="#a4533a", pattern=r"^#[0-9a-fA-F]{6}$")
    color2: str = Field(default="#8a4330", pattern=r"^#[0-9a-fA-F]{6}$")
    joint: str = Field(default="#b7b0a4", pattern=r"^#[0-9a-fA-F]{6}$")   # mortar / grout / veins / gaps
    scale: int = Field(default=5, ge=1, le=16)           # bricks / tiles / planks per texture tile
    roughness: float = Field(default=0.85, ge=0, le=1)
    metallic: float = Field(default=0.0, ge=0, le=1)
    bump: float = Field(default=1.0, ge=0, le=3)
    variation: float = Field(default=0.5, ge=0, le=1)
    seed: int = Field(default=1, ge=0, le=999)
    resolution: Literal[256, 512, 1024, 2048] = 1024
    tile_m: float = Field(default=1.0, ge=0.1, le=20)    # real-world size of one texture tile in metres


class Material(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mat"))
    name: str
    color: str = Field(default="#b8b2a7", pattern=r"^#[0-9a-fA-F]{6}$")
    roughness: float = Field(default=0.8, ge=0, le=1)
    metallic: float = Field(default=0.0, ge=0, le=1)
    texture: str | None = None  # file name under project textures/, loaded lazily
    normal_texture: str | None = None   # tangent-space normal map (OpenGL / glTF convention)
    rough_texture: str | None = None    # glTF metallic-roughness map: G = roughness, B = metallic
    uv_scale: float = Field(default=1.0, gt=0)
    lab: MaterialLab | None = None


class ModuleDef(BaseModel):
    """Reusable building module: default parameters applied to elements."""

    id: str
    kind: Literal[
        "wall", "corner", "door_frame", "window_frame", "pillar",
        "beam", "floor", "roof", "stair",
    ]
    name: str
    defaults: dict[str, Any] = Field(default_factory=dict)


class StyleDef(BaseModel):
    """Open-ended architectural style: free-form name + parameter dict."""

    name: str = "custom"
    params: dict[str, Any] = Field(default_factory=dict)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    level_id: str
    name: str | None = None
    material: str | None = None
    module: str | None = None
    # field names the user set explicitly; a module's defaults never override these
    overrides: list[str] = Field(default_factory=list)
    props: dict[str, Any] = Field(default_factory=dict)


class WallFeature(BaseModel):
    """A 2D shape drawn on a wall's face, in wall-local coordinates (project units).

    u runs along the wall from its start point `a`; v is the height above the wall base.
    kind: cut = hole through the wall; recess = niche cut `depth` into `face`;
          relief = solid shape standing `depth` proud of `face`.
    face: the side of the wall (left/right of a->b) that a recess/relief belongs to.
    """
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("f"))
    kind: Literal["cut", "recess", "relief"] = "cut"
    shape: Literal["rect", "circle", "arch", "triangle", "star", "polygon", "ellipse", "roundrect", "hexagon", "octagon", "diamond", "cross", "semicircle", "trapezoid", "gothic", "slot"] = "polygon"  # UI hint only
    polygon: list[Point] = Field(min_length=3, max_length=256)
    depth: float = Field(default=0.05, gt=0)
    face: Literal["left", "right"] = "right"


class Wall(_Base):
    type: Literal["wall"] = "wall"
    a: Point
    b: Point
    thickness: float = Field(default=0.2, gt=0)
    height: float | None = Field(default=None, gt=0)  # None -> level height
    material_inner: str | None = None  # face on the right of a->b; None -> same as `material`
    features: list[WallFeature] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def _non_degenerate(self) -> "Wall":
        if self.a == self.b:
            raise ValueError("wall start and end points are identical")
        return self


class _Opening(_Base):
    wall_id: str
    offset: float = Field(ge=0, description="distance from wall start to opening CENTRE")
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    sill: float = Field(default=0.0, ge=0)


class Door(_Opening):
    type: Literal["door"] = "door"
    width: float = Field(default=0.9, gt=0)
    height: float = Field(default=2.1, gt=0)
    hinge: Literal["left", "right"] = "left"   # seen along the wall direction (start -> end)
    swing: Literal["left", "right"] = "left"   # side of the wall the leaf opens towards (relative to the wall direction)


class Window(_Opening):
    type: Literal["window"] = "window"
    width: float = Field(default=1.2, gt=0)
    height: float = Field(default=1.2, gt=0)
    sill: float = Field(default=0.9, ge=0)


class CustomOpening(_Opening):
    type: Literal["opening"] = "opening"
    shape: Literal["rect", "arch"] = "rect"


class Column(_Base):
    type: Literal["column"] = "column"
    pos: Point
    shape: Literal["box", "round"] = "box"
    width: float = Field(default=0.4, gt=0)
    depth: float = Field(default=0.4, gt=0)
    height: float | None = Field(default=None, gt=0)


class Beam(_Base):
    type: Literal["beam"] = "beam"
    a: Point
    b: Point
    width: float = Field(default=0.25, gt=0)
    depth: float = Field(default=0.4, gt=0)
    top: float | None = None  # elevation of beam top above level base; None -> level height


class Floor(_Base):
    type: Literal["floor"] = "floor"
    kind: Literal["floor", "ceiling", "balcony"] = "floor"
    polygon: list[Point] = Field(min_length=3)
    holes: list[list[Point]] = Field(default_factory=list)
    thickness: float = Field(default=0.2, gt=0)
    z_offset: float = 0.0


class Roof(_Base):
    type: Literal["roof"] = "roof"
    kind: Literal["flat", "shed", "gable", "hip", "cone", "dome", "barrel"] = "gable"
    polygon: list[Point] = Field(min_length=3)
    pitch_deg: float = Field(default=30.0, ge=0, lt=80)
    overhang: float = Field(default=0.3, ge=0)
    thickness: float = Field(default=0.15, gt=0)
    ridge_axis: Literal["x", "y"] = "x"


class Stair(_Base):
    type: Literal["stair"] = "stair"
    start: Point
    angle_deg: float = 0.0
    width: float = Field(default=1.0, gt=0)
    steps: int = Field(default=15, ge=1, le=200)
    rise: float = Field(default=0.18, gt=0)
    run: float = Field(default=0.28, gt=0)
    z_offset: float = 0.0   # raises the whole flight (second flight of an L/U stair starts at the landing)
    # سلّم لولبي: `start` = مركز اللولب، `angle_deg` = زاوية بداية الدرجة الأولى، `width` = عرض الدرجة (من القطر الداخلي للخارج)
    kind: Literal["straight", "spiral"] = "straight"
    inner_radius: float = Field(default=0.3, ge=0)      # نصف قطر العمود المركزي
    turn_deg: float = Field(default=360.0, gt=0, le=1440)  # الدوران الكلي للسلّم
    clockwise: bool = False


class Room(_Base):
    """Metadata-only room (no geometry): name + boundary."""

    type: Literal["room"] = "room"
    polygon: list[Point] = Field(min_length=3)
    room_type: str = "generic"


class Decor(_Base):
    type: Literal["decor"] = "decor"
    pos: Point
    z: float = 0.0
    size: tuple[float, float, float] = (0.3, 0.3, 0.3)
    shape: Literal["box", "cylinder"] = "box"
    rotation_deg: float = 0.0


ROAD_SURFACES = ("asphalt", "dirt", "stone", "gravel", "paving", "concrete", "sand")


ROAD_MATERIALS = {
    "asphalt": ("Asphalt", "#3a3b3e", 0.95), "dirt": ("Dirt road", "#8a6a44", 1.0), "stone": ("Stone road", "#8f8a7d", 0.9),
    "gravel": ("Gravel", "#9a9488", 1.0), "paving": ("Paving", "#a9998a", 0.85), "concrete": ("Concrete road", "#9b9b9b", 0.9),
    "sand": ("Sand", "#d8c690", 1.0), "sidewalk": ("Sidewalk", "#b9b6ae", 0.9),
}


def surface_material_id(surface: str) -> str:
    return f"mat_road_{surface}"


def with_surface_materials(materials: list["Material"]) -> list["Material"]:
    """Project materials + the default road-surface materials that are missing (so roads always have a colour)."""
    have = {m.id for m in materials}
    extra = [Material(id=surface_material_id(k), name=n, color=c, roughness=r) for k, (n, c, r) in ROAD_MATERIALS.items()
             if surface_material_id(k) not in have]
    for mid, name, col in (("mat_lamp_pole", "Lamp pole", "#3b3f45"), ("mat_lamp_head", "Lamp head", "#fff2cc")):
        if mid not in have:
            extra.append(Material(id=mid, name=name, color=col))
    return [*materials, *extra]


class Road(_Base):
    """طريق: خط المنتصف + عرض الطريق + عرض الرصيف على كل جانب. السطح يحدد الخامة ما لم تُحدَّد خامة صراحةً."""

    type: Literal["road"] = "road"
    path: list[Point] = Field(min_length=2, max_length=500)
    width: float = Field(default=7.0, gt=0)
    sidewalk: float = Field(default=1.5, ge=0)         # عرض الرصيف لكل جانب (0 = بلا رصيف)
    surface: Literal["asphalt", "dirt", "stone", "gravel", "paving", "concrete", "sand"] = "asphalt"
    curb_height: float = Field(default=0.15, ge=0)     # ارتفاع الرصيف عن سطح الطريق
    thickness: float = Field(default=0.1, gt=0)
    sidewalk_material: str | None = None
    z_offset: float = 0.0


class Lamp(_Base):
    """عمود إنارة مع ضوء حقيقي (KHR_lights_punctual في GLB / OmniLight3D في Godot)."""

    type: Literal["lamp"] = "lamp"
    pos: Point
    height: float = Field(default=5.0, gt=0)
    arm: float = Field(default=0.0, ge=0)              # امتداد الذراع الأفقي (0 = رأس فوق العمود)
    arm_deg: float = 0.0                               # اتجاه الذراع في المخطط
    pole_radius: float = Field(default=0.06, gt=0)
    light: bool = True
    color: str = Field(default="#ffd9a0", pattern=r"^#[0-9a-fA-F]{6}$")
    intensity: float = Field(default=300.0, ge=0)      # شمعة (cd) للـ glTF
    range: float = Field(default=12.0, gt=0)           # متر
    z_offset: float = 0.0


class Guide(BaseModel):
    """خطوط مخطط المدينة الوهمية: تظهر في المحرر ثنائي الأبعاد فقط ولا تدخل البناء ولا المعاينة ثلاثية الأبعاد ولا التصدير."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("gd"))
    name: str | None = None
    kind: Literal["line", "parallel", "grid", "radial"] = "grid"
    origin: Point = (0.0, 0.0)
    angle_deg: float = 0.0
    spacing_x: float = Field(default=50.0, gt=0)
    spacing_y: float = Field(default=50.0, gt=0)
    count_x: int = Field(default=6, ge=1, le=200)
    count_y: int = Field(default=6, ge=1, le=200)
    length: float = Field(default=300.0, gt=0)
    b: Point | None = None                             # نقطة النهاية لخط مفرد
    color: str = "#35c4ff"
    visible: bool = True
    locked: bool = False


Element = Annotated[
    Union[Wall, Door, Window, CustomOpening, Column, Beam, Floor, Roof, Stair, Room, Decor, Road, Lamp],
    Field(discriminator="type"),
]

OPENING_TYPES = ("door", "window", "opening")


class ExportSettings(BaseModel):
    format: Literal["glb", "gltf", "fbx"] = "glb"
    poly_preset: Literal["low", "medium", "high"] = "medium"
    triangulate: bool = True
    collision: Literal["none", "box", "convex", "simplified"] = "convex"
    lod_levels: list[float] = Field(default_factory=lambda: [0.5, 0.25])  # ratios kept
    lod_min_triangles: int = Field(default=150, ge=0)  # objects smaller than this get no LODs
    pivot: Literal["center", "base_center", "world_origin", "min_corner"] = "base_center"
    rotate_deg: Literal[0, 90, 180, 270] = 0   # turn the model around the vertical axis (about the pivot)
    mirror_x: bool = False                     # true mirror (left <-> right) with corrected face winding
    up_axis: Literal["Y", "Z"] = "Y"  # glTF/Godot convention is Y-up
    scale: float = Field(default=1.0, gt=0)
    uv: Literal["box", "smart", "none"] = "box"
    split_per_level: bool = True
    keep_blend: bool = False

    @field_validator("lod_levels")
    @classmethod
    def _lod_ratios(cls, v: list[float]) -> list[float]:
        if any(not (0 < r < 1) for r in v):
            raise ValueError("LOD ratios must be between 0 and 1 (exclusive)")
        return sorted(v, reverse=True)


class SceneOptions(BaseModel):
    """Options of the Godot scene export (.tscn with collision, physics and openable doors)."""
    model_config = ConfigDict(extra="forbid")
    res_dir: str = Field(default="", max_length=200, description="res:// folder the files will live in inside the Godot project")
    door_open_deg: float = Field(default=100.0, ge=30, le=120)
    player: bool = True
    ground: bool = True
    props: bool = True           # a few RigidBody3D crates to try the physics
    lights: bool = True

    @field_validator("res_dir")
    @classmethod
    def _res(cls, v: str) -> str:
        if v and not re.fullmatch(r"res://[A-Za-z0-9_./-]*", v):
            raise ValueError("res_dir must look like res://models/house/")
        if ".." in v:
            raise ValueError("res_dir must not contain '..'")
        return v


class BuildRecord(BaseModel):
    job_id: str
    kind: str
    status: str
    at: str = Field(default_factory=utcnow)
    elements_rebuilt: int = 0
    elements_cached: int = 0
    triangles: int = 0
    seconds: float = 0.0
    peak_rss_mb: float | None = None
    output: str | None = None


class Meta(BaseModel):
    description: str = ""
    author: str = ""
    style: StyleDef = Field(default_factory=StyleDef)


class Underlay(BaseModel):
    """A scanned plan / photo shown under the editor grid (never exported). Image lives in <project>/underlays/<file>."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("ul"))
    name: str = Field(default="", max_length=120)
    file: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}\.(png|jpe?g)$")
    level_id: str | None = None       # None = shown on every level
    x: float = 0.0                    # world position of the image's top-left corner (project units)
    y: float = 0.0
    width: float = Field(default=10.0, gt=0)   # world width; height follows the pixel aspect ratio
    px_w: int = Field(default=1, ge=1, le=20000)
    px_h: int = Field(default=1, ge=1, le=20000)
    rotation_deg: float = 0.0
    opacity: float = Field(default=0.5, ge=0.05, le=1.0)
    visible: bool = True
    locked: bool = False


TEMPLATE_TYPES = ("wall", "door", "window", "opening", "column", "beam", "floor", "roof", "stair")
TEMPLATE_KEYS = {
    "wall": {"thickness", "height", "material", "material_inner"},
    "door": {"width", "height", "sill", "material"},
    "window": {"width", "height", "sill", "material"},
    "opening": {"width", "height", "sill"},
    "column": {"shape", "width", "depth", "height", "material"},
    "beam": {"width", "depth", "material"},
    "floor": {"thickness", "material"},
    "roof": {"kind", "pitch_deg", "overhang", "thickness", "material"},
    "stair": {"width", "rise", "run", "steps", "material"},
}


class Template(BaseModel):
    """A reusable set of element properties (lengths in project units) applied when drawing or to a selection."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("tpl"))
    name: str = Field(min_length=1, max_length=80)
    type: Literal["wall", "door", "window", "opening", "column", "beam", "floor", "roof", "stair"]
    props: dict[str, str | float | int | bool | None] = Field(default_factory=dict, max_length=12)

    @model_validator(mode="after")
    def _keys_ok(self) -> "Template":
        bad = set(self.props) - TEMPLATE_KEYS[self.type]
        if bad:
            raise ValueError(f"template property not allowed for {self.type}: {sorted(bad)}")
        for k, v in self.props.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k in {"thickness", "width", "depth", "height", "rise", "run", "overhang"} and v <= 0:
                raise ValueError(f"template {k} must be positive")
        return self


class SiteLink(BaseModel):
    """Where this project is placed in a TerrainForge world (set when opened from a terrain 'site'). Footprint is local: centre = (0, 0), X east, Y north, metres."""
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=120)
    name: str = Field(default="", max_length=120)
    kind: str = Field(default="village", max_length=40)
    shape: Literal["circle", "rect"] = "circle"
    diameter_m: float = Field(default=300, gt=0, le=20000)
    width_m: float = Field(default=300, gt=0, le=20000)
    length_m: float = Field(default=200, gt=0, le=20000)
    rotation_deg: float = 0.0
    level_m: float | None = None


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("prj"))
    schema_version: int = SCHEMA_VERSION
    name: str
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    meta: Meta = Field(default_factory=Meta)
    site: SiteLink | None = None
    units: Units = Field(default_factory=Units)
    editor: EditorSettings = Field(default_factory=EditorSettings)
    levels: list[Level] = Field(default_factory=list)
    materials: list[Material] = Field(default_factory=list)
    modules: list[ModuleDef] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    guides: list[Guide] = Field(default_factory=list, max_length=200)
    underlays: list[Underlay] = Field(default_factory=list, max_length=20)
    templates: list[Template] = Field(default_factory=list, max_length=200)
    export: ExportSettings = Field(default_factory=ExportSettings)
    build_history: list[BuildRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs_ok(self) -> "Project":
        level_ids = {lv.id for lv in self.levels}
        mat_ids = {m.id for m in self.materials}
        for u in self.underlays:
            if u.level_id is not None and u.level_id not in level_ids:
                raise ValueError(f"underlay {u.id} refers to unknown level {u.level_id}")
        ids: set[str] = set()
        walls = {e.id for e in self.elements if e.type == "wall"}
        for e in self.elements:
            if e.id in ids:
                raise ValueError(f"duplicate element id {e.id}")
            ids.add(e.id)
            if e.level_id not in level_ids:
                raise ValueError(f"element {e.id}: unknown level_id {e.level_id}")
            if e.material and e.material not in mat_ids:
                raise ValueError(f"element {e.id}: unknown material {e.material}")
            if e.type in OPENING_TYPES and e.wall_id not in walls:  # type: ignore[union-attr]
                raise ValueError(f"element {e.id}: host wall {e.wall_id} not found")  # type: ignore[union-attr]
        return self

    # convenience ---------------------------------------------------------
    def level(self, level_id: str) -> Level:
        return next(lv for lv in self.levels if lv.id == level_id)

    def snap(self) -> float:
        return self.editor.snap_size or self.units.default_snap


def default_materials() -> list[Material]:
    return [
        Material(id="mat_plaster", name="Plaster", color="#d9d4c7"),
        Material(id="mat_concrete", name="Concrete", color="#8d8d8d", roughness=0.9),
        Material(id="mat_wood", name="Wood", color="#8a5a33"),
        Material(id="mat_glass", name="Glass", color="#9fc7d6", roughness=0.05),
        Material(id="mat_roof", name="Roof tile", color="#9b4b36"),
    ]


def new_project(name: str, units: str = "m") -> Project:
    lv = Level(id="lvl_0", name="Ground", elevation=0.0, height=3.0)
    return Project(name=name, units=Units(name=units), levels=[lv], materials=default_materials())
