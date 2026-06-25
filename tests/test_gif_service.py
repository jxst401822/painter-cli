import json

import pytest

from gif_service import handle_render_gif, GifServiceError, GIF_MAGIC

VALID_PLAN = {"description": "t", "strokes": [{"points": [[0, 0], [100, 100], [200, 0]]}]}


def test_render_returns_gif_bytes():
    gif = handle_render_gif(json.dumps(VALID_PLAN).encode())
    assert isinstance(gif, bytes)
    assert gif[:4] == GIF_MAGIC  # GIF89a or GIF87a (GIF_MAGIC == b"GIF8")


def test_render_rejects_bad_json():
    with pytest.raises(GifServiceError):
        handle_render_gif(b"not json at all")


def test_render_rejects_empty_strokes():
    with pytest.raises(GifServiceError):
        handle_render_gif(json.dumps({"strokes": []}).encode())


def test_render_rejects_short_stroke():
    with pytest.raises(GifServiceError):
        handle_render_gif(json.dumps({"strokes": [{"points": [[0, 0]]}]}).encode())
