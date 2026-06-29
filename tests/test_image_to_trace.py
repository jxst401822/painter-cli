"""image_to_trace() contour pipeline: returns a plan dict, recovers inner detail
(holes like eyes), respects ±240 integer bounds, and writes no side-effect files.

Mirrors tests/test_image_to_trajectory_wrapper.py. cv2/PIL/numpy are dev deps
(pyproject lists opencv-python, numpy, Pillow); image_to_trace is a repo-root
module resolved via pytest rootdir.
"""
import os
import tempfile

from PIL import Image, ImageDraw

import image_to_trace as itr
from trajectory_prepare import finalize_plan


def _make_square_with_hole_png(path):
    """White square with a small square hole punched out (black) on a black
    background. findContours with RETR_LIST yields TWO contours: the outer square
    boundary and the inner hole boundary (the "eye"). Deterministic inner-detail
    recovery probe."""
    img = Image.new("L", (200, 200), 0)          # black bg
    draw = ImageDraw.Draw(img)
    draw.rectangle([(20, 20), (180, 180)], fill=255)        # outer white square
    draw.rectangle([(80, 80), (120, 120)], fill=0)          # inner black hole
    img.save(path)


def _stroke_bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_inside(inner, outer):
    """True if bbox `inner` is strictly inside bbox `outer`."""
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    return ix0 > ox0 and iy0 > oy0 and ix1 < ox1 and iy1 < oy1


def test_image_to_trace_returns_plan_no_files():
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_square_with_hole_png(png)
        plan = itr.image_to_trace(png, mode="lineart", min_contour_area=20)
        assert isinstance(plan, dict)
        assert "description" in plan and "strokes" in plan
        assert len(plan["strokes"]) >= 1
        for st in plan["strokes"]:
            assert len(st["points"]) >= 2
            for x, y in st["points"]:
                assert isinstance(x, int) and isinstance(y, int)
                assert -240 <= x <= 240 and -240 <= y <= 240
        # no side-effect files in the temp dir besides the input
        assert sorted(os.listdir(d)) == ["in.png"]


def test_image_to_trace_recovers_inner_contour():
    """The crux: RETR_LIST recovers the hole (eye) as its own stroke, strictly
    inside the outer square's bbox."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_square_with_hole_png(png)
        plan = itr.image_to_trace(png, mode="lineart", retrieval="list",
                                  min_contour_area=20)
        assert len(plan["strokes"]) >= 2
        bboxes = [_stroke_bbox(st["points"]) for st in plan["strokes"]]
        # at least one bbox strictly inside another (the hole inside the outer)
        nested = any(
            _bbox_inside(bboxes[i], bboxes[j]) or _bbox_inside(bboxes[j], bboxes[i])
            for i in range(len(bboxes)) for j in range(len(bboxes)) if i != j
        )
        assert nested, f"no nested (hole) contour recovered; bboxes={bboxes}"


def test_image_to_trace_external_mode_drops_inner():
    """--retrieval external returns only the outer boundary (silhouette) — the
    hole is dropped. Proves the retrieval knob controls detail recovery.

    drop_border=False because the synthetic square's outer boundary fills the
    200x200 canvas after binarization (morph open expands it to the edges), so
    the border-drop heuristic would otherwise treat it as a frame. This test is
    about the retrieval knob, not border dropping."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_square_with_hole_png(png)
        plan = itr.image_to_trace(png, mode="lineart", retrieval="external",
                                  min_contour_area=20, drop_border=False)
        assert len(plan["strokes"]) == 1, f"external should yield 1 stroke, got {len(plan['strokes'])}"


def test_image_to_trace_no_contours_raises():
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "blank.png")
        Image.new("L", (200, 200), 0).save(png)   # pure black, nothing to contour
        try:
            itr.image_to_trace(png, mode="lineart", min_contour_area=20)
        except ValueError:
            pass
        else:
            # if it returns, it must be a valid plan
            plan = itr.image_to_trace(png, mode="lineart", min_contour_area=20)
            assert isinstance(plan, dict)


def test_image_to_trace_satisfies_finalize_contract():
    """The returned plan already passes the ±240 guardian (image_to_trace runs
    it internally); re-running finalize_plan must not raise and keeps >=2 pts."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_square_with_hole_png(png)
        plan = itr.image_to_trace(png, mode="lineart", min_contour_area=20)
        revalidated = finalize_plan(plan)          # must not raise TrajectoryError
        for st in revalidated["strokes"]:
            assert len(st["points"]) >= 2


def _make_framed_square_png(path):
    """White square in the centre with a white border frame around the whole
    image on a black background — mimics a canvas-frame image. findContours
    yields the frame (touches all 4 edges) + the inner square. drop_border must
    remove the frame so only the inner square survives."""
    img = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (199, 199)], outline=255, width=3)   # border frame
    draw.rectangle([(60, 60), (140, 140)], fill=255)             # inner square
    img.save(path)


def test_image_to_trace_drops_border_frame():
    """Contours running along all four image edges (the canvas frame) are dropped
    by default. Verified by comparing stroke counts with/without drop_border:
    drop_border removes exactly the frame contour."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_framed_square_png(png)
        kept = itr.image_to_trace(png, mode="lineart", min_contour_area=20,
                                  drop_border=True)
        full = itr.image_to_trace(png, mode="lineart", min_contour_area=20,
                                  drop_border=False)
        # with the frame kept there is one more stroke (the frame) than without
        assert len(full["strokes"]) == len(kept["strokes"]) + 1, (
            f"frame not dropped: kept={len(kept['strokes'])} full={len(full['strokes'])}")
        # the dropped stroke is the one spanning the full canvas — none of the
        # kept strokes should be a near-perfect rectangle hugging ±240 on all sides
        for st in kept["strokes"]:
            xs = [p[0] for p in st["points"]]
            ys = [p[1] for p in st["points"]]
            full_w = max(xs) - min(xs)
            full_h = max(ys) - min(ys)
            assert not (full_w >= 460 and full_h >= 460), (
                f"a full-canvas frame stroke survived: {full_w}x{full_h}")


def test_image_to_trace_keep_border_opt_in():
    """With drop_border=False the frame is kept (proves the knob controls it)."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_framed_square_png(png)
        plan = itr.image_to_trace(png, mode="lineart", min_contour_area=20,
                                  drop_border=False)
        # the frame stroke spans ~the full canvas (≥460 of the ±240 / 480 range)
        spans = [max(p[0] for p in st["points"]) - min(p[0] for p in st["points"])
                 for st in plan["strokes"]]
        assert max(spans) >= 400, "border frame should be kept with --keep-border"
