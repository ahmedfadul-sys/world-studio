"""FastAPI application. Run with ONE worker: ``uvicorn bimgame.api.app:app --workers 1``."""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..bim import debim_adapter
from ..bim.modules import module_library
from ..blender.runner import check_blender
from ..config import ROOT, Settings, get_settings
from ..geometry.cache import build_geometry
from ..geometry.validate import validate_project
from ..schema import ExportSettings, Project, SiteLink, new_project
from ..services.build import KIND_STEPS, BuildService
from ..services.jobs import JobManager
from ..services.storage import ProjectStore
from ..utils.errors import AppError, NotFound
from ..utils.memprof import measure, rss_mb, tree_rss_mb


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')


class CreateProject(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    units: Literal["m", "cm", "mm", "ft", "in"] = "m"


class OpenSite(SiteLink):
    project_id: str | None = None   # an earlier project of this site (kept when it still exists)


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    kind: Literal["build", "geometry", "preview", "optimize", "collision", "lod", "uv", "export", "scene", "matlab"] = "build"
    levels: list[str] | None = None
    force: bool = False
    textures: bool | None = None
    format: Literal["glb", "gltf", "fbx"] | None = None
    poly_preset: Literal["low", "medium", "high"] | None = None
    settings: dict[str, Any] | None = None  # partial ExportSettings overrides (validated at build time)
    scene: dict[str, Any] | None = None     # SceneOptions for kind 'scene'


class LabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    material_id: str
    lab: dict[str, Any]


class ProjectRef(BaseModel):
    project_id: str
    settings: dict[str, Any] | None = None
    levels: list[str] | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    _setup_logging(s.log_level)
    s.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = ProjectStore(s)
        app.state.store = store
        app.state.jobs = JobManager(store, BuildService(store, s))
        app.state.startup_rss = rss_mb()

        def _warmup() -> None:  # import the heavy libraries once, off the request path (first preview was ~2.5 s slower)
            try:
                from ..bim.debim_adapter import _load_debim
                _load_debim()
                import manifold3d  # noqa: F401
                import shapely  # noqa: F401
            except Exception:  # noqa: BLE001 - warm-up is best effort; real errors surface on first use
                pass
        threading.Thread(target=_warmup, name="warmup", daemon=True).start()
        yield
        app.state.jobs.shutdown()
        store.close()

    app = FastAPI(title="BIM Builder – Game Edition", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(AppError)
    async def _app_err(_: Request, e: AppError):
        return JSONResponse(e.to_dict(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _val_err(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []))
        return JSONResponse({"error": {"what": "Invalid request", "where": loc, "why": first.get("msg", ""),
                                       "fix": "Correct the field and resend", "details": [
                                           {"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()[:20]]}}, status_code=422)

    @app.exception_handler(Exception)
    async def _any_err(_: Request, e: Exception):
        logging.getLogger("bimgame").exception("unhandled")
        return JSONResponse({"error": {"what": "Internal server error", "where": "api", "why": f"{type(e).__name__}",
                                       "fix": "See server log"}}, status_code=500)

    st = lambda: app.state.store  # noqa: E731
    jm = lambda: app.state.jobs  # noqa: E731

    # system -----------------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/system")
    def system():
        try:
            dv = debim_adapter.debim_version()
        except AppError as e:
            dv = f"unavailable: {e.why}"
        return {"debim": dv, "blender": check_blender(s), "rss_mb": round(rss_mb(), 1),
                "startup_rss_mb": round(app.state.startup_rss, 1), "tree_rss_mb": round(tree_rss_mb(), 1),
                "jobs": jm().active(), "workers": 1,
                "max_concurrent_builds_seen": jm().builder.max_active}

    @app.get("/api/perf")
    def perf(limit: int = 50):
        f = s.data_dir / "profile.jsonl"
        if not f.exists():
            return {"runs": []}
        import json
        lines = f.read_text().splitlines()[-max(1, min(limit, 500)):]
        return {"runs": [json.loads(x) for x in lines]}

    # projects -----------------------------------------------------------------
    @app.post("/api/projects", status_code=201)
    def create_project(body: CreateProject):
        return st().save(new_project(body.name, body.units))

    @app.post("/api/sites/open")
    def open_site(body: OpenSite):
        """TerrainForge → BIM Builder: find or create the project that holds the buildings of one terrain site and
        (re)store the site footprint in it. Returns {project_id, created}."""
        link = SiteLink(**body.model_dump(exclude={"project_id"}))
        created = False
        if body.project_id and st().exists(body.project_id):
            p = st().load(body.project_id)
        else:
            p = new_project(link.name or link.key)
            created = True
        p.site = link
        st().save(p)
        return {"project_id": p.id, "created": created, "name": p.name}

    @app.get("/api/projects")
    def list_projects():
        return {"projects": st().list()}

    @app.get("/api/projects/{pid}")
    def get_project(pid: str):
        return st().load(pid)

    @app.put("/api/projects/{pid}")
    def put_project(pid: str, project: Project):
        if project.id != pid:
            raise AppError("Project id mismatch", "PUT /api/projects", f"URL has {pid}, body has {project.id}", "Send the same id in both")
        if not st().exists(pid):
            raise NotFound("Project not found", "PUT /api/projects", pid, "Create it with POST first")
        old = st().load(pid)
        project.build_history = old.build_history  # server-owned
        return st().save(project)

    @app.get("/api/projects/{pid}/backups")
    def list_backups(pid: str):
        st().load(pid)
        return {"backups": st().list_backups(pid)}

    @app.post("/api/projects/{pid}/backups", status_code=201)
    def make_backup(pid: str):
        return {"name": st().snapshot(pid)}

    @app.post("/api/projects/{pid}/backups/{name}/restore")
    def restore_backup(pid: str, name: str):
        return st().restore(pid, name)

    @app.delete("/api/projects/{pid}/backups/{name}", status_code=204)
    def delete_backup(pid: str, name: str):
        st().delete_backup(pid, name)

    @app.delete("/api/projects/{pid}", status_code=204)
    def delete_project(pid: str):
        st().delete(pid)

    @app.get("/api/modules/{pid}")
    def modules(pid: str):
        return {"modules": [m.model_dump() for m in module_library(st().load(pid))]}

    @app.get("/api/projects/{pid}/files/{path:path}")
    def project_file(pid: str, path: str):
        base = st().dir(pid).resolve()
        target = (base / path).resolve()
        if base not in target.parents or not target.is_file() or "tmp" in target.relative_to(base).parts[:1]:
            raise NotFound("File not found", "files", path, "Use a path from a job result")
        mt = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".glb":
            mt = "model/gltf-binary"
        return FileResponse(target, media_type=mt, filename=target.name)

    # textures (raw-body upload: no multipart dependency) ----------------------------
    TEX_RE = re.compile(r"[A-Za-z0-9_.-]{1,80}\.(png|jpe?g)$", re.I)
    MAX_TEX = 8 * 1024 * 1024
    SIGS = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")

    @app.get("/api/projects/{pid}/textures")
    def list_textures(pid: str):
        d = st().dir(pid) / "textures"
        return {"textures": sorted(f.name for f in d.glob("*") if f.is_file()) if d.exists() else []}

    @app.put("/api/projects/{pid}/textures/{name}", status_code=201)
    async def put_texture(pid: str, name: str, request: Request):
        if not st().exists(pid):
            raise NotFound("Project not found", "textures", pid, "Create or select a project first")
        if not TEX_RE.fullmatch(name):
            raise AppError("Invalid texture name", "textures", name, "Use letters, digits, _ - . and a .png/.jpg extension")
        if int(request.headers.get("content-length") or 0) > MAX_TEX:
            raise AppError("Texture too large", "textures", f"limit is {MAX_TEX // 2**20} MB", "Downscale the image (game textures rarely need >2048 px)", status=413)
        data = await request.body()
        if len(data) > MAX_TEX:
            raise AppError("Texture too large", "textures", f"limit is {MAX_TEX // 2**20} MB", "Downscale the image", status=413)
        if not data.startswith(SIGS):
            raise AppError("File is not a PNG or JPEG image", "textures", "signature check failed", "Export the texture as .png or .jpg")
        d = st().dir(pid) / "textures"
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, d / name)
        return {"name": name, "bytes": len(data)}

    @app.delete("/api/projects/{pid}/textures/{name}", status_code=204)
    def delete_texture(pid: str, name: str):
        if not TEX_RE.fullmatch(name):
            raise AppError("Invalid texture name", "textures", name, "Use a name from the texture list")
        (st().dir(pid) / "textures" / name).unlink(missing_ok=True)

    # underlays: scanned plan images shown under the 2D grid (PNG/JPEG only; PDFs are rasterised in the browser) ------
    UL_DIR = "underlays"
    MAX_UL = 12 * 1024 * 1024

    @app.put("/api/projects/{pid}/underlays/{name}", status_code=201)
    async def put_underlay(pid: str, name: str, request: Request):
        if not st().exists(pid):
            raise NotFound("Project not found", "underlays", pid, "Create or select a project first")
        if not TEX_RE.fullmatch(name):
            raise AppError("Invalid image name", "underlays", name, "Use letters, digits, _ - . and a .png/.jpg extension")
        if int(request.headers.get("content-length") or 0) > MAX_UL:
            raise AppError("Image too large", "underlays", f"limit is {MAX_UL // 2**20} MB", "Use a smaller scan (3000 px on the long side is plenty)", status=413)
        data = await request.body()
        if len(data) > MAX_UL:
            raise AppError("Image too large", "underlays", f"limit is {MAX_UL // 2**20} MB", "Use a smaller scan", status=413)
        if not data.startswith(SIGS):
            raise AppError("File is not a PNG or JPEG image", "underlays", "signature check failed", "Export the plan as .png or .jpg (PDFs are converted in the editor)")
        d = st().dir(pid) / UL_DIR
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, d / name)
        return {"name": name, "bytes": len(data)}

    @app.delete("/api/projects/{pid}/underlays/{name}", status_code=204)
    def delete_underlay(pid: str, name: str):
        if not TEX_RE.fullmatch(name):
            raise AppError("Invalid image name", "underlays", name, "Use a name from the underlay list")
        (st().dir(pid) / UL_DIR / name).unlink(missing_ok=True)

    # geometry -----------------------------------------------------------------
    @app.post("/api/geometry/validate")
    def geometry_validate(body: ProjectRef):
        p = st().load(body.project_id)
        issues = [i.to_dict() for i in validate_project(p)]
        return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues}

    @app.post("/api/geometry/generate", status_code=202)
    def geometry_generate(body: ProjectRef):
        return _submit(body.project_id, "geometry", {"levels": body.levels, "settings": body.settings})

    # jobs -----------------------------------------------------------------------
    def _submit(pid: str, kind: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        j = jm().submit(pid, kind, params)
        return {"job_id": j["id"], "status": j["status"], "kind": kind}

    def _from_req(r: JobRequest, kind: str | None = None, fmt: str | None = None) -> dict:
        return _submit(r.project_id, kind or r.kind, {"levels": r.levels, "force": r.force or None, "textures": r.textures,
                                                      "format": fmt or r.format, "poly_preset": r.poly_preset, "settings": r.settings, "scene": r.scene})

    @app.post("/api/materials/generate", status_code=202)
    def materials_generate(r: LabRequest):
        """Generate PBR maps for a material with Blender (Material Lab). The job result lists the texture file names."""
        return _submit(r.project_id, "matlab", {"material_id": r.material_id, "lab": r.lab})

    @app.post("/api/build", status_code=202)
    def build(r: JobRequest):
        return _from_req(r)

    @app.post("/api/build/preview", status_code=202)
    def build_preview(r: JobRequest):
        return _from_req(r, "preview")

    @app.get("/api/build/status/{jid}")
    def build_status(jid: str):
        j = jm().get(jid)
        return {k: j[k] for k in ("id", "project_id", "kind", "status", "created_at", "started_at", "finished_at", "error")}

    @app.get("/api/build/result/{jid}")
    def build_result(jid: str):
        j = jm().get(jid)
        if j["status"] in ("queued", "running"):
            raise AppError("Job is not finished", "build.result", j["status"], "Poll /api/build/status until it succeeds", status=409)
        if j["status"] != "succeeded":
            return JSONResponse({"status": j["status"], "error": j["error"]}, status_code=422)
        return {"status": "succeeded", "result": j["result"]}

    @app.post("/api/build/cancel/{jid}")
    def build_cancel(jid: str):
        j = jm().cancel(jid)
        return {"id": jid, "status": j["status"]}

    # asset tools ------------------------------------------------------------------
    for route, kind in (("optimize", "optimize"), ("collision", "collision"), ("lod", "lod"), ("uv", "uv")):
        def _mk(kind=kind):
            def h(r: JobRequest):
                return _from_req(r, kind)
            return h
        app.add_api_route(f"/api/assets/{route}", _mk(), methods=["POST"], status_code=202, name=f"assets_{route}")

    for fmt in ("gltf", "glb", "fbx"):
        def _mk2(fmt=fmt):
            def h(r: JobRequest):
                return _from_req(r, "export", fmt)
            return h
        app.add_api_route(f"/api/export/{fmt}", _mk2(), methods=["POST"], status_code=202, name=f"export_{fmt}")

    @app.post("/api/export/scene", status_code=202)
    def export_scene(r: JobRequest):
        """Godot 4 scene: GLB + .tscn with collision, physics, a test player and doors that open with E."""
        return _from_req(r, "scene", "glb")

    # Serve the built frontend from the same single process (no extra server, no extra RAM).
    dist = Path(os.environ.get("BIM_FRONTEND_DIST", ROOT / "frontend" / "dist"))
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    return app


app = create_app()
