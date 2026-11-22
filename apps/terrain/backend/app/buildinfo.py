"""build.json: وصف كامل للعالم لسكربت Blender (import_build.py) + أقنعة الغطاء النباتي."""
from __future__ import annotations
import json, math, re
from pathlib import Path
import numpy as np
import cv2
from .terrain import (Engine, S, POSITIVE, RELIEF, LABELS, grid_axes, poly_weight_grid, site_ext)
from .noise import fbm
from .materials import library, paint, pack_splats, colors_rgb, zone_density
from .derived import derive, to_u8
from .scatter import place as scatter_place, to_csv as scatter_csv
from .water import build as water_build, encode as water_encode
from .roads import build as roads_build
from .kits import plan as kit_plan, to_csv as kit_csv
from .routing import lots_for_site
from .gameplay import simulate

EN_LABELS = {
    "mountain": "Mountain", "hill": "Hill", "plateau": "Plateau", "mesa": "Mesa", "volcano": "Volcano", "island": "Island", "atoll": "Atoll",
    "terraces": "Terraces", "scree": "Scree slope", "delta": "River delta", "crater": "Crater", "basin": "Basin", "lake": "Lake",
    "sinkhole": "Sinkhole", "cave": "Cave entrance", "marsh": "Marsh", "dune": "Dune field", "river": "River", "road": "Road",
    "valley": "Valley", "ridge": "Ridge", "cliff": "Cliff"}


def ascii_slug(text, fallback=""):
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_") or fallback


class Namer:
    """أسماء إنجليزية فريدة للكائنات في Blender: <category>_<NN>[_<اسم ASCII من المستخدم>]."""
    def __init__(self):
        self.c = {}

    def make(self, cat, user_name=None):
        self.c[cat] = self.c.get(cat, 0) + 1
        a = ascii_slug(user_name)
        return f"{cat}_{self.c[cat]:02d}" + (f"_{a}" if a else "")


_SCRIPT = Path(__file__).resolve().parents[2] / "blender" / "import_build.py"


