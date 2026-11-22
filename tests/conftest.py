import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def studio_home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("STUDIO_HOME", str(h))
    for k in ("STUDIO_PYTHON_APP", "STUDIO_PYTHON_BPY", "STUDIO_UPDATE_FEED"):
        monkeypatch.delenv(k, raising=False)
    return h
