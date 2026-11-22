"""Blender worker: runs in its own process, reads a job JSON, writes a result JSON.

  python worker.py job.json                       (bpy module interpreter)
  blender -b --factory-startup -P worker.py -- job.json   (real Blender binary)

The worker never modifies project data: it only reads per-element mesh files
(.npz) and writes new output files. Exit code 0 = ok, 2 = failed (see result).
Everything is created through the data API / bmesh (no selection-dependent
operators) except optional smart UV, so it runs identically headless.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import bpy  # must be imported before bmesh/mathutils when running as the pip `bpy` module
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix  # noqa: E402

STEP_ORDER = ["materials", "cleanup", "optimize", "uv", "collision", "lod", "pivot", "export"]
DISSOLVE_DEG = {"high": 0.0, "medium": 1.0, "low": 5.0}


def _argv() -> list[str]:
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else a[1:]


def log(msg: str) -> None:
    print(f"[bim-worker] {msg}", flush=True)


# ---------------------------------------------------------------------------
def tri_count(me: bpy.types.Mesh) -> int:
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def make_materials(defs: list[dict], tex_dir: Path | None, warnings: list[str]) -> dict[str, bpy.types.Material]:
    out: dict[str, bpy.types.Material] = {}
    allm = list(defs) + [{"id": "__default__", "name": "Default", "color": "#b0b0b0", "roughness": 0.8, "metallic": 0.0}]
    for d in allm:
        m = bpy.data.materials.new(f"MAT_{d['name']}")
        try:
            m.use_nodes = True  # deprecated no-op in newer Blender, required in older
        except Exception:
            pass
        bsdf = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
        if bsdf is None:
            warnings.append(f"material {d['name']}: no Principled BSDF node")
            out[d["id"]] = m
            continue
        c = d["color"].lstrip("#")
        rgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        lin = [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in rgb]
        bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
        bsdf.inputs["Roughness"].default_value = float(d.get("roughness", 0.8))
        bsdf.inputs["Metallic"].default_value = float(d.get("metallic", 0.0))
        tex = d.get("texture")
        if tex and tex_dir is not None:  # textures are loaded ONLY when requested
            p = tex_dir / tex
            if p.exists():
                img = bpy.data.images.load(str(p))
                if img.size[0] == 0 or img.size[1] == 0:  # Blender loads undecodable files silently
                    bpy.data.images.remove(img)
                    warnings.append(f"texture '{tex}' could not be decoded; material {d['name']} uses its plain colour")
                else:
                    node = m.node_tree.nodes.new("ShaderNodeTexImage")
                    node.image = img
                    m.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
            else:
                warnings.append(f"texture '{tex}' for material {d['name']} not found")
        if tex_dir is not None:
            _pbr_maps(m, bsdf, d, tex_dir, warnings)
        m["bim_uv_scale"] = float(d.get("uv_scale", 1.0))
        out[d["id"]] = m
    return out


def _load_map(name: str, tex_dir: Path, mat_name: str, what: str, warnings: list[str]):
    p = tex_dir / name
    if not p.exists():
        warnings.append(f"{what} '{name}' for material {mat_name} not found")
        return None
    img = bpy.data.images.load(str(p))
    if img.size[0] == 0 or img.size[1] == 0:
        bpy.data.images.remove(img)
        warnings.append(f"{what} '{name}' could not be decoded")
        return None
    img.colorspace_settings.name = "Non-Color"
    return img


def _pbr_maps(m, bsdf, d: dict, tex_dir: Path, warnings: list[str]) -> None:
    """Normal map + glTF metallic-roughness map (G = roughness, B = metallic) wired the way the glTF exporter expects."""
    nt = m.node_tree
    if d.get("normal_texture"):
        img = _load_map(d["normal_texture"], tex_dir, d["name"], "normal map", warnings)
        if img is not None:
            tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = img
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if d.get("rough_texture"):
        img = _load_map(d["rough_texture"], tex_dir, d["name"], "roughness map", warnings)
        if img is not None:
            tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = img
            sep = nt.nodes.new("ShaderNodeSeparateColor")
            nt.links.new(tn.outputs["Color"], sep.inputs["Color"])
            nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
            nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])


def new_empty(name: str, parent=None, coll=None):
    o = bpy.data.objects.new(name, None)
    (coll or bpy.context.scene.collection).objects.link(o)
    if parent is not None:
        o.parent = parent
    return o


def mesh_obj(name: str, v: np.ndarray, f: np.ndarray, parent, coll, mats=None) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    me.from_pydata(v.tolist(), [], f.tolist())
    me.update()
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    o.parent = parent
    for m in mats or []:
        me.materials.append(m)
    return o


def bm_edit(obj, fn) -> None:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    fn(bm)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def cleanup(bm: bmesh.types.BMesh) -> None:
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def dissolve(bm: bmesh.types.BMesh, deg: float) -> None:
    if deg > 0:
        bmesh.ops.dissolve_limit(bm, angle_limit=math.radians(deg), verts=bm.verts, edges=bm.edges, delimit={"MATERIAL"})


def triangulate(bm: bmesh.types.BMesh) -> None:
    bmesh.ops.triangulate(bm, faces=bm.faces[:])


def np_verts(me) -> np.ndarray:
    a = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


# UV -------------------------------------------------------------------------
def box_uv(obj, scale_for_slot: dict[int, float]) -> None:
    """World-space box projection: each face is mapped on the plane of its dominant normal axis."""
    me = obj.data
    if "UVMap" not in me.uv_layers:
        me.uv_layers.new(name="UVMap")
    nl, npoly = len(me.loops), len(me.polygons)
    if npoly == 0:
        return
    li = np.empty(nl, np.int64); me.loops.foreach_get("vertex_index", li)
    ls = np.empty(npoly, np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(npoly, np.int64); me.polygons.foreach_get("loop_total", lt)
    nrm = np.empty(npoly * 3); me.polygons.foreach_get("normal", nrm); nrm = nrm.reshape(-1, 3)
    mi = np.empty(npoly, np.int64); me.polygons.foreach_get("material_index", mi)
    co = np_verts(me)[li]
    poly_of_loop = np.repeat(np.arange(npoly), lt)
    axis = np.abs(nrm).argmax(1)[poly_of_loop]
    sc = np.array([scale_for_slot.get(int(i), 1.0) for i in mi])[poly_of_loop]
    u = np.where(axis == 0, co[:, 1], co[:, 0])
    v = np.where(axis == 2, co[:, 1], co[:, 2])
    uv = np.stack([u * sc, v * sc], 1).astype(np.float32)
    me.uv_layers["UVMap"].data.foreach_set("uv", uv.reshape(-1))
    me.update()


def smart_uv(obj) -> None:
    bpy.context.view_layer.objects.active = obj
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")


def validate_uv(obj) -> dict:
    me = obj.data
    if not me.uv_layers:
        return {"layers": 0, "degenerate_faces": len(me.polygons), "ok": False}
    me.calc_loop_triangles()
    nl = len(me.loops)
    uv = np.empty(nl * 2, np.float32); me.uv_layers.active.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("loops", tri); tri = tri.reshape(-1, 3)
    a, b, c = uv[tri[:, 0]], uv[tri[:, 1]], uv[tri[:, 2]]
    area = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])) / 2
    finite = bool(np.isfinite(uv).all())
    deg = int((area < 1e-10).sum())
    return {"layers": len(me.uv_layers), "degenerate_faces": deg, "finite": finite,
            "bounds": [float(uv.min()), float(uv.max())] if nl else [0, 0], "ok": finite and deg == 0}


# collision ---------------------------------------------------------------------
def obb(points: np.ndarray):
    """Minimum-area rotated box in XY (1-degree search) + Z range -> (cx,cy,z0,sx,sy,sz,rot_deg)."""
    xy = points[:, :2]
    best = None
    for ang in range(0, 90):
        a = math.radians(ang)
        c, s = math.cos(a), math.sin(a)
        r = xy @ np.array([[c, s], [-s, c]]).T
        mn, mx = r.min(0), r.max(0)
        area = (mx[0] - mn[0]) * (mx[1] - mn[1])
        if best is None or area < best[0] - 1e-12:
            best = (area, ang, mn, mx)
    _, ang, mn, mx = best
    a = math.radians(ang)
    cr = (mn + mx) / 2
    cx = cr[0] * math.cos(a) - cr[1] * math.sin(a)
    cy = cr[0] * math.sin(a) + cr[1] * math.cos(a)
    return [cx, cy, float(points[:, 2].min()), float(mx[0] - mn[0]), float(mx[1] - mn[1]),
            float(points[:, 2].max() - points[:, 2].min()), float(ang)]


def box_geometry(cx, cy, z0, sx, sy, sz, rot_deg):
    x, y = sx / 2, sy / 2
    v = np.array([[-x, -y, 0], [x, -y, 0], [x, y, 0], [-x, y, 0], [-x, -y, sz], [x, -y, sz], [x, y, sz], [-x, y, sz]], float)
    a = math.radians(rot_deg)
    R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    v = v @ R.T + np.array([cx, cy, z0])
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return v, f


def hull_geometry(points: np.ndarray):
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p.tolist())
    res = bmesh.ops.convex_hull(bm, input=bm.verts[:])
    drop = {g for g in list(res["geom_interior"]) + list(res["geom_unused"]) if isinstance(g, bmesh.types.BMVert)}
    if drop:  # the two lists overlap, so de-duplicate before deleting
        bmesh.ops.delete(bm, geom=list(drop), context="VERTS")
    bm.verts.index_update()
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    v = np.array([vv.co[:] for vv in bm.verts], float)
    idx = {vv.index: i for i, vv in enumerate(bm.verts)}
    f = np.array([[idx[vv.index] for vv in face.verts] for face in bm.faces], int)
    bm.free()
    return v, f


# ---------------------------------------------------------------------------
def run(job: dict) -> dict:
    t_start = time.time()
    steps = [s for s in STEP_ORDER if s in set(job["steps"])]
    st = job["settings"]
    warnings: list[str] = []
    report: dict = {"blender": bpy.app.version_string, "steps": steps, "warnings": warnings}
    timings: dict[str, float] = {}
    _t = [time.time()]

    def tick(name: str) -> None:
        now = time.time()
        timings[name] = round(now - _t[0], 3)
        _t[0] = now

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene_coll = bpy.context.scene.collection
    root = new_empty(job["project_name"], coll=scene_coll)
    root["bim_project"] = job["project_id"]

    tex_dir = Path(job["textures_dir"]) if job.get("use_textures") else None
    mats = make_materials(job["materials"], tex_dir, warnings) if "materials" in steps else {}
    default_mat = mats.get("__default__")
    scale_by_matid = {d["id"]: float(d.get("uv_scale", 1.0)) for d in job["materials"]}

    levels = {l["id"]: l for l in job["levels"]}
    vis_coll = bpy.data.collections.new("Visual"); scene_coll.children.link(vis_coll)
    col_coll = bpy.data.collections.new("Collision"); scene_coll.children.link(col_coll)
    lod_coll = bpy.data.collections.new("LOD"); scene_coll.children.link(lod_coll)
    level_nodes: dict[str, bpy.types.Object] = {}

    def level_node(lid: str):
        if not st.get("split_per_level", True):
            return root
        if lid not in level_nodes:
            lv = levels.get(lid, {"name": lid})
            level_nodes[lid] = new_empty(f"Level_{lv['name']}".replace(" ", "_"), root, vis_coll)
        return level_nodes[lid]

    used: set[str] = set()

    def uname(n: str) -> str:
        base, i = n, 1
        while n in used:
            n = f"{base}_{i}"; i += 1
        used.add(n)
        return n

    # ---- load parts ---------------------------------------------------------
    visuals: list[tuple[bpy.types.Object, dict, str]] = []
    gdir = Path(job["geometry_dir"])
    for pid, part in sorted(job["parts"].items()):
        if not part.get("file") or part.get("tris", 0) == 0:
            continue
        with np.load(gdir / part["file"]) as z:
            v, f, slot, slots = z["v"].astype(np.float64), z["f"], z["slot"], z["slots"].tolist()
        name = uname(part["name"] if part["name"].startswith(part["type"]) else f"{part['type']}_{part['name']}")
        o = mesh_obj(name, v, f, level_node(part["level"]), vis_coll, None)
        me = o.data
        ids = [(s or None) for s in slots]
        if mats:
            for mid in ids:
                me.materials.append(mats.get(mid) or default_mat)
        me.polygons.foreach_set("material_index", slot.astype(np.int32))
        o["bim_id"], o["bim_type"], o["bim_level"] = pid, part["type"], part["level"]
        o["_slot_mats"] = json.dumps(ids)
        visuals.append((o, part, pid))
    tick("load")
    report["parts_loaded"] = len(visuals)
    if not visuals:
        raise RuntimeError("no geometry parts to process (project has no mesh-producing elements)")
    tris_loaded = sum(tri_count(o.data) for o, _, _ in visuals)

    # ---- cleanup / optimize ------------------------------------------------
    if "cleanup" in steps:
        for o, _, _ in visuals:
            bm_edit(o, cleanup)
    tick("cleanup")
    tris_cleaned = sum(tri_count(o.data) for o, _, _ in visuals)
    if "optimize" in steps:
        deg = DISSOLVE_DEG[st["poly_preset"]]
        for o, _, _ in visuals:
            bm_edit(o, lambda bm, d=deg: dissolve(bm, d))
    tick("optimize")
    report["triangles"] = {"loaded": tris_loaded, "after_cleanup": tris_cleaned,
                           "after_optimize": sum(tri_count(o.data) for o, _, _ in visuals),
                           "preset": st["poly_preset"]}

    # ---- UV -------------------------------------------------------------------
    uv_report = {"mode": st["uv"], "objects": 0, "invalid": []}
    if "uv" in steps and st["uv"] != "none":
        for o, part, pid in visuals:
            ids = json.loads(o["_slot_mats"])
            if st["uv"] == "box":
                box_uv(o, {i: scale_by_matid.get(m, 1.0) for i, m in enumerate(ids)})
            else:
                smart_uv(o)
            r = validate_uv(o)
            uv_report["objects"] += 1
            if not r["ok"]:
                uv_report["invalid"].append({"object": o.name, **r})
        uv_report["ok"] = not uv_report["invalid"]
    tick("uv")
    report["uv"] = uv_report

    # ---- collision ------------------------------------------------------------
    collision_objs: list[bpy.types.Object] = []
    mode = st["collision"]
    if "collision" in steps and mode != "none":
        for o, part, pid in visuals:
            t = part["type"]
            if t in ("door", "window", "opening"):
                continue
            node = o.parent
            V = np_verts(o.data)
            pieces: list[tuple[str, np.ndarray, np.ndarray, str]] = []  # (suffix, v, f, godot_hint)
            if t == "wall" and mode in ("box", "convex"):
                for i, b in enumerate(part.get("coll_boxes", [])):
                    bv, bf = box_geometry(*b)
                    pieces.append((f"_p{i}", bv, bf, "-convcolonly"))
            elif t == "wall":  # simplified: dissolved trimesh of the visual
                pieces.append(("", V, _tri_faces(o.data), "-colonly"))
            elif t in ("stair", "roof"):
                hv, hf = hull_geometry(V)
                pieces.append(("", hv, hf, "-convcolonly"))
            elif t == "floor" and part.get("has_holes"):
                pieces.append(("", V, _tri_faces(o.data), "-colonly"))
            elif mode == "box":
                bv, bf = box_geometry(*obb(V))
                pieces.append(("", bv, bf, "-convcolonly"))
            elif mode == "convex":
                hv, hf = hull_geometry(V)
                pieces.append(("", hv, hf, "-convcolonly"))
            else:  # simplified
                pieces.append(("", V, _tri_faces(o.data), "-colonly"))
            for suffix, pv, pf, hint in pieces:
                co = mesh_obj(uname(f"{o.name}{suffix}{hint}"), pv, pf, node, col_coll)
                co["bim_role"], co["bim_for"] = "collision", pid
                if hint == "-colonly":
                    bm_edit(co, lambda bm: (cleanup(bm), dissolve(bm, 10.0)))
                collision_objs.append(co)
    tick("collision")
    report["collision"] = {"mode": mode, "objects": len(collision_objs),
                           "triangles": sum(tri_count(c.data) for c in collision_objs)}

    # ---- LOD --------------------------------------------------------------------
    lod_objs: list[bpy.types.Object] = []
    if "lod" in steps and st["lod_levels"]:
        # Batch: attach all decimate modifiers, ONE depsgraph update, then bake each result.
        # (Updating the scene per object is O(n^2): 19 s for 350 objects before this change.)
        pending: list[tuple[bpy.types.Object, bpy.types.Object, int]] = []
        for o, part, pid in visuals:
            if tri_count(o.data) < max(24, int(st.get("lod_min_triangles", 150))) or part["type"] in ("door", "window"):
                continue
            for i, ratio in enumerate(st["lod_levels"], 1):
                dup = bpy.data.objects.new(uname(f"{o.name}_LOD{i}"), o.data.copy())
                lod_coll.objects.link(dup)
                dup.parent = o.parent
                md = dup.modifiers.new("lod_decimate", "DECIMATE")
                md.ratio = float(ratio)
                md.use_collapse_triangulate = True
                dup["lod"], dup["bim_role"] = i, "lod"
                pending.append((o, dup, i))
        if pending:
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            for _, dup, _i in pending:
                new_me = bpy.data.meshes.new_from_object(dup.evaluated_get(dg))
                old = dup.data
                dup.modifiers.clear()
                dup.data = new_me
                bpy.data.meshes.remove(old)
                lod_objs.append(dup)
    tick("lod")
    report["lod"] = {"levels": st["lod_levels"], "objects": len(lod_objs),
                     "triangles_by_level": {str(i): sum(tri_count(l.data) for l in lod_objs if l["lod"] == i)
                                            for i in range(1, len(st["lod_levels"]) + 1)}}

    # ---- pivot / scale ----------------------------------------------------------
    all_mesh = [o for o in bpy.data.objects if o.type == "MESH"]
    allv = np.vstack([np_verts(o.data) for o, _, _ in visuals])
    lo, hi = allv.min(0), allv.max(0)
    piv = {"center": (lo + hi) / 2, "base_center": np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]]),
           "world_origin": np.zeros(3), "min_corner": lo}[st["pivot"] if "pivot" in steps else "world_origin"]
    orient = Matrix.Rotation(math.radians(float(st.get("rotate_deg", 0))), 4, "Z")
    mirror = bool(st.get("mirror_x", False))
    if mirror:
        orient = orient @ Matrix.Scale(-1.0, 4, (1.0, 0.0, 0.0))
    M = Matrix.Scale(float(st["scale"]), 4) @ orient @ Matrix.Translation((-piv[0], -piv[1], -piv[2]))
    for o in all_mesh:
        o.data.transform(M)
        if mirror:   # a reflection reverses triangle winding: flip it back so faces still look outward
            bm_edit(o, lambda bm: bmesh.ops.reverse_faces(bm, faces=bm.faces[:]))
        o.data.update()
    after = np.vstack([np_verts(o.data) for o, _, _ in visuals])
    nlo, nhi = after.min(0), after.max(0)
    tick("pivot")
    report["pivot"] = {"mode": st["pivot"], "offset_applied": [round(float(x), 6) for x in piv],
                       "bbox_min": [round(float(x), 4) for x in nlo], "bbox_max": [round(float(x), 4) for x in nhi]}

    if st.get("triangulate", True):
        for o in all_mesh:
            bm_edit(o, triangulate)
    tick("triangulate")
    report["objects"] = {"visual": len(visuals), "collision": len(collision_objs), "lod": len(lod_objs),
                         "materials": len([m for m in bpy.data.materials])}
    report["final_triangles"] = {"visual": sum(tri_count(o.data) for o, _, _ in visuals),
                                 "collision": report["collision"]["triangles"]}
    report["final_triangles"]["collision"] = sum(tri_count(c.data) for c in collision_objs)

    # ---- export -------------------------------------------------------------------
    outputs: list[str] = []
    if "export" in steps:
        out_dir = Path(job["output_dir"]); out_dir.mkdir(parents=True, exist_ok=True)
        stem = job["output_stem"]
        fmt = st["format"]
        yup = st["up_axis"] == "Y"
        if fmt in ("glb", "gltf"):
            path = out_dir / f"{stem}.{fmt}"
            kw = dict(filepath=str(path), export_format="GLB" if fmt == "glb" else "GLTF_SEPARATE",
                      use_selection=False, export_yup=yup, export_extras=True, export_cameras=False,
                      export_lights=False, export_apply=False)
            props = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
            skipped = [k for k in kw if k not in props]
            if skipped:
                warnings.append(f"glTF exporter ignores unsupported options: {skipped}")
            bpy.ops.export_scene.gltf(**{k: v for k, v in kw.items() if k in props})
            outputs.append(str(path))
            if fmt == "gltf":
                outputs += [str(p) for p in out_dir.glob(f"{stem}*.bin")]
        else:
            path = out_dir / f"{stem}.fbx"
            kw = dict(filepath=str(path), use_selection=False, axis_up="Y" if yup else "Z", axis_forward="-Z" if yup else "Y",
                      apply_scale_options="FBX_SCALE_ALL", mesh_smooth_type="FACE", add_leaf_bones=False, bake_anim=False,
                      use_custom_props=True)
            props = bpy.ops.export_scene.fbx.get_rna_type().properties.keys()
            skipped = [k for k in kw if k not in props]
            if skipped:
                warnings.append(f"FBX exporter ignores unsupported options: {skipped}")
            bpy.ops.export_scene.fbx(**{k: v for k, v in kw.items() if k in props})
            outputs.append(str(path))
        if st.get("keep_blend"):
            bp = out_dir / f"{stem}.blend"
            bpy.ops.wm.save_as_mainfile(filepath=str(bp), compress=True)
            outputs.append(str(bp))
    tick("export")
    report["outputs"] = outputs
    report["timings"] = timings
    report["seconds"] = round(time.time() - t_start, 3)
    return report


def _tri_faces(me) -> np.ndarray:
    me.calc_loop_triangles()
    a = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", a)
    return a.reshape(-1, 3)


def main() -> None:
    job = json.loads(Path(_argv()[0]).read_text())
    try:
        res = run(job)
        res["ok"] = True
        code = 0
    except Exception as exc:  # noqa: BLE001 - report everything back to the parent
        res = {"ok": False, "error": {"what": str(exc), "where": "blender_scripts/worker.py",
                                      "trace": traceback.format_exc()[-3000:]}}
        code = 2
    Path(job["result_path"]).write_text(json.dumps(res))
    log("done" if code == 0 else f"failed: {res['error']['what']}")
    sys.exit(code)


if __name__ == "__main__":
    main()