def generate_masks(project, eng: Engine, Z, xs, ys):
    """يعيد (قناع uint8 لكل طبقة نباتات، كثافة float لكل منطقة id). الكثافة = المضلع × الكثافة × تكتّل × ميل × ارتفاع × (1-استبعاد)."""
    if not any(z.layer not in RELIEF for z in project.zones):
        return {}, {}
    dx, dy = xs[1] - xs[0], ys[0] - ys[1]
    gy, gx = np.gradient(Z.astype(np.float64), dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    free = 1.0 - eng.exclusion(xs, ys, Z)
    out, dens = {}, {}
    for z in project.zones:
        if z.layer in RELIEF:
            continue
        d = zone_density(project, eng, z, Z, xs, ys, slope, free)
        dens[z.id] = d
        out[z.layer] = np.maximum(out.get(z.layer, 0.0), d)
    return {k: (np.clip(v, 0, 1) * 255 + 0.5).astype(np.uint8) for k, v in out.items()}, dens


def _lerp(a, b, t):
    return a + (b - a) * t


def _outline(s, n=48):
    if s.shape == "circle":
        R = s.diameter_m / 2
        return [(s.x_m + R * math.cos(2 * math.pi * i / n), s.y_m + R * math.sin(2 * math.pi * i / n)) for i in range(n)]
    th = math.radians(s.rotation_deg)
    pts = []
    for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        a, b = u * s.width_m / 2, v * s.length_m / 2
        pts.append((s.x_m + a * math.cos(th) - b * math.sin(th), s.y_m + a * math.sin(th) + b * math.cos(th)))
    return pts


def plan_chunks(project, eng: Engine, hm: dict, suggested=None) -> dict:
    """تقسيم العالم إلى Chunks بحجم المنطقة المحمّلة + خطة LOD/HLOD + ما يقع في كل Chunk."""
    w = project.world
    T = w.chunk_size_m
    nx, ny = math.ceil(w.size_x_m / T), math.ceil(w.size_y_m / T)
    circ = lambda x, y, R, b: math.hypot(max(b[0] - x, 0, x - b[2]), max(b[1] - y, 0, y - b[3])) <= R
    lines = []
    for i, (typ, f) in enumerate(eng.stages):
        if typ == "line":
            d = eng._design(i)
            if d:
                lines.append((f, np.asarray(d["x"]), np.asarray(d["y"])))
    chunks = []
    for r in range(ny):
        for c in range(nx):
            b = (c * T, w.size_y_m - (r + 1) * T, (c + 1) * T, w.size_y_m - r * T)
            inb = lambda x, y, m=0: b[0] - m <= x <= b[2] + m and b[1] - m <= y <= b[3] + m
            chunks.append({"id": f"{c}_{r}", "col": c, "row": r, "bounds_m": list(b), "features": {
                "points": [f.id for f in project.points if circ(f.x_m, f.y_m, f.diameter_m / 2, b)],
                "lines": [f.id for f, X, Y in lines if any(inb(x, y, f.width_m) for x, y in zip(X[::3], Y[::3]))],
                "sites": [s.id for s in project.sites if circ(s.x_m, s.y_m, site_ext(s), b)],
                "pois": [p.id for p in project.pois if circ(p.x_m, p.y_m, p.radius_m, b)],
                "zones": [z.id for z in project.zones if (lambda P: not (P[:, 0].max() < b[0] or P[:, 0].min() > b[2] or P[:, 1].max() < b[1] or P[:, 1].min() > b[3]))(np.asarray(z.polygon))],
            }})
    px = hm.get("tile_px") or max(2, int(round(T / ((hm.get("meters_per_pixel_x") or hm.get("meters_per_pixel") or 1.0)))) + 1)
    steps = [1, 2, 4, 8]
    default_d = [T * 0.75 * 2 ** i for i in range(4)]
    hl = min(4, math.ceil(math.log2(max(nx, ny)))) if max(nx, ny) > 1 else 0
    return {"chunk_size_m": T, "chunks_x": nx, "chunks_y": ny, "chunk_px": px, "chunks": chunks,
            "lod": {"levels": [{"lod": i, "decimation": steps[i], "max_distance_m": default_d[i], "grid_vertices_per_side": max(2, (px - 1) // steps[i] + 1)} for i in range(4)],
                    "suggested_distances_from_player_view_m": suggested, "note": "Default distances derive from the chunk size; suggested_distances_from_player_view_m come from the expected player's view range along the route."},
            "hlod": [{"level": L, "group_chunks": 2 ** L, "from_distance_m": default_d[3] * 2 ** (L - 1)} for L in range(1, hl + 1)]}


def build_dict(project, eng: Engine, hm: dict, masks: dict, mats=None, sim=None, sim_error=None) -> dict:
    w = project.world
    P = lambda pts: [[round(x, 3), round(y, 3), round(float(z), 3)] for (x, y), z in zip(pts, eng.points([q[0] for q in pts], [q[1] for q in pts]))]
    nm, bn = Namer(), {}
    points, lakes, marsh = [], [], []
    for f in project.points:
        bn["p:" + f.id] = nm.make(f.kind)
        gz = float(eng.points([f.x_m], [f.y_m])[0])
        item = {"id": f.id, "blender_name": bn["p:" + f.id], "kind": f.kind, "label": EN_LABELS[f.kind], "label_ar": LABELS[f.kind], "center": {"x": f.x_m, "y": f.y_m, "z": round(gz, 3)},
                "diameter_m": f.diameter_m, "footprint_radius_m": f.diameter_m / 2, "high_m": f.high_m, "low_m": f.low_m,
                "shape": f.shape, "inner_ratio": f.inner_ratio, "depth_ratio": f.depth_ratio, "amplitude_m": f.amplitude_m,
                "wavelength_m": f.wavelength_m, "direction_deg": f.direction_deg, "steps": f.steps,
                "role": "positive" if f.kind in POSITIVE else "negative" if f.kind not in ("dune", "marsh") else "surface",
                "materials": {"low": f.mat_low, "mid": f.mat_mid, "high": f.mat_high}}
        points.append(item)
        if f.kind == "lake":
            lakes.append({"id": f.id, "blender_name": bn["p:" + f.id], "x": f.x_m, "y": f.y_m, "radius_m": f.diameter_m / 2, "water_level_m": f.high_m})
        if f.kind == "marsh":
            marsh.append({"id": f.id, "blender_name": bn["p:" + f.id], "x": f.x_m, "y": f.y_m, "radius_m": f.diameter_m / 2, "water_level_m": f.high_m})
    lines, sites = [], []
    for i, (typ, f) in enumerate(eng.stages):
        if typ == "line":
            d = eng._design(i)
            if not d:
                continue
            ix = np.unique(np.linspace(0, len(d["s"]) - 1, min(1200, len(d["s"]))).astype(int))
            sx, sy, ss = d["x"][ix], d["y"][ix], d["s"][ix]
            sz = eng.points(sx, sy)
            fr = ss / max(d["L"], 1e-9)
            bn["l:" + f.id] = nm.make(f.kind)
            item = {"id": f.id, "blender_name": bn["l:" + f.id], "kind": f.kind, "label": EN_LABELS[f.kind], "label_ar": LABELS[f.kind], "length_m": d["L"], "width_m": f.width_m,
                    "depth_m": f.depth_m, "grade_mode": f.grade_mode if f.kind == "river" else None,
                    "materials": {"main": f.mat_main, "edge": f.mat_edge},
                    "polyline": [[round(float(a), 3), round(float(b), 3), round(float(c), 3)] for a, b, c in zip(sx, sy, sz)],
                    "width_profile_m": [round(float(_lerp(f.width_m, f.width_end_m or f.width_m, t)), 3) for t in fr]}
            if f.kind == "river":
                dep = _lerp(f.depth_m, f.depth_end_m if f.depth_end_m is not None else f.depth_m, fr)
                bed = d["bed"][ix]
                item["bed_z"] = [round(float(v), 3) for v in bed]
                item["water_z"] = [round(float(v), 3) for v in bed + 0.6 * dep]      # سطح الماء ≈ القاع + 60% من العمق
                item["flows_from"] = "first point"
            if f.kind == "road":
                item["road_z"] = [round(float(v), 3) for v in d["z"][ix]]
                item["shoulder_m"] = f.shoulder_m
            if f.kind == "cliff":
                item["high_side"] = "left of drawing direction"
            lines.append(item)
        elif typ == "pad" and not getattr(f, "is_poi", False):
            d = eng._site_design(i)
            bn["s:" + f.id] = nm.make("site_" + f.kind, f.name)
            sites.append({"id": f.id, "blender_name": bn["s:" + f.id], "kind": f.kind, "name": f.name or f.id, "center": {"x": f.x_m, "y": f.y_m, "z": round(d["level"], 3)},
                          "level_z": round(d["level"], 3), "shape": f.shape, "diameter_m": f.diameter_m, "width_m": f.width_m,
                          "length_m": f.length_m, "rotation_deg": f.rotation_deg, "blend_m": f.blend_m, "strength": f.strength,
                          "pad_area_m2": round(math.pi * (f.diameter_m / 2) ** 2 if f.shape == "circle" else f.width_m * f.length_m, 1),
                          "outline": [[round(x, 3), round(y, 3), round(d["level"], 3)] for x, y in _outline(f)],
                          "original_ground": {"min": round(d["ground_min"], 3), "max": round(d["ground_max"], 3), "mean": round(d["ground_mean"], 3)},
                          "cut_m": round(d["cut"], 3), "fill_m": round(d["fill"], 3), "flat": True, "material": f.mat_ground})
    pad_idx = {f.id: i for i, (typ, f) in enumerate(eng.stages) if typ == "pad"}
    lots_out = {}
    for s in project.sites:
        if s.id in pad_idx:
            lots_out[s.id] = lots_for_site(s, eng._site_design(pad_idx[s.id])["level"])
            for it in sites:
                if it["id"] == s.id:
                    it["building_lots"] = lots_out[s.id]
    pois = []
    for p in project.pois:
        z = float(eng.points([p.x_m], [p.y_m])[0])
        bn["o:" + p.id] = nm.make("poi_" + p.kind, p.name)
        item = {"id": p.id, "blender_name": bn["o:" + p.id], "kind": p.kind, "name": p.name or p.id, "center": {"x": p.x_m, "y": p.y_m, "z": round(z, 3)}, "radius_m": p.radius_m,
                "order": p.order, "difficulty": p.difficulty, "level_range": [p.level_min, max(p.level_min, p.level_max)], "dwell_min": p.dwell_min,
                "landmark_height_m": p.landmark_height_m, "flatten": p.flatten, "notes": p.notes}
        if p.id in pad_idx:
            item["arena_level_z"] = round(eng._site_design(pad_idx[p.id])["level"], 3)
        pois.append(item)
    zones = []
    for z in project.zones:
        zones.append({"id": z.id, "blender_name": nm.make("zone_" + z.layer, z.name), "name": z.name, "layer": z.layer, "polygon": P([tuple(q) for q in z.polygon]), "density": z.density,
                      "falloff_m": z.falloff_m, "max_slope_deg": z.max_slope_deg, "min_elev_m": z.min_elev_m, "max_elev_m": z.max_elev_m,
                      "patchiness": z.patchiness, "affects_height": z.layer in RELIEF, "material": z.mat_main, "mask": f"masks/{z.layer}.png" if z.layer in masks else None})
    wfalls = eng.waterfalls()
    for k, wf in enumerate(wfalls):
        wf["river_blender_name"] = bn.get("l:" + wf["river"], "river")
        wf["blender_name"] = f"waterfall_{k + 1:02d}_{wf['river_blender_name']}"
    mat_i = 0
    for m in (mats or []):
        mat_i += 1
        m["blender_name"] = m["id"] if re.fullmatch(r"[A-Za-z0-9_\-]+", m["id"]) else f"material_{mat_i:02d}"
    if sim:
        for k, leg in enumerate(sim["legs"]):
            leg["blender_name"] = f"expected_path_{k + 1:02d}"
            leg["from_name"], leg["to_name"] = bn.get("o:" + leg["from"], leg["from"]), bn.get("o:" + leg["to"], leg["to"])
    return {
        "project_slug": ascii_slug(project.name, "World"),
        "format": "terrainforge-build", "version": 1, "generator": "TerrainForge", "project": project.name,
        "coordinate_system": {"units": "meter", "x": "east", "y": "north", "z": "up", "origin": "south-west corner of the world at sea datum",
                              "handedness": "right", "blender": "same axes (X east, Y north, Z up) — no conversion needed"},
        "world": {"size_x_m": w.size_x_m, "size_y_m": w.size_y_m, "sea_level_m": w.sea_level_m, "cell_size_m": w.cell_size_m,
                  "chunk_size_m": w.chunk_size_m, "seed": w.seed},
        "heightmap": hm,
        "water": {"sea_level_m": w.sea_level_m, "lakes": lakes, "marshes": marsh, "waterfalls": wfalls,
                  "rivers": [l["id"] for l in lines if l["kind"] == "river"]},
        "biomes": [{"id": b.id, "blender_name": f"biome_{k + 1:02d}" + ("_" + ascii_slug(b.name) if ascii_slug(b.name) else ""), "name": b.name, "polygon": [list(q) for q in b.polygon], "base_elevation_m": b.base_elevation_m,
                    "noise_amplitude_m": b.noise_amplitude_m, "min_elev_m": b.min_elev_m, "max_elev_m": b.max_elev_m} for k, b in enumerate(project.biomes)],
        "features": {"points": points, "lines": lines},
        "sites": sites,
        "gameplay": {"pois": pois, "player_model": project.player.model_dump(),
                     "player_start": next((p for p in pois if p["kind"] == "player_start"), None),
                     "expected_route": sim, "simulation_error": sim_error},
        "scatter_zones": zones,
        "masks": masks,
        "materials": mats or [],
        "paint_rules": project.paint.model_dump(),
        "markers": [{"id": f.id, "blender_name": bn["p:" + f.id], "kind": f.kind, "x": f.x_m, "y": f.y_m, "note": "Cave entrance: model the interior in 3D (a heightmap cannot hold cavities)."} for f in project.points if f.kind == "cave"],
        "erosion": project.erosion.model_dump(),
        "surface": project.surface.model_dump(),
        "atmosphere": project.atmosphere.model_dump(),
        "chunks": plan_chunks(project, eng, hm, (sim or {}).get("suggested_lod_distances_m")),
        "blender": {"import_script": "import_build.py", "uv": "terrain meshes get UV 'world_uv' = (x/size_x, y/size_y) so masks align",
                    "heights": "elevation_m = z_min_m + pixel/65535 * height_range_m"},
    }


def make_extras(project, hm: dict) -> dict:
    """يعيد {اسم_ملف: bytes}: build.json، أقنعة النباتات، صور توزيع المواد (Splat)، معاينة ألوان، وسكربت Blender."""
    w = project.world
    N = project.export.mask_px
    eng = Engine(project, step=0.75 * max(w.size_x_m, w.size_y_m) / (N - 1))
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, N)
    Z = eng.grid(xs, ys)
    files, info = {}, {}
    masks, dens = generate_masks(project, eng, Z, xs, ys)
    for layer, arr in masks.items():
        files[f"masks/{layer}.png"] = cv2.imencode(".png", arr)[1].tobytes()
        info[layer] = {"file": f"masks/{layer}.png", "width_px": arr.shape[1], "height_px": arr.shape[0], "encoding": "8-bit density 0-255",
                       "origin": "row 0 = north", "world_extent_m": [0, 0, w.size_x_m, w.size_y_m]}
    dv, dv_info = None, None
    if project.derived.enabled:
        dx, dy = xs[1] - xs[0], ys[0] - ys[1]
        dv = derive(Z, dx, dy, project.derived)
        enc = {"curv_convex": "8-bit 0-255: 255 = sharp convex edge/crest", "curv_concave": "8-bit 0-255: 255 = sharp concave channel/hollow",
               "cavity": "8-bit 0-255: 255 = deep enclosed hollow (ambient-occlusion proxy)", "flow": "8-bit 0-255: log-scaled flow accumulation",
               "stream": "8-bit 0-255: 255 = stream (contributing area above stream_area_m2)", "wetness": "8-bit 0-255: topographic wetness index, 255 = wettest"}
        dv_info = {"stream_area_m2": project.derived.stream_area_m2, "slope_classes_deg": project.derived.slope_classes_deg, "masks": {}}
        for k, e in enc.items():
            files[f"masks/derived_{k}.png"] = cv2.imencode(".png", to_u8(dv[k]))[1].tobytes()
            dv_info["masks"][k] = {"file": f"masks/derived_{k}.png", "encoding": e, "origin": "row 0 = north", "world_extent_m": [0, 0, w.size_x_m, w.size_y_m]}
        files["masks/derived_slope_class.png"] = cv2.imencode(".png", dv["slope_class"])[1].tobytes()
        dv_info["masks"]["slope_class"] = {"file": "masks/derived_slope_class.png", "encoding": "8-bit class index: 0 = below first limit ... N = above last (see slope_classes_deg)",
                                           "origin": "row 0 = north", "world_extent_m": [0, 0, w.size_x_m, w.size_y_m]}
    sc_info = []
    if project.scatter.enabled and project.scatter.species:
        layer_d = {}
        for zn in project.zones:
            if zn.id in dens:
                layer_d[zn.layer] = np.maximum(layer_d.get(zn.layer, 0.0), dens[zn.id])
        for i, sp in enumerate(project.scatter.species):
            rec = {"id": sp.id, "name": sp.name, "kind": sp.kind, "layer": sp.layer, "asset": sp.asset or f"TF_Assets_{ascii_slug(sp.id) or i}",
                   "align_to_normal": sp.align_to_normal, "count": 0, "file": None}
            d = layer_d.get(sp.layer)
            if d is None:
                rec["note"] = "لا توجد منطقة نباتات بهذه الطبقة"
            else:
                pts = scatter_place(sp, d, Z, xs, ys)
                if pts is not None:
                    fn = f"scatter/{i:02d}_{ascii_slug(sp.id) or 'sp'}.csv"
                    files[fn] = scatter_csv(pts)
                    rec.update(count=int(len(pts["x"])), file=fn, min_dist_m=round(float(pts["min_dist_m"]), 3),
                               columns=["x", "y", "z", "yaw_deg", "scale", "nx", "ny", "nz"], units="meters, world frame (x east, y north, z up); yaw in degrees")
                else:
                    rec["note"] = "لا مواضع صالحة (تحقق من الميل والارتفاع والكثافة)"
            sc_info.append(rec)
    pt, _ = paint(project, eng, Z, xs, ys, dens, dv)
    imgs, minfo = pack_splats(project, pt)
    for i, img in enumerate(imgs):
        files[f"masks/splat_{i}.png"] = cv2.imencode(".png", img)[1].tobytes()          # RGBA: 4 مواد لكل صورة
    files["masks/materials_preview.png"] = cv2.imencode(".png", colors_rgb(project, pt)[:, :, ::-1])[1].tobytes()
    sim, sim_err = None, None
    if any(p.kind == "player_start" for p in project.pois):
        try:
            sim = simulate(project, 513)
            for leg in sim["legs"]:
                if leg.get("reachable"):
                    P = np.asarray(leg["points"], float)
                    leg["points"] = [[x, y, round(float(z), 2)] for (x, y), z in zip(P, eng.points(P[:, 0], P[:, 1]))]
        except Exception as e:  # noqa: BLE001
            sim_err = str(e)
    bd = build_dict(project, eng, hm, info, minfo, sim, sim_err)
    bd["derived"] = dv_info
    bd["kit"] = None
    if project.kit.enabled and project.kit.pieces:
        rows = kit_plan(project.kit, bd["sites"], [l for l in bd["features"]["lines"] if l["kind"] == "road"])
        counts = {}
        for r_ in rows:
            counts[r_["piece"]] = counts.get(r_["piece"], 0) + 1
        files["kit/placements.csv"] = kit_csv(rows)
        bd["kit"] = {"file": "kit/placements.csv" if rows else None, "count": len(rows), "columns": ["site", "piece", "role", "x", "y", "z", "yaw_deg", "scale"],
                     "convention": "piece front = local +X; yaw in degrees about Z (x east, y north); scale uniform",
                     "pieces": [{"id": p.id, "name": p.name, "role": p.role, "collection": p.collection or f"TF_Kit_{ascii_slug(p.id) or p.id}", "width_m": p.width_m,
                                 "length_m": p.length_m, "height_m": p.height_m, "count": counts.get(p.id, 0)} for p in project.kit.pieces]}
    bd["road_maps"] = None
    if project.roads.enabled:
        rd_list = [l for l in bd["features"]["lines"] if l["kind"] == "road"]
        rm = roads_build(xs, ys, rd_list, project.roads.dust_width_m)
        if rm is not None:
            ext = [0, 0, w.size_x_m, w.size_y_m]
            bd["road_maps"] = {"settings": project.roads.model_dump(), "origin": "row 0 = north", "world_extent_m": ext, "masks": {}}
            for k, e in (("surface", "8-bit: fractional pixel coverage of the road surface"), ("shoulder", "8-bit: fractional coverage of the shoulder band (shoulder_m)"),
                         ("dust", "8-bit: irregular dusty edge outside the surface, width varies along the road")):
                files[f"masks/road_{k}.png"] = cv2.imencode(".png", to_u8(rm[k]))[1].tobytes()
                bd["road_maps"]["masks"][k] = {"file": f"masks/road_{k}.png", "encoding": e}
            bd["road_maps"]["tire_tracks"] = {"gauge_m": project.roads.track_gauge_m, "width_m": project.roads.track_width_m,
                                              "note": "procedural in the Blender shader (too fine for the mask resolution); engines: decal two strips at +/- gauge/2 from the centerline"}
    bd["water_maps"] = None
    if project.water.enabled:
        rivers = [l for l in bd["features"]["lines"] if l["kind"] == "river"]
        mp = water_build(Z, xs, ys, w.sea_level_m, bd["water"]["lakes"] + bd["water"]["marshes"], rivers, project.water)
        if mp["water_mask"].any():
            dmax, p_depth, p_shore, p_foam, p_flow = water_encode(mp)
            files.update({"masks/water_depth.png": p_depth, "masks/water_shore.png": p_shore, "masks/water_foam.png": p_foam, "masks/water_flow.png": p_flow})
            ext = [0, 0, w.size_x_m, w.size_y_m]
            bd["water_maps"] = {
                "settings": project.water.model_dump(), "origin": "row 0 = north", "world_extent_m": ext, "max_depth_m": round(dmax, 3),
                "depth": {"file": "masks/water_depth.png", "encoding": "16-bit: depth_m = value / 65535 * max_depth_m"},
                "shore": {"file": "masks/water_shore.png", "encoding": "8-bit: 255 at the waterline on land, 0 at shore_width_m"},
                "foam": {"file": "masks/water_foam.png", "encoding": "8-bit: edge foam inside water + river rapids"},
                "flow": {"file": "masks/water_flow.png", "encoding": "RGB 8-bit: R,G = 0.5 + 0.5 * downstream direction (x east, y north), B = speed 0..1"}}
    bd["scatter"] = sc_info
    files["build.json"] = json.dumps(bd, ensure_ascii=False, indent=1).encode("utf-8")
    if _SCRIPT.exists():
        files["import_build.py"] = _SCRIPT.read_bytes()
    return files
