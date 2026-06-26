"""
Contour-based image-to-trajectory pipeline for sugar painting (detail recovery).

Unlike image_to_trajectory.py (skeleton-based: Zhang-Suen thinning extracts the
*centerline* of strokes), this pipeline extracts the *contours* (outlines) of
shapes via OpenCV findContours. Contours recover outline detail that the
centerline approach loses: a unicorn's horn (triangle outline), eyes and mouth
(ring/hole outlines), facial features. Each contour becomes one stroke.

Pipeline (mirrors docs/task.md):
  1. Preprocess:  load + convert("L")  -> grayscale (alpha stripped)        [reused]
  2. Contour ext:  threshold/Canny mask -> cv2.findContours                 [NEW]
  3. Path optim:   Douglas-Peucker (approxPolyDP-equivalent) thinning       [NEW/reused]
  4. Coord map:    affine -> ±240 Y-up, proportional scale, hard clip       [NEW]
  Then reuse downstream: optimize_stroke_order -> finalize_plan (guardian) -> output.

Per the task.md pitfall table:
  - noise      -> drop contours with < 3 points and area < min_contour_area
  - non-lineart-> photo mode uses Canny edge detection (binarize_photo already does)
  - out-of-bnd-> hard clip min()/max() at the final mapping step

This is a DESKTOP script only (not wired into gif_service /trace). Its JSON output
satisfies the same ±240 contract as the skeleton pipeline, so trajectory_gif /
render-gif / trajectory_prepare work on it unchanged.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# Reuse the shared front-end (preprocess + binarize) and downstream helpers.
# image_to_trajectory.py and trajectory_prepare.py live at repo root alongside
# this file; repo root is on sys.path when run as a script and under pytest rootdir.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_to_trajectory import (  # noqa: E402
    COLORS,
    MODE_DEFAULTS,
    binarize_lineart,
    binarize_photo,
    build_plan,
    detect_source_type,
    douglas_peucker,
    load_and_resize,
    optimize_stroke_order,
    write_outputs,
)
from trajectory_prepare import finalize_plan  # noqa: E402

# ─── Mode-specific default parameters ───────────────────────────────────────
# eps_frac is a FRACTION of each contour's arc length (scale-invariant), NOT
# absolute pixels (unlike image_to_trajectory.py's --eps). 0.01 = 1% of perimeter.
MODE_DEFAULTS_CONTOUR = {
    "lineart": {"eps_frac": 0.01, "max_dim": 200, "retrieval": "list"},
    "photo":   {"eps_frac": 0.015, "max_dim": 250, "retrieval": "list"},
}

CANVAS = 240           # half-extent; full range is ±240
RETRIEVAL_MODES = {
    "external": cv2.RETR_EXTERNAL if HAS_CV2 else 0,
    "list":     cv2.RETR_LIST if HAS_CV2 else 1,
    "tree":     cv2.RETR_TREE if HAS_CV2 else 2,
}

# TODO(v2): RETR_TREE gives parent/child (outer/hole) hierarchy — exploit it to
# order each outer contour immediately before its holes, and drop a hole whose
# parent was filtered out. v1 flattens like RETR_LIST.


# ─── Contour Extraction (NEW core) ──────────────────────────────────────────

def extract_contours(mask, retrieval="list", min_contour_area=50):
    """Run findContours on a 0/1 fg mask; return list of (N,2) float arrays
    in image coordinates (x, y; y-down). Filters noise per task.md:
    drops contours with area < min_contour_area or fewer than 3 vertices.

    retrieval: 'external' (outer boundaries only — drops eyes/mouth holes),
               'list'     (all contours incl. holes, flattened — DEFAULT, recovers
                           facial features), 'tree' (all + hierarchy, v1 flattened).
    """
    if not HAS_CV2:
        raise RuntimeError("contour extraction requires opencv-python (cv2)")

    mode = RETRIEVAL_MODES[retrieval]
    contours, _ = cv2.findContours(mask, mode, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for cnt in contours:
        pts = cnt.reshape(-1, 2).astype(np.float64)            # (N,2) [x,y], y-down
        if cv2.contourArea(cnt) < min_contour_area:            # pitfall: noise
            continue
        if len(pts) < 3:                                       # pitfall: filter <3
            continue
        out.append(pts)
    # Largest first so optimize_stroke_order / area sorting see dominant shapes first
    out.sort(key=lambda a: -len(a))
    return out


# ─── Path Simplification (DP, arcLength-relative) ───────────────────────────

def approx_contour(cnt, eps_frac=0.01, closed=True):
    """Douglas-Peucker simplification with epsilon = eps_frac * arcLength
    (scale-invariant). Reuses the numpy douglas_peucker for parity with the
    skeleton pipeline. If closed, appends the first vertex to close the loop."""
    peri = cv2.arcLength(cnt.reshape(-1, 1, 2).astype(np.int32), closed)
    eps_abs = eps_frac * peri if peri > 0 else 0.0
    simp = douglas_peucker(cnt, eps_abs) if eps_abs > 0 else cnt
    if closed and len(simp) > 1 and not np.allclose(simp[0], simp[-1]):
        simp = np.vstack([simp, simp[:1]])                     # close the loop
    return simp


# ─── Coordinate Mapping (global bbox -> ±240 Y-up, hard clip) ───────────────

def scale_contours_to_canvas(contours, eps_frac, closed=True):
    """Map contour point sets to ±240 integer strokes (Y flipped: image y-down
    -> machine y-up). Global bbox proportional scale preserves relative sizes
    (eyes stay proportional to the head). Hard-clips to ±240 at the final step
    (task.md out-of-bounds pitfall)."""
    if not contours:
        return []
    all_pts = np.vstack(contours)
    cx = (all_pts[:, 0].min() + all_pts[:, 0].max()) / 2
    cy = (all_pts[:, 1].min() + all_pts[:, 1].max()) / 2
    xr = all_pts[:, 0].max() - all_pts[:, 0].min()
    yr = all_pts[:, 1].max() - all_pts[:, 1].min()
    s = (480 * 0.85) / max(xr, yr) if max(xr, yr) > 0 else 1.0   # 0.85 margin, parity

    strokes = []
    for cnt in contours:
        simp = approx_contour(cnt, eps_frac, closed)
        if len(simp) < 2:
            continue
        mapped = []
        for p in simp:
            nx = max(-CANVAS, min(CANVAS, int(round((p[0] - cx) * s))))    # hard clip
            ny = max(-CANVAS, min(CANVAS, int(round(-(p[1] - cy) * s))))   # y flip
            mapped.append([nx, ny])
        d = [mapped[0]]
        for p in mapped[1:]:
            if p != d[-1]:                                     # dedup consecutive
                d.append(p)
        if len(d) >= 2:
            strokes.append({"points": d})
    return strokes


# ─── Debug Output ────────────────────────────────────────────────────────────

def save_debug_images_contours(binary, contours, output_path):
    """Write _debug_binary.png (the binarized mask) and _debug_contours.png
    (all recovered contours overlaid in COLORS) for --debug eyeballing."""
    base = output_path.replace(".json", "")
    bin_img = Image.fromarray((binary * 255).astype(np.uint8))
    bin_img.save(f"{base}_debug_binary.png")
    print(f"  Debug: {base}_debug_binary.png")

    sz = max(binary.shape) if binary.size else 200
    canvas = Image.new("RGB", (sz, sz), "black")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(canvas)
    for i, cnt in enumerate(contours):
        c = COLORS[i % len(COLORS)]
        pts = [(int(p[0]), int(p[1])) for p in cnt]
        if len(pts) >= 2:
            draw.line(pts + [pts[0]], fill=c, width=2)          # closed polygon
    dbg_path = f"{base}_debug_contours.png"
    canvas.save(dbg_path)
    print(f"  Debug: {dbg_path}  ({len(contours)} contours)")


# ─── Library entry point ────────────────────────────────────────────────────

def image_to_trace(image_path, mode="auto", max_dim=None, eps_frac=None,
                   retrieval=None, min_contour_area=50, threshold=None,
                   closed=True, debug=False, debug_out=None):
    """Run the contour pipeline and return a plan dict ({description, strokes})
    WITHOUT writing files. This is the library entry point (mirrors
    image_to_trajectory()). main() wraps this + write_outputs for the CLI.

    mode:      'auto' | 'lineart' | 'photo'
    eps_frac:  DP epsilon as a FRACTION of arc length (0.01 = 1%). None -> mode default.
    retrieval: 'external' | 'list' | 'tree' (default 'list' recovers inner detail)
    closed:    append closing vertex so each contour draws as a closed loop
    debug:     recompute binary + contours and write debug images to debug_out path
    """
    if mode == "auto":
        arr_tmp = np.array(Image.open(image_path).convert("L"))
        mode = detect_source_type(arr_tmp)
        print(f"Auto-detected: {mode}")
    defaults = MODE_DEFAULTS_CONTOUR[mode]
    max_dim = max_dim or defaults["max_dim"]
    eps_frac = eps_frac if eps_frac is not None else defaults["eps_frac"]
    retrieval = retrieval or defaults["retrieval"]

    gray_arr, _ = load_and_resize(image_path, max_dim)
    print(f"Mode: {mode} | eps_frac={eps_frac} max_dim={max_dim} retrieval={retrieval}")
    print("Binarizing...")
    binary = (binarize_lineart(gray_arr, threshold=threshold) if mode == "lineart"
              else binarize_photo(gray_arr, min_contour_area=min_contour_area))
    print("Extracting contours...")
    contours = extract_contours(binary, retrieval=retrieval,
                                min_contour_area=min_contour_area)
    print(f"  Contours: {len(contours)}")
    if not contours:
        raise ValueError("no contours found")
    if debug:
        save_debug_images_contours(binary, contours, debug_out or image_path + ".json")
    print("Mapping to ±240...")
    strokes = scale_contours_to_canvas(contours, eps_frac, closed=closed)
    if not strokes:
        raise ValueError("no contours survived simplification")
    print("Ordering strokes...")
    strokes = optimize_stroke_order(strokes)
    print("Finalizing (guardian)...")
    plan = finalize_plan({"description": f"{mode} contour ({len(strokes)} strokes)",
                          "strokes": strokes})
    return build_plan(plan["strokes"], plan["description"])


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(image_path, output_path, mode="auto", max_dim=None, eps_frac=None,
         retrieval=None, min_contour_area=50, threshold=None, closed=True,
         debug=False):
    plan = image_to_trace(image_path, mode=mode, max_dim=max_dim, eps_frac=eps_frac,
                          retrieval=retrieval, min_contour_area=min_contour_area,
                          threshold=threshold, closed=closed, debug=debug,
                          debug_out=output_path)
    total = sum(len(st["points"]) for st in plan["strokes"])
    print(f"Final: {len(plan['strokes'])} strokes, {total} points")
    write_outputs(plan, output_path)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Contour-based image to sugar painting trajectory converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contour pipeline (recovers outline detail: eyes, mouth, horns). Each contour
becomes one stroke. Default --retrieval list recovers inner contours (holes);
use --retrieval external for silhouettes only.

Examples:
  python image_to_trace.py unicorn.jpg output.json
  python image_to_trace.py portrait.jpg out.json --mode photo
  python image_to_trace.py sketch.png out.json --retrieval external
  python image_to_trace.py face.jpg out.json --eps 0.005 --debug
        """)
    parser.add_argument("input", help="Input image path")
    parser.add_argument("output", nargs="?", default=None,
                        help="Output JSON (default: <input>_contour.json)")
    parser.add_argument("--mode", choices=["auto", "lineart", "photo"],
                        default="auto", help="Processing mode (default: auto)")
    parser.add_argument("--eps", type=float, default=None, dest="eps_frac",
                        help="Douglas-Peucker epsilon as a FRACTION of arc length "
                             "(0.01 = 1%%; not absolute px)")
    parser.add_argument("--max-dim", type=int, default=None, dest="max_dim",
                        help="Max image dimension in pixels")
    parser.add_argument("--min-contour", type=int, default=50, dest="min_contour_area",
                        help="Min contour area to keep (default: 50; lower to keep "
                             "small features like eyes)")
    parser.add_argument("--threshold", type=int, default=None,
                        help="Manual threshold (lineart only)")
    parser.add_argument("--retrieval", choices=["external", "list", "tree"],
                        default=None, help="Contour retrieval mode (default: list; "
                           "external = silhouettes only, list/tree = incl. holes)")
    closed_group = parser.add_mutually_exclusive_group()
    closed_group.add_argument("--closed", dest="closed", action="store_true",
                              default=True, help="Close each contour loop (default)")
    closed_group.add_argument("--no-closed", dest="closed", action="store_false",
                              help="Do not append closing vertex")
    parser.add_argument("--debug", action="store_true",
                        help="Save _debug_binary.png + _debug_contours.png")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    out = args.output or args.input.rsplit(".", 1)[0] + "_contour.json"
    main(
        args.input, out,
        mode=args.mode,
        max_dim=args.max_dim,
        eps_frac=args.eps_frac,
        retrieval=args.retrieval,
        min_contour_area=args.min_contour_area,
        threshold=args.threshold,
        closed=args.closed,
        debug=args.debug,
    )
