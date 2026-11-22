"""Build orchestration: validate -> incremental geometry -> Blender -> verify outputs -> record."""
from __future__ import annotations

import json
import os
import shutil
import logging
import re
import threading
import time
from pathlib import Path

from ..blender.runner import run_blender
from ..config import Settings
from ..geometry.cache import build_geometry, load_manifest
from ..geometry.validate import validate_project
from ..schema import BuildRecord, ExportSettings, MaterialLab, Project, SceneOptions
from ..utils.errors import AppError, BuildError
from ..utils.memprof import measure
from .godot_scene import write_scene
from .preview_glb import write_preview_glb
from .export_validate import validate_outputs
from .storage import ProjectStore

log = logging.getLogger("bimgame.build")

FULL = ["materials", "cleanup", "optimize", "uv", "collision", "lod", "pivot", "export"]
KIND_STEPS: dict[str, list[str]] = {
    "build": FULL,
    "export": FULL,
    "scene": FULL,
    "preview": ["materials", "cleanup", "pivot", "export"],
    "optimize": ["materials", "cleanup", "optimize", "pivot", "export"],
    "collision": ["materials", "cleanup", "collision", "pivot", "export"],
    "lod": ["materials", "cleanup", "lod", "pivot", "export"],
    "uv": ["materials", "cleanup", "uv", "pivot", "export"],
}
KINDS = set(KIND_STEPS) | {"geometry", "matlab"}


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "project"


