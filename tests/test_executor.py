"""Tests for the drawing executor with a mock Modbus client."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call

import pytest

from painter_cli.drawing.executor import DrawingExecutor
from painter_cli.drawing.models import Point, Stroke, StrokePlan


class FakeModbus:
    """A mock Modbus client that records all write_position calls."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int, bool]] = []
        self.pen_up_calls = 0
        self.connected = True

    def write_position(self, x: int, y: int, pen: bool) -> None:
        self.writes.append((x, y, pen))

    def pen_up(self) -> None:
        self.pen_up_calls += 1


@pytest.fixture
def fake_modbus():
    return FakeModbus()


@pytest.fixture
def simple_plan():
    return StrokePlan(
        description="test line",
        strokes=(
            Stroke(points=(Point(10, 20), Point(30, 40), Point(50, 60))),
        ),
    )


@pytest.fixture
def multi_stroke_plan():
    return StrokePlan(
        description="two strokes",
        strokes=(
            Stroke(points=(Point(0, 0), Point(10, 10))),
            Stroke(points=(Point(-20, -20), Point(-30, -30))),
        ),
    )


class TestDrawingExecutor:
    def test_single_stroke_write_sequence(self, fake_modbus, simple_plan):
        """Verify the write order: pen up at start, pen down, trace, pen up at end."""
        executor = DrawingExecutor(fake_modbus, interval_s=0, max_step=0)
        executor.execute(simple_plan)

        writes = fake_modbus.writes
        # First write: pen up at stroke start
        assert writes[0] == (10, 20, False)
        # Second write: pen down at stroke start
        assert writes[1] == (10, 20, True)
        # Trace all points with pen down
        assert writes[2] == (10, 20, True)
        assert writes[3] == (30, 40, True)
        assert writes[4] == (50, 60, True)
        # Last write: pen up at stroke end
        assert writes[5] == (50, 60, False)

    def test_multi_stroke_pen_up_between(self, fake_modbus, multi_stroke_plan):
        """Pen should be up between strokes."""
        executor = DrawingExecutor(fake_modbus, interval_s=0, max_step=0)
        executor.execute(multi_stroke_plan)

        writes = fake_modbus.writes
        # After first stroke pen up, second stroke starts with pen up
        pen_states = [w[2] for w in writes]
        # Should have pen up (False) writes between strokes
        assert pen_states.count(False) >= 3  # start up, end up of stroke1, start up of stroke2, end up of stroke2

    def test_progress_callback_called(self, fake_modbus, simple_plan):
        progress_calls = []

        def on_progress(stroke_idx, total_strokes, point_idx, total_points, point):
            progress_calls.append((stroke_idx, total_strokes, point_idx, total_points))

        executor = DrawingExecutor(fake_modbus, interval_s=0, max_step=0, on_progress=on_progress)
        executor.execute(simple_plan)

        assert len(progress_calls) == 3  # 3 points in the stroke
        assert progress_calls[0] == (0, 1, 0, 3)
        assert progress_calls[1] == (0, 1, 1, 3)
        assert progress_calls[2] == (0, 1, 2, 3)

    def test_abort_stops_execution(self, fake_modbus):
        """Aborting should stop writing and raise the pen."""
        plan = StrokePlan(
            description="long line",
            strokes=(
                Stroke(points=tuple(Point(i, i) for i in range(50))),
            ),
        )

        executor = DrawingExecutor(fake_modbus, interval_s=0, max_step=0)

        # Abort after a few points
        call_count = 0
        original_write = fake_modbus.write_position

        def write_with_abort(x, y, pen):
            nonlocal call_count
            call_count += 1
            original_write(x, y, pen)
            if call_count >= 5:
                executor.abort()

        fake_modbus.write_position = write_with_abort
        executor.execute(plan)

        # Should not have written all 50 points (plus overhead)
        assert len(fake_modbus.writes) < 55
        # Pen up should have been called during abort
        assert fake_modbus.pen_up_calls >= 1

    def test_empty_plan_no_writes(self, fake_modbus):
        plan = StrokePlan(description="empty", strokes=())
        executor = DrawingExecutor(fake_modbus, interval_s=0, max_step=0)
        executor.execute(plan)
        assert len(fake_modbus.writes) == 0

    def test_interpolation_adds_points(self, fake_modbus):
        """With max_step > 0, sparse strokes should be densified."""
        plan = StrokePlan(
            description="sparse line",
            strokes=(
                Stroke(points=(Point(0, 0), Point(100, 0))),
            ),
        )
        executor = DrawingExecutor(fake_modbus, interval_s=0, max_step=5)
        executor.execute(plan)

        # Without interpolation: 2 points + 3 overhead = 5 writes
        # With interpolation (max_step=5 on a 100-unit line): ~21 points + overhead
        pen_down_writes = [w for w in fake_modbus.writes if w[2] is True]
        assert len(pen_down_writes) > 10  # significantly more than the original 2


class TestStrokePlan:
    def test_total_points(self):
        plan = StrokePlan(
            description="test",
            strokes=(
                Stroke(points=(Point(0, 0), Point(1, 1))),
                Stroke(points=(Point(2, 2), Point(3, 3), Point(4, 4))),
            ),
        )
        assert plan.total_points == 5
        assert len(plan) == 2

    def test_stroke_start_end(self):
        stroke = Stroke(points=(Point(10, 20), Point(30, 40), Point(50, 60)))
        assert stroke.start == Point(10, 20)
        assert stroke.end == Point(50, 60)
        assert len(stroke) == 3
