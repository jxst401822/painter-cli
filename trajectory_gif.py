"""
Generate an animated GIF showing the trajectory drawing process.
Uses PIL to render frames progressively.

Usage:
    python trajectory_gif.py <input.json> [output.gif] [--speed ms] [--size px]
"""
import json, sys, math
from PIL import Image, ImageDraw, ImageFont


def render_gif(json_path: str, gif_path: str = None,
               canvas_size: int = 600, stroke_ms: int = 800,
               point_ms: int = 15, pause_ms: int = 300,
               bg_color: str = "white", line_color: str = "#333333",
               line_width: int = 3, dot_color: str = "#e6194b",
               show_stick: bool = True):
    """
    Args:
        json_path:   Input trajectory JSON
        gif_path:    Output GIF path (default: same name .gif)
        canvas_size: Canvas pixel size (square)
        stroke_ms:   Max time for one stroke (ms) — overrides point_ms for long strokes
        point_ms:    Time per point (ms) for short strokes
        pause_ms:    Pause between strokes (ms)
        bg_color:    Background color
        line_color:  Stroke color
        line_width:  Stroke line width
        dot_color:   Color for the current drawing position dot
        show_stick:  Show X=0 reference line
    """
    if gif_path is None:
        gif_path = json_path.replace(".json", ".gif")

    with open(json_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    strokes = plan["strokes"]
    total_points = sum(len(s["points"]) for s in strokes)
    print(f"Plan: {len(strokes)} strokes, {total_points} points")

    # Compute coordinate transform: ±240 → canvas
    margin = 40
    draw_size = canvas_size - margin * 2
    scale = draw_size / 480.0  # 480 = 240*2

    def tx(x):
        return int(margin + (x + 240) * scale)

    def ty(y):
        return int(margin + (240 - y) * scale)  # flip Y

    # Pre-compute all frames
    frames = []
    durations = []

    # Base canvas with stick line
    def make_canvas():
        img = Image.new("RGB", (canvas_size, canvas_size), bg_color)
        draw = ImageDraw.Draw(img)
        if show_stick:
            sx = tx(0)
            draw.line([(sx, margin), (sx, canvas_size - margin)],
                      fill="#dddddd", width=1)
            # Label
            draw.text((sx + 3, canvas_size - margin - 12), "X=0", fill="#bbbbbb")
        return img, draw

    # Draw completed strokes on a base image
    base_img, base_draw = make_canvas()
    # Add title
    desc = plan.get("description", "")
    if desc:
        base_draw.text((margin, 8), desc[:60], fill="#999999")

    # Colors for each stroke
    colors = [
        "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
        "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
        "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
        "#ffd8b1", "#000075", "#a9a9a9", "#fffac8", "#7cb342",
    ]

    # Accumulated drawing: keep track of all completed strokes
    completed_lines = []  # list of (points, color) for already-drawn strokes

    for si, stroke in enumerate(strokes):
        pts = stroke["points"]
        color = colors[si % len(colors)]

        if len(pts) < 1:
            continue

        # Calculate per-point duration for this stroke
        if len(pts) > 1:
            per_point = min(point_ms, stroke_ms // len(pts))
            per_point = max(per_point, 5)  # minimum 5ms
        else:
            per_point = point_ms

        # Draw points progressively
        drawn_so_far = []  # points drawn in this stroke so far

        for pi in range(len(pts)):
            drawn_so_far.append(pts[pi])

            # Only render every Nth frame to keep GIF size manageable
            skip = max(1, len(pts) // 80)  # max ~80 frames per stroke
            if pi < len(pts) - 1 and pi % skip != 0:
                continue

            # Create frame
            frame, fdraw = make_canvas()
            # Add title
            fdraw.text((margin, 8), desc[:60], fill="#999999")

            # Draw all completed strokes
            for cpts, ccolor in completed_lines:
                canvas_pts = [(tx(p[0]), ty(p[1])) for p in cpts]
                if len(canvas_pts) >= 2:
                    fdraw.line(canvas_pts, fill=ccolor, width=line_width,
                               joint="curve")

            # Draw current stroke progress
            canvas_pts = [(tx(p[0]), ty(p[1])) for p in drawn_so_far]
            if len(canvas_pts) >= 2:
                fdraw.line(canvas_pts, fill=color, width=line_width,
                           joint="curve")

            # Draw current position dot
            if drawn_so_far:
                cx, cy = tx(drawn_so_far[-1][0]), ty(drawn_so_far[-1][1])
                r = 4
                fdraw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], fill=dot_color)

            frames.append(frame)
            durations.append(per_point * skip if pi < len(pts) - 1 else per_point)

        # Add completed stroke
        completed_lines.append((pts, color))

        # Pause frame between strokes
        pause_frame, _ = make_canvas()
        pdraw = ImageDraw.Draw(pause_frame)
        pdraw.text((margin, 8), desc[:60], fill="#999999")
        for cpts, ccolor in completed_lines:
            canvas_pts = [(tx(p[0]), ty(p[1])) for p in cpts]
            if len(canvas_pts) >= 2:
                pdraw.line(canvas_pts, fill=ccolor, width=line_width,
                           joint="curve")
        frames.append(pause_frame)
        durations.append(pause_ms)

        print(f"  Stroke {si+1}/{len(strokes)}: {len(pts)} points, "
              f"~{len(pts) * per_point}ms")

    # Final frame — hold longer
    durations[-1] = 2000  # 2s hold on final frame

    # Save GIF
    total_ms = sum(durations)
    print(f"\nTotal frames: {len(frames)}, Duration: ~{total_ms/1000:.1f}s")
    print(f"Saving GIF ({canvas_size}x{canvas_size})...")

    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,  # infinite loop
    )
    print(f"Saved: {gif_path}")

    # File size
    import os
    size_kb = os.path.getsize(gif_path) / 1024
    print(f"File size: {size_kb:.0f} KB")


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "unicorn_trace.json"
    gif_file = sys.argv[2] if len(sys.argv) > 2 else None

    # Parse optional --speed (ms per point)
    speed = 15
    size = 600
    for i, arg in enumerate(sys.argv):
        if arg == "--speed" and i + 1 < len(sys.argv):
            speed = int(sys.argv[i + 1])
        if arg == "--size" and i + 1 < len(sys.argv):
            size = int(sys.argv[i + 1])

    render_gif(json_file, gif_file, canvas_size=size, point_ms=speed)
