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


def enforce_stick_adhesion(plan, stick_tol=STICK_TOL):
    """Ensure at least one stroke touches the X=0 stick axis.

    If no stroke crosses |x| <= stick_tol, prepend [0, y] to whichever
    stroke contains the point closest to x=0 (using that point's y).
    """
    def crosses_stick(stroke):
        return any(abs(p[0]) <= stick_tol for p in stroke["points"])

    if any(crosses_stick(s) for s in plan["strokes"]):
        return plan

    best_stroke = 0
    best_point_idx = 0
    best_dist = float("inf")
    for si, st in enumerate(plan["strokes"]):
        for pi, p in enumerate(st["points"]):
            d = abs(p[0])
            if d < best_dist:
                best_dist = d
                best_stroke = si
                best_point_idx = pi

    anchor = [0, plan["strokes"][best_stroke]["points"][best_point_idx][1]]
    plan["strokes"][best_stroke]["points"] = [anchor] + plan["strokes"][best_stroke]["points"]
    return plan


def finalize_plan(plan, stick_tol=STICK_TOL):
    """Guardian for an ALREADY-±240 plan: dedup, enforce stick adhesion, validate.
    Does NO coordinate mapping (unlike parse_and_map, which maps normalized->±240
    then calls this)."""
    strokes = []
    for i, st in enumerate(plan["strokes"]):
        pts = dedup_points(st["points"])
        if len(pts) < 2:
            raise TrajectoryError(f"stroke {i} has fewer than 2 points after dedup")
        strokes.append({"points": pts})
    plan = {"description": plan.get("description", ""), "strokes": strokes}
    plan = enforce_stick_adhesion(plan, stick_tol=stick_tol)
    return plan


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
        strokes.append({"points": pts})

    return finalize_plan({"description": description, "strokes": strokes})


COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
    "#ffd8b1", "#000075", "#a9a9a9", "#fffac8", "#7cb342",
]


def render_svg(plan, size=600):
    """Render a plan (±240, Y-up) to an SVG string. Pure stdlib."""
    strokes = plan["strokes"]
    pad = 30
    draw = size - 2 * pad
    scale = draw / (2 * CANVAS)

    def tx(x):
        return round(pad + (x + CANVAS) * scale)

    def ty(y):
        return round(pad + (CANVAS - y) * scale)  # Y flip for SVG (y-down)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">',
        f'<rect width="{size}" height="{size}" fill="#111"/>',
        # stick axis
        f'<line x1="{tx(0)}" y1="{pad}" x2="{tx(0)}" y2="{size - pad}" '
        f'stroke="#444" stroke-width="1"/>',
    ]
    for i, st in enumerate(strokes):
        c = COLORS[i % len(COLORS)]
        pts = st["points"]
        d = " ".join(
            f"{'M' if j == 0 else 'L'} {tx(p[0])} {ty(p[1])}"
            for j, p in enumerate(pts)
        )
        parts.append(
            f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Validate + map a model-traced trajectory to ±240 and emit SVG.")
    ap.add_argument("input", help="Input JSON (normalized [0,1] or already ±240)")
    ap.add_argument("output", nargs="?", default=None, help="Output ±240 JSON path")
    ap.add_argument("--svg", default=None, help="Also write an SVG preview here")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw = f.read()
    plan = parse_and_map(raw)

    out_path = args.output or args.input.rsplit(".", 1)[0] + "_plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"Written: {out_path}")

    svg_path = args.svg or out_path.replace(".json", ".svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(render_svg(plan))
    print(f"SVG: {svg_path}")


if __name__ == "__main__":
    main()
