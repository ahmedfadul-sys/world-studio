"""Builds the code-only update package: dist/world-studio-app-<version>.zip (+ .sha256).
Run after the frontends are built (apps/*/frontend/dist). Environments and the Python runtime are NOT included: they live in the
installer and in the user's data folder, so an update is a few MB and never rebuilds anything unless a requirements file changed."""
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["studio", "shell", "apps", "requirements", "VERSION", "update.json"]
SKIP_DIRS = {"node_modules", "__pycache__", ".pytest_cache", ".venv", ".venv-blender", "data", "tests", ".vite", "src"}   # frontend src is not needed at runtime (dist is)
SKIP_SUFFIX = {".pyc", ".log"}


def keep(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    parts = set(rel.parts)
    if rel.parts[0] == "apps" and len(rel.parts) > 3 and rel.parts[2] == "frontend" and rel.parts[3] not in ("dist",):
        return False                                     # keep only frontend/dist from the web projects
    if parts & (SKIP_DIRS - {"src"}) or p.suffix in SKIP_SUFFIX:
        return False
    return True


def main() -> int:
    version = (ROOT / "VERSION").read_text().strip()
    missing = [a for a in (ROOT / "apps").glob("*/frontend") if not (a / "dist" / "index.html").exists()]
    if missing:
        print("frontend not built:", ", ".join(str(m.parent.name) for m in missing), file=sys.stderr)
        return 1
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    zpath = out / f"world-studio-app-{version}.zip"
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in INCLUDE:
            base = ROOT / name
            for p in ([base] if base.is_file() else sorted(base.rglob("*"))):
                if p.is_file() and keep(p):
                    z.write(p, p.relative_to(ROOT).as_posix())
                    n += 1
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (out / (zpath.name + ".sha256")).write_text(f"{digest}  {zpath.name}\n")
    print(f"{zpath.name}: {n} files, {zpath.stat().st_size / 1e6:.1f} MB, sha256 {digest[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
