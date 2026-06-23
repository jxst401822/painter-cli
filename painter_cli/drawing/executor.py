"""Drawing executor: translates a StrokePlan into Modbus write sequences."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from painter_cli.drawing.interpolator import DEFAULT_MAX_STEP, interpolate_plan
from painter_cli.drawing.models import Point, Stroke, StrokePlan

if TYPE_CHECKING:
    from painter_cli.modbus.client import ModbusClient

logger = logging.getLogger(__name__)

# Callback signature: (stroke_index, total_strokes, point_index, total_points, current_point)
ProgressCallback = Callable[[int, int, int, int, Point], None]

# Timing constants (seconds)
PEN_SETTLE_TIME = 0.5    # Wait after pen up/down for mechanical settling
TRAVEL_TIME = 2.0         # Wait after moving to stroke start (pen up travel)


class DrawingExecutor:
    """Executes a StrokePlan by writing coordinates to the PLC via Modbus.

    Drawing sequence per stroke:
        1. Pen up   (sleep PEN_SETTLE_TIME)
        2. Move to stroke start point (sleep TRAVEL_TIME)
        3. Pen down (sleep PEN_SETTLE_TIME)
        4. Write each point at the configured interval
        5. Pen up   (sleep PEN_SETTLE_TIME)

    Supports abort via `abort()` which raises the pen immediately.
    """

    def __init__(
        self,
        modbus: ModbusClient,
        interval_s: float = 0.15,
        max_step: int = DEFAULT_MAX_STEP,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._modbus = modbus
        self._interval = interval_s
        self._max_step = max_step
        self._on_progress = on_progress
        self._abort_event = threading.Event()

    def abort(self) -> None:
        """Emergency stop: raise the pen and halt execution."""
        self._abort_event.set()
        self._modbus.pen_up()
        logger.warning("Drawing aborted — pen raised")

    @property
    def aborted(self) -> bool:
        return self._abort_event.is_set()

    def execute(self, plan: StrokePlan) -> None:
        """Execute the full drawing plan.

        If *max_step* is set, the plan is first interpolated so that
        consecutive points within each stroke are no farther apart than
        *max_step* coordinate units.  This produces smooth, continuous
        sugar flow instead of point-to-point jumps.

        Args:
            plan: The StrokePlan to execute.

        Raises:
            RuntimeError: If the execution was aborted.
        """
        self._abort_event.clear()

        if self._max_step > 0:
            original = plan.total_points
            plan = interpolate_plan(plan, self._max_step)
            logger.info(
                "Interpolated plan: %d → %d points (max_step=%d)",
                original, plan.total_points, self._max_step,
            )

        total_strokes = len(plan.strokes)

        for stroke_idx, stroke in enumerate(plan.strokes):
            if self._abort_event.is_set():
                logger.info("Aborted before stroke %d", stroke_idx + 1)
                return

            self._execute_stroke(stroke_idx, total_strokes, stroke)

        logger.info("Drawing complete: %s", plan.description)

    def _execute_stroke(
        self, stroke_idx: int, total_strokes: int, stroke: Stroke
    ) -> None:
        """Execute a single stroke."""
        total_points = len(stroke)
        logger.info(
            "Stroke %d/%d: %d points starting at %s",
            stroke_idx + 1,
            total_strokes,
            total_points,
            stroke.start,
        )

        # 1. Pen up before moving
        self._modbus.write_position(stroke.start.x, stroke.start.y, pen=False)
        time.sleep(PEN_SETTLE_TIME)
        if self._abort_event.is_set():
            return

        # 2. Move to start position (pen up) and wait for travel
        time.sleep(TRAVEL_TIME)
        if self._abort_event.is_set():
            return

        # 3. Pen down
        self._modbus.write_position(stroke.start.x, stroke.start.y, pen=True)
        time.sleep(PEN_SETTLE_TIME)
        if self._abort_event.is_set():
            return

        # 4. Trace all points
        for point_idx, point in enumerate(stroke.points):
            if self._abort_event.is_set():
                return

            self._modbus.write_position(point.x, point.y, pen=True)

            if self._on_progress:
                self._on_progress(
                    stroke_idx, total_strokes, point_idx, total_points, point
                )

            time.sleep(self._interval)

        # 5. Pen up after stroke
        self._modbus.write_position(stroke.end.x, stroke.end.y, pen=False)
        time.sleep(PEN_SETTLE_TIME)
