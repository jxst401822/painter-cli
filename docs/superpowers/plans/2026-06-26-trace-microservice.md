# Trajectory Generation Micro-Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend desktop `gif_service.py` with `POST /trace` (multipart PNG → ±240 trajectory JSON + svg via the existing CV pipeline + guardian), keeping `/render-gif` unchanged, so the device replaces the unstable LLM vision-tracing step with a deterministic HTTP call.

**Architecture:** Three changes. (1) `trajectory_prepare.py`: extract `finalize_plan(plan)` — the guardian (dedup + stick adhesion + ≥2-points validation) operating on an already-±240 plan; `parse_and_map` reuses it after its normalized→±240 mapping. (2) `image_to_trajectory.py`: add `image_to_trajectory(...) -> dict` wrapper returning a plan dict without writing files; `main()` reuses it + `write_outputs`. (3) `gif_service.py`: add `handle_trace(image_bytes, mode) -> dict` and route `do_POST` between `/trace` (multipart) and `/render-gif`; multipart parsed with stdlib `email.parser` (not deprecated `cgi`).

**Tech Stack:** Python 3.12+ (device) / 3.14 (desktop), pytest 9, PIL/numpy/opencv on desktop only, stdlib `http.server` + `email.parser` for the service.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-06-26-trace-microservice-design.md`:

- **Two endpoints, one service:** `POST /trace` (multipart PNG → ±240 JSON + svg) and `POST /render-gif` (unchanged). `GET /healthz` unchanged.
- **`/trace` returns ±240 JSON**, Y-up, stick-adhered, deduped, each stroke ≥2 points. Response includes an `svg` field (the `trajectory_prepare.render_svg` output).
- **Reuse the guardian core:** `finalize_plan` is the shared dedup+adhesion+validation on ±240 plans; `parse_and_map` calls it after mapping. **No coordinate mapping inside `finalize_plan`** (it must not re-map ±240 values).
- **`image_to_trajectory.py` is reused, not rewritten.** Add a thin `image_to_trajectory(...) -> dict` wrapper; `main()` calls it + `write_outputs`. CLI behavior unchanged.
- **Desktop-only CV:** PIL/numpy/opencv available on the service host. Device stays zero-dependency (only urllib).
- **Multipart via stdlib `email.parser`** (not `cgi` — deprecated in 3.13+, removed in 3.15).
- **`/render-gif` and `GET /healthz` must not change behavior** (existing tests stay green).

---

## File Structure

- **`trajectory_prepare.py`** (`.import_bundle/image-to-trajectory/scripts/`) — add `finalize_plan`; refactor `parse_and_map` to call it.
- **`image_to_trajectory.py`** (repo root) — add `image_to_trajectory()` wrapper; refactor `main()` to use it.
- **`gif_service.py`** (repo root) — add `handle_trace` + multipart parsing + `do_POST` routing.
- **Tests:** extend `tests/test_trajectory_prepare.py`, `tests/test_gif_service.py`; add `tests/test_image_to_trajectory_wrapper.py`.

---

### Task 1: `trajectory_prepare.finalize_plan` — the ±240 guardian

**Files:**
- Modify: `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`
- Test: `tests/test_trajectory_prepare.py`

**Interfaces:**
- Consumes: existing `dedup_points`, `enforce_stick_adhesion`, `STICK_TOL` (already defined in this module).
- Produces: `finalize_plan(plan: dict, stick_tol: int = STICK_TOL) -> dict` — takes an already-±240 plan `{"description", "strokes":[{"points":[[x,y]...]}]}`, dedups each stroke, enforces stick adhesion, validates each stroke ≥2 points (raises `TrajectoryError` otherwise). **No `map_point` call.** `parse_and_map` is refactored to call `finalize_plan` after its mapping step.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trajectory_prepare.py`:

