"""
TerrainForge -> Blender importer. Reads build.json and builds the whole scene (all object names are English):
  * Terrain split into Chunks, each with LOD0..3 meshes (coarser LODs hidden) + HLOD meshes for chunk groups (hidden),
    UV map "world_uv" = (x/size_x, y/size_y), custom properties with distances and chunk contents
  * Sea, lakes, marshes, waterfalls
  * Rivers and roads as flat ribbons of their real width (water surface / road surface) plus a thin centerline curve;
    valleys, ridges and cliffs as centerline curves
  * Site pads (flat outlines at the leveled elevation) with empties, suggested building lots
  * Gameplay: POIs (player start, landmarks, boss/story zones...), expected player route
  * Vegetation/scatter zones + density masks, and one terrain material that blends the world's materials
    (color or Albedo/Normal per material) using the splat maps masks/splat_N.png
  * Kit (step 9): village/building pieces (houses, walls, gates, towers, props) instanced at the tool's placements (kit/placements.csv); your collections
    named TF_Kit_<id> win over the placeholders.
  * Road shader (step 7): road ribbons carry road-space UVs; tire tracks, patchy wear and an irregular dusty edge are procedural (meters), settings from the tool.
  * Water shader (step 6): depth absorption, shore/rapids foam and flow-driven ripples from the tool's water maps (masks/water_*.png).
  * Scatter (step 4): trees/bushes/rocks from the tool's Poisson-disk positions (scatter/*.csv) via Geometry Nodes instancing; put your own
    assets in a collection named after the species' asset (a simple placeholder is used otherwise).
  * PBR surface (step 2): per material a texture-pack folder (auto-detected Albedo/Roughness/Height/Normal), world-space triplanar
    projection, tiling breakup, height-aware blending and micro relief; tuned from the tool (build.json -> "surface").
  * Atmosphere (step 1): Nishita physical sky, angled sun lamp, volumetric fog, AgX color management, and a camera with
    depth of field aimed at the world. The values come from the tool (build.json -> "atmosphere", set in the TerrainForge UI);
    the ATMOSPHERE dict below is only the fallback for older build.json files. {"enabled": false} skips the step.

Run:  Blender > Scripting tab > Open this file > Run Script   (keep build.json and the PNG files next to it)
  or: blender --python import_build.py -- /path/to/build.json
Axes match the tool: X east, Y north, Z up, meters (no conversion needed).
Note: written without access to Blender; try it on a small world first.
"""
import json, math, os, sys, zlib
import numpy as np
import bpy

DECIMATE = 2          # 1 = every pixel (very heavy for big images), 2 = half resolution, 4 = quarter


def _here():
    try:
        return os.path.dirname(bpy.path.abspath(bpy.context.space_data.text.filepath))
    except Exception:
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return os.getcwd()


def _coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    par = parent or bpy.context.scene.collection
    if c.name not in par.children:
        par.children.link(c)
    return c


def _material(name, rgba):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = rgba
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
    return m


def _poly_curve(name, pts, coll, closed=False, bevel=0.0, props=None):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        p.co = (q[0], q[1], q[2], 1.0)
    sp.use_cyclic_u = closed
    cu.bevel_depth = bevel
    ob = bpy.data.objects.new(name, cu)
    for k, v in (props or {}).items():
        ob[k] = v
    coll.objects.link(ob)
    return ob


def _ribbon(name, pts, widths, coll, mat, props=None, road_hw=None):
    """Flat strip along a polyline: left/right = point +/- normal * width/2 (real road/river width)."""
    P = np.asarray(pts, float)
    n = len(P)
    if n < 2:
        return None
    d = np.gradient(P[:, :2], axis=0)
    L = np.hypot(d[:, 0], d[:, 1])
    L[L == 0] = 1.0
    nx, ny = -d[:, 1] / L, d[:, 0] / L
    hw = np.asarray(widths, float)[:n] / 2.0
    left, right = P.copy(), P.copy()
    left[:, 0] += nx * hw
    left[:, 1] += ny * hw
    right[:, 0] -= nx * hw
    right[:, 1] -= ny * hw
    verts = np.vstack([left, right]).tolist()
    faces = [(i, n + i, n + i + 1, i + 1) for i in range(n - 1)]          # counter-clockwise seen from +Z
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    if road_hw is not None:                                      # road shader inputs: "road_uv" = (lateral m, distance along m), "road_uv2" = (road half-width m, 0)
        s_along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P[:, :2], axis=0).T))])
        H = hw                                                   # total half-width (road + dust) at each point
        R = np.asarray(road_hw, float)[:n] / 2.0
        uv1, uv2 = [], []
        for i in range(n - 1):
            for lat, k in ((H[i], i), (-H[i], i), (-H[i + 1], i + 1), (H[i + 1], i + 1)):
                uv1 += [lat, s_along[k]]
                uv2 += [R[k], 0.0]
        me.uv_layers.new(name="road_uv").data.foreach_set("uv", uv1)
        me.uv_layers.new(name="road_uv2").data.foreach_set("uv", uv2)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    for k, v in (props or {}).items():
        ob[k] = v
    coll.objects.link(ob)
    return ob


def _empty(name, loc, coll, props=None, size=10.0, kind="PLAIN_AXES"):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type, ob.empty_display_size, ob.location = kind, size, loc
    for k, v in (props or {}).items():
        ob[k] = v
    coll.objects.link(ob)
    return ob


def _disc(name, cx, cy, z, r, coll, mat, n=64):
    verts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], [list(range(n))])
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _separate(nodes, tex):
    """Split image channels. Blender 3.3+ uses SeparateColor, older versions SeparateRGB."""
    try:
        sep = nodes.new("ShaderNodeSeparateColor")
        names = ("Red", "Green", "Blue")
    except RuntimeError:
        sep = nodes.new("ShaderNodeSeparateRGB")
        names = ("R", "G", "B")
    tex.id_data.links.new(tex.outputs["Color"], sep.inputs[0])       # the image must feed the splitter (it was never linked before)
    return sep, {"R": sep.outputs[names[0]], "G": sep.outputs[names[1]], "B": sep.outputs[names[2]]}


def _weighted_sum(nodes, links, terms):
    """Sum of (color x weight) using MixRGB nodes (multiply, then add)."""
    acc = None
    for col, w in terms:
        mul = nodes.new("ShaderNodeMixRGB")
        mul.blend_type = "MULTIPLY"
        mul.inputs["Fac"].default_value = 1.0
        links.new(col, mul.inputs["Color1"])
        links.new(w, mul.inputs["Color2"])
        if acc is None:
            acc = mul.outputs["Color"]
        else:
            add = nodes.new("ShaderNodeMixRGB")
            add.blend_type = "ADD"
            add.inputs["Fac"].default_value = 1.0
            links.new(acc, add.inputs["Color1"])
            links.new(mul.outputs["Color"], add.inputs["Color2"])
            acc = add.outputs["Color"]
    return acc


# ── Step 2: PBR surface. Fallback defaults (build.json -> "surface" overrides every key; same defaults as the tool) ──
SURFACE = {
    "triplanar": True,            # project textures from X/Y/Z so steep slopes do not stretch (Image Texture "Box" projection, world space)
    "triplanar_blend": 0.2,       # 0 = hard seams between projections, 1 = very soft
    "break_tiling": True,         # sample every texture twice (rotated + rescaled) and mix by low-frequency noise
    "break_strength": 0.6,        # 0..1 how much of the second sample shows
    "break_scale_m": 80.0,        # size of the noise patches in meters
    "height_blend": True,         # let each material's height map decide who wins where two materials overlap
    "height_contrast": 0.35,      # 0 = plain linear blend, 1 = very sharp breakup
    "relief_m": 0.15,             # depth of the micro relief from the height maps (Bump distance); 0 = off
    "normal_strength": 1.0,
    "normal_convention": "GL",    # convention of the normal maps you supply: GL (Poly Haven, ambientCG NormalGL) or DX (NormalDX)
    "cavity_strength": 0.5,       # step 3: darken hollows with the derived cavity mask
    "wet_darken": 0.3,            # step 3: darken wet ground (derived wetness mask)
    "wet_gloss": 0.4,             # step 3: lower roughness on wet ground
}
_IMG_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".webp")
_KEYS = {"albedo": ("_color", "_diff", "albedo", "basecolor", "base_color"),
         "roughness": ("roughness", "_rough"),
         "height": ("displacement", "_disp", "_height")}


