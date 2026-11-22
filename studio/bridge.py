"""Glue between the modules: terrain sites <-> BIM Builder projects, and the combined 'world' export
(terrain + one GLB per site + a placements list). The modules never talk to each other directly; the shell orchestrates."""
from __future__ import annotations

import io
import json
import math
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException

from . import paths
from .supervisor import Supervisor

SITE_KEYS = ("shape", "diameter_m", "width_m", "length_m", "rotation_deg", "kind")


def slug(s: str, default: str = "site") -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "").strip("_.")
    return s[:60] or default


def site_footprint(site: dict) -> dict:
    return {k: site[k] for k in SITE_KEYS if site.get(k) is not None}


def godot_tscn(sites: list[dict], root: str = "res://world/") -> str:
    """Godot 4 scene instancing every site GLB. Godot axes: (x, z, -y); yaw about Z becomes yaw about Y (same sign)."""
    rows = [s for s in sites if s.get("model")]
    out = [f"[gd_scene load_steps={len(rows) + 1} format=3]", ""]
    for i, s in enumerate(rows, 1):
        out.append(f'[ext_resource type="PackedScene" path="{root}{s["model"]}" id="{i}"]')
    out += ["", '[node name="Sites" type="Node3D"]']
    for i, s in enumerate(rows, 1):
        th = math.radians(s.get("yaw_deg", 0.0))
        c, sn = math.cos(th), math.sin(th)
        x, y, z = s["x"], s["y"], s["z"]
        # row-major basis of a rotation by +th about Godot's +Y (a +x vector goes towards -z = north), origin (x, z, -y)
        out += ["", f'[node name="{slug(s["id"])}" parent="." instance=ExtResource("{i}")]',
                f"transform = Transform3D({c:.6f}, 0, {sn:.6f}, 0, 1, 0, {-sn:.6f}, 0, {c:.6f}, {x:.4f}, {z:.4f}, {-y:.4f})"]
    return "\n".join(out) + "\n"