```python
from trajectory_prepare import finalize_plan


def test_finalize_plan_dedups_and_keeps_anchored():
    # already ±240, already crosses x=0 → adhesion no-op, dedup removes dup
    plan = {"description": "x", "strokes": [{"points": [[0, 0], [10, 10], [10, 10], [20, 20]]}]}
    out = finalize_plan(plan)
    assert out["strokes"][0]["points"] == [[0, 0], [10, 10], [20, 20]]


def test_finalize_plan_anchors_when_no_stick_crossing():
    plan = {"description": "x", "strokes": [{"points": [[40, 5], [80, 50]]}]}
    out = finalize_plan(plan)
    # nearest point to x=0 is [40,5] → anchor [0,5] prepended
    assert out["strokes"][0]["points"][0] == [0, 5]


def test_finalize_plan_rejects_short_stroke():
    import pytest
    plan = {"description": "x", "strokes": [{"points": [[40, 5]]}]}
    with pytest.raises(TrajectoryError):
        finalize_plan(plan)


def test_finalize_plan_does_not_remap_coordinates():
    # ±240 values must pass through unchanged (no [0,1] mapping applied)
    plan = {"description": "x", "strokes": [{"points": [[0, -240], [240, 240]]}]}
    out = finalize_plan(plan)
    pts = out["strokes"][0]["points"]
    # anchored already (x=0 present), so no prepend; values intact
    assert [240, 240] in pts
    assert [0, -240] in pts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trajectory_prepare.py -k finalize_plan -v`
Expected: FAIL — `ImportError: cannot import name 'finalize_plan'`.

- [ ] **Step 3: Implement finalize_plan and refactor parse_and_map**

In `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`, add `finalize_plan` after `enforce_stick_adhesion` (before `parse_and_map`):

```python
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
```

Then refactor `parse_and_map`'s tail. Its current ending is:

```python
    strokes = []
    for i, rs in enumerate(raw_strokes):
        ...
        strokes.append({"points": pts})

    plan = {"description": description, "strokes": strokes}
    plan = enforce_stick_adhesion(plan)
    return plan
```

Replace the `strokes.append` loop + the final 3 lines with a mapping step that produces raw ±240 strokes, then delegates to `finalize_plan`. The per-stroke block currently does `pts = [map_point(*_parse_point(p)) for p in raw_points]; pts = dedup_points(pts); if len(pts) < 2: raise ...; strokes.append(...)`. Simplify it to only map (no dedup/raise here — `finalize_plan` does those):

```python
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
```

This keeps `parse_and_map`'s external behavior identical (mapping + guardian) while sharing the guardian with `finalize_plan`.

- [ ] **Step 4: Run the full trajectory_prepare suite**

Run: `python -m pytest tests/test_trajectory_prepare.py -v`
Expected: PASS — all existing tests (parse_and_map, map_point, stick adhesion, render_svg) AND the 4 new `finalize_plan` tests. The `parse_and_map` tests must still pass unchanged (they assert mapped + anchored output, which `finalize_plan` now produces).

- [ ] **Step 5: Commit**

```bash
git add .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py tests/test_trajectory_prepare.py
git commit -m "feat(trajectory): extract finalize_plan (±240 guardian) shared by parse_and_map"
```

---

### Task 2: `image_to_trajectory()` callable wrapper

**Files:**
- Modify: `image_to_trajectory.py` (repo root) — `main()` is at lines 765-815.
- Test: `tests/test_image_to_trajectory_wrapper.py` (new)

