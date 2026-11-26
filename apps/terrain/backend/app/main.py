from __future__ import annotations
import base64, json, math, os, re, tempfile, threading, uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from .schemas import Project, PreviewRequest, ProfileRequest, RouteRequest, SuggestRequest, LotsRequest, SimRequest, ViewRequest
from .terrain import engine_for, grid_axes, validate
from .materials import paint, colors_rgb
from .exporter import build_zip, normalize
from .tiles import export_tiles, tile_plan
from .routing import route, suggest_sites, lots_for_site
from .gameplay import simulate, viewshed
from . import texlib, glb as glb_mod, blendexport

app = FastAPI(title="TerrainForge")
JOBS: dict = {}
MAX_TILES = 400


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/preview")
def preview(req: PreviewRequest):
    p, w = req.project, req.project.world
    eng = engine_for(p, req.resolution)
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, req.resolution)
    Z = eng.grid(xs, ys)
    q, zmin, zmax = normalize(Z, p.export.mode, p.export.zmin_m, p.export.zmax_m)
    errors, warnings = validate(p, eng, Z, xs, ys)
    out = {"nx": len(xs), "ny": len(ys), "zmin": zmin, "zmax": zmax,
           "data_b64": base64.b64encode(q.astype("<u2").tobytes()).decode(),
           "errors": errors, "warnings": warnings, "linear_info": eng.linear_info()}
    if req.colors:
        pt, _ = paint(p, eng, Z, xs, ys)
        out["color_b64"] = base64.b64encode(colors_rgb(p, pt).tobytes()).decode()
    return out


@app.post("/api/profile")
def profile(req: ProfileRequest):
    eng = engine_for(req.project, 1025)
    dist, z = eng.profile(req.p0, req.p1, req.samples)
    return {"dist": dist.tolist(), "z": z.tolist()}


def _check(p: Project, res: int):
    errors, _ = validate(p, engine_for(p, res))
    if errors:
        raise HTTPException(422, detail="لا يمكن التصدير قبل إصلاح الأخطاء: " + " | ".join(errors))


@app.post("/api/route")
def api_route(req: RouteRequest):
    try:
        return route(req.project, req.kind, req.points, req.resolution, req.max_grade)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.post("/api/suggest-sites")
def api_suggest(req: SuggestRequest):
    return {"candidates": suggest_sites(req.project, req.kind, req.diameter_m, req.count, req.resolution)}


@app.post("/api/lots")
def api_lots(req: LotsRequest):
    p = req.project
    s = next((x for x in p.sites if x.id == req.site_id), None)
    if s is None:
        raise HTTPException(404, detail="الموقع غير موجود")
    eng = engine_for(p, 513)
    i = next(k for k, (t, f) in enumerate(eng.stages) if t == "pad" and f.id == s.id)
    return {"lots": lots_for_site(s, eng._site_design(i)["level"])}


@app.post("/api/simulate")
def api_simulate(req: SimRequest):
    try:
        return simulate(req.project, req.resolution)
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@app.post("/api/viewshed")
def api_viewshed(req: ViewRequest):
    r = viewshed(req.project, req.x_m, req.y_m, req.height_m, req.radius_m, req.resolution)
    r["mask_b64"] = base64.b64encode(r.pop("mask").tobytes()).decode()
    return r


