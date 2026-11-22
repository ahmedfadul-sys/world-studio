"""The shell: one local page with a tab per module (kept alive in iframes), status, language, updates and environment info."""
from __future__ import annotations

import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import envmgr, paths, settings, updater
from . import bridge
from .supervisor import Supervisor


def create_shell(sup: Supervisor, code_root=paths.CODE_ROOT, on_restart=None, on_quit=None) -> FastAPI:
    app = FastAPI(title="World Studio shell")
    state = {"last_ping": time.time(), "pinged": False, "update": None, "updating": False}
    app.state.shell = state

    bridge.register(app, sup)

    @app.get("/studio/api/health")
    def health():
        return {"ok": True}

    @app.get("/studio/api/modules")
    def modules():
        lang = settings.load().get("lang", "ar")
        return {"modules": [{"id": m.id, "title": m.title(lang), "titles": m.manifest.get("title", {}), "icon": m.manifest.get("icon", "▣"),
                             "url": m.url, "state": m.state, "error": m.error} for m in sup.modules]}

    @app.post("/studio/api/modules/{mid}/restart")
    def restart(mid: str):
        if not sup.restart(mid):
            raise HTTPException(404, "unknown module")
        return {"ok": True}

    @app.get("/studio/api/info")
    def info():
        s = settings.load()
        envs = {}
        for name in ("app", "bpy"):
            py = envmgr.resolve_python(name)
            ext = bool(settings.python_override(name))
            envs[name] = {"python": str(py), "exists": py.exists(), "external": ext, **({"missing": envmgr.verify(name)["missing"]} if ext else {})}
        return {"version": paths.read_version(code_root), "home": str(paths.home()), "lang": s["lang"], "envs": envs,
                "auto_update": s["auto_update"], "update": state["update"], "updating": state["updating"]}

    @app.post("/studio/api/settings")
    def set_settings(patch: dict):
        allowed = {k: v for k, v in patch.items() if k in ("lang", "auto_update", "envs")}
        return settings.save(allowed)

    @app.post("/studio/api/env")
    def set_env(body: dict):
        """Use an existing interpreter for environment 'app' or 'bpy' (verified first; takes effect after restart). python=null → managed again."""
        from . import setup as _setup
        name = body.get("name")
        if name not in ("app", "bpy"):
            raise HTTPException(422, "name must be 'app' or 'bpy'")
        return {**_setup.set_env(name, body.get("python")), "restart_required": True}

    @app.post("/studio/api/ping")
    def ping():
        state["last_ping"], state["pinged"] = time.time(), True
        return {"ok": True}

    @app.post("/studio/api/update/check")
    def update_check():
        state["update"] = updater.check(paths.read_version(code_root))
        return state["update"]

    @app.post("/studio/api/update/apply")
    def update_apply():
        info = state["update"] or updater.check(paths.read_version(code_root))
        if not info.get("available"):
            raise HTTPException(409, "no update available")
        if state["updating"]:
            raise HTTPException(409, "update already running")
        state["updating"] = True
        try:
            ver = updater.download_and_stage(info)
        except updater.UpdateError as e:
            raise HTTPException(502, str(e))
        finally:
            state["updating"] = False
        return {"ok": True, "version": ver, "restart_required": True}

    @app.post("/studio/api/update/rollback")
    def update_rollback():
        try:
            return {"ok": True, "version": updater.rollback(), "restart_required": True}
        except updater.UpdateError as e:
            raise HTTPException(409, str(e))

    @app.post("/studio/api/restart")
    def restart_app():
        if on_restart:
            threading.Timer(0.4, on_restart).start()
        return {"ok": True}

    @app.post("/studio/api/quit")
    def quit_app():
        if on_quit:
            threading.Timer(0.2, on_quit).start()
        return {"ok": True}

    @app.get("/studio/api/logs/{mid}")
    def logs(mid: str, lines: int = 200):
        f = paths.logs_dir() / f"{mid}.log"
        if not f.is_file() or mid not in {m.id for m in sup.modules}:
            raise HTTPException(404, "no log")
        return JSONResponse({"text": "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-min(lines, 1000):])})

    shell_dir = code_root / "shell"
    app.mount("/", StaticFiles(directory=shell_dir, html=True), name="shell")
    return app