class BuildService:
    def __init__(self, store: ProjectStore, settings: Settings):
        self.store, self.s = store, settings
        self._gauge = threading.Lock()
        self.active = 0
        self.max_active = 0  # highest number of builds ever running at once (must stay 1)

    def project_dir(self, pid: str) -> Path:
        return self.store.dir(pid)

    def effective_settings(self, p: Project, kind: str, params: dict) -> ExportSettings:
        d = p.export.model_dump()
        d.update({k: v for k, v in (params.get("settings") or {}).items() if v is not None})
        for k in ("format", "poly_preset"):
            if params.get(k):
                d[k] = params[k]
        if kind == "preview":
            d.update(format="glb", poly_preset="low", triangulate=True)
        if kind == "scene":   # Godot scene: glTF, Y-up, always with collision shapes
            d.update(format="glb", up_axis="Y", triangulate=True)
            if d.get("collision") == "none":
                d["collision"] = "convex"
        return ExportSettings.model_validate(d)

    def run(self, job_id: str, project_id: str, kind: str, params: dict, cancel: threading.Event) -> dict:
        with self._gauge:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            return self._run(job_id, project_id, kind, params, cancel)
        finally:
            with self._gauge:
                self.active -= 1

    def _run(self, job_id: str, project_id: str, kind: str, params: dict, cancel: threading.Event) -> dict:
        if kind not in KINDS:
            raise AppError("Unknown job kind", "build.run", kind, f"Use one of {sorted(KINDS)}")
        if kind == "matlab":
            return self._run_matlab(project_id, params, cancel)
        p = self.store.load(project_id)
        es = self.effective_settings(p, kind, params)
        errs = [i for i in validate_project(p) if i.level == "error"]
        if errs:
            raise AppError("Project has geometry errors", "build.validate",
                           "; ".join(f"{i.element_id}: {i.message}" for i in errs[:8]),
                           "Fix the listed elements (see POST /api/geometry/validate)", status=422)
        levels = set(params["levels"]) if params.get("levels") else None
        if levels and not levels <= {lv.id for lv in p.levels}:
            raise AppError("Unknown level in 'levels'", "build.run", str(sorted(levels - {lv.id for lv in p.levels})), "Use level ids from the project")

        pdir = self.project_dir(project_id)
        detail = es.poly_preset
        gdir = pdir / "geometry" / detail
        result: dict = {"kind": kind, "settings": es.model_dump()}
        t0 = time.perf_counter()

        with measure("geometry", include_children=False) as mg:
            st = build_geometry(p, gdir, detail=detail, force=bool(params.get("force")), levels=levels)
        mg.extra = {"rebuilt": len(st.rebuilt), "cached": len(st.cached), "triangles": st.triangles}
        result["geometry"] = {**st.to_dict(), "memory": mg.to_dict()}
        if cancel.is_set():
            raise BuildError("Build cancelled", "build.run", "cancel requested", "Start a new build", status=499)

        outputs_info: dict = {}
        blender: dict | None = None
        if kind != "geometry":
            man = load_manifest(gdir)["parts"]
            parts = {i: v for i, v in man.items() if v.get("file") and (levels is None or v["level"] in levels)
                     and not (kind == "scene" and v.get("type") == "door")}   # doors become separate openable nodes
            if not parts:
                raise BuildError("Nothing to build", "build.run", "the project has no mesh-producing elements" + (" on the chosen levels" if levels else ""),
                                 "Draw walls/floors first or choose other levels")
            out_rel = Path("exports") / ("preview" if kind == "preview" else f"{kind}_{job_id[:8]}")
            use_tex = bool(params.get("textures", kind != "preview"))
            job = {
                "project_id": p.id, "project_name": _slug(p.name), "steps": KIND_STEPS[kind], "settings": es.model_dump(),
                "materials": [m.model_dump() for m in p.materials], "levels": [lv.model_dump() for lv in p.levels],
                "geometry_dir": str(gdir), "parts": parts, "textures_dir": str(pdir / "textures"), "use_textures": use_tex,
                "output_dir": str(pdir / out_rel), "output_stem": _slug(p.name) + ("" if kind == "preview" else f"_{kind}"),
            }
            if kind == "preview":
                job["output_stem"] = "preview"
            if kind == "preview" and os.environ.get("BIM_PREVIEW_BLENDER") != "1":
                # Fast path: write the preview GLB directly from the cached numpy meshes (no Blender start-up).
                tw = time.perf_counter()
                rep = write_preview_glb(parts, gdir, job["materials"], Path(job["output_dir"]) / "preview.glb")
                outputs_info = validate_outputs(rep["outputs"], rep["objects"], None)
                result["outputs"] = [str(Path(o).relative_to(pdir)) for o in rep["outputs"]]
                result["validation"] = outputs_info
                result["blender"] = None
                result["fast_preview"] = {"seconds": round(time.perf_counter() - tw, 3), "objects": rep["objects"], "bbox_size": rep["bbox_size"]}
                result["triangles"] = {"visual": rep["triangles"], "collision": 0}
            else:
                rr = run_blender(self.s, "worker.py", job, pdir / "tmp", cancel)
                blender = {"peak_rss_mb": round(rr.peak_rss_mb, 1), "seconds": round(rr.seconds, 2), "report": rr.report}
                exp_vis = rr.report["objects"]["visual"]
                exp_col = rr.report["collision"]["objects"] if es.format in ("glb", "gltf") else None
                outputs_info = validate_outputs(rr.report["outputs"], exp_vis, exp_col)
                result["outputs"] = [str(Path(o).relative_to(pdir)) for o in rr.report["outputs"] if Path(o).suffix != ".blend" or True]
                result["validation"] = outputs_info
                result["blender"] = blender
                result["triangles"] = rr.report["final_triangles"]
                if kind == "scene":
                    try:
                        so = SceneOptions(**(params.get("scene") or {}))
                    except Exception as e:  # noqa: BLE001
                        raise AppError("Invalid scene options", "build.scene", str(e)[:300], "Check res_dir and the other scene options", status=422) from e
                    glb = next(Path(o) for o in rr.report["outputs"] if o.endswith(".glb"))
                    sc = write_scene(p, glb.parent, job["output_stem"], glb.name, rr.report["pivot"], es.model_dump(), so)
                    result["scene"] = sc
                    result["outputs"] = [str((glb.parent / f).relative_to(pdir)) for f in sc["files"]]
        result["seconds"] = round(time.perf_counter() - t0, 3)

        self._record(p.id, BuildRecord(
            job_id=job_id, kind=kind, status="succeeded", elements_rebuilt=len(st.rebuilt), elements_cached=len(st.cached),
            triangles=(blender["report"]["final_triangles"]["visual"] if blender else (result.get("triangles") or {}).get("visual", st.triangles)),
            seconds=result["seconds"], peak_rss_mb=(blender or {}).get("peak_rss_mb"),
            output=(result.get("outputs") or [None])[0]))
        self._profile(p.id, kind, result)
        if kind != "preview" and kind != "geometry":
            self._prune_exports(pdir, keep_name=f"{kind}_{job_id[:8]}")
        return result

    def _run_matlab(self, project_id: str, params: dict, cancel: threading.Event) -> dict:
        """Material Lab: Blender builds a procedural material and bakes tileable colour / normal / roughness maps."""
        import hashlib
        p = self.store.load(project_id)
        mid = params.get("material_id")
        mat = next((m for m in p.materials if m.id == mid), None)
        if mat is None:
            raise AppError("Unknown material", "matlab", str(mid), "Save the project first, then pick a material from the list", status=404)
        try:
            lab = MaterialLab(**(params.get("lab") or {}))
        except Exception as e:  # noqa: BLE001 - pydantic details are useful to the user
            raise AppError("Invalid material parameters", "matlab", str(e)[:300], "Check the values in the Material Lab", status=422) from e
        tex_dir = self.project_dir(project_id) / "textures"
        tex_dir.mkdir(parents=True, exist_ok=True)
        tag = hashlib.sha1(lab.model_dump_json().encode()).hexdigest()[:8]
        prefix = f"{_slug(mid)}_lab_"
        job = {"preset": lab.preset, "params": lab.model_dump(), "out_dir": str(tex_dir), "stem": prefix + tag}
        rr = run_blender(self.s, "matlab.py", job, self.project_dir(project_id) / "tmp", cancel, timeout_s=min(self.s.blender_timeout_s, 240))
        files = rr.report["files"]
        for old in tex_dir.glob(prefix + "*"):         # drop the previous generation of this material
            if old.name not in files.values():
                old.unlink(missing_ok=True)
        return {"kind": "matlab", "material_id": mid, "files": files, "lab": lab.model_dump(), "uv_scale": round(1.0 / lab.tile_m, 6),
                "seconds": round(rr.seconds, 2), "peak_rss_mb": round(rr.peak_rss_mb, 1), "stats": rr.report.get("stats")}

    EXPORT_KEEP = int(os.environ.get("BIM_KEEP_EXPORTS", "6"))   # newest export folders kept per project (disk is the limit, not RAM)

    def _prune_exports(self, pdir: Path, keep_name: str) -> None:
        """Delete the oldest ``exports/<kind>_<job>`` folders beyond EXPORT_KEEP (the preview folder and the one just built are never touched)."""
        try:
            root = pdir / "exports"
            dirs = sorted((d for d in root.iterdir() if d.is_dir() and d.name != "preview"), key=lambda d: d.stat().st_mtime, reverse=True)
            for old in [d for d in dirs if d.name != keep_name][max(0, self.EXPORT_KEEP - 1):]:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass   # housekeeping must never fail a build

    def _record(self, pid: str, rec: BuildRecord) -> None:
        self.store.append_build(pid, rec)

    def _profile(self, pid: str, kind: str, result: dict) -> None:
        line = {"at": time.time(), "project": pid, "kind": kind, "seconds": result["seconds"],
                "geometry": result["geometry"]["memory"], "rebuilt": result["geometry"]["rebuilt"],
                "cached": result["geometry"]["cached"], "triangles": result.get("triangles"),
                "blender_peak_mb": (result.get("blender") or {}).get("peak_rss_mb")}
        try:
            pf = self.s.data_dir / "profile.jsonl"
            if pf.exists() and pf.stat().st_size > 512 * 1024:      # keep the log small: one rotated generation
                os.replace(pf, pf.with_suffix(".jsonl.1"))
            with open(pf, "a") as f:
                f.write(json.dumps(line) + "\n")
        except OSError:
            log.warning("could not write profile log")
