import hashlib
import http.server
import json
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from studio import envmgr, paths, settings, supervisor, updater
from studio.shellserver import create_shell


# ------------------------------------------------------------------ settings / paths
def test_settings_roundtrip_and_override(tmp_path, monkeypatch):
    assert settings.load()["lang"] == "ar"
    settings.save({"lang": "en"})
    assert settings.load()["lang"] == "en"
    py = tmp_path / "py"
    py.write_text("x")
    assert settings.python_override("bpy") is None
    settings.save({"envs": {"bpy": {"python": str(py)}}})
    assert settings.python_override("bpy") == str(py)
    monkeypatch.setenv("STUDIO_PYTHON_APP", str(py))
    assert envmgr.resolve_python("app") == py
    assert envmgr.resolve_python("other") == paths.env_python("other")          # managed path when no override


# ------------------------------------------------------------------ environments are persistent
def test_env_created_once_reused_then_updated_on_requirement_change(tmp_path):
    req = tmp_path / "r.txt"
    req.write_text("six==1.16.0\n")
    spec = envmgr.EnvSpec("t", [req])
    assert envmgr.status(spec) == "missing"
    assert envmgr.ensure(spec) == "created"
    assert envmgr.status(spec) == "ready"
    t0 = time.time()
    assert envmgr.ensure(spec) == "reused" and time.time() - t0 < 1.0              # instant: no pip, no venv
    req.write_text("six==1.16.0\npackaging==24.1\n")
    assert envmgr.status(spec) == "stale"
    assert envmgr.ensure(spec) == "updated"
    import subprocess
    out = subprocess.run([str(paths.env_python("t")), "-c", "import six, packaging; print(six.__version__, packaging.__version__)"], capture_output=True, text=True)
    assert out.stdout.split() == ["1.16.0", "24.1"], out.stderr


def test_env_failure_is_reported_and_not_stamped(tmp_path):
    req = tmp_path / "r.txt"
    req.write_text("this-package-does-not-exist-zzz==9.9.9\n")
    spec = envmgr.EnvSpec("bad", [req])
    with pytest.raises(envmgr.EnvError):
        envmgr.ensure(spec)
    assert envmgr.status(spec) == "stale"          # will be retried next start, never treated as ready


def test_external_env_is_never_touched(tmp_path):
    settings.save({"envs": {"bpy": {"python": sys.executable}}})
    spec = envmgr.EnvSpec("bpy", [tmp_path / "does-not-matter.txt"])
    assert envmgr.status(spec) == "external"
    assert envmgr.ensure(spec) == "reused"
    assert not paths.env_dir("bpy").exists()


