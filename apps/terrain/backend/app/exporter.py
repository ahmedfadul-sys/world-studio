from __future__ import annotations
import io, json, zipfile
import numpy as np
import cv2
from .buildinfo import make_extras

QMAX = 65535


def normalize(Z: np.ndarray, mode: str, zmin: float, zmax: float):
    if mode == "auto":
        zmin, zmax = float(Z.min()), float(Z.max())
    if zmax - zmin < 1e-6:
        zmax = zmin + 1.0
    q = np.rint((Z.astype(np.float64) - zmin) / (zmax - zmin) * QMAX)
    return np.clip(q, 0, QMAX).astype(np.uint16), zmin, zmax


def build_metadata(project, Z: np.ndarray, zmin: float, zmax: float, clipped: bool, extra=None) -> dict:
    w = project.world
    ny, nx = Z.shape
    rng = zmax - zmin
    return {
        "tool": "TerrainForge", "schema_version": project.version, "project": project.name,
        "width_px": nx, "height_px": ny, "bit_depth": 16, "byte_order_r16": "little-endian",
        "world_size_x_m": w.size_x_m, "world_size_y_m": w.size_y_m,
        "meters_per_pixel_x": w.size_x_m / (nx - 1), "meters_per_pixel_y": w.size_y_m / (ny - 1),
        "cell_size_m": w.cell_size_m, "chunk_size_m": w.chunk_size_m, "seed": w.seed,
        "z_min_m": zmin, "z_max_m": zmax, "height_range_m": rng,
        "sea_level_m": w.sea_level_m, "sea_level_pixel_value": (w.sea_level_m - zmin) / rng * QMAX,
        "height_formula": "elevation_m = z_min_m + pixel / 65535 * (z_max_m - z_min_m)",
        "orientation": "row 0 = north (top of image)",
        "values_clipped_to_fixed_range": clipped,
        "lakes": [{"id": f.id, "x_m": f.x_m, "y_m": f.y_m, "diameter_m": f.diameter_m, "water_level_m": f.high_m}
                  for f in project.points if f.kind == "lake"],
        "blender_hint": "Displace modifier: Strength = height_range_m, Midlevel = 0, texture Color Space = Non-Color; "
                        "then move the object up along Z by z_min_m. Lake water levels are in build.json (water.lakes).",
        "markers": [{"id": f.id, "kind": f.kind, "x_m": f.x_m, "y_m": f.y_m, "note": "Cave entrance: model the interior in 3D (a heightmap cannot hold cavities)"}
                    for f in project.points if f.kind == "cave"],
        "biomes": [{"id": b.id, "name": b.name, "polygon_m": b.polygon} for b in project.biomes],
        **(extra or {}),
        "unity_hint": "Import .r16: Depth 16 bit, Byte Order Windows (little-endian). Unity needs a square heightmap: use a square world or tiles.",
    }


def build_zip(project, Z: np.ndarray, extra=None) -> bytes:
    ex = project.export
    q, zmin, zmax = normalize(Z, ex.mode, ex.zmin_m, ex.zmax_m)
    clipped = ex.mode == "fixed" and (float(Z.min()) < zmin or float(Z.max()) > zmax)
    ok, png = cv2.imencode(".png", q)
    if not ok:
        raise RuntimeError("فشل ترميز PNG")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("heightmap_16bit.png", png.tobytes())
        zf.writestr("heightmap.r16", q.astype("<u2").tobytes())
        zf.writestr("metadata.json", json.dumps(build_metadata(project, Z, zmin, zmax, clipped, extra), ensure_ascii=False, indent=2))
        zf.writestr("project.json", project.model_dump_json(indent=2))
        ny, nx = Z.shape
        hm = {"mode": "single", "file_png": "heightmap_16bit.png", "file_r16": "heightmap.r16", "width_px": nx, "height_px": ny,
              "meters_per_pixel_x": project.world.size_x_m / (nx - 1), "meters_per_pixel_y": project.world.size_y_m / (ny - 1),
              "bit_depth": 16, "z_min_m": zmin, "z_max_m": zmax, "height_range_m": zmax - zmin,
              "sea_level_pixel_value": (project.world.sea_level_m - zmin) / (zmax - zmin) * QMAX,
              "formula": "elevation_m = z_min_m + pixel / 65535 * (z_max_m - z_min_m)", "image_origin": "row 0 = north"}
        for name, data in make_extras(project, hm).items():
            zf.writestr(name, data)
    return buf.getvalue()
