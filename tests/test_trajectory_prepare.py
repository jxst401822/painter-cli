import json
import pytest

from trajectory_prepare import parse_and_map, map_point, TrajectoryError
from trajectory_prepare import enforce_stick_adhesion, STICK_TOL
from trajectory_prepare import render_svg
from trajectory_prepare import finalize_plan


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
    raw = '```json\n{"description":"dragon","strokes":[{"points":[[0.5,0.2],[0.3,0.4]]}]}\n```'
    plan = parse_and_map(raw)
    assert plan["description"] == "dragon"
    pts = plan["strokes"][0]["points"]
    assert pts[0] == map_point(0.5, 0.2)
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


def _plan(strokes):
    return {"description": "", "strokes": [{"points": list(s)} for s in strokes]}


def test_stick_adhesion_noop_when_already_anchored():
    # First stroke already crosses x=0.
    plan = _plan([[[0, 10], [5, 20]], [[100, 0], [100, 50]]])
    out = enforce_stick_adhesion(plan)
    assert out["strokes"][0]["points"][0] == [0, 10]  # unchanged


def test_stick_adhesion_prepends_anchor_to_nearest_stroke():
    # No stroke crosses x=0; nearest stroke's first point is (10, 30).
    plan = _plan([[[10, 30], [50, 60]], [[20, -20], [80, -40]]])
    out = enforce_stick_adhesion(plan)
    # The anchor [0, y] is prepended to the stroke with the point closest to x=0.
    first = out["strokes"][0]["points"][0]
    assert first[0] == 0
    # Anchor y is the y of the closest point (here (10,30) -> y=30).
    assert first[1] == 30


def test_stick_adhesion_picks_truly_nearest_point():
    # Second stroke has a point at x=4, closer than first stroke's x=10.
    plan = _plan([[[10, 30], [50, 60]], [[4, -5], [80, -40]]])
    out = enforce_stick_adhesion(plan)
    anchored = out["strokes"][1]["points"][0]
    assert anchored[0] == 0
    assert anchored[1] == -5


def test_render_svg_contains_paths_and_coords():
    plan = _plan([[[0, 0], [100, 100]], [[0, 0], [-100, -100]]])
    svg = render_svg(plan, size=600)
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # Two strokes -> two <path> elements.
    assert svg.count("<path") == 2


def test_render_svg_is_valid_xml():
    import xml.etree.ElementTree as ET
    plan = _plan([[[0, 0], [240, 240]]])
    svg = render_svg(plan)
    ET.fromstring(svg)  # raises if not well-formed


def test_finalize_plan_dedups_and_keeps_anchored():
    # already ±240, already crosses x=0 → adhesion no-op, dedup removes dup
    plan = {"description": "x", "strokes": [{"points": [[0, 0], [10, 10], [10, 10], [20, 20]]}]}
    out = finalize_plan(plan)
    assert out["strokes"][0]["points"] == [[0, 0], [10, 10], [20, 20]]


def test_finalize_plan_anchors_when_no_stick_crossing():
    plan = {"description": "x", "strokes": [{"points": [[40, 5], [80, 50]]}]}
    out = finalize_plan(plan)
    # nearest point to x=0 is [40,5] → anchor [0,5] prepended
    assert out["strokes"][0]["points"][0] == [0, 5]


def test_finalize_plan_rejects_short_stroke():
    plan = {"description": "x", "strokes": [{"points": [[40, 5]]}]}
    with pytest.raises(TrajectoryError):
        finalize_plan(plan)


def test_finalize_plan_does_not_remap_coordinates():
    # ±240 values must pass through unchanged (no [0,1] mapping applied)
    plan = {"description": "x", "strokes": [{"points": [[0, -240], [240, 240]]}]}
    out = finalize_plan(plan)
    pts = out["strokes"][0]["points"]
    # anchored already (x=0 present), so no prepend; values intact
    assert [240, 240] in pts
    assert [0, -240] in pts
