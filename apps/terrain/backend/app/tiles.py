"""تصدير مربعات (Tiles) بحجم المنطقة المحمّلة. كلها بنفس zmin/zmax العالمي وبكسل حافة مشترك => لا شقوق."""
from __future__ import annotations
import json, math, os, tempfile, zipfile
import numpy as np
import cv2
from .terrain import Engine
from .exporter import normalize, QMAX
from .buildinfo import make_extras, generate_masks
from .terrain import grid_axes
from .materials import paint, library
from .detail import DetailContext, padded_axes


def _detail_context(project):
    """أوزان المواد العالمية (دقة الأقنعة) تُؤخذ منها عيّنات لكل بكسل مربع؛ نفس قواعد التلوين المستعملة في التصدير."""
    w, N = project.world, project.export.mask_px
    eg = Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (N - 1))
    gx, gy = grid_axes(w.size_x_m, w.size_y_m, N)
    Zg = eg.grid(gx, gy)
    _, dens = generate_masks(project, eg, Zg, gx, gy)
    pt, _ = paint(project, eg, Zg, gx, gy, dens, None)
    return DetailContext(project, pt.W, gx, gy, library(project))


def tile_plan(project):
    w, tp = project.world, project.export.tile_px
    T = w.chunk_size_m
    return math.ceil(w.size_x_m / T), math.ceil(w.size_y_m / T), T / (tp - 1)


def tile_axes(project, c, r):
    w, tp = project.world, project.export.tile_px
    T = w.chunk_size_m
    ytop = w.size_y_m - r * T
    return np.linspace(c * T, (c + 1) * T, tp), np.linspace(ytop, ytop - T, tp)


