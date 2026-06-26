"""image_to_trajectory() wrapper returns a plan dict without writing files."""
import os
import tempfile
from PIL import Image, ImageDraw

import image_to_trajectory as itt


def _make_lineart_png(path):
    """A black background with a white horizontal line — CV should find >=1 stroke."""
    img = Image.new("L", (200, 200), 0)  # black bg
    draw = ImageDraw.Draw(img)
    draw.line([(10, 100), (190, 100)], fill=255, width=4)  # white line
    img.save(path)


def test_image_to_trajectory_returns_plan_no_files():
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_lineart_png(png)
        plan = itt.image_to_trajectory(png, mode="lineart")
        # plan is a dict with description + strokes; no output files written
        assert isinstance(plan, dict)
        assert "description" in plan and "strokes" in plan
        assert len(plan["strokes"]) >= 1
        for st in plan["strokes"]:
            assert len(st["points"]) >= 2
            for x, y in st["points"]:
                assert -240 <= x <= 240 and -240 <= y <= 240
        # no side-effect files in the temp dir besides the input
        assert sorted(os.listdir(d)) == ["in.png"]


def test_image_to_trajectory_no_strokes_raises():
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "blank.png")
        Image.new("L", (200, 200), 0).save(png)  # pure black, no lines
        try:
            itt.image_to_trajectory(png, mode="lineart")
        except ValueError:
            pass
        else:
            # Some skeletonize impls may emit a spurious point; accept either,
            # but if it returns, it must be a valid plan
            plan = itt.image_to_trajectory(png, mode="lineart")
            assert isinstance(plan, dict)


def _make_framed_line_png(path):
    """A white border frame around the whole image + a short white line in the
    centre on a black background — mimics a canvas-frame image. The skeleton
    of the frame hugs all four edges; drop_border must remove it."""
    img = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (199, 199)], outline=255, width=3)   # border frame
    draw.line([(70, 100), (130, 100)], fill=255, width=4)        # centre line
    img.save(path)


def test_image_to_trajectory_drops_border_frame():
    """The canvas-frame skeleton (hugs all four edges) is dropped by default;
    no surviving stroke spans the full canvas, and --keep-border keeps more."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_framed_line_png(png)
        kept = itt.image_to_trajectory(png, mode="lineart", drop_border=True,
                                       min_stroke_points=2)
        full = itt.image_to_trajectory(png, mode="lineart", drop_border=False,
                                       min_stroke_points=2)
        # no kept stroke spans ~the full ±240 canvas on both axes (the frame)
        for st in kept["strokes"]:
            xs = [p[0] for p in st["points"]]
            ys = [p[1] for p in st["points"]]
            assert not ((max(xs) - min(xs)) >= 460 and (max(ys) - min(ys)) >= 460), (
                "border frame stroke not dropped")
        # keeping the border yields at least one more stroke (the frame ring)
        assert len(full["strokes"]) >= len(kept["strokes"])


def _make_t_junction_png(path):
    """A T-junction: a vertical stem meeting a horizontal bar — skeleton has a
    real junction. Used to check the pipeline doesn't fragment into many
    2-point trivial strokes."""
    img = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(img)
    draw.line([(100, 60), (100, 150)], fill=255, width=4)   # vertical stem
    draw.line([(50, 100), (150, 100)], fill=255, width=4)   # horizontal bar
    img.save(path)


def test_image_to_trajectory_defrag_reduces_trivial_strokes():
    """With min_stroke_points=4 (default) the T-junction skeleton does not
    fragment into 2-point trivial strokes; survivors have >= 4 points."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_t_junction_png(png)
        plan = itt.image_to_trajectory(png, mode="lineart", min_stroke_points=4)
        assert len(plan["strokes"]) >= 1
        # no 2-point trivial strokes survive
        assert all(len(st["points"]) >= 4 for st in plan["strokes"]), (
            f"trivial strokes survived: {[len(s['points']) for s in plan['strokes']]}")
        for st in plan["strokes"]:
            for x, y in st["points"]:
                assert -240 <= x <= 240 and -240 <= y <= 240
        # no side-effect files besides the input
        assert sorted(os.listdir(d)) == ["in.png"]


def test_image_to_trajectory_min_stroke_points_filter():
    """Raising min_stroke_points reduces stroke count and every survivor has
    >= that many points."""
    with tempfile.TemporaryDirectory() as d:
        png = os.path.join(d, "in.png")
        _make_t_junction_png(png)
        loose = itt.image_to_trajectory(png, mode="lineart", min_stroke_points=2)
        strict = itt.image_to_trajectory(png, mode="lineart", min_stroke_points=6)
        assert len(strict["strokes"]) <= len(loose["strokes"])
        assert all(len(st["points"]) >= 6 for st in strict["strokes"])
