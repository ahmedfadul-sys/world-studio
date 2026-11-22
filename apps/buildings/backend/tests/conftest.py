import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bimgame.schema import (Column, Door, Floor, Project, Roof, Stair, Wall, Window, new_project)  # noqa: E402


def house(name="house") -> Project:
    """4 walls (rectangle 6x4), door+window, floor, column, roof, stair."""
    p = new_project(name)
    L = "lvl_0"
    p.elements += [
        Wall(id="w_s", level_id=L, a=(0, 0), b=(6, 0), thickness=0.2),
        Wall(id="w_e", level_id=L, a=(6, 0), b=(6, 4), thickness=0.2),
        Wall(id="w_n", level_id=L, a=(6, 4), b=(0, 4), thickness=0.2),
        Wall(id="w_w", level_id=L, a=(0, 4), b=(0, 0), thickness=0.2),
        Door(id="d1", level_id=L, wall_id="w_s", offset=2.0),
        Window(id="n1", level_id=L, wall_id="w_s", offset=4.5),
        Floor(id="f1", level_id=L, polygon=[(0, 0), (6, 0), (6, 4), (0, 4)], thickness=0.2),
        Column(id="c1", level_id=L, pos=(3, 2), shape="round", width=0.4),
        Roof(id="r1", level_id=L, kind="gable", polygon=[(0, 0), (6, 0), (6, 4), (0, 4)]),
        Stair(id="s1", level_id=L, start=(1, 1), steps=10),
    ]
    return Project.model_validate(p.model_dump())


@pytest.fixture
def proj() -> Project:
    return house()