# ------------------------------------------------------------------ supervisor
FAKE = '''
import http.server, sys
port = int(sys.argv[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def make_code_root(tmp_path, n=2, crash=False):
    root = tmp_path / "code"
    for i in range(n):
        d = root / "apps" / f"m{i}"
        d.mkdir(parents=True)
        (d / "fake.py").write_text(FAKE if not crash else "import sys; sys.exit(3)")
        (d / "module.json").write_text(json.dumps({"id": f"m{i}", "title": {"en": f"M{i}", "ar": f"و{i}"}, "env": "app", "cwd": ".",
                                                   "command": [sys.executable, "fake.py", "{port}"], "health": "/h"}))
    (d.parent / "broken").mkdir()
    (d.parent / "broken" / "module.json").write_text("{not json")                  # must be skipped, not fatal
    return root


def test_supervisor_starts_restarts_and_stops(tmp_path):
    mods = supervisor.load_modules(make_code_root(tmp_path))
    assert [m.id for m in mods] == ["m0", "m1"]
    sup = supervisor.Supervisor(mods)
    sup.start_all(wait_s=20)
    try:
        assert [m.state for m in mods] == ["ready", "ready"]
        assert mods[0].port != mods[1].port
        old = mods[0].proc.pid
        mods[0].proc.kill()
        for _ in range(100):
            time.sleep(0.2)
            if mods[0].proc.pid != old and mods[0].state == "ready":
                break
        assert mods[0].proc.pid != old and mods[0].state == "ready"                  # watchdog brought it back
    finally:
        sup.stop_all()
    assert all(m.proc.poll() is not None for m in mods)


def test_supervisor_gives_up_on_a_crashing_module(tmp_path):
    mods = supervisor.load_modules(make_code_root(tmp_path, n=1, crash=True))
    sup = supervisor.Supervisor(mods)
    sup.start_all(wait_s=10)
    try:
        assert mods[0].state == "failed" and "exited with code 3" in mods[0].error
    finally:
        sup.stop_all()


# ------------------------------------------------------------------ updater (against a local fake GitHub feed)
def release_zip(path: Path, version: str, evil=False):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("studio/__init__.py", "")
        z.writestr("VERSION", version)
        if evil:
            z.writestr("../escape.txt", "x")


class Feed:
    def __init__(self, tmp_path, version="1.2.0", bad_hash=False, evil=False):
        self.dir = tmp_path / "feed"
        self.dir.mkdir()
        z = self.dir / f"world-studio-app-{version}.zip"
        release_zip(z, version, evil)
        digest = hashlib.sha256(z.read_bytes()).hexdigest()
        (self.dir / (z.name + ".sha256")).write_text(("0" * 64 if bad_hash else digest) + "  " + z.name)
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(self.dir), **k)  # noqa: E731
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.srv.server_address[1]
        base = f"http://127.0.0.1:{self.port}"
        (self.dir / "latest.json").write_text(json.dumps({"tag_name": f"v{version}", "body": "notes", "assets": [
            {"name": z.name, "browser_download_url": f"{base}/{z.name}"},
            {"name": z.name + ".sha256", "browser_download_url": f"{base}/{z.name}.sha256"}]}))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"{base}/latest.json"

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def feed(tmp_path, monkeypatch):
    made = []

    def make(**kw):
        f = Feed(tmp_path, **kw)
        made.append(f)
        monkeypatch.setenv("STUDIO_UPDATE_FEED", f.url)
        return f
    yield make
    for f in made:
        f.close()


def test_version_ordering():
    assert updater.vkey("1.10.0") > updater.vkey("1.9.9") > updater.vkey("v1.9")
    assert updater.vkey("2") > updater.vkey("1.99.99")


def test_update_check_stage_activate_and_rollback(feed):
    feed()
    info = updater.check("1.0.0")
    assert info["available"] and info["latest"] == "1.2.0"
    assert not updater.check("1.2.0")["available"] and not updater.check("1.3.0")["available"]
    assert updater.active_root() == paths.CODE_ROOT                                 # nothing downloaded yet
    assert updater.download_and_stage(info) == "1.2.0"
    root = updater.active_root()
    assert root.name == "1.2.0" and (root / "studio").is_dir() and paths.read_version(root) == "1.2.0"
    assert updater.pointer() == {"current": "1.2.0", "previous": None}
    assert updater.rollback() == paths.read_version(paths.CODE_ROOT)                # back to the installer's own code
    assert updater.active_root() == paths.CODE_ROOT


def test_update_rejects_bad_checksum(feed):
    feed(bad_hash=True)
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download_and_stage(updater.check("1.0.0"))
    assert updater.pointer() == {} and not (paths.home() / "app" / "1.2.0").exists()


def test_update_rejects_zip_slip(feed, tmp_path):
    feed(evil=True)
    with pytest.raises(updater.UpdateError, match="unsafe"):
        updater.download_and_stage(updater.check("1.0.0"))
    assert not (tmp_path / "escape.txt").exists() and updater.pointer() == {}


def test_update_check_never_raises_offline(monkeypatch):
    monkeypatch.setenv("STUDIO_UPDATE_FEED", "http://127.0.0.1:9/none")
    r = updater.check("1.0.0")
    assert r["available"] is False and "error" in r
    monkeypatch.delenv("STUDIO_UPDATE_FEED")
    assert "not configured" in updater.check("1.0.0")["error"]                       # placeholder repo in update.json


# ------------------------------------------------------------------ shell API
def test_shell_api(tmp_path, feed):
    from fastapi.testclient import TestClient
    mods = supervisor.load_modules(make_code_root(tmp_path, n=1))
    sup = supervisor.Supervisor(mods)
    sup.start_all(wait_s=20)
    flags = {}
    try:
        shell_root = tmp_path / "shellroot"
        (shell_root / "shell").mkdir(parents=True)
        (shell_root / "shell" / "index.html").write_text("<html>shell</html>")
        (shell_root / "VERSION").write_text("1.0.0")
        c = TestClient(create_shell(sup, shell_root, on_restart=lambda: flags.update(restart=1)))
        assert c.get("/").text.startswith("<html>shell")
        ms = c.get("/studio/api/modules").json()["modules"]
        assert ms[0]["id"] == "m0" and ms[0]["state"] == "ready" and ms[0]["url"].startswith("http://127.0.0.1:")
        info = c.get("/studio/api/info").json()
        assert info["version"] == "1.0.0" and set(info["envs"]) == {"app", "bpy"}
        assert c.post("/studio/api/settings", json={"lang": "en", "evil": 1}).json()["lang"] == "en"
        assert "evil" not in settings.load()
        assert c.post("/studio/api/update/apply").status_code in (409, 502)           # nothing to apply (placeholder repo)
        feed()
        assert c.post("/studio/api/update/check").json()["available"] is True
        r = c.post("/studio/api/update/apply").json()
        assert r["restart_required"] and updater.pointer()["current"] == "1.2.0"
        assert c.post("/studio/api/update/rollback").json()["ok"]
        assert c.get("/studio/api/logs/nope").status_code == 404
        assert c.get("/studio/api/logs/m0").status_code in (200, 404)
    finally:
        sup.stop_all()


def test_env_verify_and_setup(tmp_path, monkeypatch):
    import sys
    from studio import envmgr, setup, settings
    monkeypatch.setenv("STUDIO_HOME", str(tmp_path))
    v = envmgr.verify("app", sys.executable)          # this interpreter lacks several modules or not; result must be well-formed
    assert set(v) >= {"ok", "python", "missing"}
    assert envmgr.verify("bpy", tmp_path / "nope")["ok"] is False
    r = setup.set_env("bpy", sys.executable)
    assert (not r["ok"]) == bool(r["missing"])
    if r["ok"]:
        assert settings.python_override("bpy") == sys.executable
    setup.set_env("bpy", "none")
    assert settings.python_override("bpy") is None


def _zip_bytes(files):
    import io, zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


def test_godot_tscn_axes_and_rotation():
    import math
    from studio.bridge import godot_tscn
    t = godot_tscn([{"id": "a", "x": 10, "y": 20, "z": 5, "yaw_deg": 90, "model": "sites/a/a.glb"}, {"id": "b", "x": 0, "y": 0, "z": 0, "model": None}])
    assert 'path="res://world/sites/a/a.glb"' in t and 'name="b"' not in t
    nums = [float(x) for x in t.split("Transform3D(")[1].split(")")[0].split(",")]
    assert nums[9:] == [10.0, 5.0, -20.0]                       # (x, z, -y)
    c, s = nums[0], nums[2]                                      # +90° about Y: +x axis -> -z (north)
    assert abs(c) < 1e-6 and abs(nums[6] - (-1.0)) < 1e-6 and abs(s - 1.0) < 1e-6


def test_world_export_orchestration(tmp_path, monkeypatch):
    import json
    from studio import bridge
    we = bridge.WorldExport(sup=None)
    build = {"sites": [{"id": "v1", "name": "V", "kind": "village", "center": {"x": 1, "y": 2, "z": 3}, "level_z": 3, "rotation_deg": 15},
                       {"id": "c2", "name": "C", "kind": "castle", "center": {"x": 5, "y": 6, "z": 7}, "level_z": 7, "rotation_deg": 0}]}
    monkeypatch.setattr(we, "_terrain_zip", lambda p, m, j: _zip_bytes({"build.json": json.dumps(build), "heightmap.png": "x"}))

    def fake_site(s, placed, out, job):
        rel = f"sites/{s['id']}/m.glb"
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(b"glb")
        return {"id": s["id"], "name": "V", "kind": "village", "x": 1, "y": 2, "z": 3, "yaw_deg": 15, "model": rel, "footprint": {}}
    monkeypatch.setattr(we, "_site_model", fake_site)
    proj = {"name": "W", "sites": [{"id": "v1", "bim_project": "prj_1"}, {"id": "c2"}]}
    job = {"state": "running", "step": "", "done": 0, "total": 1, "error": None, "warnings": [], "sites": []}
    we._run(job, proj, "single", tmp_path / "out")
    assert job["state"] == "done", job
    out = tmp_path / "out"
    assert (out / "sites/v1/m.glb").read_bytes() == b"glb" and (out / "sites_placement.tscn").exists()
    sj = json.loads((out / "sites.json").read_text())
    assert [s["id"] for s in sj["sites"]] == ["v1", "c2"] and sj["sites"][1]["model"] is None and sj["sites"][1]["z"] == 7
    assert json.loads((out / "terrain/build.json").read_text())["sites"][0]["model"] == "../sites/v1/m.glb"


def test_world_export_rejects_zip_slip(tmp_path, monkeypatch):
    from studio import bridge
    we = bridge.WorldExport(sup=None)
    monkeypatch.setattr(we, "_terrain_zip", lambda p, m, j: _zip_bytes({"../evil.txt": "x"}))
    job = {"state": "running", "step": "", "done": 0, "total": 1, "error": None, "warnings": [], "sites": []}
    we._run(job, {"name": "W", "sites": []}, "single", tmp_path / "out")
    assert job["state"] == "error" and not (tmp_path / "evil.txt").exists()
