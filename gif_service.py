#!/usr/bin/env python3
"""
gif_service.py — tiny HTTP micro-service that renders trajectory JSON to a GIF.

Reuses trajectory_gif.render_gif (PIL) unchanged. Designed to run on a desktop
or cloud host reachable by the quantum-bot device over HTTP.

Run:
    python gif_service.py --host 0.0.0.0 --port 8765

Use:
    POST /render-gif   body = trajectory JSON   -> image/gif
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

GIF_MAGIC = b"GIF8"  # matches GIF87a and GIF89a


class GifServiceError(Exception):
    """Raised when the request body is not a renderable trajectory JSON."""


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
        if self.path != "/render-gif":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            gif = handle_render_gif(body)
        except GifServiceError as e:
            self._send(400, str(e).encode(), "text/plain")
            return
        self._send(200, gif, "image/gif")


def main():
    ap = argparse.ArgumentParser(description="Trajectory -> GIF HTTP micro-service")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = http.server.HTTPServer((args.host, args.port), Handler)
    print(f"gif_service on http://{args.host}:{args.port}  (POST /render-gif)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
