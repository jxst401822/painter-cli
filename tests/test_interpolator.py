"""Tests for the path interpolation module."""

from __future__ import annotations

import math

import pytest

from painter_cli.drawing.interpolator import interpolate_plan, interpolate_stroke
from painter_cli.drawing.models import Point, Stroke, StrokePlan


class TestInterpolateStroke:
    def test_short_stroke_unchanged(self):
        """Points already closer than max_step should not be modified."""
        stroke = Stroke(points=(Point(0, 0), Point(3, 4)))  # distance = 5
        result = interpolate_stroke(stroke, max_step=5)
        assert result.points == stroke.points

    def test_sparse_line_densified(self):
        """A line from (0,0) to (100,0) with max_step=5 should produce ~21 points."""
        stroke = Stroke(points=(Point(0, 0), Point(100, 0)))
        result = interpolate_stroke(stroke, max_step=5)
        assert len(result) == 21  # 0, 5, 10, ..., 100

        # First and last points preserved
        assert result.start == Point(0, 0)
        assert result.end == Point(100, 0)

        # All consecutive points are <= 5 apart
        for i in range(len(result.points) - 1):
            p1 = result.points[i]
            p2 = result.points[i + 1]
            dist = math.sqrt((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2)
            assert dist <= 5.1  # small float tolerance

    def test_diagonal_line(self):
        """Diagonal line should be interpolated correctly."""
        stroke = Stroke(points=(Point(0, 0), Point(30, 40)))  # distance = 50
        result = interpolate_stroke(stroke, max_step=10)
        assert len(result) == 6  # 0, 10, 20, 30, 40, 50

    def test_multi_segment_stroke(self):
        """Each segment is independently interpolated."""
        stroke = Stroke(points=(Point(0, 0), Point(20, 0), Point(20, 30)))
        result = interpolate_stroke(stroke, max_step=5)
        # Segment 1: (0,0)->(20,0) = 20 units -> 5 points
        # Segment 2: (20,0)->(20,30) = 30 units -> 7 points
        # Shared point at (20,0) counted once
        assert len(result) == 5 + 7 - 1  # 11 total

    def test_single_point_stroke(self):
        """A stroke with 1 point should be returned as-is."""
        stroke = Stroke(points=(Point(5, 5),))
        result = interpolate_stroke(stroke, max_step=5)
        assert result.points == stroke.points

    def test_max_step_zero_disables(self):
        """max_step=0 should disable interpolation."""
        stroke = Stroke(points=(Point(0, 0), Point(100, 0)))
        result = interpolate_stroke(stroke, max_step=0)
        assert result.points == stroke.points

    def test_original_points_preserved(self):
        """Original control points must appear in the output."""
        stroke = Stroke(points=(Point(0, 0), Point(50, 50), Point(100, 0)))
        result = interpolate_stroke(stroke, max_step=5)

        # All original points should be in the result
        for p in stroke.points:
            assert p in result.points

    def test_already_dense_stroke(self):
        """A stroke with points every 2 units shouldn't gain extra points at max_step=5."""
        points = tuple(Point(i * 2, 0) for i in range(6))  # 0, 2, 4, 6, 8, 10
        stroke = Stroke(points=points)
        result = interpolate_stroke(stroke, max_step=5)
        assert result.points == stroke.points


class TestInterpolatePlan:
    def test_all_strokes_interpolated(self):
        plan = StrokePlan(
            description="test",
            strokes=(
                Stroke(points=(Point(0, 0), Point(50, 0))),
                Stroke(points=(Point(0, 0), Point(0, 30))),
            ),
        )
        result = interpolate_plan(plan, max_step=10)
        assert len(result.strokes) == 2
        assert len(result.strokes[0]) == 6  # 50/10 + 1
        assert len(result.strokes[1]) == 4  # 30/10 + 1

    def test_description_preserved(self):
        plan = StrokePlan(
            description="my drawing",
            strokes=(Stroke(points=(Point(0, 0), Point(1, 1))),),
        )
        result = interpolate_plan(plan, max_step=5)
        assert result.description == "my drawing"
