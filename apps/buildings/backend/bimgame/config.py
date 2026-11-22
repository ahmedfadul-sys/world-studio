"""Runtime configuration (environment-driven, local-first)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("BIM_DATA_DIR", ROOT / "data")))
    blender_scripts: Path = ROOT / "blender_scripts"
    # Either a Blender binary (run as `blender -b -P script -- args`) or a Python
    # interpreter that can `import bpy` (run as `python script args`).
    blender_cmd: str | None = os.environ.get("BIM_BLENDER_CMD")
    blender_python: str = os.environ.get(
        "BIM_BLENDER_PYTHON", str(ROOT / ".venv-blender" / "bin" / "python")
    )
    blender_timeout_s: int = int(os.environ.get("BIM_BLENDER_TIMEOUT", "300"))
    blender_max_rss_mb: int = int(os.environ.get("BIM_BLENDER_MAX_RSS_MB", "3500"))
    log_level: str = os.environ.get("BIM_LOG_LEVEL", "INFO")

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bim.sqlite3"

    def blender_command(self, script: str, *args: str) -> list[str]:
        """Build the subprocess command for a Blender script."""
        path = str(self.blender_scripts / script)
        if self.blender_cmd:
            return [self.blender_cmd, "-b", "--factory-startup", "-P", path, "--", *args]
        return [self.blender_python, path, *args]  # missing interpreter is reported by the runner, never masked


def get_settings() -> Settings:
    return Settings()
