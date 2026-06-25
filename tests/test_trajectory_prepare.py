import json
import pytest

from trajectory_prepare import parse_and_map, map_point, TrajectoryError


def test_map_point_corners():
    # Normalized [0,1] -> ±240, Y flipped (image y-down -> machine y-up).
    assert map_point(0.0, 0.0) == (-240, 240)     # top-left image  -> bottom-left machine Y... see below
    assert map_point(1.0, 0.0) == (240, 240)      # top-right
    assert map_point(0.0, 1.0) == (-240, -240)    # bottom-left
    assert map_point(1.0, 1.0) == (240, -240)     # bottom-right
    assert map_point(0.5, 0.5) == (0, 0)          # center


def test_map_point_clamps():
    # Values outside [0,1] clamp to the edges.
    assert map_point(-0.5, 1.5) == (-240, -240)
    assert map_point(2.0, -1.0) == (240, 240)


def test_parse_and_map_strips_markdown_fence():
    raw = '```json\n{"description":"dragon","strokes":[{"points":[[0.1,0.2],[0.3,0.4]]}]}\n```'
    plan = parse_and_map(raw)
    assert plan["description"] == "dragon"
    pts = plan["strokes"][0]["points"]
    assert pts[0] == map_point(0.1, 0.2)
    assert pts[1] == map_point(0.3, 0.4)


def test_parse_and_map_requires_strokes():
    with pytest.raises(TrajectoryError):
        parse_and_map('{"description":"x","strokes":[]}')


def test_parse_and_map_requires_points():
    with pytest.raises(TrajectoryError):
        parse_and_map('{"description":"x","strokes":[{"points":[]}]}')


def test_parse_and_map_stroke_needs_two_points():
    with pytest.raises(TrajectoryError):
        parse_and_map('{"description":"x","strokes":[{"points":[[0.5,0.5]]}]}')


def test_parse_and_map_coords_are_ints_in_range():
    plan = parse_and_map('{"strokes":[{"points":[[0.0,0.0],[0.9,0.9]]}]}')
    for x, y in plan["strokes"][0]["points"]:
        assert isinstance(x, int) and isinstance(y, int)
        assert -240 <= x <= 240 and -240 <= y <= 240
