"""Data models for drawing plans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    """A single 2D coordinate in the HMI coordinate system.

    Attributes:
        x: X position in [-240, 240]. Positive = right.
        y: Y position in [-240, 240]. Positive = up.
    """

    x: int
    y: int

    def __repr__(self) -> str:
        return f"({self.x}, {self.y})"


@dataclass(frozen=True)
class Stroke:
    """A continuous pen-down path consisting of ordered points.

    The pen is lowered at the first point and raised after the last point.
    """

    points: tuple[Point, ...]

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]

    def __len__(self) -> int:
        return len(self.points)


@dataclass(frozen=True)
class StrokePlan:
    """A complete drawing plan composed of one or more strokes.

    The drawing arm executes strokes sequentially, lifting the pen
    between each stroke.

    Attributes:
        strokes: Ordered sequence of strokes to draw.
        description: Human-readable description of the shape.
    """

    strokes: tuple[Stroke, ...]
    description: str

    @property
    def total_points(self) -> int:
        return sum(len(s) for s in self.strokes)

    def __len__(self) -> int:
        return len(self.strokes)
