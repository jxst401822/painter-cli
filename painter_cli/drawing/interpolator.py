"""Path interpolation for smooth sugar painting strokes.

Ensures each stroke has uniformly spaced points so the sugar liquid
flows continuously without jumping between distant coordinates.
"""

from __future__ import annotations

import math

from painter_cli.drawing.models import Point, Stroke, StrokePlan

# Default maximum distance (in coordinate units) between consecutive points.
# Smaller values produce smoother paths but take longer to execute.
DEFAULT_MAX_STEP = 5


def interpolate_stroke(stroke: Stroke, max_step: int = DEFAULT_MAX_STEP) -> Stroke:
    """Insert intermediate points so no two consecutive points are farther
    apart than *max_step* coordinate units (Euclidean distance).

    Uses linear interpolation between each pair of consecutive points.
    Original points are always preserved.

    Args:
        stroke: The stroke to densify.
        max_step: Maximum allowed distance between consecutive points.

    Returns:
        A new Stroke with interpolated points.
    """
    if len(stroke.points) < 2 or max_step <= 0:
        return stroke

    new_points: list[Point] = [stroke.points[0]]

    for i in range(len(stroke.points) - 1):
        p1 = stroke.points[i]
        p2 = stroke.points[i + 1]

        dx = p2.x - p1.x
        dy = p2.y - p1.y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist > max_step:
            n = math.ceil(dist / max_step)
            for step in range(1, n):
                t = step / n
                x = int(round(p1.x + dx * t))
                y = int(round(p1.y + dy * t))
                new_points.append(Point(x=x, y=y))

        new_points.append(p2)

    return Stroke(points=tuple(new_points))


def interpolate_plan(plan: StrokePlan, max_step: int = DEFAULT_MAX_STEP) -> StrokePlan:
    """Apply interpolation to all strokes in a plan.

    Args:
        plan: The StrokePlan to densify.
        max_step: Maximum allowed distance between consecutive points.

    Returns:
        A new StrokePlan with densified strokes.
    """
    strokes = tuple(interpolate_stroke(s, max_step) for s in plan.strokes)
    return StrokePlan(strokes=strokes, description=plan.description)
