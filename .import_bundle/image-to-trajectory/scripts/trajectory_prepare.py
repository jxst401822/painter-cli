#!/usr/bin/env python3
"""
trajectory_prepare.py — contract guardian for model-traced sugar-painting trajectories.

The LLM emits normalized [0,1] coordinates. This module validates that JSON,
maps to the machine's ±240 integer space (Y flipped: image y-down -> machine
y-up), and renders an SVG preview. Pure stdlib so it runs on the quantum-bot
device (no PIL/numpy).

Contract (matches painter_cli.servo.json_loader + painter_cli.drawing.parser):
    {"description": str, "strokes": [{"points": [[x,y], ...]}]}
with integer x,y in [-240, 240], each stroke >= 2 points.
"""
import json
import re
import math

CANVAS = 240          # half-extent; full range is ±240
STICK_TOL = 3         # |x| <= STICK_TOL counts as touching the X=0 stick axis


class TrajectoryError(Exception):
    """Raised when the model's trajectory JSON violates the contract."""


def _strip_code_fences(text):
    text = text.strip()
    m = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def map_point(nx, ny):
    """Map normalized [0,1] -> (x, y) integer in [-240, 240], Y flipped."""
    nx = min(1.0, max(0.0, float(nx)))
    ny = min(1.0, max(0.0, float(ny)))
    x = int(round(nx * (2 * CANVAS) - CANVAS))
    y = int(round((1.0 - ny) * (2 * CANVAS) - CANVAS))
    return x, y


def _parse_point(p):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise TrajectoryError(f"point must be [nx, ny], got {p!r}")
    try:
        return float(p[0]), float(p[1])
    except (TypeError, ValueError):
        raise TrajectoryError(f"point coordinates must be numeric, got {p!r}")


def dedup_points(points):
    """Drop consecutive duplicate points."""
    out = []
    for p in points:
        if not out or out[-1] != p:
            out.append(p)
    return out


def parse_and_map(raw_json):
    """Validate the model's normalized JSON and map to ±240 integer strokes."""
    cleaned = _strip_code_fences(raw_json)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise TrajectoryError(f"invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise TrajectoryError(f"expected JSON object, got {type(data).__name__}")

    description = data.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    raw_strokes = data.get("strokes")
    if not isinstance(raw_strokes, list) or not raw_strokes:
        raise TrajectoryError("missing or empty strokes array")

    strokes = []
    for i, rs in enumerate(raw_strokes):
        if not isinstance(rs, dict):
            raise TrajectoryError(f"stroke {i} must be an object")
        raw_points = rs.get("points")
        if not isinstance(raw_points, list) or not raw_points:
            raise TrajectoryError(f"stroke {i} must contain a non-empty points array")
        pts = [map_point(*_parse_point(p)) for p in raw_points]
        pts = dedup_points(pts)
        if len(pts) < 2:
            raise TrajectoryError(f"stroke {i} has fewer than 2 points after dedup")
        strokes.append({"points": pts})

    return {"description": description, "strokes": strokes}
