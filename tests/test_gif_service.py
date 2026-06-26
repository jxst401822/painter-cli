import io
import json
import os
import uuid

import pytest
from PIL import Image, ImageDraw

from gif_service import (
    GIF_MAGIC,
    GifServiceError,
    TraceServiceError,
    handle_render_gif,
    handle_trace,
    parse_multipart,
)

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


def _png_bytes():
    img = Image.new("L", (200, 200), 0)
    ImageDraw.Draw(img).line([(10, 100), (190, 100)], fill=255, width=4)
    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()


def test_handle_trace_returns_plan_with_svg():
    plan = handle_trace(_png_bytes(), mode="lineart")
    assert isinstance(plan, dict)
    assert "strokes" in plan and len(plan["strokes"]) >= 1
    assert "svg" in plan and plan["svg"].startswith("<svg")
    for st in plan["strokes"]:
        assert len(st["points"]) >= 2
        for x, y in st["points"]:
            assert -240 <= x <= 240 and -240 <= y <= 240


def test_handle_trace_bad_png_raises():
    with pytest.raises(TraceServiceError):
        handle_trace(b"not a png", mode="lineart")


def test_parse_multipart_extracts_image():
    boundary = uuid.uuid4().hex
    png = b"\x89PNG\r\n\x1a\n fake"
    body = (
        f"--{boundary}\r\n".encode()
        + b'Content-Disposition: form-data; name="image"; filename="s.png"\r\n'
        + b"Content-Type: image/png\r\n\r\n"
        + png + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    fields = parse_multipart(body, boundary)
    assert fields["image"] == png


def test_parse_multipart_missing_image_raises():
    boundary = uuid.uuid4().hex
    body = f"--{boundary}--\r\n".encode()
    with pytest.raises(TraceServiceError):
        parse_multipart(body, boundary)
