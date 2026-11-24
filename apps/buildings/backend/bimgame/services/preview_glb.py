"""Fast in-process GLB writer for the 3D preview (no Blender start-up).

The preview needs only flat-shaded coloured meshes, so we convert the cached per-element numpy meshes straight to a
GLB: Z-up plan coordinates -> glTF Y-up (x, z, -y), pivot = base centre of the whole model. The full-quality
asset pipeline (UV, collision, LOD, textures, FBX ...) still goes through Blender.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from ..geometry.mesh import MeshData


def _lin(c: str) -> list[float]:
    rgb = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in rgb]


def write_preview_glb(parts: dict, gdir: Path, materials: list[dict], out_path: Path) -> dict:
    mats = {m["id"]: m for m in materials}
    loaded = []
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for eid, info in parts.items():
        mesh, slots = MeshData.load(gdir / info["file"])
        if not len(mesh.f):
            continue
        loaded.append((eid, info, mesh, slots))
        lo, hi = np.minimum(lo, mesh.v.min(0)), np.maximum(hi, mesh.v.max(0))
    if not loaded:
        raise ValueError("no meshes to preview")
    origin = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])

    bin_parts: list[bytes] = []
    views: list[dict] = []
    accessors: list[dict] = []
    gl_materials: list[dict] = []
    mat_index: dict[str | None, int] = {}
    nodes: list[dict] = []
    meshes_json: list[dict] = []
    tris_total = 0
    offset = 0

    def add_buffer(arr: np.ndarray, count: int, atype: str, bounds: tuple | None) -> int:
        nonlocal offset
        raw = np.ascontiguousarray(arr, dtype="<f4").tobytes()
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": 34962})
        acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": count, "type": atype}
        if bounds:
            acc["min"], acc["max"] = [float(x) for x in bounds[0]], [float(x) for x in bounds[1]]
        accessors.append(acc)
        bin_parts.append(raw)
        offset += len(raw)
        return len(accessors) - 1

    def material(mid: str | None) -> int:
        if mid not in mat_index:
            d = mats.get(mid) if mid else None
            gl_materials.append({"name": (d or {}).get("name", "default"), "pbrMetallicRoughness": {
                "baseColorFactor": [*_lin((d or {}).get("color", "#b8b2a7")), 1.0],
                "metallicFactor": float((d or {}).get("metallic", 0.0)), "roughnessFactor": float((d or {}).get("roughness", 0.8))}})
            mat_index[mid] = len(gl_materials) - 1
        return mat_index[mid]

    # Z-up (x, y, z) -> glTF Y-up (x, z, -y): a proper rotation, so triangle winding stays outward.
    def conv(v: np.ndarray) -> np.ndarray:
        w = v - origin
        return np.stack([w[:, 0], w[:, 2], -w[:, 1]], 1)

    for eid, info, mesh, slots in loaded:
        v = conv(mesh.v.astype(np.float64))
        prims = []
        for s in np.unique(mesh.slot):
            f = mesh.f[mesh.slot == s]
            a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
            n = np.cross(b - a, c - a)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            ln[ln == 0] = 1.0
            n = n / ln
            pos = np.stack([a, b, c], 1).reshape(-1, 3)
            nrm = np.repeat(n, 3, axis=0)
            mid = slots[int(s)] if int(s) < len(slots) else None
            prims.append({"attributes": {"POSITION": add_buffer(pos, len(pos), "VEC3", (pos.min(0), pos.max(0))),
                                         "NORMAL": add_buffer(nrm, len(nrm), "VEC3", None)},
                          "material": material(mid or None), "mode": 4})
            tris_total += len(f)
        meshes_json.append({"name": eid, "primitives": prims})
        nodes.append({"name": f"{info.get('type', 'part')}_{eid}", "mesh": len(meshes_json) - 1,
                      "extras": {"bim_id": eid, "bim_type": info.get("type"), "bim_level": info.get("level")}})

    # أعمدة الإنارة: ضوء نقطي KHR_lights_punctual (الموضع بنفس تحويل المحاور)
    lights_json: list[dict] = []
    for eid, info, _m, _s in loaded:
        lt = info.get("light")
        if not lt:
            continue
        pos = conv(np.array([lt["pos"]], np.float64))[0]
        lights_json.append({"type": "point", "color": [round(int(lt["color"][i:i + 2], 16) / 255, 4) for i in (1, 3, 5)],
                            "intensity": float(lt["intensity"]), "range": float(lt["range"]), "name": f"light_{eid}"})
        nodes.append({"name": f"light_{eid}", "translation": [round(float(x), 5) for x in pos],
                      "extensions": {"KHR_lights_punctual": {"light": len(lights_json) - 1}}})

    gltf = {"asset": {"version": "2.0", "generator": "BIM Builder fast preview"},
            "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes_json,
            "materials": gl_materials, "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": offset}]}
    if lights_json:
        gltf["extensionsUsed"] = ["KHR_lights_punctual"]
        gltf["extensions"] = {"KHR_lights_punctual": {"lights": lights_json}}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob = b"".join(bin_parts)
    blob += b"\0" * (-len(blob) % 4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<I4s", len(js), b"JSON") + js)
        f.write(struct.pack("<I4s", len(blob), b"BIN\0") + blob)
    tmp.replace(out_path)
    size = (hi - lo).tolist()
    return {"outputs": [str(out_path)], "objects": len(nodes), "triangles": tris_total, "bbox_size": [round(x, 3) for x in size]}
