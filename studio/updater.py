"""Auto-update from GitHub Releases (code only: environments are never rebuilt unless a requirements file changed).

Release convention: tag `vX.Y.Z`, asset `world-studio-app-X.Y.Z.zip` (+ optional `world-studio-app-X.Y.Z.zip.sha256`).
Versions are unpacked next to each other in <home>/app/<version>/ and switched atomically through <home>/app/current.json,
so a failed or interrupted update leaves the running version untouched and `rollback()` returns to the previous one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import paths, settings

UA = "WorldStudio-Updater"


class UpdateError(RuntimeError):
    pass


def _cfg() -> dict:
    try:
        return json.loads((paths.CODE_ROOT / "update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def vkey(v: str) -> tuple:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def feed_url() -> str:
    env = os.environ.get("STUDIO_UPDATE_FEED")
    if env:
        return env
    repo = _cfg().get("repo", "")
    if not repo or repo.startswith("OWNER/"):
        raise UpdateError("update source not configured (set \"repo\" in update.json)")
    return f"https://api.github.com/repos/{repo}/releases/latest"


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(current: str | None = None) -> dict:
    """{'available': bool, 'current', 'latest', 'notes', 'asset_url', 'sha256_url'} — never raises for network problems."""
    cur = current or paths.read_version()
    try:
        rel = json.loads(_get(feed_url()))
    except UpdateError as e:
        return {"available": False, "current": cur, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "current": cur, "error": f"cannot reach the update server: {e}"}
    latest = str(rel.get("tag_name", "")).lstrip("v")
    prefix = _cfg().get("asset_prefix", "world-studio-app-")
    assets = {a["name"]: a.get("browser_download_url") for a in rel.get("assets", []) if a.get("name")}
    zname = next((n for n in assets if n.startswith(prefix) and n.endswith(".zip")), None)
    out = {"available": False, "current": cur, "latest": latest, "notes": rel.get("body", "")[:2000]}
    if latest and zname and vkey(latest) > vkey(cur):
        out.update(available=True, asset_url=assets[zname], sha256_url=assets.get(zname + ".sha256"), asset_name=zname)
    settings.save({"last_update_check": int(time.time())})
    return out


def _versions_dir() -> Path:
    return paths.sub("app")


def _pointer() -> Path:
    return _versions_dir() / "current.json"


def pointer() -> dict:
    try:
        return json.loads(_pointer().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def active_root() -> Path:
    """Code folder to run: the activated downloaded version when valid, else the code that shipped with the installer."""
    cur = pointer().get("current")
    if cur:
        d = _versions_dir() / cur
        if (d / "studio").is_dir() and (d / "VERSION").exists():
            return d
    return paths.CODE_ROOT


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for info in zf.infolist():
        target = (dest / info.filename).resolve()
        if root != target and root not in target.parents:
            raise UpdateError(f"unsafe path in update archive: {info.filename}")       # zip-slip
    zf.extractall(dest)


def download_and_stage(info: dict, progress: Callable[[int, int], None] | None = None) -> str:
    """Download → verify SHA-256 → unpack to app/<version>/ → activate. Returns the new version."""
    if not info.get("available"):
        raise UpdateError("no update available")
    ver = info["latest"]
    tmp = _versions_dir() / f".dl-{ver}.zip"
    req = urllib.request.Request(info["asset_url"], headers={"User-Agent": UA})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    want = None
    if info.get("sha256_url"):
        want = _get(info["sha256_url"]).decode().split()[0].lower()
    if want and want != h.hexdigest():
        tmp.unlink(missing_ok=True)
        raise UpdateError("checksum mismatch: the download is corrupted or tampered with; nothing was installed")
    stage = _versions_dir() / f".stage-{ver}"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        with zipfile.ZipFile(tmp) as zf:
            _safe_extract(zf, stage)
        inner = stage if (stage / "studio").is_dir() else next((d for d in stage.iterdir() if (d / "studio").is_dir()), None)
        if inner is None or not (inner / "VERSION").exists():
            raise UpdateError("the update archive does not look like a World Studio release")
        final = _versions_dir() / ver
        shutil.rmtree(final, ignore_errors=True)
        shutil.move(str(inner), str(final))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        tmp.unlink(missing_ok=True)
    activate(ver)
    _prune(keep=3)
    return ver


def activate(ver: str) -> None:
    p = pointer()
    prev = p.get("current")
    new = {"current": ver, "previous": prev if prev != ver else p.get("previous")}
    tmp = _pointer().with_suffix(".tmp")
    tmp.write_text(json.dumps(new), encoding="utf-8")
    os.replace(tmp, _pointer())              # atomic switch


def rollback() -> str:
    p = pointer()
    prev = p.get("previous")
    if prev and (_versions_dir() / prev / "studio").is_dir():
        activate(prev)
        return prev
    if p.get("current"):                      # no previous download: go back to the installer's own code
        _pointer().unlink(missing_ok=True)
        return paths.read_version(paths.CODE_ROOT)
    raise UpdateError("nothing to roll back to")


def _prune(keep: int) -> None:
    p = pointer()
    live = {p.get("current"), p.get("previous")}
    dirs = sorted((d for d in _versions_dir().iterdir() if d.is_dir() and not d.name.startswith(".") and d.name not in live), key=lambda d: vkey(d.name), reverse=True)
    for d in dirs[max(0, keep - len(live)):]:
        shutil.rmtree(d, ignore_errors=True)