@app.post("/api/export")
def export(p: Project):
    w = p.world
    _check(p, p.export.resolution)
    eng = engine_for(p, p.export.resolution)
    xs, ys = grid_axes(w.size_x_m, w.size_y_m, p.export.resolution)
    Z = eng.grid(xs, ys)
    return Response(build_zip(p, Z, {"waterfalls": eng.waterfalls()}), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="terrain_export.zip"'})


@app.post("/api/export-tiles")
def export_tiles_start(p: Project):
    nx, ny, _ = tile_plan(p)
    if nx * ny > MAX_TILES:
        raise HTTPException(422, detail=f"عدد المربعات {nx * ny} يتجاوز الحد {MAX_TILES}. كبّر المنطقة المحمّلة.")
    _check(p, 513)
    jid = uuid.uuid4().hex[:12]
    job = {"state": "running", "done": 0, "total": 2 * nx * ny, "error": None,
           "path": os.path.join(tempfile.gettempdir(), f"terrainforge_{jid}.zip")}
    JOBS[jid] = job

    def run():
        try:
            export_tiles(p, job["path"], lambda d, t: job.update(done=d, total=t))
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001
            job.update(state="error", error=str(e))
    threading.Thread(target=run, daemon=True).start()
    return {"job_id": jid, "tiles": nx * ny}


@app.get("/api/job/{jid}")
def job_status(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "مهمة غير موجودة")
    return {k: j.get(k) for k in ("state", "done", "total", "error", "stage")}


@app.get("/api/job/{jid}/download")
def job_download(jid: str):
    j = JOBS.get(jid)
    if not j or j["state"] != "done":
        raise HTTPException(404, "الملف غير جاهز")
    return FileResponse(j["path"], media_type=j.get("media", "application/zip"), filename=j.get("filename", "terrain_tiles.zip"))


# ───────────── قياس الأداء على جهاز المستخدم ─────────────
@app.post("/api/bench")
def bench_start(body: dict):
    from . import bench
    p = Project.model_validate(body["project"]) if body.get("project") else None
    try:
        return {"job_id": bench.start(p)}
    except RuntimeError as e:
        raise HTTPException(409, detail=str(e))


@app.get("/api/bench/{jid}")
def bench_status(jid: str):
    from . import bench
    j = bench.BENCH.get(jid)
    if not j:
        raise HTTPException(404, "قياس غير موجود")
    return j


# ───────────── تصدير العالم: GLB / .blend (يبقى تصدير الصور والأكواد كما هو) ─────────────
def _reap(keep: int = 12):
    """يحذف ملفات المهام القديمة (الأقدم أولاً) كي لا تتراكم في المجلد المؤقت."""
    done = [k for k, v in JOBS.items() if v["state"] != "running"]
    for k in done[:-keep] if len(done) > keep else []:
        try:
            os.remove(JOBS[k]["path"])
        except OSError:
            pass
        JOBS.pop(k, None)


@app.get("/api/export-capabilities")
def export_capabilities(refresh: bool = False):
    return {"glb": {"available": True, "max_resolution": glb_mod.MAX_GLB_RES}, "blend": blendexport.availability(force=refresh)}


@app.post("/api/export-world")
def export_world(p: Project, fmt: str = Query(..., pattern="^(glb|blend)$")):
    _check(p, 513)
    if fmt == "blend":
        av = blendexport.availability()
        if not av["available"]:
            raise HTTPException(503, detail=av["reason"] + " — يمكنك تصدير GLB بدلاً منه.")
    jid = uuid.uuid4().hex[:12]
    name = "".join(ch if (ch.isascii() and ch.isalnum()) or ch in "-_" else "_" for ch in (p.name or "world"))[:40].strip("_") or "world"
    job = {"state": "running", "done": 0, "total": 100, "error": None, "stage": "بدء", "fmt": fmt,
           "path": os.path.join(tempfile.gettempdir(), f"terrainforge_{jid}.{fmt}"), "filename": f"{name}.{fmt}",
           "media": "model/gltf-binary" if fmt == "glb" else "application/octet-stream"}
    _reap()
    JOBS[jid] = job

    def run():
        try:
            if fmt == "glb":
                data, rep = glb_mod.build_glb(p, p.export.glb_resolution, p.export.glb_texture_px,
                                              progress=lambda s, f: job.update(stage=s, done=int(f * 100)))
                with open(job["path"], "wb") as fh:
                    fh.write(data)
                job["report"] = rep
            else:
                job.update(stage="حساب التضاريس والمواد", done=5)
                w = p.world
                eng = engine_for(p, p.export.resolution)
                xs, ys = grid_axes(w.size_x_m, w.size_y_m, p.export.resolution)
                Z = eng.grid(xs, ys)
                job.update(stage="تجهيز ملفات التصدير", done=25)
                zbytes = build_zip(p, Z, {"waterfalls": eng.waterfalls()})
                job.update(stage="Blender", done=45)
                job["report"] = blendexport.export_blend(zbytes, job["path"], on_state=lambda s: job.update(stage=s))
            job.update(state="done", done=100, stage="تم")
        except Exception as e:  # noqa: BLE001
            job.update(state="error", error=str(e))
    threading.Thread(target=run, daemon=True).start()
    return {"job_id": jid, "format": fmt}


@app.post("/api/preview-glb")
def preview_glb(p: Project, res: int = Query(257, ge=65, le=513), tex: int = Query(1024, ge=256, le=2048)):
    """GLB خفيف لنافذة المعاينة (نفس مسار التصدير بدقة أقل) — ما تراه هو ما سيُصدَّر."""
    _check(p, 257)
    data, rep = glb_mod.build_glb(p, res, tex, jpeg_quality=80)
    return Response(data, media_type="model/gltf-binary", headers={"X-TF-Report": json.dumps({k: rep[k] for k in ("vertices", "triangles")})})


# ───────────── خامات CC0 مفتوحة (1K) ─────────────
def _tex_call(fn, *a):
    try:
        return fn(*a)
    except texlib.TexError as e:
        raise HTTPException(422, detail=str(e))


@app.get("/api/textures/providers")
def tex_providers():
    return [{"id": k, "title": v.title, "credit": v.credit, "license": texlib.LICENSE_ID, "resolution": texlib.RESOLUTION} for k, v in texlib.PROVIDERS.items()]


@app.get("/api/textures/search")
def tex_search(provider: str, q: str = "", limit: int = 24):
    return {"results": _tex_call(texlib.search, provider, q, limit)}


@app.post("/api/textures/fetch")
def tex_fetch(req: dict):
    r = _tex_call(texlib.fetch, str(req.get("provider", "")), str(req.get("asset_id", "")))
    return {**r, "ref": texlib.make_ref(r["provider"], r["id"])}


@app.post("/api/textures/ensure")
def tex_ensure(req: dict):
    """ينزّل مراجع cc0: الناقصة لمشروع فُتح على جهاز آخر (أفضل جهد؛ كل مرجع بحالته)."""
    return {"results": texlib.ensure(req.get("refs") or [])}


@app.get("/api/textures/cache")
def tex_cache():
    return {"items": texlib.cached()}


@app.get("/api/textures/file/{provider}/{asset_id}/{name}")
def tex_file(provider: str, asset_id: str, name: str):
    d = _tex_call(texlib.pack_dir, provider, asset_id)
    f = d / name
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+\.(jpg|jpeg|png)", name) or not f.is_file():
        raise HTTPException(404, "الملف غير موجود")
    return FileResponse(f)


_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="ui")
    try:                                                      # تنبيه: الواجهة المبنية أقدم من المصدر فلن تظهر آخر التعديلات
        _src = max(f.stat().st_mtime for f in (_DIST.parent / "src").rglob("*") if f.is_file())
        if _src > (_DIST / "index.html").stat().st_mtime:
            print("\n⚠ TerrainForge: الواجهة المبنية (frontend/dist) أقدم من المصدر. شغّل run.bat أو: cd frontend && npm run build\n")
    except (OSError, ValueError):
        pass
else:
    print("\nTerrainForge: لا توجد واجهة مبنية (frontend/dist). شغّل run.bat أو: cd frontend && npm install && npm run build\n")
