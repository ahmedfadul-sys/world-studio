"""Validate exported files so a build is never reported successful on bad output."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from ..utils.errors import BuildError


def _fail(path: Path, why: str) -> BuildError:
    return BuildError("Export validation failed", f"export_validate:{path.name}", why,
                      "Rebuild; if it persists check the Blender log and the project geometry")


def read_glb(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 20:
        raise _fail(path, "file shorter than a GLB header")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise _fail(path, "missing 'glTF' magic")
    if version != 2:
        raise _fail(path, f"unsupported glTF version {version}")
    if length != len(data):
        raise _fail(path, f"header length {length} != file size {len(data)}")
    clen, ctype = struct.unpack_from("<II", data, 12)
    if ctype != 0x4E4F534A:
        raise _fail(path, "first chunk is not JSON")
    try:
        return json.loads(data[20:20 + clen])
    except ValueError as exc:
        raise _fail(path, f"JSON chunk invalid: {exc}") from exc


def summarize_gltf(doc: dict) -> dict:
    nodes = doc.get("nodes", [])
    names = [n.get("name", "") for n in nodes]
    return {
        "nodes": len(nodes), "meshes": len(doc.get("meshes", [])), "materials": len(doc.get("materials", [])),
        "node_names": names,
        "collision_nodes": [n for n in names if n.endswith(("-colonly", "-convcolonly"))],
        "lod_nodes": [n for n in names if "_LOD" in n],
    }


def validate_outputs(outputs: list[str], expect_visual: int, expect_collision: int | None = None) -> dict:
    """Raise BuildError if any output is missing/empty/invalid. Returns a summary."""
    if not outputs:
        raise BuildError("No output files were produced", "export_validate", "worker returned an empty file list", "Rebuild")
    summary: dict = {"files": []}
    for o in outputs:
        p = Path(o)
        if not p.exists() or p.stat().st_size == 0:
            raise _fail(p, "file is missing or empty")
        summary["files"].append({"name": p.name, "bytes": p.stat().st_size})
        ext = p.suffix.lower()
        if ext == ".glb":
            s = summarize_gltf(read_glb(p))
        elif ext == ".gltf":
            try:
                s = summarize_gltf(json.loads(p.read_text()))
            except ValueError as exc:
                raise _fail(p, f"invalid JSON: {exc}") from exc
            for b in (json.loads(p.read_text()).get("buffers") or []):
                if "uri" in b and not (p.parent / b["uri"]).exists():
                    raise _fail(p, f"external buffer {b['uri']} missing")
        elif ext == ".fbx":
            if not p.read_bytes()[:20].startswith(b"Kaydara FBX Binary"):
                raise _fail(p, "not a binary FBX file")
            continue
        else:
            continue
        if s["meshes"] == 0:
            raise _fail(p, "contains no meshes")
        mesh_nodes = s["nodes"]
        if mesh_nodes < expect_visual:
            raise _fail(p, f"expected at least {expect_visual} nodes, found {mesh_nodes}")
        if expect_collision is not None and len(s["collision_nodes"]) != expect_collision:
            raise _fail(p, f"expected {expect_collision} collision nodes, found {len(s['collision_nodes'])}")
        summary.update({k: v for k, v in s.items() if k != "node_names"})
        summary["node_names_sample"] = s["node_names"][:12]
    return summary