def export_tiles(project, out_path: str, progress=lambda d, t: None) -> None:
    w, ex = project.world, project.export
    nx, ny, mpp = tile_plan(project)
    eng = Engine(project, step=0.75 * mpp)
    dctx, detail_info = None, {"applied": False, "enabled": project.detail.enabled}
    if project.detail.enabled:
        if mpp * 2.0 > project.detail.wavelength_max_m:
            detail_info["reason"] = f"دقة المربع {mpp:.2f} م/بكسل أخشن من نصف أطول طول موجة ({project.detail.wavelength_max_m} م): قلّل حجم المنطقة أو ارفع دقة المربع"
        else:
            dctx = _detail_context(project)
            detail_info.update(applied=True, wavelength_max_m=project.detail.wavelength_max_m, slope_gain=project.detail.slope_gain,
                               materials={k: {"kind": v[0], "amplitude_m": v[1]} for k, v in dctx.prof.items()})
    hl = min(4, math.ceil(math.log2(max(nx, ny)))) if max(nx, ny) > 1 else 0
    hl_tiles = sum(math.ceil(nx / 2 ** L) * math.ceil(ny / 2 ** L) for L in range(1, hl + 1))
    total = 2 * nx * ny + hl_tiles
    done = 0
    with tempfile.TemporaryDirectory() as tmp:
        lo, hi = np.inf, -np.inf
        for r in range(ny):
            for c in range(nx):
                txs, tys = tile_axes(project, c, r)
                if dctx:                                          # شبكة موسّعة بهامش لحساب الميل فتتطابق الحواف المشتركة
                    xp, yp = padded_axes(txs, tys)
                    Z = dctx.apply(eng, eng.grid(xp, yp), xp, yp, mpp)
                else:
                    Z = eng.grid(txs, tys)
                np.save(os.path.join(tmp, f"{c}_{r}.npy"), Z)
                lo, hi = min(lo, float(Z.min())), max(hi, float(Z.max()))
                done += 1; progress(done, total)
        if ex.mode == "fixed":
            lo, hi = ex.zmin_m, ex.zmax_m
        if hi - lo < 1e-6:
            hi = lo + 1.0
        rng, tiles = hi - lo, []
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            for r in range(ny):
                for c in range(nx):
                    Z = np.load(os.path.join(tmp, f"{c}_{r}.npy"))
                    q, _, _ = normalize(Z, "fixed", lo, hi)
                    ok, png = cv2.imencode(".png", q)
                    zf.writestr(f"tiles/tile_{c}_{r}.png", png.tobytes())
                    zf.writestr(f"tiles/tile_{c}_{r}.r16", q.astype("<u2").tobytes())
                    T = w.chunk_size_m
                    tiles.append({"col": c, "row": r, "file_png": f"tiles/tile_{c}_{r}.png", "file_r16": f"tiles/tile_{c}_{r}.r16",
                                  "x_min_m": c * T, "x_max_m": (c + 1) * T, "y_max_m": w.size_y_m - r * T, "y_min_m": w.size_y_m - (r + 1) * T})
                    done += 1; progress(done, total)
            hlod = []
            for L in range(1, hl + 1):
                g = 2 ** L
                gx, gy = math.ceil(nx / g), math.ceil(ny / g)
                mpp_l = g * w.chunk_size_m / (ex.tile_px - 1)
                engL = Engine(project, step=0.75 * mpp_l)
                lt = []
                for r in range(gy):
                    for c in range(gx):
                        T = w.chunk_size_m * g
                        ytop = w.size_y_m - r * T
                        Z = engL.grid(np.linspace(c * T, (c + 1) * T, ex.tile_px), np.linspace(ytop, ytop - T, ex.tile_px))
                        q, _, _ = normalize(Z, "fixed", lo, hi)
                        zf.writestr(f"hlod/level{L}/tile_{c}_{r}.png", cv2.imencode(".png", q)[1].tobytes())
                        lt.append({"col": c, "row": r, "file_png": f"hlod/level{L}/tile_{c}_{r}.png", "x_min_m": c * T, "x_max_m": (c + 1) * T,
                                   "y_max_m": ytop, "y_min_m": ytop - T})
                        done += 1; progress(done, total)
                hlod.append({"level": L, "group_chunks": g, "meters_per_pixel": mpp_l, "tiles_x": gx, "tiles_y": gy, "tiles": lt})
            index = {
                "tool": "TerrainForge", "project": project.name, "tile_size_m": w.chunk_size_m, "tile_px": ex.tile_px,
                "meters_per_pixel": mpp, "tiles_x": nx, "tiles_y": ny, "bit_depth": 16, "byte_order_r16": "little-endian",
                "z_min_m": lo, "z_max_m": hi, "height_range_m": rng, "sea_level_m": w.sea_level_m,
                "sea_level_pixel_value": (w.sea_level_m - lo) / rng * QMAX,
                "height_formula": "elevation_m = z_min_m + pixel / 65535 * (z_max_m - z_min_m)",
                "orientation": "tile (0,0) = north-west; row 0 of each image = north",
                "shared_edges": "The last pixel of a tile equals the first pixel of its neighbour (same value). Skip the duplicate when merging.",
                "outside_world_note": "Edge tiles may extend beyond the world if its size is not a multiple of the tile size.",
                "waterfalls": eng.waterfalls(),
                "lakes": [{"id": f.id, "x_m": f.x_m, "y_m": f.y_m, "diameter_m": f.diameter_m, "water_level_m": f.high_m} for f in project.points if f.kind == "lake"],
                "markers": [{"id": f.id, "kind": f.kind, "x_m": f.x_m, "y_m": f.y_m} for f in project.points if f.kind == "cave"],
                "biomes": [{"id": b.id, "name": b.name, "polygon_m": b.polygon} for b in project.biomes],
                "detail": detail_info, "tiles": tiles, "hlod": hlod,
            }
            zf.writestr("tiles_index.json", json.dumps(index, ensure_ascii=False, indent=2))
            zf.writestr("project.json", project.model_dump_json(indent=2))
            hm = {"mode": "tiles", "tile_size_m": w.chunk_size_m, "tile_px": ex.tile_px, "meters_per_pixel": mpp, "tiles_x": nx, "tiles_y": ny,
                  "bit_depth": 16, "z_min_m": lo, "z_max_m": hi, "height_range_m": rng, "sea_level_pixel_value": (w.sea_level_m - lo) / rng * QMAX,
                  "formula": "elevation_m = z_min_m + pixel / 65535 * (z_max_m - z_min_m)", "image_origin": "row 0 = north",
                  "shared_edges": True, "index_file": "tiles_index.json", "tiles": tiles, "hlod": hlod}
            for name, data in make_extras(project, hm).items():
                zf.writestr(name, data)