class WorldExport:
    def __init__(self, sup: Supervisor):
        self.sup = sup
        self.jobs: dict[str, dict] = {}

    def url(self, mid: str) -> str:
        m = next((m for m in self.sup.modules if m.id == mid), None)
        if not m or m.state != "ready":
            raise HTTPException(503, f"module '{mid}' is not ready")
        return m.url.rstrip("/")

    # ---- site -> BIM -----------------------------------------------------------------
    def open_site(self, site: dict) -> dict:
        if not site.get("id"):
            raise HTTPException(422, "site.id is required")
        body = {"key": str(site["id"]), "name": site.get("name") or str(site["id"]), "project_id": site.get("bim_project"), **site_footprint(site)}
        r = httpx.post(self.url("buildings") + "/api/sites/open", json=body, timeout=30)
        if r.status_code >= 400:
            raise HTTPException(r.status_code, r.text)
        return r.json()

    # ---- world export ----------------------------------------------------------------
    def start(self, project: dict, mode: str, out_dir: str | None) -> str:
        jid = uuid.uuid4().hex[:10]
        name = slug(project.get("name", "world"), "world")
        out = Path(out_dir) if out_dir else paths.home() / "exports" / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"
        job = {"state": "running", "step": "start", "done": 0, "total": 1, "error": None, "out": str(out), "warnings": [], "sites": []}
        self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, project, mode, out), daemon=True).start()
        return jid

    def _run(self, job: dict, project: dict, mode: str, out: Path) -> None:
        try:
            sites = [s for s in project.get("sites", []) if s.get("bim_project")]
            job["total"] = 1 + len(sites)
            out.mkdir(parents=True, exist_ok=True)
            job["step"] = "terrain"
            tz = self._terrain_zip(project, mode, job)
            tdir = out / "terrain"
            with zipfile.ZipFile(io.BytesIO(tz)) as z:
                for n in z.namelist():                      # zip-slip guard
                    t = (tdir / n).resolve()
                    if tdir.resolve() not in t.parents and t != tdir.resolve():
                        raise ValueError(f"unsafe path in terrain zip: {n}")
                z.extractall(tdir)
            job["done"] = 1
            build = next(iter(tdir.rglob("build.json")), None)
            bj = json.loads(build.read_text(encoding="utf-8")) if build else {}
            placed = {s["id"]: s for s in bj.get("sites", [])}
            rows = []
            for s in sites:
                job["step"] = f"site:{s['id']}"
                row = self._site_model(s, placed.get(s["id"]), out, job)
                rows.append(row)
                job["done"] += 1
            for s in project.get("sites", []):
                if not s.get("bim_project") and s["id"] in placed:
                    p = placed[s["id"]]
                    rows.append({"id": s["id"], "name": p.get("name"), "kind": p.get("kind"), "x": p["center"]["x"], "y": p["center"]["y"], "z": p["level_z"],
                                 "yaw_deg": p.get("rotation_deg", 0), "model": None, "footprint": site_footprint(s)})
            if build:
                for it in bj.get("sites", []):
                    r = next((r for r in rows if r["id"] == it["id"] and r.get("model")), None)
                    if r:
                        it["model"] = os.path.relpath(out / r["model"], build.parent).replace("\\", "/")   # relative to build.json
                build.write_text(json.dumps(bj, ensure_ascii=False, indent=1), encoding="utf-8")
            (out / "sites.json").write_text(json.dumps({
                "format": "world-studio-sites", "version": 1,
                "coordinate_system": "x east, y north, z up, metres; model origin = site centre; yaw_deg counter-clockwise about +Z; z = leveled terrain elevation",
                "terrain_build": str(build.relative_to(out)).replace("\\", "/") if build else None, "sites": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
            (out / "sites_placement.tscn").write_text(godot_tscn(rows), encoding="utf-8")
            job["sites"] = rows
            job["state"] = "done"
        except Exception as e:  # noqa: BLE001
            job.update(state="error", error=f"{type(e).__name__}: {e}")

    def _terrain_zip(self, project: dict, mode: str, job: dict) -> bytes:
        base = self.url("terrain")
        with httpx.Client(timeout=httpx.Timeout(600, connect=10)) as c:
            if mode == "single":
                r = c.post(base + "/api/export", json=project)
                if r.status_code >= 400:
                    raise RuntimeError(f"terrain export failed: {r.text[:300]}")
                return r.content
            r = c.post(base + "/api/export-tiles", json=project)
            if r.status_code >= 400:
                raise RuntimeError(f"terrain export failed: {r.text[:300]}")
            jid = r.json()["job_id"]
            while True:
                st = c.get(f"{base}/api/job/{jid}").json()
                job["sub"] = [st.get("done", 0), st.get("total", 1)]
                if st["state"] == "done":
                    break
                if st["state"] == "error":
                    raise RuntimeError(f"terrain export failed: {st.get('error')}")
                time.sleep(0.5)
            return c.get(f"{base}/api/job/{jid}/download").content

    def _site_model(self, s: dict, placed: dict | None, out: Path, job: dict) -> dict:
        sid, base = s["id"], self.url("buildings")
        pos = placed["center"] if placed else {"x": s["x_m"], "y": s["y_m"], "z": s.get("level_m", 0.0)}
        row = {"id": sid, "name": s.get("name") or sid, "kind": s.get("kind"), "x": pos["x"], "y": pos["y"], "z": pos.get("z", 0.0),
               "yaw_deg": s.get("rotation_deg", 0.0) if s.get("shape") == "rect" else 0.0, "bim_project": s["bim_project"], "model": None, "footprint": site_footprint(s)}
        with httpx.Client(timeout=httpx.Timeout(900, connect=10)) as c:
            pr = c.get(f"{base}/api/projects/{s['bim_project']}")
            if pr.status_code == 404:
                job["warnings"].append(f"{sid}: BIM project {s['bim_project']} no longer exists")
                return row
            if not pr.json().get("elements"):
                job["warnings"].append(f"{sid}: BIM project is empty — nothing to export")
                return row
            r = c.post(f"{base}/api/export/glb", json={"project_id": s["bim_project"], "format": "glb"})
            if r.status_code >= 400:
                raise RuntimeError(f"{sid}: BIM export failed: {r.text[:300]}")
            jid = r.json()["job_id"]
            while True:
                st = c.get(f"{base}/api/build/status/{jid}").json()
                if st["status"] == "succeeded":
                    break
                if st["status"] in ("failed", "cancelled"):
                    raise RuntimeError(f"{sid}: BIM export {st['status']}: {st.get('error')}")
                time.sleep(0.7)
            res = c.get(f"{base}/api/build/result/{jid}").json()["result"]
            glbs = [o for o in res.get("outputs", []) if o.lower().endswith(".glb")]
            if not glbs:
                raise RuntimeError(f"{sid}: BIM export produced no GLB")
            data = c.get(f"{base}/api/projects/{s['bim_project']}/files/{glbs[0]}").content
        rel = f"sites/{slug(sid)}/{slug(row['name'], 'site')}.glb"
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(data)
        row["model"] = rel
        return row


def register(app: FastAPI, sup: Supervisor) -> WorldExport:
    we = WorldExport(sup)

    @app.post("/studio/api/sites/open")
    def sites_open(body: dict):
        """Terrain site -> BIM project (created or reused). Body: the terrain Site as JSON. -> {project_id, created, url}"""
        r = we.open_site(body.get("site") or {})
        return {**r, "url": we.url("buildings") + "/?project=" + r["project_id"] + "&from=studio"}

    @app.post("/studio/api/export/world")
    def export_world(body: dict):
        if not isinstance(body.get("project"), dict):
            raise HTTPException(422, "project (terrain project JSON) is required")
        return {"job_id": we.start(body["project"], body.get("mode", "tiles"), body.get("out_dir"))}

    @app.get("/studio/api/export/world/{jid}")
    def export_world_status(jid: str):
        j = we.jobs.get(jid)
        if not j:
            raise HTTPException(404, "unknown job")
        return j

    @app.post("/studio/api/open-folder")
    def open_folder(body: dict):
        p = Path(body.get("path", "")).resolve()
        if not p.is_dir() or (paths.home() / "exports").resolve() not in [p, *p.parents]:
            raise HTTPException(422, "only export folders can be opened")
        import os, subprocess, sys
        if sys.platform == "win32":
            os.startfile(str(p))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True}

    return we