def _pack_map(base, pack, kind, want_conv="GL"):
    """Find a map inside a texture-pack folder by the usual ambientCG / Poly Haven file names.
    Returns (path, convention) where convention is "GL"/"DX" for a normal map whose file name states it, else None."""
    d = os.path.join(base, pack) if pack else ""
    if not d or not os.path.isdir(d):
        return None, None
    files = sorted(f for f in os.listdir(d) if f.lower().endswith(_IMG_EXT))
    stem = lambda f: os.path.splitext(f.lower())[0]
    if kind != "normal":
        hit = [f for f in files if any(k in stem(f) for k in _KEYS[kind])]
        return (os.path.join(d, hit[0]), None) if hit else (None, None)
    gl = [f for f in files if any(k in stem(f) for k in ("normalgl", "nor_gl", "normal_gl"))]
    dx = [f for f in files if any(k in stem(f) for k in ("normaldx", "nor_dx", "normal_dx"))]
    gen = [f for f in files if f not in gl and f not in dx and ("normal" in stem(f) or "_nor" in stem(f))]
    order = ([("GL", gl), (None, gen), ("DX", dx)] if want_conv != "DX" else [("DX", dx), (None, gen), ("GL", gl)])
    for conv, lst in order:
        if lst:
            return os.path.join(d, lst[0]), conv
    return None, None


