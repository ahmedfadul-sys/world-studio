"""Material Lab: build a procedural PBR material with Blender's shader nodes and bake it to tileable PNG maps.

  python matlab.py job.json                          (bpy module interpreter)
  blender -b --factory-startup -P matlab.py -- job.json

job: {"preset", "params": {...}, "out_dir", "stem", "result_path"}
Writes <stem>_c.png (base colour, sRGB), <stem>_n.png (tangent-space normal, OpenGL / glTF convention) and
<stem>_r.png (glTF metallic-roughness map: G = roughness, B = metallic).  Everything is seamless: noise is sampled on a
torus (4D noise on cos/sin of the UV) and bricks / tiles use whole numbers of cells per texture tile.
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

import bpy  # must come first when running as the pip `bpy` module
import numpy as np

TAU = 2 * math.pi


def _argv() -> list[str]:
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else a[1:]


def hex_lin(h: str) -> tuple[float, float, float, float]:
    c = h.lstrip("#")
    rgb = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return (*[((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in rgb], 1.0)


class N:
    """Tiny node-graph helper: every method returns an output socket (or a plain number)."""

    def __init__(self, tree):
        self.t, self.nodes, self.links = tree, tree.nodes, tree.links

    def _put(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.links.new(v, sock)
        elif isinstance(v, (tuple, list)):
            sock.default_value = tuple(v) if len(v) == 4 else (*v, 1.0)
        else:
            sock.default_value = v

    def new(self, typ, **props):
        n = self.nodes.new(typ)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math(self, op, a, b=None, c=None):
        n = self.new("ShaderNodeMath", operation=op)
        self._put(n.inputs[0], a)
        if b is not None:
            self._put(n.inputs[1], b)
        if c is not None:
            self._put(n.inputs[2], c)
        return n.outputs[0]

    def add(self, a, b): return self.math("ADD", a, b)
    def sub(self, a, b): return self.math("SUBTRACT", a, b)
    def mul(self, a, b): return self.math("MULTIPLY", a, b)
    def pw(self, a, b): return self.math("POWER", a, b)
    def clamp(self, a): return self.math("MINIMUM", self.math("MAXIMUM", a, 0.0), 1.0)

    def lerp(self, fac, a, b):
        """float mix"""
        n = self.new("ShaderNodeMix", data_type="FLOAT")
        self._put(n.inputs[0], fac); self._put(n.inputs[2], a); self._put(n.inputs[3], b)
        return n.outputs[0]

    def cmix(self, fac, a, b, blend="MIX"):
        """colour mix"""
        n = self.new("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self._put(n.inputs[0], fac); self._put(n.inputs[6], a); self._put(n.inputs[7], b)
        return n.outputs[2]

    def ramp(self, fac, stops):
        n = self.new("ShaderNodeValToRGB")
        el = n.color_ramp.elements
        while len(el) > 2:
            el.remove(el[-1])
        el[0].position, el[0].color = stops[0][0], stops[0][1]
        el[1].position, el[1].color = stops[-1][0], stops[-1][1]
        for pos, col in stops[1:-1]:
            e = el.new(pos)
            e.color = col
        self._put(n.inputs[0], fac)
        return n.outputs["Color"]

    def fram(self, fac, a, b):
        """float -> float remap through a 2-stop ramp (lo..hi)"""
        n = self.new("ShaderNodeMapRange")
        n.clamp = True
        self._put(n.inputs[0], fac); n.inputs[1].default_value = 0.0; n.inputs[2].default_value = 1.0
        self._put(n.inputs[3], a); self._put(n.inputs[4], b)
        return n.outputs[0]

    # -- seamless texture coordinates and noise ------------------------------------------------
    def uv(self):
        if not hasattr(self, "_uv"):
            self._uv = self.new("ShaderNodeTexCoord").outputs["UV"]
        return self._uv

    def uvc(self):
        sep = self.new("ShaderNodeSeparateXYZ")
        self.links.new(self.uv(), sep.inputs[0])
        return sep.outputs[0], sep.outputs[1]

    def torus(self, fx, fy, seed=0.0):
        """4D coordinates that wrap exactly at the tile border. fx / fy = how fast features vary along u / v."""
        sep = self.new("ShaderNodeSeparateXYZ")
        self.links.new(self.uv(), sep.inputs[0])
        a, b = self.mul(sep.outputs[0], TAU), self.mul(sep.outputs[1], TAU)
        comb = self.new("ShaderNodeCombineXYZ")
        self.links.new(self.mul(self.math("COSINE", a), fx), comb.inputs[0])
        self.links.new(self.mul(self.math("SINE", a), fx), comb.inputs[1])
        self.links.new(self.mul(self.math("COSINE", b), fy), comb.inputs[2])
        w = self.add(self.mul(self.math("SINE", b), fy), seed * 17.31 + 3.7)
        return comb.outputs[0], w

    def noise(self, fx, fy=None, seed=0.0, detail=4.0, rough=0.5, distort=0.0):
        vec, w = self.torus(fx, fx if fy is None else fy, seed)
        n = self.new("ShaderNodeTexNoise", noise_dimensions="4D")
        self.links.new(vec, n.inputs["Vector"]); self.links.new(w, n.inputs["W"])
        n.inputs["Scale"].default_value = 1.0
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = rough
        n.inputs["Distortion"].default_value = distort
        return n.outputs["Fac"]

    def voronoi(self, f, seed=0.0, rand=1.0, out="Distance"):
        vec, w = self.torus(f, f, seed)
        n = self.new("ShaderNodeTexVoronoi", voronoi_dimensions="4D", feature="F1")
        self.links.new(vec, n.inputs["Vector"]); self.links.new(w, n.inputs["W"])
        n.inputs["Scale"].default_value = 1.0
        n.inputs["Randomness"].default_value = rand
        return n.outputs[out]

    def brick(self, c1, c2, mortar, cols, rows, msize, msmooth, offset=0.5, freq=2, bias=0.0):
        n = self.new("ShaderNodeTexBrick", offset=offset, offset_frequency=freq, squash=1.0, squash_frequency=2)
        self.links.new(self.uv(), n.inputs["Vector"])
        self._put(n.inputs["Color1"], c1); self._put(n.inputs["Color2"], c2); self._put(n.inputs["Mortar"], mortar)
        n.inputs["Scale"].default_value = 1.0
        n.inputs["Mortar Size"].default_value = msize
        n.inputs["Mortar Smooth"].default_value = msmooth
        n.inputs["Bias"].default_value = bias
        n.inputs["Brick Width"].default_value = 1.0 / cols
        n.inputs["Row Height"].default_value = 1.0 / rows
        # Blender's Fac is 1 on the mortar; return the opposite: 1 on the brick body, 0 on the joint
        return n.outputs["Color"], self.sub(1.0, n.outputs["Fac"])


# ------------------------------------------------------------------------------------------------
# presets: each returns (colour, roughness, height) sockets.  P = parameter dict
# ------------------------------------------------------------------------------------------------
def p_brick(g: N, P):
    cols = max(2, int(P["scale"]))
    rows = 14
    c1, c2, mortar = hex_lin(P["color1"]), hex_lin(P["color2"]), hex_lin(P["joint"])
    col, fac = g.brick(c1, c2, mortar, cols, rows, 0.0095, 0.25)
    n1 = g.noise(1.4, 1.4, P["seed"], 6, 0.55)
    n2 = g.noise(9.0, 9.0, P["seed"] + 1, 3, 0.6)
    v = P["variation"]
    col = g.cmix(g.mul(g.fram(n1, 0.0, 0.55), v), col, hex_lin("#1b140f"))        # soot / weathering
    col = g.cmix(g.mul(g.fram(n2, 0.0, 0.25), v), col, hex_lin("#d8cfc2"))          # lime bloom
    rough = g.add(g.fram(fac, 0.95, 0.0), g.mul(n2, 0.15))
    rough = g.lerp(0.5, g.fram(fac, 1.0, P["roughness"]), g.clamp(g.add(rough, 0.0)))
    height = g.add(g.mul(fac, 0.8), g.mul(n2, 0.2))
    return col, rough, height


def p_concrete(g: N, P):
    s = P["seed"]
    low = g.noise(2.2, 2.2, s, 5, 0.55, 0.4)
    mid = g.noise(12.0, 12.0, s + 1, 4, 0.6)
    pores = g.voronoi(45.0, s + 2)
    v = P["variation"]
    base = g.cmix(g.fram(low, 0.0, 1.0), hex_lin(P["color1"]), hex_lin(P["color2"]))
    col = g.cmix(g.mul(g.fram(mid, 0.0, 0.35), v), base, hex_lin("#2b2b2b"))
    pit = g.fram(pores, 1.0, 0.0)               # 1 inside tiny cells
    pit = g.math("GREATER_THAN", pit, 0.82)
    col = g.cmix(g.mul(pit, 0.5 * v + 0.15), col, hex_lin("#1c1c1c"))
    rough = g.lerp(0.6, g.fram(mid, P["roughness"] - 0.1, min(1.0, P["roughness"] + 0.1)), g.fram(low, P["roughness"] - 0.05, min(1.0, P["roughness"] + 0.05)))
    height = g.add(g.mul(mid, 0.55), g.mul(g.fram(pores, 0.45, 0.0), 0.45))
    return col, rough, height


def p_plaster(g: N, P):
    s = P["seed"]
    low = g.noise(1.6, 1.6, s, 3, 0.5, 0.3)
    fine = g.noise(40.0, 40.0, s + 1, 5, 0.65)
    v = P["variation"]
    col = g.cmix(g.fram(low, 0.0, v), hex_lin(P["color1"]), hex_lin(P["color2"]))
    col = g.cmix(g.mul(g.fram(fine, 0.0, 0.12), v), col, hex_lin("#ffffff"))
    rough = g.fram(fine, max(0.0, P["roughness"] - 0.08), min(1.0, P["roughness"] + 0.08))
    height = g.add(g.mul(fine, 0.8), g.mul(low, 0.2))
    return col, rough, height


def p_wood(g: N, P):
    cols, rows = 1, max(2, int(P["scale"]) * 2)
    light, darkc, gap = hex_lin(P["color1"]), hex_lin(P["color2"]), hex_lin(P["joint"])
    plank_col, fac = g.brick(light, darkc, gap, cols, rows, 0.012, 0.05)
    s = P["seed"]
    # grain: stretched along u (low fx, high fy), warped by a second noise
    warp = g.noise(0.8, 6.0, s + 5, 3, 0.5)
    grain = g.noise(0.7, 26.0, s, 6, 0.65, 1.2)
    rings = g.math("PINGPONG", g.mul(g.add(grain, g.mul(warp, 0.6)), 7.0), 1.0)
    pore = g.noise(2.0, 160.0, s + 2, 2, 0.5)
    v = P["variation"]
    col = g.cmix(g.mul(g.fram(rings, 0.0, 1.0), 0.45 + 0.55 * v), plank_col, (0.62, 0.55, 0.48), "MULTIPLY")   # darker grain lines
    col = g.cmix(g.mul(g.fram(pore, 0.0, 0.3), v), col, (0.45, 0.4, 0.35), "MULTIPLY")                         # open pores
    col = g.cmix(g.fram(fac, 1.0, 0.0), col, gap)                                                              # gaps between planks
    rough = g.add(g.fram(pore, P["roughness"] - 0.12, P["roughness"] + 0.1), g.mul(g.fram(fac, 0.0, 0.2), 1.0))
    height = g.add(g.mul(fac, 0.55), g.mul(g.add(g.mul(pore, 0.5), g.mul(rings, 0.5)), 0.45))
    return col, g.clamp(rough), height


def p_tile(g: N, P):
    n = max(2, int(P["scale"]))
    t1, t2, grout = hex_lin(P["color1"]), hex_lin(P["color2"]), hex_lin(P["joint"])
    tcol, fac = g.brick(t1, t2, grout, n, n if n % 2 == 0 else n + 1, 0.025, 0.06, offset=0.0, freq=1)
    s = P["seed"]
    n1 = g.noise(3.0, 3.0, s, 3, 0.5)
    fine = g.noise(30.0, 30.0, s + 1, 4, 0.6)
    v = P["variation"]
    col = g.cmix(g.mul(g.fram(n1, 0.0, 0.25), v), tcol, hex_lin("#ffffff"))
    col = g.cmix(g.fram(fac, 1.0, 0.0), col, grout)
    rough = g.lerp(g.fram(fac, 1.0, 0.0), g.fram(fine, P["roughness"] * 0.8, P["roughness"] * 1.2), 0.85)
    height = g.mul(fac, 1.0)
    return col, g.clamp(rough), height


def p_marble(g: N, P):
    s = P["seed"]
    warp = g.noise(1.3, 1.3, s, 5, 0.5, 0.5)
    fine = g.noise(6.0, 6.0, s + 2, 4, 0.55)
    low = g.noise(1.1, 1.1, s + 3, 3, 0.5)
    u, v_ = g.uvc()
    ph1 = g.add(g.mul(g.add(g.mul(u, 2.0), g.mul(v_, 1.0)), TAU), g.mul(warp, 9.0))      # integer weights: wraps at the tile border
    ph2 = g.add(g.mul(g.add(g.mul(u, -1.0), g.mul(v_, 3.0)), TAU), g.mul(fine, 5.0))
    vein1 = g.pw(g.sub(1.0, g.math("ABSOLUTE", g.math("SINE", ph1))), 18.0)
    vein2 = g.mul(g.pw(g.sub(1.0, g.math("ABSOLUTE", g.math("SINE", ph2))), 40.0), 0.6)
    veins = g.clamp(g.add(vein1, vein2))
    v = P["variation"]
    base = g.cmix(g.fram(low, 0.0, 1.0), hex_lin(P["color1"]), hex_lin(P["color2"]))
    col = g.cmix(g.mul(veins, 0.25 + 0.75 * v), base, hex_lin(P["joint"]))
    rough = g.fram(g.add(fine, g.mul(veins, 0.5)), max(0.0, P["roughness"] - 0.04), min(1.0, P["roughness"] + 0.08))
    height = g.mul(fine, 0.1)
    return col, rough, height


def p_stone(g: N, P):
    cols, rows = max(2, int(P["scale"])), 8
    c1, c2, mortar = hex_lin(P["color1"]), hex_lin(P["color2"]), hex_lin(P["joint"])
    col, fac = g.brick(c1, c2, mortar, cols, rows, 0.018, 0.3, bias=0.25)
    s = P["seed"]
    gr = g.voronoi(26.0, s)
    nz = g.noise(5.0, 5.0, s + 1, 6, 0.6)
    v = P["variation"]
    col = g.cmix(g.mul(g.fram(nz, 0.0, 0.5), v), col, hex_lin("#2a2824"))
    col = g.cmix(g.mul(g.fram(gr, 0.0, 0.25), v), col, hex_lin("#e6e0d4"))
    rough = g.lerp(0.5, g.fram(fac, 1.0, P["roughness"]), g.fram(nz, P["roughness"] - 0.1, min(1.0, P["roughness"] + 0.1)))
    height = g.add(g.mul(fac, 0.65), g.add(g.mul(nz, 0.25), g.mul(g.fram(gr, 0.0, 1.0), 0.1)))
    return col, g.clamp(rough), height


def p_metal(g: N, P):
    s = P["seed"]
    streak = g.noise(1.0, 150.0, s, 4, 0.6)                              # brushed along u
    fine = g.noise(2.5, 320.0, s + 1, 2, 0.5)
    low = g.noise(1.5, 1.5, s + 2, 3, 0.5)
    v = P["variation"]
    col = g.cmix(g.mul(g.fram(streak, 0.0, 0.5), v), hex_lin(P["color1"]), hex_lin(P["color2"]))
    col = g.cmix(g.mul(g.fram(low, 0.0, 0.25), v), col, hex_lin("#ffffff"))
    rough = g.fram(g.add(g.mul(streak, 0.6), g.mul(fine, 0.4)), max(0.0, P["roughness"] - 0.12), min(1.0, P["roughness"] + 0.18))
    height = g.mul(g.add(g.mul(streak, 0.5), g.mul(fine, 0.5)), 0.4)
    return col, rough, height


def p_asphalt(g: N, P):
    s = P["seed"]
    gravel = g.voronoi(70.0, s)
    nz = g.noise(10.0, 10.0, s + 1, 6, 0.7)
    low = g.noise(2.0, 2.0, s + 2, 3, 0.5)
    v = P["variation"]
    base = g.cmix(g.fram(nz, 0.0, 1.0), hex_lin(P["color1"]), hex_lin(P["color2"]))
    col = g.cmix(g.mul(g.fram(gravel, 0.9, 0.0), 0.6 * v + 0.15), base, hex_lin("#7d7a75"))
    col = g.cmix(g.mul(g.fram(low, 0.0, 0.35), v), col, hex_lin("#0d0d0d"))
    rough = g.fram(nz, P["roughness"] - 0.1, min(1.0, P["roughness"] + 0.08))
    height = g.add(g.mul(g.fram(gravel, 1.0, 0.0), 0.55), g.mul(nz, 0.45))
    return col, rough, height


PRESETS = {
    "brick": p_brick, "concrete": p_concrete, "plaster": p_plaster, "wood": p_wood, "tile": p_tile,
    "marble": p_marble, "stone": p_stone, "metal": p_metal, "asphalt": p_asphalt,
}


# ------------------------------------------------------------------------------------------------
def make_scene(size: int):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 1
    sc.cycles.use_denoising = False
    sc.render.bake.margin = 0
    sc.render.bake.use_clear = True
    bpy.ops.mesh.primitive_plane_add(size=1.0)
    obj = bpy.context.active_object
    mat = bpy.data.materials.new("LAB")
    obj.data.materials.append(mat)
    mat.use_nodes = True
    return obj, mat


def bake(obj, mat, sock, size: int, tag: str) -> np.ndarray:
    """Bake any socket (colour or float) to a float image via an Emission shader; returns (size, size, 3) float array."""
    tree = mat.node_tree
    nodes, links = tree.nodes, tree.links
    for n in list(nodes):
        if n.type in ("OUTPUT_MATERIAL", "EMISSION", "TEX_IMAGE"):
            nodes.remove(n)
    out = nodes.new("ShaderNodeOutputMaterial")
    em = nodes.new("ShaderNodeEmission")
    links.new(sock, em.inputs["Color"])
    links.new(em.outputs[0], out.inputs["Surface"])
    img = bpy.data.images.new(f"bake_{tag}", size, size, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    tn = nodes.new("ShaderNodeTexImage")
    tn.image = img
    nodes.active = tn
    for o in bpy.context.view_layer.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="EMIT")
    px = np.empty(size * size * 4, np.float32)
    img.pixels.foreach_get(px)
    arr = px.reshape(size, size, 4)[:, :, :3].copy()
    bpy.data.images.remove(img)
    return arr


def srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def normal_from_height(h: np.ndarray, strength: float) -> np.ndarray:
    """Tangent-space normal map (OpenGL / glTF: +Y = up in v) from a height map, wrapping at the borders so it tiles."""
    size = h.shape[0]
    lo, hi = np.percentile(h, [1, 99])                      # same bump scale for every preset
    h = np.clip((h - lo) / max(hi - lo, 1e-4), 0.0, 1.0)
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5          # rows run along +v (Blender images are bottom-up)
    k = strength * size / 160.0
    n = np.stack([-dx * k, -dy * k, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


def save_png(arr: np.ndarray, path: Path) -> None:
    size = arr.shape[0]
    img = bpy.data.images.new(path.stem, size, size, alpha=False)
    img.colorspace_settings.name = "Non-Color"      # raw values: we already encoded them
    rgba = np.ones((size, size, 4), np.float32)
    rgba[:, :, :3] = np.clip(arr, 0, 1)
    img.pixels.foreach_set(rgba.reshape(-1))
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def run(job: dict) -> dict:
    t0 = time.time()
    P = dict(job["params"])
    size = int(P.get("resolution", 1024))
    preset = job["preset"]
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}'")
    out_dir = Path(job["out_dir"]); out_dir.mkdir(parents=True, exist_ok=True)
    obj, mat = make_scene(size)
    g = N(mat.node_tree)
    col, rough, height = PRESETS[preset](g, P)
    c = srgb(bake(obj, mat, col, size, "c"))
    r = bake(obj, mat, rough, size, "r")[:, :, 0]
    h = bake(obj, mat, height, size, "h")[:, :, 0]
    stem = job["stem"]
    nrm = normal_from_height(h, float(P["bump"]))
    orm = np.stack([np.ones_like(r), np.clip(r, 0.02, 1.0), np.full_like(r, float(P.get("metallic", 0.0)))], -1)
    files = {"texture": f"{stem}_c.png", "normal_texture": f"{stem}_n.png", "rough_texture": f"{stem}_r.png"}
    save_png(c, out_dir / files["texture"])
    save_png(nrm, out_dir / files["normal_texture"])
    save_png(orm, out_dir / files["rough_texture"])
    return {"files": files, "size": size, "seconds": round(time.time() - t0, 2),
            "stats": {"colour_mean": [round(float(x), 3) for x in c.reshape(-1, 3).mean(0)], "rough_mean": round(float(r.mean()), 3),
                      "height_range": [round(float(h.min()), 3), round(float(h.max()), 3)]}}


def main() -> None:
    job = json.loads(Path(_argv()[0]).read_text())
    try:
        res = run(job)
        res["ok"] = True
        code = 0
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": {"what": str(exc), "where": "blender_scripts/matlab.py", "trace": traceback.format_exc()[-3000:]}}
        code = 2
    Path(job["result_path"]).write_text(json.dumps(res))
    sys.exit(code)


if __name__ == "__main__":
    main()
