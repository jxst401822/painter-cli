"""Parse JSON coordinate plans into StrokePlan objects."""

from __future__ import annotations

import json
import logging
import re

from painter_cli.drawing.models import Point, Stroke, StrokePlan
from painter_cli.modbus.encoder import clamp

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised when input cannot be parsed into a valid StrokePlan."""


def parse_plan(raw: str) -> StrokePlan:
    """Parse a JSON string into a StrokePlan.

    Handles markdown code fences, validates structure, and clamps
    coordinates to the valid range [-240, 240].

    Args:
        raw: JSON string with drawing plan.

    Returns:
        A validated StrokePlan.

    Raises:
        ParseError: If the input is invalid JSON, missing required
            fields, or has no strokes/points.
    """
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ParseError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ParseError(f"Expected a JSON object, got {type(data).__name__}")

    description = data.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    raw_strokes = data.get("strokes")
    if not isinstance(raw_strokes, list) or len(raw_strokes) == 0:
        raise ParseError("Missing or empty 'strokes' array")

    strokes = []
    for i, raw_stroke in enumerate(raw_strokes):
        stroke = _parse_stroke(raw_stroke, i)
        if stroke is not None:
            strokes.append(stroke)

    if not strokes:
        raise ParseError("No valid strokes found in input")

    return StrokePlan(strokes=tuple(strokes), description=description)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    pattern = r"^```(?:json|JSON)?\s*\n?(.*?)\n?\s*```$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_stroke(raw: dict, index: int) -> Stroke | None:
    """Parse a single stroke object from the JSON data."""
    if not isinstance(raw, dict):
        logger.warning("Stroke %d is not a dict, skipping", index)
        return None

    raw_points = raw.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        logger.warning(
            "Stroke %d has < 2 points (%s), skipping",
            index,
            len(raw_points) if raw_points else 0,
        )
        return None

    points = []
    for j, raw_point in enumerate(raw_points):
        point = _parse_point(raw_point, index, j)
        if point is not None:
            points.append(point)

    if len(points) < 2:
        logger.warning("Stroke %d has < 2 valid points after parsing, skipping", index)
        return None

    return Stroke(points=tuple(points))


def _parse_point(raw: list | tuple, stroke_idx: int, point_idx: int) -> Point | None:
    """Parse a single [x, y] coordinate pair, clamping to valid range."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        logger.warning(
            "Invalid point at stroke %d, point %d: %s", stroke_idx, point_idx, raw
        )
        return None

    try:
        x = int(round(float(raw[0])))
        y = int(round(float(raw[1])))
    except (TypeError, ValueError):
        logger.warning(
            "Non-numeric point at stroke %d, point %d: %s", stroke_idx, point_idx, raw
        )
        return None

    x_clamped = clamp(x)
    y_clamped = clamp(y)
    if x_clamped != x or y_clamped != y:
        logger.info(
            "Clamped point (%d, %d) -> (%d, %d) at stroke %d, point %d",
            x, y, x_clamped, y_clamped, stroke_idx, point_idx,
        )

    return Point(x=x_clamped, y=y_clamped)