def _math(nodes, links, op, a, b=None):
    """ShaderNodeMath helper: a / b may be sockets or floats."""
    n = nodes.new("ShaderNodeMath")
    n.operation = op
    for idx, v in ((0, a), (1, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[idx].default_value = float(v)
        else:
            links.new(v, n.inputs[idx])
    return n.outputs[0]


def _height_blend(nodes, links, weights, heights, contrast):
    """Re-weight material weights by their height maps: w' = w * max(0.02, 1 + K*(h-0.5)) / sum(...).
    A zero weight stays zero (no leaking), and where two materials overlap the one whose height is higher wins, giving organic edges."""
    K = contrast * 10.0
    scores = []
    for w, h in zip(weights, heights):
        if h is None:
            scores.append(w)
            continue
        g = _math(nodes, links, "MAXIMUM", _math(nodes, links, "ADD", _math(nodes, links, "MULTIPLY", _math(nodes, links, "SUBTRACT", h, 0.5), K), 1.0), 0.02)   # floor: a low height never erases a material
        scores.append(_math(nodes, links, "MULTIPLY", w, g))
    total = scores[0]
    for sc in scores[1:]:
        total = _math(nodes, links, "ADD", total, sc)
    total = _math(nodes, links, "ADD", total, 1e-6)
    return [_math(nodes, links, "DIVIDE", sc, total) for sc in scores]


def _terrain_material(B, base):
    """Terrain material. Each material = color or PBR set (Albedo, Roughness, Height, Normal; a pack folder is auto-detected),
    projected in world space (triplanar), de-tiled, and blended by the splat weights (optionally height-aware)."""
    mats = B.get("materials") or []
    if not mats:
        return None
    S = dict(SURFACE)
    S.update(B.get("surface") or {})
    world = B["world"]
    mat = bpy.data.materials.new("TF_Terrain")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    uvn = nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "world_uv"
    geo = nodes.new("ShaderNodeNewGeometry")                       # world-space position: seamless across chunks
    chans = {}
    for sp in sorted({m["splat"] for m in mats}):
        path = os.path.join(base, sp)
        if not os.path.exists(path):
            print("TerrainForge: missing", path)
            continue
        img = bpy.data.images.load(path, check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        img.alpha_mode = "CHANNEL_PACKED"
        tn = nodes.new("ShaderNodeTexImage")
        tn.image, tn.interpolation, tn.extension = img, "Linear", "EXTEND"
        links.new(uvn.outputs["UV"], tn.inputs["Vector"])
        _, ch = _separate(nodes, tn)
        ch["A"] = tn.outputs["Alpha"]
        chans[sp] = ch

    # one shared low-frequency noise drives the de-tiling mix of every texture
    brk = None
    if S["break_tiling"] and S["break_strength"] > 0:
        nm_map = nodes.new("ShaderNodeMapping")
        nm_map.inputs["Scale"].default_value = (1.0 / max(S["break_scale_m"], 1.0),) * 3
        links.new(geo.outputs["Position"], nm_map.inputs["Vector"])
        noise = nodes.new("ShaderNodeTexNoise")
        links.new(nm_map.outputs["Vector"], noise.inputs["Vector"])
        rng = nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value, rng.inputs["From Max"].default_value = 0.35, 0.65
        rng.inputs["To Min"].default_value, rng.inputs["To Max"].default_value = 0.0, float(S["break_strength"])
        links.new(noise.outputs["Fac"], rng.inputs["Value"])
        brk = rng.outputs["Result"]

    def _sample(path, noncolor, tile):
        """Color output of an image sampled planar (UV) or triplanar (world), de-tiled when enabled."""
        img = bpy.data.images.load(path, check_existing=True)
        if noncolor:
            img.colorspace_settings.name = "Non-Color"

        def one(rot, mul):
            mp = nodes.new("ShaderNodeMapping")
            if S["triplanar"]:
                mp.inputs["Scale"].default_value = (mul / tile,) * 3
                links.new(geo.outputs["Position"], mp.inputs["Vector"])
            else:
                mp.inputs["Scale"].default_value = (mul * world["size_x_m"] / tile, mul * world["size_y_m"] / tile, 1.0)
                links.new(uvn.outputs["UV"], mp.inputs["Vector"])
            if rot:
                mp.inputs["Rotation"].default_value = (0.0, 0.0, rot)
            t = nodes.new("ShaderNodeTexImage")
            t.image = img
            if S["triplanar"]:
                t.projection, t.projection_blend = "BOX", float(S["triplanar_blend"])
            links.new(mp.outputs["Vector"], t.inputs["Vector"])
            return t.outputs["Color"]

        a = one(0.0, 1.0)
        if brk is None:
            return a
        b = one(0.6435, 0.71)                                      # ~37 degrees, 0.71x scale: the two tilings never line up
        mx = nodes.new("ShaderNodeMixRGB")
        links.new(brk, mx.inputs["Fac"])
        links.new(a, mx.inputs["Color1"])
        links.new(b, mx.inputs["Color2"])
        return mx.outputs["Color"]

    def _const(v):
        n = nodes.new("ShaderNodeRGB")
        n.outputs[0].default_value = (v, v, v, 1.0) if isinstance(v, float) else v
        return n.outputs[0]

    flat = _const((0.5, 0.5, 1.0, 1.0))
    used, albedo_c, rough_c, height_c, normal_c = [], [], [], [], []
    want = S["normal_convention"]
    for m in mats:
        if m["splat"] not in chans:
            continue
        tile = max(m.get("tile_m") or 10.0, 0.01)
        pack = m.get("pack")

        def find(kind):
            if m.get(kind):                                          # an explicit path wins over the pack folder
                p = os.path.join(base, m[kind])
                return (p, None) if os.path.exists(p) else (None, None)
            return _pack_map(base, pack, kind, want)

        pa, _ = find("albedo")
        pr, _ = find("roughness")
        ph, _ = find("height")
        pn, nconv = find("normal")
        print(f"TerrainForge: material {m.get('name') or m['id']}: albedo={bool(pa)} roughness={bool(pr)} height={bool(ph)} normal={bool(pn)}")
        if pa:
            col = _sample(pa, False, tile)
        else:
            h = m["color"].lstrip("#")
            col = _const(tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,))
        rv = float(m.get("roughness_value", 0.9))
        rgh = _sample(pr, True, tile) if pr else _const(rv)
        hgt = _sample(ph, True, tile) if ph else None
        nrm = None
        if pn:                                                       # normal maps stay top-down (tangent space needs the UV tangents)
            mp = nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (world["size_x_m"] / tile, world["size_y_m"] / tile, 1.0)
            links.new(uvn.outputs["UV"], mp.inputs["Vector"])
            t = nodes.new("ShaderNodeTexImage")
            t.image = bpy.data.images.load(pn, check_existing=True)
            t.image.colorspace_settings.name = "Non-Color"
            links.new(mp.outputs["Vector"], t.inputs["Vector"])
            nrm = t.outputs["Color"]
            if (nconv or want) == "DX":                              # DirectX -> OpenGL: invert the green channel
                v1 = nodes.new("ShaderNodeVectorMath")
                v1.operation = "MULTIPLY"
                v1.inputs[1].default_value = (1.0, -1.0, 1.0)
                links.new(nrm, v1.inputs[0])
                v2 = nodes.new("ShaderNodeVectorMath")
                v2.operation = "ADD"
                v2.inputs[1].default_value = (0.0, 1.0, 0.0)
                links.new(v1.outputs["Vector"], v2.inputs[0])
                nrm = v2.outputs["Vector"]
        used.append(chans[m["splat"]][m["channel"]])
        albedo_c.append(col)
        rough_c.append(rgh)
        height_c.append(hgt)
        normal_c.append(nrm)

    if not used or not bsdf:
        return mat
    weights = _height_blend(nodes, links, used, height_c, S["height_contrast"]) if (S["height_blend"] and any(h is not None for h in height_c)) else used
    col_out = _weighted_sum(nodes, links, list(zip(albedo_c, weights)))
    rgh_out = _weighted_sum(nodes, links, list(zip(rough_c, weights)))
    # Step 3: masks derived from the heights (exported by the tool) darken hollows and wet ground and make wet ground glossier
    dmask = (B.get("derived") or {}).get("masks") or {}

    def _dmask(name):
        info = dmask.get(name)
        pth = os.path.join(base, info["file"]) if info else ""
        if not (info and os.path.exists(pth)):
            return None
        img = bpy.data.images.load(pth, check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        tn = nodes.new("ShaderNodeTexImage")
        tn.image, tn.interpolation, tn.extension = img, "Linear", "EXTEND"
        links.new(uvn.outputs["UV"], tn.inputs["Vector"])
        return tn.outputs["Color"]

    def _scale_by(color, mask, amount):                              # color * (1 - mask * amount)
        f = _math(nodes, links, "ADD", _math(nodes, links, "MULTIPLY", mask, -float(amount)), 1.0)
        mx = nodes.new("ShaderNodeMixRGB")
        mx.blend_type = "MULTIPLY"
        mx.inputs["Fac"].default_value = 1.0
        links.new(color, mx.inputs["Color1"])
        links.new(f, mx.inputs["Color2"])
        return mx.outputs["Color"]

    cav = _dmask("cavity") if S["cavity_strength"] > 0 else None
    if cav is not None:
        col_out = _scale_by(col_out, cav, S["cavity_strength"])
    wet = _dmask("wetness") if (S["wet_darken"] > 0 or S["wet_gloss"] > 0) else None
    if wet is not None:
        if S["wet_darken"] > 0:
            col_out = _scale_by(col_out, wet, S["wet_darken"])
        if S["wet_gloss"] > 0:
            rgh_out = _scale_by(rgh_out, wet, S["wet_gloss"])
    links.new(col_out, bsdf.inputs["Base Color"])
    links.new(rgh_out, bsdf.inputs["Roughness"])
    normal_out = None
    if any(n is not None for n in normal_c):
        nm = nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = float(S["normal_strength"])
        links.new(_weighted_sum(nodes, links, [(n or flat, w) for n, w in zip(normal_c, weights)]), nm.inputs["Color"])
        normal_out = nm.outputs["Normal"]
    if S["relief_m"] > 0 and any(h is not None for h in height_c):
        bump = nodes.new("ShaderNodeBump")                          # micro relief from the blended height: works with triplanar projection
        bump.inputs["Strength"].default_value = float(S["normal_strength"])
        bump.inputs["Distance"].default_value = float(S["relief_m"])
        links.new(_weighted_sum(nodes, links, [(h or _const(0.5), w) for h, w in zip(height_c, weights)]), bump.inputs["Height"])
        if normal_out is not None:
            links.new(normal_out, bump.inputs["Normal"])
        normal_out = bump.outputs["Normal"]
    if normal_out is not None:
        links.new(normal_out, bsdf.inputs["Normal"])
    return mat


def _read_png(path, hm):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    buf = np.empty(w * h * img.channels, np.float32)
    img.pixels.foreach_get(buf)
    a = buf.reshape(h, w, img.channels)[:, :, 0]            # Blender row 0 = south (flipped vs the PNG), so y increases with the row
    bpy.data.images.remove(img)
    return hm["z_min_m"] + a.astype(np.float64) * hm["height_range_m"]


def _terrain(name, z, x0, y0, mx, my, world, coll, mat=None, step=None):
    step = max(1, int(step or DECIMATE))
    h, w = z.shape
    ci = np.unique(np.r_[np.arange(0, w, step), w - 1])
    ri = np.unique(np.r_[np.arange(0, h, step), h - 1])
    X, Y = np.meshgrid(x0 + ci * mx, y0 + ri * my)
    Zs = z[np.ix_(ri, ci)]
    ny, nx = Zs.shape
    co = np.stack([X, Y, Zs], -1).reshape(-1, 3)
    i = np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)[None, :]
    faces = np.stack([i, i + 1, i + 1 + nx, i + nx], -1).reshape(-1, 4)
    me = bpy.data.meshes.new(name)
    me.from_pydata(co.tolist(), [], faces.tolist())
    me.update()
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    uv = me.uv_layers.new(name="world_uv")
    vidx = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", vidx)
    uvv = np.stack([co[:, 0] / world["size_x_m"], co[:, 1] / world["size_y_m"]], -1)
    uv.data.foreach_set("uv", uvv[vidx].ravel())
    ob = bpy.data.objects.new(name, me)
    if mat:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


# ── Step 1: atmosphere, lighting, camera ─────────────────────────────────────────────────────────────
# Angles in degrees. sun_azimuth is a compass bearing of the sun's position: 0 = north (+Y), 90 = east (+X).
# Fallback defaults (same as the tool's defaults). build.json -> "atmosphere" overrides every key. None = derive from the world size.
ATMOSPHERE = {
    "enabled": True,
    "engine": "EEVEE",            # "EEVEE" (fast preview) or "CYCLES" (final quality; the sky's own sun disc casts the light)
    "view_transform": "AgX",      # AgX (Blender 4+); falls back to Filmic, then Standard
    "exposure": 0.0,
    "sun_elevation": 28.0,        # low sun = long shadows that reveal relief
    "sun_azimuth": 300.0,
    "sun_energy": 4.0,            # W/m2 of the sun lamp (EEVEE only; Cycles uses the sky disc)
    "sun_size_deg": 0.545,        # real angular diameter of the sun
    "air_density": 1.0, "dust_density": 1.0, "ozone_density": 1.0,
    "sky_altitude_m": None,       # None = z_min of the terrain (the sky is computed for that altitude)
    "fog": True,
    "fog_density": None,          # per meter; None = 3 / world_size (about 5% visibility left at world-size distance)
    "fog_anisotropy": 0.35,       # forward scattering: glow toward the sun
    "camera": True,
    "camera_azimuth": 225.0,      # where the camera stands relative to the world center (bearing). 225 = south-west -> side light
    "camera_distance_factor": 0.6,  # x the larger world side
    "camera_height_above_peak_m": None,   # None = 8% of world size
    "focal_length_mm": 35.0,
    "sensor_width_mm": 36.0,
    "dof": True,
    "f_stop": 4.0,
}


def _try_set(obj, attr, value):
    """Set a property when this Blender version has it; return True on success (the API changed a lot between 2.8 and 5.0)."""
    try:
        setattr(obj, attr, value)
        return True
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False


def _set_engine(scn, want):
    names = (("CYCLES",) if want == "CYCLES" else ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"))   # EEVEE Next in 4.2-4.5, 'BLENDER_EEVEE' again in 5.0 and before 4.2
    for n in names:
        if _try_set(scn.render, "engine", n):
            return n
    return scn.render.engine


def _color_management(scn, cfg):
    vs = scn.view_settings
    for t in (cfg["view_transform"], "Filmic", "Standard"):
        if _try_set(vs, "view_transform", t):
            break
    for look in ("None",):
        _try_set(vs, "look", look)
    vs.exposure = cfg["exposure"]
    vs.gamma = 1.0
    print("TerrainForge: view transform =", vs.view_transform)


def _sun_direction(el_deg, az_deg):
    """Unit vector from the ground toward the sun (X east, Y north, Z up)."""
    el, az = math.radians(el_deg), math.radians(az_deg)
    return (math.cos(el) * math.sin(az), math.cos(el) * math.cos(az), math.sin(el))


def _sky_world(scn, cfg, size, z_min, engine):
    """Nishita sky + optional volumetric fog on the world."""
    w = bpy.data.worlds.get("TF_Atmosphere") or bpy.data.worlds.new("TF_Atmosphere")
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    for kind in ("NISHITA", "MULTIPLE_SCATTERING", "SINGLE_SCATTERING"):   # physical sky: renamed in Blender 5.0
        if _try_set(sky, "sky_type", kind):
            break
    sky.sun_elevation = math.radians(cfg["sun_elevation"])
    sky.sun_rotation = math.radians(cfg["sun_azimuth"])        # assumed: 0 = sun toward +Y (north), clockwise. Verify once in the viewport.
    sky.sun_size = math.radians(cfg["sun_size_deg"])
    sky.altitude = max(0.0, float(cfg["sky_altitude_m"] if cfg["sky_altitude_m"] is not None else z_min))
    _try_set(sky, "air_density", cfg["air_density"])
    if not _try_set(sky, "dust_density", cfg["dust_density"]):         # renamed 'aerosol_density' in Blender 5.0
        _try_set(sky, "aerosol_density", cfg["dust_density"])
    _try_set(sky, "ozone_density", cfg["ozone_density"])
    _try_set(sky, "sun_disc", engine == "CYCLES")             # EEVEE gets its sun from the lamp; Cycles from the disc (no double lighting)
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    if cfg["fog"]:
        dens = cfg["fog_density"] if cfg["fog_density"] is not None else 3.0 / max(size, 1.0)
        vol = nt.nodes.new("ShaderNodeVolumeScatter")
        vol.inputs["Density"].default_value = dens
        vol.inputs["Anisotropy"].default_value = cfg["fog_anisotropy"]
        vol.inputs["Color"].default_value = (0.82, 0.88, 1.0, 1.0)
        nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
        ev = scn.eevee
        _try_set(ev, "volumetric_end", size * 1.5)              # how far fog is computed in EEVEE
        _try_set(ev, "volumetric_start", 1.0)
        _try_set(ev, "use_volumetric_shadows", True)
    scn.world = w
    return sky


def _sun_lamp(cfg, coll):
    """Sun lamp pointing along -d (d = direction toward the sun). Euler XYZ derived analytically: (90 - el, 0, 180 - az)."""
    ld = bpy.data.lights.get("TF_Sun") or bpy.data.lights.new("TF_Sun", "SUN")
    ld.energy = cfg["sun_energy"]
    ld.angle = math.radians(cfg["sun_size_deg"])
    ld.color = (1.0, 0.96, 0.9)
    _try_set(ld, "use_shadow", True)
    ob = bpy.data.objects.get("TF_Sun") or bpy.data.objects.new("TF_Sun", ld)
    ob.rotation_euler = (math.radians(90.0 - cfg["sun_elevation"]), 0.0, math.radians(180.0 - cfg["sun_azimuth"]))
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    return ob


def _camera(scn, cfg, world, hm, coll):
    sx, sy = world["size_x_m"], world["size_y_m"]
    size = max(sx, sy)
    cx, cy = sx / 2.0, sy / 2.0
    zmid = 0.5 * (hm["z_min_m"] + hm["z_max_m"])
    target = bpy.data.objects.get("TF_Camera_Target") or bpy.data.objects.new("TF_Camera_Target", None)
    target.empty_display_type, target.empty_display_size = "PLAIN_AXES", max(size * 0.01, 5.0)
    target.location = (cx, cy, zmid)
    if target.name not in coll.objects:
        coll.objects.link(target)
    az = math.radians(cfg["camera_azimuth"])
    dist = cfg["camera_distance_factor"] * size
    up = cfg["camera_height_above_peak_m"] if cfg["camera_height_above_peak_m"] is not None else 0.08 * size
    pos = (cx + dist * math.sin(az), cy + dist * math.cos(az), hm["z_max_m"] + up)
    cd = bpy.data.cameras.get("TF_Camera") or bpy.data.cameras.new("TF_Camera")
    cd.lens, cd.sensor_width = cfg["focal_length_mm"], cfg["sensor_width_mm"]
    cd.clip_start, cd.clip_end = max(0.1, size * 1e-4), size * 6.0
    cd.dof.use_dof = bool(cfg["dof"])
    cd.dof.focus_object = target                                  # focus follows the target, so moving it re-focuses
    cd.dof.aperture_fstop = cfg["f_stop"]
    cam = bpy.data.objects.get("TF_Camera") or bpy.data.objects.new("TF_Camera", cd)
    cam.location = pos
    if not cam.constraints:
        tc = cam.constraints.new("TRACK_TO")
        tc.target, tc.track_axis, tc.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    if cam.name not in coll.objects:
        coll.objects.link(cam)
    scn.camera = cam
    return cam


def _viewport_clip(size):
    """Large worlds vanish in the default 1 km viewport clip distance."""
    for scr in bpy.data.screens:
        for area in scr.areas:
            if area.type == "VIEW_3D":
                for sp in area.spaces:
                    if sp.type == "VIEW_3D":
                        sp.clip_start, sp.clip_end = max(0.1, size * 1e-4), size * 6.0


def setup_atmosphere(B, root):
    cfg = dict(ATMOSPHERE)
    cfg.update(B.get("atmosphere") or {})
    if not cfg["enabled"]:
        return None
    scn = bpy.context.scene
    world, hm = B["world"], B["heightmap"]
    size = max(world["size_x_m"], world["size_y_m"])
    want = "CYCLES" if str(cfg["engine"]).upper().startswith("CYC") else "EEVEE"
    engine = _set_engine(scn, want)
    _color_management(scn, cfg)
    c_atm = _coll("Atmosphere", root)
    _sky_world(scn, cfg, size, hm["z_min_m"], want)
    if want == "EEVEE":
        _sun_lamp(cfg, c_atm)
    if cfg["camera"]:
        _camera(scn, cfg, world, hm, c_atm)
    _viewport_clip(size)
    print(f"TerrainForge: atmosphere ready (engine={engine}, sun el={cfg['sun_elevation']} az={cfg['sun_azimuth']}, fog={cfg['fog']})")
    return cfg


# ── Step 4: scatter (trees, bushes, rocks...) from the tool's deterministic Poisson-disk positions ─────────────
_PLACEHOLDER = {"tree": ("cone", 9.0, (0.16, 0.38, 0.14, 1.0)), "bush": ("ico", 1.2, (0.22, 0.42, 0.18, 1.0)),
                "rock": ("ico", 1.4, (0.45, 0.44, 0.42, 1.0)), "grass": ("cone", 0.8, (0.35, 0.5, 0.2, 1.0)), "prop": ("ico", 1.0, (0.5, 0.4, 0.3, 1.0))}


def _placeholder_asset(coll_name, kind):
    """A simple stand-in so the scatter is visible at once. Replace it by putting your own objects in a collection with this name."""
    import bmesh
    shape, size, rgba = _PLACEHOLDER.get(kind, _PLACEHOLDER["prop"])
    bm = bmesh.new()
    if shape == "cone":
        try:
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=8, radius1=size * 0.22, radius2=size * 0.02, depth=size)
        except TypeError:                                        # Blender < 3.0 used diameter1/diameter2
            bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=8, diameter1=size * 0.44, diameter2=size * 0.04, depth=size)
        bmesh.ops.translate(bm, vec=(0.0, 0.0, size / 2.0), verts=bm.verts)
    else:
        try:
            bmesh.ops.create_icosphere(bm, subdivisions=1, radius=size / 2.0)
        except TypeError:
            bmesh.ops.create_icosphere(bm, subdivisions=1, diameter=size)
        bmesh.ops.translate(bm, vec=(0.0, 0.0, size * 0.3), verts=bm.verts)
    me = bpy.data.meshes.new(coll_name + "_mesh")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(_material(coll_name + "_mat", rgba))
    ob = bpy.data.objects.new(coll_name + "_obj", me)
    col = bpy.data.collections.new(coll_name)                    # not linked to the scene: Collection Info still instances it
    col.objects.link(ob)
    return col


def _scatter_nodes(name, col):
    """Geometry Nodes: instance the collection's objects on the points, with per-point rotation (rot), scale (scale) and pick (instance index)."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    if hasattr(ng, "interface"):                                 # Blender 4.0+
        ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        ng.inputs.new("NodeSocketGeometry", "Geometry")
        ng.outputs.new("NodeSocketGeometry", "Geometry")
    nd, ln = ng.nodes, ng.links
    nin, nout = nd.new("NodeGroupInput"), nd.new("NodeGroupOutput")
    iop = nd.new("GeometryNodeInstanceOnPoints")
    ci = nd.new("GeometryNodeCollectionInfo")
    ci.inputs["Collection"].default_value = col
    _try_set(ci, "transform_space", "RELATIVE")
    for k, v in (("Separate Children", True), ("Reset Children", True)):
        if k in ci.inputs:
            ci.inputs[k].default_value = v
    iop.inputs["Pick Instance"].default_value = True

    def attr(attr_name, dtype):
        a = nd.new("GeometryNodeInputNamedAttribute")
        a.data_type = dtype
        a.inputs["Name"].default_value = attr_name
        return a.outputs["Attribute"]

    rot = attr("rot", "FLOAT_VECTOR")
    try:                                                         # 4.0+: Euler -> Rotation socket
        e2r = nd.new("FunctionNodeEulerToRotation")
        ln.new(rot, e2r.inputs["Euler"])
        rot = e2r.outputs["Rotation"]
    except (RuntimeError, KeyError, TypeError):
        pass
    ln.new(nin.outputs[0], iop.inputs["Points"])
    ln.new(ci.outputs["Instances"], iop.inputs["Instance"])
    ln.new(attr("pick", "INT"), iop.inputs["Instance Index"])
    ln.new(rot, iop.inputs["Rotation"])
    ln.new(attr("scale", "FLOAT"), iop.inputs["Scale"])
    ln.new(iop.outputs["Instances"], nout.inputs[0])
    return ng


def setup_scatter(B, base, root):
    sc = B.get("scatter") or []
    if not sc:
        return
    from mathutils import Matrix, Vector
    c_sc = _coll("Scatter", root)
    for rec in sc:
        if not rec.get("file"):
            print("TerrainForge: scatter", rec["id"], "-", rec.get("note", "no points"))
            continue
        path = os.path.join(base, rec["file"])
        if not os.path.exists(path):
            print("TerrainForge: missing", path)
            continue
        D = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
        n = len(D)
        x, y, z, yaw, scale = D[:, 0], D[:, 1], D[:, 2], D[:, 3], D[:, 4]
        norm = D[:, 5:8]
        align = float(rec.get("align_to_normal", 0.0))
        rots = np.zeros((n, 3))
        if align <= 0.0:
            rots[:, 2] = np.radians(yaw)
        else:                                                    # tilt toward the surface normal, then spin by yaw
            up = Vector((0.0, 0.0, 1.0))
            for i in range(n):
                nb = up.lerp(Vector(norm[i].tolist()), align)
                nb.normalize()
                r = Matrix.Rotation(math.radians(yaw[i]), 3, "Z") @ up.rotation_difference(nb).to_matrix()
                rots[i] = r.to_euler()[:]
        col = bpy.data.collections.get(rec["asset"]) or _placeholder_asset(rec["asset"], rec.get("kind", "prop"))
        kids = max(1, len(col.objects))
        pick = np.random.default_rng(zlib.crc32(rec["id"].encode("utf-8"))).integers(0, kids, n)   # crc32, not hash(): hash() changes every run
        me = bpy.data.meshes.new(f"TF_Scatter_{rec['id']}")
        me.from_pydata(np.stack([x, y, z], 1).tolist(), [], [])
        for nm, ty, key, arr in (("rot", "FLOAT_VECTOR", "vector", rots.ravel()), ("scale", "FLOAT", "value", scale), ("pick", "INT", "value", pick)):
            at = me.attributes.new(name=nm, type=ty, domain="POINT")
            at.data.foreach_set(key, arr.astype(np.int32 if ty == "INT" else np.float32))
        ob = bpy.data.objects.new(f"TF_Scatter_{rec['id']}", me)
        c_sc.objects.link(ob)
        try:
            mod = ob.modifiers.new("TF_Scatter", "NODES")
            mod.node_group = _scatter_nodes(f"TF_Scatter_{rec['id']}", col)
        except Exception as e:                                   # Geometry Nodes API differs between versions: keep the points
            print("TerrainForge: could not build Geometry Nodes for", rec["id"], "-", e)
        print(f"TerrainForge: scatter {rec['id']}: {n} instances of '{rec['asset']}'")


# ── Step 6: realistic water shader driven by the tool's depth / shore / foam / flow maps ───────────────────
def _water_material(B, base):
    """Depth-based absorption (shallow -> deep color), edge foam + rapids foam, transmission with IOR, and ripples that drift with the river flow."""
    wm = B.get("water_maps")
    if not wm:
        return None
    cfg, world = wm["settings"], B["world"]
    mat = bpy.data.materials.new("TF_Water")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    geo = nodes.new("ShaderNodeNewGeometry")
    uvw = nodes.new("ShaderNodeMapping")                            # world position -> 0..1 over the world (v = y / size_y: row 0 = north = top of the image)
    uvw.inputs["Scale"].default_value = (1.0 / world["size_x_m"], 1.0 / world["size_y_m"], 1.0)
    links.new(geo.outputs["Position"], uvw.inputs["Vector"])

    def tex(key):
        info = wm.get(key) or {}
        pth = os.path.join(base, info.get("file", ""))
        if not os.path.exists(pth):
            return None
        img = bpy.data.images.load(pth, check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        t = nodes.new("ShaderNodeTexImage")
        t.image, t.interpolation, t.extension = img, "Linear", "EXTEND"
        links.new(uvw.outputs["Vector"], t.inputs["Vector"])
        return t

    def rgb(hexs):
        h = hexs.lstrip("#")
        n = nodes.new("ShaderNodeRGB")
        n.outputs[0].default_value = tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)
        return n.outputs[0]

    color = rgb(cfg["shallow_color"])
    td = tex("depth")
    if td is not None:                                               # absorption: color goes shallow -> deep with depth
        depth_m = _math(nodes, links, "MULTIPLY", td.outputs["Color"], float(wm["max_depth_m"]))
        k = _math(nodes, links, "MINIMUM", _math(nodes, links, "DIVIDE", depth_m, max(float(cfg["absorption_depth_m"]), 1e-3)), 1.0)
        mx = nodes.new("ShaderNodeMixRGB")
        links.new(k, mx.inputs["Fac"])
        links.new(rgb(cfg["shallow_color"]), mx.inputs["Color1"])
        links.new(rgb(cfg["deep_color"]), mx.inputs["Color2"])
        color = mx.outputs["Color"]
    rough = float(cfg["roughness"])
    tf = tex("foam")
    foam = None
    if tf is not None and cfg["foam_amount"] > 0:                    # foam: whiter and rougher
        foam = tf.outputs["Color"]
        fm = nodes.new("ShaderNodeMixRGB")
        links.new(foam, fm.inputs["Fac"])
        links.new(color, fm.inputs["Color1"])
        fm.inputs["Color2"].default_value = (0.95, 0.97, 1.0, 1.0)
        color = fm.outputs["Color"]
    if bsdf:
        links.new(color, bsdf.inputs["Base Color"])
        bsdf.inputs["IOR"].default_value = float(cfg["ior"])
        for nm in ("Transmission Weight", "Transmission"):           # 4.x name first, then 3.x
            if nm in bsdf.inputs:
                bsdf.inputs[nm].default_value = 1.0
                break
        if foam is not None:
            links.new(_math(nodes, links, "ADD", _math(nodes, links, "MULTIPLY", foam, 0.6), rough), bsdf.inputs["Roughness"])
        else:
            bsdf.inputs["Roughness"].default_value = rough
        # ripples: 4D noise whose position drifts downstream where the flow map says so, and slowly in time everywhere
        if cfg["wave_height_m"] > 0:
            try:
                time_v = nodes.new("ShaderNodeValue")
                fc = time_v.outputs[0].driver_add("default_value")    # seconds at 24 fps
                fc.driver.expression = "frame / 24"
                pos = geo.outputs["Position"]
                tfl = tex("flow")
                if tfl is not None:
                    _, ch = _separate(nodes, tfl)
                    vec = nodes.new("ShaderNodeVectorMath")
                    vec.operation = "SUBTRACT"
                    links.new(tfl.outputs["Color"], vec.inputs[0])
                    vec.inputs[1].default_value = (0.5, 0.5, 0.0)
                    dirv = nodes.new("ShaderNodeVectorMath")
                    dirv.operation = "SCALE"
                    links.new(vec.outputs["Vector"], dirv.inputs[0])
                    dirv.inputs["Scale"].default_value = 2.0
                    drift = nodes.new("ShaderNodeVectorMath")
                    drift.operation = "SCALE"
                    links.new(dirv.outputs["Vector"], drift.inputs[0])
                    links.new(_math(nodes, links, "MULTIPLY", _math(nodes, links, "MULTIPLY", ch["B"], time_v.outputs[0]), 4.0 * float(cfg["wave_speed"])), drift.inputs["Scale"])
                    sub = nodes.new("ShaderNodeVectorMath")
                    sub.operation = "SUBTRACT"
                    links.new(pos, sub.inputs[0])
                    links.new(drift.outputs["Vector"], sub.inputs[1])
                    pos = sub.outputs["Vector"]
                sc = nodes.new("ShaderNodeMapping")
                sc.inputs["Scale"].default_value = (1.0 / max(float(cfg["wave_scale_m"]), 0.1),) * 3
                links.new(pos, sc.inputs["Vector"])
                nz = nodes.new("ShaderNodeTexNoise")
                nz.noise_dimensions = "4D"
                links.new(sc.outputs["Vector"], nz.inputs["Vector"])
                links.new(_math(nodes, links, "MULTIPLY", time_v.outputs[0], 0.25 * float(cfg["wave_speed"])), nz.inputs["W"])
                bp = nodes.new("ShaderNodeBump")
                bp.inputs["Distance"].default_value = float(cfg["wave_height_m"])
                links.new(nz.outputs["Fac"], bp.inputs["Height"])
                links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
            except (RuntimeError, KeyError, TypeError, AttributeError) as e:
                print("TerrainForge: water ripples skipped -", e)
    print("TerrainForge: water shader ready (depth map:", td is not None, ", foam:", foam is not None, ")")
    return mat


# ── Step 7: road shader: tire tracks, patchy wear, and an irregular dusty edge, all in road coordinates (meters) ─────
def _maprange(nodes, links, val, a0, a1, b0, b1):
    n = nodes.new("ShaderNodeMapRange")
    for k, v in (("From Min", a0), ("From Max", a1), ("To Min", b0), ("To Max", b1)):
        n.inputs[k].default_value = float(v)
    links.new(val, n.inputs["Value"])
    return n.outputs["Result"]


def _road_material(B, color_hex):
    rm = B.get("road_maps")
    if not rm:
        return None
    cfg = rm["settings"]
    mat = bpy.data.materials.new("TF_Road_PBR")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if not bsdf:
        return mat

    def uvsep(name):
        u = nodes.new("ShaderNodeUVMap")
        u.uv_map = name
        sp = nodes.new("ShaderNodeSeparateXYZ")
        links.new(u.outputs["UV"], sp.inputs[0])
        return sp.outputs["X"], sp.outputs["Y"]

    lat, along = uvsep("road_uv")
    hw, _ = uvsep("road_uv2")

    def hexc(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)

    def noise(scale, lat_k=1.0):                                  # noise that follows the road (along, lateral)
        c = nodes.new("ShaderNodeCombineXYZ")
        links.new(_math(nodes, links, "MULTIPLY", along, 1.0 / scale), c.inputs["X"])
        links.new(_math(nodes, links, "MULTIPLY", lat, lat_k / scale), c.inputs["Y"])
        t = nodes.new("ShaderNodeTexNoise")
        links.new(c.outputs["Vector"], t.inputs["Vector"])
        return t.outputs["Fac"]

    lat_abs = _math(nodes, links, "ABSOLUTE", lat)
    off = _math(nodes, links, "SUBTRACT", lat_abs, hw)            # meters beyond the road edge (negative = on the road)
    on_road = _maprange(nodes, links, off, -0.25, 0.25, 1.0, 0.0)
    # dusty edge: width varies along the road, edge breaks up with fine noise
    dust_w = max(float(cfg["dust_width_m"]), 1e-3)
    dw = _math(nodes, links, "MULTIPLY", _math(nodes, links, "ADD", _math(nodes, links, "MULTIPLY", noise(18.0, 0.2), 1.1), 0.45), dust_w)
    fall = _maprange(nodes, links, _math(nodes, links, "DIVIDE", _math(nodes, links, "MAXIMUM", off, 0.0), _math(nodes, links, "MAXIMUM", dw, 1e-3)), 0.0, 1.0, 1.0, 0.0)
    breakup = _math(nodes, links, "ADD", _math(nodes, links, "MULTIPLY", noise(0.9, 1.0), 0.8), 0.3)
    dust_a = _math(nodes, links, "MULTIPLY", fall, _math(nodes, links, "MINIMUM", breakup, 1.0))
    alpha = _math(nodes, links, "MAXIMUM", on_road, dust_a)
    # surface color: base with patchy wear, dust color outside the road
    base = nodes.new("ShaderNodeRGB")
    base.outputs[0].default_value = hexc(color_hex)
    patch = _math(nodes, links, "MULTIPLY", noise(6.0, 1.0), float(cfg["surface_variation"]))
    dim = nodes.new("ShaderNodeMixRGB")
    dim.blend_type = "MULTIPLY"
    dim.inputs["Fac"].default_value = 1.0
    links.new(base.outputs[0], dim.inputs["Color1"])
    links.new(_math(nodes, links, "SUBTRACT", 1.0, patch), dim.inputs["Color2"])
    # tire tracks: two strips at +/- gauge/2, broken up along the road, darker/glossier and slightly pressed in
    d1 = _math(nodes, links, "ABSOLUTE", _math(nodes, links, "SUBTRACT", lat_abs, float(cfg["track_gauge_m"]) / 2.0))
    tw = float(cfg["track_width_m"])
    strip = _maprange(nodes, links, d1, tw * 0.3, tw * 0.9, 1.0, 0.0)
    wear = _maprange(nodes, links, noise(2.5, 6.0), 0.35, 0.65, 0.35, 1.0)
    track = _math(nodes, links, "MULTIPLY", _math(nodes, links, "MULTIPLY", strip, wear), _math(nodes, links, "MULTIPLY", on_road, float(cfg["track_wear"])))
    tr = nodes.new("ShaderNodeMixRGB")
    tr.blend_type = "MULTIPLY"
    links.new(track, tr.inputs["Fac"])
    links.new(dim.outputs["Color"], tr.inputs["Color1"])
    tr.inputs["Color2"].default_value = (0.45, 0.43, 0.41, 1.0)
    dust_mix = nodes.new("ShaderNodeMixRGB")
    links.new(_math(nodes, links, "SUBTRACT", 1.0, on_road), dust_mix.inputs["Fac"])
    links.new(tr.outputs["Color"], dust_mix.inputs["Color1"])
    dust_mix.inputs["Color2"].default_value = hexc(cfg["dust_color"])
    links.new(dust_mix.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(_math(nodes, links, "SUBTRACT", 0.92, _math(nodes, links, "MULTIPLY", track, 0.3)), bsdf.inputs["Roughness"])
    links.new(alpha, bsdf.inputs["Alpha"])
    bp = nodes.new("ShaderNodeBump")                              # pressed-in tracks (height lower where track = 1)
    bp.inputs["Distance"].default_value = float(cfg["track_depth_m"])
    links.new(_math(nodes, links, "SUBTRACT", 1.0, track), bp.inputs["Height"])
    links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])
    for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):   # 4.2+ / older
        _try_set(mat, attr, val)
    return mat


# ── Step 9: village/building kit: instance your pieces (or placeholders) at the tool's placements ───────────
_KIT_COLORS = {"house": (0.62, 0.5, 0.38, 1.0), "main": (0.55, 0.45, 0.4, 1.0), "wall": (0.5, 0.48, 0.45, 1.0), "gate": (0.42, 0.32, 0.22, 1.0),
               "tower": (0.46, 0.44, 0.42, 1.0), "prop": (0.4, 0.5, 0.3, 1.0)}


def _kit_placeholder(piece):
    """Stand-in geometry sized by the piece footprint (front = +X, width on X, length on Y). Replace it with your own collection of the same name."""
    import bmesh
    from mathutils import Matrix
    role, w, l, h = piece["role"], piece["width_m"], piece["length_m"], piece["height_m"]
    bm = bmesh.new()

    def box(sx, sy, sz, z0):
        v = bmesh.ops.create_cube(bm, size=1.0)["verts"]
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=v)
        bmesh.ops.translate(bm, vec=(0.0, 0.0, z0 + sz / 2.0), verts=v)

    def cone(r1, r2, depth, segs):
        try:
            return bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r1, radius2=r2, depth=depth)["verts"]
        except TypeError:                                          # Blender < 3.0
            return bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segs, diameter1=2 * r1, diameter2=2 * r2, depth=depth)["verts"]

    try:
        if role in ("house", "main"):
            box(w, l, h * 0.62, 0.0)
            v = cone(0.7071, 0.0, 1.0, 4)                          # unit pyramid (base side 1) turned square, then scaled over the body
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(45.0), 3, "Z"), verts=v)
            bmesh.ops.scale(bm, vec=(w * 1.1, l * 1.1, h * 0.38), verts=v)
            bmesh.ops.translate(bm, vec=(0.0, 0.0, h * 0.62 + h * 0.19), verts=v)
        elif role == "tower":
            v = cone(w / 2.0, w / 2.0 * 0.9, h, 12)
            bmesh.ops.translate(bm, vec=(0.0, 0.0, h / 2.0), verts=v)
        else:
            box(w, l, h, 0.0)
    except Exception as e:
        print("TerrainForge: kit placeholder fallback to a box -", e)
        bm.clear()
        box(w, l, h, 0.0)
    nm = piece["collection"]
    me = bpy.data.meshes.new(nm + "_mesh")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(_material(nm + "_mat", _KIT_COLORS.get(role, _KIT_COLORS["prop"])))
    col = bpy.data.collections.new(nm)                             # not linked to the scene: collection instances still show it
    col.objects.link(bpy.data.objects.new(nm + "_obj", me))
    return col


def setup_kit(B, base, root):
    kit = B.get("kit")
    if not kit or not kit.get("file"):
        return
    path = os.path.join(base, kit["file"])
    if not os.path.exists(path):
        print("TerrainForge: missing", path)
        return
    pieces = {p["id"]: p for p in kit["pieces"]}
    cols = {}
    for pid, p in pieces.items():
        cols[pid] = bpy.data.collections.get(p["collection"]) or _kit_placeholder(p)
    c_kit = _coll("Kit", root)
    n = 0
    with open(path, encoding="utf-8") as f:
        next(f)                                                    # header
        for line in f:
            site, piece, role, x, y, z, yaw, sc = line.strip().split(",")
            if piece not in cols:
                continue
            ob = bpy.data.objects.new(f"{site}_{piece}_{n:04d}", None)
            ob.instance_type = "COLLECTION"
            ob.instance_collection = cols[piece]
            ob.location = (float(x), float(y), float(z))
            ob.rotation_euler = (0.0, 0.0, math.radians(float(yaw)))
            ob.scale = (float(sc),) * 3
            ob["site"], ob["role"] = site, role
            c_kit.objects.link(ob)
            n += 1
    print(f"TerrainForge: kit {n} instances of {len(cols)} pieces")


def setup_sites(B, base, root):
    """World Studio: GLB models drawn in BIM Builder for each site (build.json sites[].model, path relative to build.json).
    Each model goes under an empty named Site_<id> placed at the site's leveled centre and rotated by the site's rotation (about Z)."""
    todo = [s for s in B.get("sites", []) if s.get("model")]
    if not todo:
        return
    c_sites = _coll("Sites", root)
    n = 0
    for s in todo:
        path = os.path.normpath(os.path.join(base, s["model"]))
        if not os.path.exists(path):
            print("TerrainForge: missing site model", path)
            continue
        before = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=path)
        except Exception as e:                                       # noqa: BLE001
            print("TerrainForge: could not import", path, e)
            continue
        new = [o for o in bpy.data.objects if o not in before]
        c = s["center"]
        anchor = bpy.data.objects.new("Site_" + str(s["id"]), None)
        anchor.empty_display_type = "ARROWS"
        anchor.empty_display_size = 5.0
        anchor.location = (c["x"], c["y"], c.get("z", s.get("level_z", 0.0)))
        anchor.rotation_euler = (0.0, 0.0, math.radians(s.get("rotation_deg", 0.0) if s.get("shape") == "rect" else 0.0))
        anchor["site"], anchor["kind"], anchor["model"] = str(s["id"]), s.get("kind", ""), s["model"]
        c_sites.objects.link(anchor)
        for o in new:
            for col in list(o.users_collection):
                col.objects.unlink(o)
            c_sites.objects.link(o)
            if o.parent is None or o.parent not in new:
                o.parent = anchor
        n += 1
    print(f"TerrainForge: {n} site model(s) imported")


def main(path=None):
    if path is None:
        path = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.path.join(_here(), "build.json")
    base = os.path.dirname(os.path.abspath(path))
    B = json.load(open(path, encoding="utf-8"))
    world, hm = B["world"], B["heightmap"]
    scn = bpy.context.scene
    scn.unit_settings.system, scn.unit_settings.scale_length = "METRIC", 1.0
    root = _coll(f"TerrainForge_{B.get('project_slug', 'World')}")
    c_terrain, c_water, c_lines, c_sites, c_zones, c_marks = [_coll(n, root) for n in ("Terrain", "Water", "Lines", "Sites", "Scatter_zones", "Markers")]
    land = _terrain_material(B, base) or _material("TF_Land", (0.35, 0.42, 0.25, 1.0))
    water = _water_material(B, base) or _material("TF_Water", (0.05, 0.25, 0.5, 0.7))

    # ── Terrain: Chunks + LOD + HLOD ──
    ch = B["chunks"]
    c_chunks = _coll("Chunks", root)
    c_hlod = _coll("HLOD", root)
    steps = [DECIMATE * l["decimation"] for l in ch["lod"]["levels"]]
    by_id = {c["id"]: c for c in ch["chunks"]}

    def add_chunk(col, row, z, x0, y0, mx, my):
        info = by_id.get(f"{col}_{row}", {})
        cc = _coll(f"Chunk_{col}_{row}", c_chunks)
        for i, lv in enumerate(ch["lod"]["levels"]):
            ob = _terrain(f"Chunk_{col}_{row}_LOD{i}", z, x0, y0, mx, my, world, cc, land, step=steps[i])
            ob["chunk"], ob["lod"], ob["max_distance_m"] = f"{col}_{row}", i, lv["max_distance_m"]
            if i == 0:
                ob["bounds_m"] = json.dumps(info.get("bounds_m", []))
                ob["features"] = json.dumps(info.get("features", {}))
            else:
                ob.hide_viewport = ob.hide_render = True            # show them when needed or drive them with your own LOD system

    if hm["mode"] == "single":
        z = _read_png(os.path.join(base, hm["file_png"]), hm)
        mx, my = hm["meters_per_pixel_x"], hm["meters_per_pixel_y"]
        h, w = z.shape
        T = ch["chunk_size_m"]
        for c in range(ch["chunks_x"]):
            for r in range(ch["chunks_y"]):
                c0, c1 = int(round(c * T / mx)), min(w - 1, int(round((c + 1) * T / mx)))
                r0, r1 = max(0, int(round((world["size_y_m"] - (r + 1) * T) / my))), min(h - 1, int(round((world["size_y_m"] - r * T) / my)))
                if c1 > c0 and r1 > r0:
                    add_chunk(c, r, z[r0:r1 + 1, c0:c1 + 1], c0 * mx, r0 * my, mx, my)
        for hl in ch["hlod"]:                                       # HLOD: groups of chunks at very low resolution
            g, Tg = hl["group_chunks"], T * hl["group_chunks"]
            for gc in range(int(math.ceil(ch["chunks_x"] / g))):
                for gr in range(int(math.ceil(ch["chunks_y"] / g))):
                    c0, c1 = int(round(gc * Tg / mx)), min(w - 1, int(round((gc + 1) * Tg / mx)))
                    r0, r1 = max(0, int(round((world["size_y_m"] - (gr + 1) * Tg) / my))), min(h - 1, int(round((world["size_y_m"] - gr * Tg) / my)))
                    if c1 > c0 and r1 > r0:
                        ob = _terrain(f"HLOD{hl['level']}_{gc}_{gr}", z[r0:r1 + 1, c0:c1 + 1], c0 * mx, r0 * my, mx, my, world, c_hlod, land, step=steps[-1] * 2 ** hl["level"])
                        ob["hlod_level"], ob["group_chunks"], ob["from_distance_m"] = hl["level"], g, hl["from_distance_m"]
                        ob.hide_viewport = ob.hide_render = True
    else:
        mpp = hm["meters_per_pixel"]
        for t in hm["tiles"]:
            add_chunk(t["col"], t["row"], _read_png(os.path.join(base, t["file_png"]), hm), t["x_min_m"], t["y_min_m"], mpp, mpp)
        for hl in hm.get("hlod", []):
            for t in hl["tiles"]:
                ob = _terrain(f"HLOD{hl['level']}_{t['col']}_{t['row']}", _read_png(os.path.join(base, t["file_png"]), hm), t["x_min_m"], t["y_min_m"],
                              hl["meters_per_pixel"], hl["meters_per_pixel"], world, c_hlod, land, step=steps[-1])
                ob["hlod_level"], ob["group_chunks"] = hl["level"], hl["group_chunks"]
                ob.hide_viewport = ob.hide_render = True

    # ── Water ──
    sx, sy, sea = world["size_x_m"], world["size_y_m"], world["sea_level_m"]
    sea_me = bpy.data.meshes.new("Sea")
    sea_me.from_pydata([(0, 0, sea), (sx, 0, sea), (sx, sy, sea), (0, sy, sea)], [], [[0, 1, 2, 3]])
    sea_ob = bpy.data.objects.new("Sea", sea_me)
    sea_me.materials.append(water)
    c_water.objects.link(sea_ob)
    for lk in B["water"]["lakes"] + B["water"]["marshes"]:
        _disc(f"{lk['blender_name']}_water", lk["x"], lk["y"], lk["water_level_m"], lk["radius_m"], c_water, water)
    for wf in B["water"]["waterfalls"]:
        _empty(wf["blender_name"], (wf["x_m"], wf["y_m"], 0.0), c_marks, {"height_m": wf["height_m"], "river": wf["river_blender_name"]}, 5.0, "SINGLE_ARROW")

    # ── Lines: flat ribbons (real width) + thin centerline curves ──
    road_mat = _material("TF_Road", (0.16, 0.16, 0.17, 1.0))
    road_pbr = {}                                                # one shader per road surface color
    for ln in B["features"]["lines"]:
        pl, nm = ln["polyline"], ln["blender_name"]
        widths = ln.get("width_profile_m") or [ln["width_m"]] * len(pl)
        props = {"kind": ln["kind"], "width_m": ln["width_m"], "depth_m": ln["depth_m"]}
        if ln["kind"] == "river":
            pts = [(p[0], p[1], z) for p, z in zip(pl, ln["water_z"])]
            props.update({"bed_z_first": ln["bed_z"][0], "bed_z_last": ln["bed_z"][-1]})
            _poly_curve(nm + "_path", pts, c_lines, props=props)
            _ribbon(nm + "_water", pts, widths, c_lines, water, props)
        elif ln["kind"] == "road":
            z = ln.get("road_z") or [p[2] for p in pl]
            pts = [(p[0], p[1], zz + 0.12) for p, zz in zip(pl, z)]
            _poly_curve(nm + "_path", pts, c_lines, props=props)
            rmat = None
            if B.get("road_maps"):
                col = next((m["color"] for m in B.get("materials", []) if m["id"] == (ln.get("materials") or {}).get("main")), "#4a4742")
                rmat = road_pbr.setdefault(col, _road_material(B, col))
            if rmat is not None:                                  # wider ribbon (road + dusty edge) with road UVs for the shader
                pad = 2.0 * 1.7 * float(B["road_maps"]["settings"]["dust_width_m"])
                _ribbon(nm + "_surface", pts, [w_ + pad for w_ in widths], c_lines, rmat, props, road_hw=widths)
            else:
                _ribbon(nm + "_surface", pts, widths, c_lines, road_mat, props)
        else:
            _poly_curve(nm + "_path", [(p[0], p[1], p[2] + 0.2) for p in pl], c_lines, props=props)

    # ── Sites ──
    for s in B["sites"]:
        c = s["center"]
        _empty(s["blender_name"], (c["x"], c["y"], c["z"]), c_sites,
               {"kind": s["kind"], "name": s["blender_name"], "level_z": s["level_z"], "area_m2": s["pad_area_m2"], "cut_m": s["cut_m"], "fill_m": s["fill_m"]},
               max(s["diameter_m"], s["width_m"]) / 2, "CIRCLE" if s["shape"] == "circle" else "CUBE")
        _poly_curve(s["blender_name"] + "_pad", [tuple(p) for p in s["outline"]], c_sites, closed=True, props={"kind": s["kind"]})

    # ── Caves + scatter zones + masks ──
    for m in B["markers"]:
        _empty(m["blender_name"], (m["x"], m["y"], 0.0), c_marks, {"note": m["note"]}, 8.0, "ARROWS")
    for z in B["scatter_zones"]:
        _poly_curve(z["blender_name"], [tuple(p) for p in z["polygon"]], c_zones, closed=True,
                    props={"layer": z["layer"], "density": z["density"], "mask": z["mask"] or "", "affects_height": z["affects_height"]})
    for layer, mk in B["masks"].items():
        img = bpy.data.images.load(os.path.join(base, mk["file"]), check_existing=False)
        img.colorspace_settings.name = "Non-Color"
        img.name = f"tf_mask_{layer}"
        img.use_fake_user = True
    # ── Gameplay: POIs, expected player route, building lots ──
    c_poi, c_route, c_lots = _coll("Gameplay_POI", root), _coll("Gameplay_ExpectedRoute", root), _coll("Building_lots", root)
    style = {"player_start": ("ARROWS", 6.0), "landmark": ("SINGLE_ARROW", 8.0), "boss": ("SPHERE", 6.0), "story": ("CUBE", 5.0),
             "quest": ("PLAIN_AXES", 5.0), "dungeon": ("CONE", 6.0), "resource": ("PLAIN_AXES", 4.0), "fast_travel": ("CIRCLE", 6.0), "poi": ("PLAIN_AXES", 5.0)}
    for p in B["gameplay"]["pois"]:
        c = p["center"]
        z0 = p.get("arena_level_z", c["z"])
        kind, size = style.get(p["kind"], ("PLAIN_AXES", 5.0))
        props = {k: p[k] for k in ("kind", "order", "difficulty", "dwell_min", "landmark_height_m", "notes")}
        props["level_range"] = json.dumps(p["level_range"])
        _empty(p["blender_name"], (c["x"], c["y"], z0), c_poi, props, max(size, p["radius_m"] * 0.1), kind)
        if p["radius_m"] > 0:
            n = 48
            ring = [(c["x"] + p["radius_m"] * math.cos(2 * math.pi * i / n), c["y"] + p["radius_m"] * math.sin(2 * math.pi * i / n), z0 + 0.5) for i in range(n)]
            _poly_curve(p["blender_name"] + "_zone", ring, c_poi, closed=True, props={"kind": p["kind"], "radius_m": p["radius_m"]})
        if p["landmark_height_m"] > 0:
            _poly_curve(p["blender_name"] + "_landmark", [(c["x"], c["y"], z0), (c["x"], c["y"], z0 + p["landmark_height_m"])], c_poi, bevel=1.0, props={"kind": p["kind"]})
    er = B["gameplay"].get("expected_route")
    if er:
        for i, leg in enumerate(er["legs"]):
            if leg.get("reachable") and len(leg["points"]) > 1:
                _poly_curve(leg["blender_name"], [(q[0], q[1], q[2] + 0.5) for q in leg["points"]], c_route, bevel=0.6,
                            props={"from": leg["from_name"], "to": leg["to_name"], "distance_m": leg["distance_m"], "walk_s": leg["walk_s"], "climb_m": leg["climb_m"], "max_slope_deg": leg["max_slope_deg"]})
        scn["tf_expected_total_s"] = er["totals"]["total_s"]
    count = 0
    for s in B["sites"]:
        for lot in s.get("building_lots", []):
            if count >= 3000:
                break
            ob = _empty(f"{s['blender_name']}_lot_{count:03d}", (lot["x_m"], lot["y_m"], lot["z_m"]), c_lots, {"site": s["blender_name"], "main": lot["main"]}, 1.0, "CUBE")
            ob.scale = (lot["width_m"] / 2, lot["length_m"] / 2, 3.0)
            ob.rotation_euler.z = math.radians(lot["rotation_deg"])
            count += 1
    setup_kit(B, base, root)
    setup_sites(B, base, root)
    setup_scatter(B, base, root)
    setup_atmosphere(B, root)
    print(f"TerrainForge: imported '{B['project']}' ({hm['mode']}), {len(B['sites'])} sites, {len(B['features']['lines'])} lines, {len(B['masks'])} masks, {len(B['chunks']['chunks'])} chunks")


if __name__ == "__main__":
    main()
