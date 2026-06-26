#!/usr/bin/env python3
"""
gif_service.py — tiny HTTP micro-service that renders trajectory JSON to a GIF.

Reuses trajectory_gif.render_gif (PIL) unchanged. Designed to run on a desktop
or cloud host reachable by the quantum-bot device over HTTP.

Run:
    python gif_service.py --host 0.0.0.0 --port 8765

Use:
    POST /render-gif   body = trajectory JSON   -> image/gif
    POST /trace        body = multipart/form-data PNG upload -> application/json (±240 plan + svg)
    GET  /healthz                              -> 200 OK
"""
import argparse
import http.server
import json
import os
import tempfile

# trajectory_gif.py lives at repo root alongside this file.
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trajectory_gif import render_gif  # noqa: E402

from image_to_trajectory import image_to_trajectory  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".import_bundle", "image-to-trajectory", "scripts"))
from trajectory_prepare import finalize_plan, render_svg, TrajectoryError  # noqa: E402

GIF_MAGIC = b"GIF8"  # matches GIF87a and GIF89a


class GifServiceError(Exception):
    """Raised when the request body is not a renderable trajectory JSON."""


class TraceServiceError(Exception):
    """Raised when /trace cannot produce a trajectory from the uploaded PNG."""


def _boundary_from_ctype(ctype):
    """Extract the boundary=... value from a Content-Type header."""
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part[len("boundary="):].strip('"')
    return None


def handle_render_gif(body_bytes, canvas_size=600, point_ms=15):
    """Render a trajectory JSON (bytes) to GIF bytes. Raises GifServiceError."""
    try:
        plan = json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise GifServiceError(f"invalid JSON: {e}") from e

    if not isinstance(plan, dict):
        raise GifServiceError("expected a JSON object")
    strokes = plan.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        raise GifServiceError("missing or empty strokes array")
    for i, s in enumerate(strokes):
        pts = s.get("points") if isinstance(s, dict) else None
        if not isinstance(pts, list) or len(pts) < 2:
            raise GifServiceError(f"stroke {i} needs >= 2 points")

    with tempfile.TemporaryDirectory() as d:
        json_path = os.path.join(d, "plan.json")
        gif_path = os.path.join(d, "out.gif")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        render_gif(json_path, gif_path, canvas_size=canvas_size, point_ms=point_ms)
        with open(gif_path, "rb") as f:
            return f.read()


def parse_multipart(body, boundary):
    """Parse a multipart/form-data body, return {"image": bytes}. Stdlib only.
    Uses email.parser to avoid the deprecated cgi module."""
    import email
    from email.parser import BytesParser
    from email.policy import default as default_policy

    header = f"Content-Type: multipart/form-data; boundary={boundary}\r\n\r\n".encode()
    msg = BytesParser(policy=default_policy).parsebytes(header + body)
    fields = {}
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = part.get_param("name", header="content-disposition")
        if name == "image":
            fields["image"] = part.get_payload(decode=True)
    if "image" not in fields:
        raise TraceServiceError("multipart body missing 'image' field")
    return fields


def handle_trace(image_bytes, mode="auto"):
    """Run the CV pipeline on an uploaded PNG; return a ±240 plan dict with an 'svg' field."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        png_path = os.path.join(d, "in.png")
        try:
            with open(png_path, "wb") as f:
                f.write(image_bytes)
            from PIL import Image  # validate it's a real image
            Image.open(png_path).verify()
        except Exception as e:
            raise TraceServiceError(f"invalid PNG: {e}") from e
        try:
            plan = image_to_trajectory(png_path, mode=mode)
        except ValueError as e:
            raise TraceServiceError(f"no strokes found in image: {e}") from e
        except Exception as e:
            raise TraceServiceError(f"trace failed: {e}") from e
    try:
        plan = finalize_plan(plan)          # dedup + stick adhesion + validate (no remap)
        plan["svg"] = render_svg(plan)      # preview, ±240-native
    except TrajectoryError as e:
        raise TraceServiceError(f"trajectory validation failed: {e}") from e
    except Exception as e:
        raise TraceServiceError(f"finalize/svg failed: {e}") from e
    return plan


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # silence default stderr logging

    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, b"ok", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        if self.path == "/render-gif":
            try:
                gif = handle_render_gif(body)
            except GifServiceError as e:
                self._send(400, str(e).encode(), "text/plain")
                return
            self._send(200, gif, "image/gif")
        elif self.path == "/trace":
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype:
                self._send(400, b"expected multipart/form-data", "text/plain")
                return
            boundary = _boundary_from_ctype(ctype)
            if not boundary:
                self._send(400, b"missing multipart boundary", "text/plain")
                return
            try:
                fields = parse_multipart(body, boundary)
                mode = "auto"  # query param optional; default auto
                plan = handle_trace(fields["image"], mode=mode)
                payload = json.dumps(plan).encode("utf-8")
            except TraceServiceError as e:
                self._send(400, str(e).encode(), "text/plain")
                return
            self._send(200, payload, "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser(description="Trajectory -> GIF HTTP micro-service")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = http.server.HTTPServer((args.host, args.port), Handler)
    print(f"gif_service on http://{args.host}:{args.port}  (POST /render-gif, POST /trace)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
