"""Tests for the JSON coordinate plan parser."""

import json

import pytest

from painter_cli.drawing.parser import ParseError, parse_plan


class TestParsePlan:
    def test_valid_simple_plan(self):
        data = {
            "description": "a line",
            "strokes": [
                {"points": [[0, 0], [10, 10], [20, 20]]}
            ],
        }
        plan = parse_plan(json.dumps(data))
        assert plan.description == "a line"
        assert len(plan) == 1
        assert len(plan.strokes[0]) == 3
        assert plan.strokes[0].points[0].x == 0

    def test_multiple_strokes(self):
        data = {
            "description": "two lines",
            "strokes": [
                {"points": [[0, 0], [100, 0]]},
                {"points": [[0, 0], [0, 100]]},
            ],
        }
        plan = parse_plan(json.dumps(data))
        assert len(plan) == 2
        assert plan.total_points == 4

    def test_strips_json_code_fence(self):
        data = json.dumps({
            "description": "test",
            "strokes": [{"points": [[0, 0], [10, 10]]}],
        })
        raw = f"```json\n{data}\n```"
        plan = parse_plan(raw)
        assert plan.description == "test"

    def test_strips_plain_code_fence(self):
        data = json.dumps({
            "description": "test",
            "strokes": [{"points": [[0, 0], [10, 10]]}],
        })
        raw = f"```\n{data}\n```"
        plan = parse_plan(raw)
        assert plan.description == "test"

    def test_clamps_out_of_range_coordinates(self):
        data = {
            "description": "clamped",
            "strokes": [
                {"points": [[-500, 300], [100, 100]]}
            ],
        }
        plan = parse_plan(json.dumps(data))
        assert plan.strokes[0].points[0].x == -240
        assert plan.strokes[0].points[0].y == 240

    def test_float_coordinates_are_rounded(self):
        data = {
            "description": "floats",
            "strokes": [
                {"points": [[1.7, 2.3], [10.5, -5.5]]}
            ],
        }
        plan = parse_plan(json.dumps(data))
        assert plan.strokes[0].points[0].x == 2
        assert plan.strokes[0].points[0].y == 2

    def test_invalid_json_raises_parse_error(self):
        with pytest.raises(ParseError, match="Invalid JSON"):
            parse_plan("not json at all")

    def test_missing_strokes_raises_parse_error(self):
        with pytest.raises(ParseError, match="strokes"):
            parse_plan('{"description": "no strokes"}')

    def test_empty_strokes_raises_parse_error(self):
        with pytest.raises(ParseError, match="strokes"):
            parse_plan('{"description": "empty", "strokes": []}')

    def test_stroke_with_single_point_skipped(self):
        data = {
            "description": "mixed",
            "strokes": [
                {"points": [[0, 0]]},  # invalid: only 1 point
                {"points": [[10, 10], [20, 20]]},
            ],
        }
        plan = parse_plan(json.dumps(data))
        assert len(plan) == 1

    def test_all_strokes_invalid_raises_parse_error(self):
        data = {
            "description": "all bad",
            "strokes": [
                {"points": [[0, 0]]},
            ],
        }
        with pytest.raises(ParseError, match="No valid strokes"):
            parse_plan(json.dumps(data))

    def test_not_a_dict_raises_parse_error(self):
        with pytest.raises(ParseError, match="JSON object"):
            parse_plan("[1, 2, 3]")

    def test_invalid_point_format_skipped(self):
        data = {
            "description": "bad points",
            "strokes": [
                {"points": [[0, 0], [1, 2, 3], [10, 10]]}
            ],
        }
        plan = parse_plan(json.dumps(data))
        assert len(plan.strokes[0]) == 2

    def test_empty_description_defaults_to_empty(self):
        data = {
            "strokes": [{"points": [[0, 0], [10, 10]]}],
        }
        plan = parse_plan(json.dumps(data))
        assert plan.description == ""