**Interfaces:**
- Consumes: the existing pipeline functions (`load_and_resize`, `binarize_lineart`/`binarize_photo`, `skeletonize`, `prune_skeleton`, `extract_all_paths`, `smooth_path`, `scale_to_canvas`, `enforce_connectivity`, `optimize_stroke_order`, `build_plan`, `detect_source_type`, `MODE_DEFAULTS`).
- Produces: `image_to_trajectory(image_path, mode="auto", max_dim=None, smooth_sigma=None, simplify_eps=None, resample_n=None, threshold=None, min_contour_area=50, prune=15) -> dict` — returns `{"description", "strokes"}` (±240, the same shape `build_plan` produces), **without writing files**. Raises `ValueError("no strokes found")` if the pipeline extracts zero paths. `main()` is refactored to call this then `write_outputs` (CLI behavior unchanged). Does NOT handle `compare`/`debug` (those stay in `main`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_image_to_trajectory_wrapper.py`:

```python
"""image_to_trajectory() wrapper returns a plan dict without writing files."""
import os
import tempfile
from PIL import Image, ImageDraw

import image_to_trajectory as itt


def _make_lineart_png(path):
    """A black background with a white horizontal line — CV should find ≥1 stroke."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_image_to_trajectory_wrapper.py -v`
Expected: FAIL — `AttributeError: module 'image_to_trajectory' has no attribute 'image_to_trajectory'` (the wrapper doesn't exist yet). Note: `image_to_trajectory.py` is at repo root, which `tests/conftest.py` already puts on sys.path (verify; if not, the existing `trajectory_gif`/`gif_service` imports wouldn't work — they do, so root is on path).

- [ ] **Step 3: Add the wrapper and refactor main()**

In `image_to_trajectory.py`, add the wrapper immediately **before** `def main(...)` (around line 764):

```python
def image_to_trajectory(image_path, mode="auto", max_dim=None,
                        smooth_sigma=None, simplify_eps=None, resample_n=None,
                        threshold=None, min_contour_area=50, prune=15):
    """Run the CV pipeline and return a plan dict ({description, strokes}) WITHOUT writing files.

    This is the library entry point used by gif_service's /trace endpoint.
    main() wraps this + write_outputs for the CLI.
    """
    if mode == "auto":
        img_tmp = Image.open(image_path).convert("L")
        arr_tmp = np.array(img_tmp)
        mode = detect_source_type(arr_tmp)
        print(f"Auto-detected: {mode}")
    defaults = MODE_DEFAULTS[mode]
    max_dim = max_dim or defaults["max_dim"]
    smooth_sigma = smooth_sigma if smooth_sigma is not None else defaults["sigma"]
    simplify_eps = simplify_eps if simplify_eps is not None else defaults["eps"]
    resample_n = resample_n if resample_n is not None else defaults["resample"]
    gray_arr, orig_size = load_and_resize(image_path, max_dim)
    print(f"Mode: {mode} | sigma={smooth_sigma} eps={simplify_eps} "
          f"resample={resample_n} max_dim={max_dim}")
    print("Binarizing...")
    binary = binarize_lineart(gray_arr, threshold=threshold) if mode == "lineart" \
        else binarize_photo(gray_arr, min_contour_area=min_contour_area)
    print("Skeletonizing...")
    skel = skeletonize(binary)
    if prune > 0:
        skel = prune_skeleton(skel, max_spur=prune)
    print("Tracing skeleton graph...")
    strokes_raw = extract_all_paths(skel)
    if not strokes_raw:
        raise ValueError("no strokes found")
    strokes_smooth = [smooth_path(s, sigma=smooth_sigma) for s in strokes_raw]
    strokes = scale_to_canvas(strokes_smooth, simplify_eps, resample_n)
    strokes = enforce_connectivity(strokes)
    strokes = optimize_stroke_order(strokes)
    return build_plan(strokes, f"{mode} ({len(strokes)} strokes)")
```

Then refactor `main()` to reuse it. Replace the body of `main` (lines 768-815) with:

```python
def main(image_path, output_path, mode="auto", max_dim=None,
         smooth_sigma=None, simplify_eps=None, resample_n=None,
         threshold=None, min_contour_area=50, prune=15, compare=False, debug=False):
    if mode == "auto":
        img_tmp = Image.open(image_path).convert("L")
        arr_tmp = np.array(img_tmp)
        mode = detect_source_type(arr_tmp)
        print(f"Auto-detected: {mode}")
    defaults = MODE_DEFAULTS[mode]
    max_dim = max_dim or defaults["max_dim"]
    smooth_sigma = smooth_sigma if smooth_sigma is not None else defaults["sigma"]
    simplify_eps = simplify_eps if simplify_eps is not None else defaults["eps"]
    resample_n = resample_n if resample_n is not None else defaults["resample"]
    gray_arr, orig_size = load_and_resize(image_path, max_dim)
    if compare:
        run_comparison(gray_arr, output_path, lineart_threshold=threshold,
                       min_contour_area=min_contour_area, prune=prune)
        return
    if debug:
        # need binary + skel for debug images; recompute here (debug is CLI-only)
        binary = binarize_lineart(gray_arr, threshold=threshold) if mode == "lineart" \
            else binarize_photo(gray_arr, min_contour_area=min_contour_area)
        skel = skeletonize(binary)
        if prune > 0:
            skel = prune_skeleton(skel, max_spur=prune)
        save_debug_images(binary, skel, output_path)
    plan = image_to_trajectory(image_path, mode=mode, max_dim=max_dim,
                               smooth_sigma=smooth_sigma, simplify_eps=simplify_eps,
                               resample_n=resample_n, threshold=threshold,
                               min_contour_area=min_contour_area, prune=prune)
    total = sum(len(st["points"]) for st in plan["strokes"])
    print(f"Final: {len(plan['strokes'])} strokes, {total} points")
    write_outputs(plan, output_path)
```

Note: `main` re-resolves `mode`/defaults itself (not via the wrapper's auto-detect) because it needs `gray_arr` for `compare`/`debug` branches before calling the wrapper. The wrapper re-resolves them too — that's a minor double-resolve in the auto path, acceptable (auto-detect is cheap and only re-runs if mode=="auto", which `main` has already resolved to a concrete mode before calling the wrapper, so the wrapper's `if mode == "auto"` branch won't fire). Confirm: `main` passes `mode=mode` where `mode` is already concrete after its own auto-detect → wrapper's auto branch is skipped. Good.

- [ ] **Step 4: Run the wrapper tests**

Run: `python -m pytest tests/test_image_to_trajectory_wrapper.py -v`
Expected: PASS (2 tests). The lineart PNG yields ≥1 stroke; the blank PNG either raises `ValueError` or returns a valid plan (test accepts both).

- [ ] **Step 5: Verify the CLI still works (regression)**

Run:
```bash
python -c "
import image_to_trajectory as itt, tempfile, os
from PIL import Image, ImageDraw
d = tempfile.mkdtemp(); png = os.path.join(d, 'in.png'); out = os.path.join(d, 'out.json')
img = Image.new('L',(200,200),0); ImageDraw.Draw(img).line([(10,100),(190,100)],fill=255,width=4); img.save(png)
itt.main(png, out, mode='lineart')
print('CLI wrote:', os.path.exists(out), os.path.exists(out.replace('.json','.png')), os.path.exists(out.replace('.json','.svg')))
"
```
Expected: `CLI wrote: True True True` — `main` still writes JSON + PNG + SVG (CLI behavior unchanged).

- [ ] **Step 6: Commit**

```bash
git add image_to_trajectory.py tests/test_image_to_trajectory_wrapper.py
git commit -m "feat(image-to-trajectory): add image_to_trajectory() library wrapper; main reuses it"
```

---

### Task 3: `gif_service.handle_trace` + multipart + routing

**Files:**
- Modify: `gif_service.py` (repo root)
- Test: `tests/test_gif_service.py`

**Interfaces:**
- Consumes: `image_to_trajectory.image_to_trajectory(...)` (Task 2), `trajectory_prepare.finalize_plan` + `render_svg` (Task 1, already in the bundle on sys.path via conftest).
- Produces: `handle_trace(image_bytes: bytes, mode: str = "auto") -> dict` (returns the final plan dict with an added `svg` field); `parse_multipart(body: bytes, boundary: str) -> dict` (returns `{"image": bytes}`); `Handler.do_POST` routes `/trace` (multipart) vs `/render-gif` (JSON).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gif_service.py`:

```python
import os
import uuid
from PIL import Image, ImageDraw

from gif_service import handle_trace, parse_multipart, TraceServiceError


def _png_bytes():
    img = Image.new("L", (200, 200), 0)
    ImageDraw.Draw(img).line([(10, 100), (190, 100)], fill=255, width=4)
    import io
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gif_service.py -k "handle_trace or parse_multipart" -v`
Expected: FAIL — `ImportError: cannot import name 'handle_trace'` (and `parse_multipart`, `TraceServiceError`).

- [ ] **Step 3: Implement handle_trace, parse_multipart, TraceServiceError, and routing**

In `gif_service.py`:

Add the `image_to_trajectory` and `trajectory_prepare` imports near the top (after the existing `from trajectory_gif import render_gif`):

```python
from image_to_trajectory import image_to_trajectory
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".import_bundle", "image-to-trajectory", "scripts"))
from trajectory_prepare import finalize_plan, render_svg, TrajectoryError
```

(Keep the existing `sys.path.insert(0, os.path.dirname(...))` for `trajectory_gif`; add the `.import_bundle/...` insert for `trajectory_prepare`.)

Add `TraceServiceError` alongside the existing `GifServiceError`:

```python
class TraceServiceError(Exception):
    """Raised when /trace cannot produce a trajectory from the uploaded PNG."""
```

Add `parse_multipart` and `handle_trace` after `handle_render_gif`:

```python
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
    plan = finalize_plan(plan)          # dedup + stick adhesion + validate (no remap)
    plan["svg"] = render_svg(plan)      # preview, ±240-native
    return plan
```

Refactor `Handler.do_POST` to route on path (replace the existing `do_POST`):

```python
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
```

Add the boundary helper near the top of the module (after the constants):

```python
def _boundary_from_ctype(ctype):
    """Extract the boundary=... value from a Content-Type header."""
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part[len("boundary="):].strip('"')
    return None
```

(Optional: support `?mode=lineart` query on `/trace` — parse `self.path` for a query string and pass it as `mode`. Keep it simple: default `auto` per spec; if you add query parsing, test it. The plan keeps `auto` default and does not require query parsing for the core flow.)

- [ ] **Step 4: Run the gif_service tests**

Run: `python -m pytest tests/test_gif_service.py -v`
Expected: PASS — the existing 4 render_gif tests AND the 4 new trace/multipart tests.

- [ ] **Step 5: Manual end-to-end smoke (trace then render-gif)**

```bash
python -c "
import io, json, urllib.request, uuid
from PIL import Image, ImageDraw
img = Image.new('L',(200,200),0); ImageDraw.Draw(img).line([(10,100),(190,100)],fill=255,width=4)
buf = io.BytesIO(); img.save(buf, format='PNG'); png = buf.getvalue()
b = uuid.uuid4().hex
body = f'--{b}\r\n'.encode()+b'Content-Disposition: form-data; name=\"image\"; filename=\"s.png\"\r\nContent-Type: image/png\r\n\r\n'+png+b'\r\n'+f'--{b}--\r\n'.encode()
req = urllib.request.Request('http://192.168.0.113:8765/trace', data=body, headers={'Content-Type':f'multipart/form-data; boundary={b}'}, method='POST')
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        plan = json.loads(r.read())
    print('trace strokes:', len(plan['strokes']), 'has svg:', plan['svg'].startswith('<svg'))
    # now POST plan to /render-gif
    req2 = urllib.request.Request('http://192.168.0.113:8765/render-gif', data=json.dumps(plan).encode(), headers={'Content-Type':'application/json'}, method='POST')
    with urllib.request.urlopen(req2, timeout=120) as r2:
        gif = r2.read()
    print('gif bytes:', len(gif), 'magic:', gif[:6])
except urllib.error.URLError as e:
    print('service not running — skipped live e2e:', e)
"
```
Expected (service running): `trace strokes: <N> has svg: True` and `gif bytes: <N> magic: b'GIF89a'`. If the service isn't running, the URLError path prints "service not running — skipped live e2e" — that's acceptable (the unit tests in Step 4 already prove the logic); just report which path ran.

- [ ] **Step 6: Commit**

```bash
git add gif_service.py tests/test_gif_service.py
git commit -m "feat(gif-service): add POST /trace (multipart PNG -> ±240 JSON + svg) + routing"
```

---

### Task 4: Device-side skill update + end-to-end verification

**Files:**
- Modify: `.import_bundle/sugar-painting-flow/SKILL.md` — Step 2 changes from "agent vision-traces" to "POST /trace".
- No new tests (doc change + verification).

**Interfaces:**
- Consumes: `/trace` (Task 3) and `/render-gif` (existing).

- [ ] **Step 1: Update sugar-painting-flow SKILL.md Step 2**

Read the current Step 2 (lines ~87-101). Replace the "agent vision-traces the PNG" procedure with a `POST /trace` call. The new Step 2:

```markdown
## Step 2: Trace the PNG into a trajectory (POST /trace)

The device cannot run CV (no PIL/numpy/opencv). Upload the PNG to the trace
service, which runs the CV pipeline on the desktop host and returns a ±240
trajectory JSON (+ an SVG preview). The device has **no `curl`** — use `urllib`
with a hand-built multipart body (pure stdlib):

```python
import urllib.request, uuid

TRACE_SERVICE = "http://192.168.0.113:8765"   # same host as the GIF service

def post_png(url, png_path):
    png = open(png_path, "rb").read()
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n".encode()
        + b'Content-Disposition: form-data; name="image"; filename="sugar.png"\r\n'
        + b"Content-Type: image/png\r\n\r\n"
        + png + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        f"{url}/trace", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8")  # the ±240 trajectory JSON

import json
plan = json.loads(post_png(TRACE_SERVICE, "/tmp/sugar.png"))
open("/tmp/trace.json", "w").write(json.dumps(plan))
open("/tmp/trace.svg", "w").write(plan["svg"])
print(f"traced: {len(plan['strokes'])} strokes")
```

`/tmp/trace.json` is the machine-ready ±240 trajectory; `/tmp/trace.svg` is the
preview (returned in the `svg` field — no separate call needed). This replaces
the previous agent-vision-tracing step with a deterministic CV service call.
```

Also update the **Pipeline** diagram in the same file: Step 2 box changes from `agent vision-traces PNG → /tmp/trace_norm.json` to `POST /trace → /tmp/trace.json + .svg`. And **Step 3** (the `trajectory_prepare.py` run) is now redundant — the service already finalized the plan. Replace Step 3 with a short note: "Step 3 (was: run trajectory_prepare.py) — now done server-side by /trace; skip." Keep the end-to-end example consistent (Step 1 → Step 2 POST /trace → Step 3 POST /render-gif).

- [ ] **Step 2: Verify the updated SKILL.md**

```bash
head -6 .import_bundle/sugar-painting-flow/SKILL.md
grep -c "192.168.0.113:8765" .import_bundle/sugar-painting-flow/SKILL.md
grep -nE "/home/se|\.hermes|venv/bin|category: creative" .import_bundle/sugar-painting-flow/SKILL.md || echo "no residual local/hermes paths: OK"
grep -n "POST /trace" .import_bundle/sugar-painting-flow/SKILL.md
grep -n "trajectory_prepare.py" .import_bundle/sugar-painting-flow/SKILL.md || echo "Step 3 trajectory_prepare removed: OK"
```
Expected: nanobot frontmatter intact; GIF/trace URL count ≥2; no residual local/hermes paths; `POST /trace` present; the device-side `trajectory_prepare.py` call is gone (it's now server-side).

- [ ] **Step 3: End-to-end verification (live, if service running)**

Start the service in one terminal: `python gif_service.py --port 8765`. Then run the Task 3 Step 5 smoke (trace → render-gif). Confirm: trace returns ≥1 stroke + svg; render-gif returns a GIF89a. If the service can't be started here, the unit tests (Tasks 1-3) + the manual smoke from Task 3 cover the logic; report what ran.

- [ ] **Step 4: Commit**

```bash
git add .import_bundle/sugar-painting-flow/SKILL.md
git commit -m "docs(sugar-painting-flow): Step 2 now POSTs /trace (deterministic CV) instead of LLM vision-trace"
```

---

## Self-Review Notes

**Spec coverage:**
- `/trace` multipart PNG → ±240 JSON + svg → Task 3. ✓
- `/render-gif` unchanged → Task 3 keeps it; existing tests guard. ✓
- `finalize_plan` guardian, shared by `parse_and_map`, no remap → Task 1. ✓
- `image_to_trajectory()` wrapper, no file writes, `main` reuses → Task 2. ✓
- auto mode + default params → Task 2 wrapper passes mode through; Task 3 `handle_trace` default mode="auto". ✓
- multipart via stdlib `email.parser` (not cgi) → Task 3 `parse_multipart`. ✓
- Device SKILL.md updated to call `/trace` → Task 4. ✓
- Tests for finalize_plan, wrapper, handle_trace, multipart → Tasks 1-3. ✓

**Placeholder scan:** None — every code step has complete code; every test has real assertions; commands have expected output. The `mode` query-param on `/trace` is explicitly left at default `auto` (spec says default auto; optional query noted as out-of-scope for the core flow).

**Type consistency:** `finalize_plan(plan) -> dict` used identically in Task 1 (`parse_and_map` calls it) and Task 3 (`handle_trace` calls it). `image_to_trajectory(...) -> dict` (Task 2) is what `handle_trace` (Task 3) calls. `parse_multipart(body, boundary) -> {"image": bytes}` + `TraceServiceError` consistent between Task 3 tests and impl. The plan dict shape `{"description", "strokes":[{"points":[[x,y]...]}]}` (+`svg` in `/trace` response) is consistent across all tasks. ✓
