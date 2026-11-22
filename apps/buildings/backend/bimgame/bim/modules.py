"""Reusable building modules: default parameters applied to elements.

A module supplies values for every field the element has NOT listed in
``overrides`` (the editor records a field there when the user edits it), so a
module edit updates only the elements that reference it and never clobbers
explicit per-element choices. (``model_fields_set`` is unusable here: it is
lost after JSON save/load.)
"""
from __future__ import annotations

from ..schema import ModuleDef, Project

# Module defaults are stored in METRES for every project unit; length-like
# fields are converted to the project unit when applied.
LENGTH_KEYS = {"thickness", "height", "width", "depth", "sill", "overhang", "rise", "run", "top", "z_offset"}

BUILTIN_MODULES: list[ModuleDef] = [
    ModuleDef(id="mod_wall_thin", kind="wall", name="Wall 10 cm", defaults={"thickness": 0.1}),
    ModuleDef(id="mod_wall_std", kind="wall", name="Wall 20 cm", defaults={"thickness": 0.2}),
    ModuleDef(id="mod_wall_thick", kind="wall", name="Stone wall 60 cm", defaults={"thickness": 0.6, "material": "mat_concrete"}),
    ModuleDef(id="mod_corner_post", kind="corner", name="Corner post", defaults={"width": 0.4, "depth": 0.4}),
    ModuleDef(id="mod_door_single", kind="door_frame", name="Door 0.9x2.1", defaults={"width": 0.9, "height": 2.1}),
    ModuleDef(id="mod_door_double", kind="door_frame", name="Door 1.6x2.2", defaults={"width": 1.6, "height": 2.2}),
    ModuleDef(id="mod_window_std", kind="window_frame", name="Window 1.2x1.2", defaults={"width": 1.2, "height": 1.2, "sill": 0.9}),
    ModuleDef(id="mod_window_wide", kind="window_frame", name="Window 2.0x1.2", defaults={"width": 2.0, "height": 1.2, "sill": 0.9}),
    ModuleDef(id="mod_pillar", kind="pillar", name="Round pillar", defaults={"shape": "round", "width": 0.5, "depth": 0.5}),
    ModuleDef(id="mod_beam_std", kind="beam", name="Beam 25x40", defaults={"width": 0.25, "depth": 0.4}),
    ModuleDef(id="mod_floor_slab", kind="floor", name="Slab 20 cm", defaults={"thickness": 0.2}),
    ModuleDef(id="mod_roof_gable", kind="roof", name="Gable 30°", defaults={"kind": "gable", "pitch_deg": 30.0}),
    ModuleDef(id="mod_stair_std", kind="stair", name="Stair 18/28", defaults={"rise": 0.18, "run": 0.28, "width": 1.0}),
]

_KIND_BY_TYPE = {
    "wall": {"wall", "corner"}, "door": {"door_frame"}, "window": {"window_frame"},
    "column": {"pillar", "corner"}, "beam": {"beam"}, "floor": {"floor"},
    "roof": {"roof"}, "stair": {"stair"},
}


def module_library(project: Project) -> list[ModuleDef]:
    """Project modules override built-ins with the same id."""
    merged = {m.id: m for m in BUILTIN_MODULES}
    merged.update({m.id: m for m in project.modules})
    return list(merged.values())


def apply_modules(project: Project) -> Project:
    """Return a copy of the project where module defaults fill unset fields."""
    lib = {m.id: m for m in module_library(project)}
    out = project.model_copy(deep=True)
    unit_m = project.units.to_meters
    for e in out.elements:
        if not e.module:
            continue
        mod = lib.get(e.module)
        if mod is None:
            continue
        if mod.kind not in _KIND_BY_TYPE.get(e.type, set()):
            continue
        for key, v in mod.defaults.items():
            if key in type(e).model_fields and key not in e.overrides:
                setattr(e, key, v / unit_m if key in LENGTH_KEYS else v)
    return out
