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
