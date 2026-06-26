# Trajectory Generation Micro-Service — Design

**Date:** 2026-06-26
**Status:** Approved (pending spec review)
**Scope:** Extend the existing desktop `gif_service.py` with a `POST /trace` endpoint that runs CV (the existing `image_to_trajectory.py`) on an uploaded PNG and returns a ±240 trajectory JSON — replacing the unstable LLM vision-tracing step. The service now exposes two endpoints: `/trace` (PNG → trajectory JSON) and `/render-gif` (trajectory JSON → GIF, unchanged).

## Background & Motivation

The current `sugar-painting-flow` skill's Step 2 has the **LLM visually trace** the generated PNG into a normalized trajectory JSON. In practice this is **unstable** — vision-tracing produces inconsistent strokes across runs. The device itself cannot run CV (m310, BogoMIPS 48, no PIL/numpy/opencv), but a desktop/cloud host can. The fix: move PNG→trajectory onto the desktop micro-service (deterministic CV), leaving the device with only zero-dependency HTTP calls.

`gif_service.py` already exists and serves `/render-gif` over `http.server` + the existing `trajectory_gif.py`. Extending it with `/trace` gives one service, two endpoints — the device calls both over `urllib`, same mechanism as dayin.la.

## Goals

- `POST /trace` — accepts a PNG (multipart upload), runs `image_to_trajectory.py`'s CV pipeline (auto mode, default params), returns a **±240 trajectory JSON** that has been through the stick-adhesion/dedup guardian.
- `POST /render-gif` — unchanged (trajectory JSON → GIF).
- The device stays zero-dependency: only `urllib` multipart POSTs, no PIL/numpy/opencv, no LLM vision step.
- Reuse the existing `trajectory_prepare.py` guardian core (stick adhesion, dedup, validation) for the `/trace` output — no duplicated contract logic.

## Non-Goals

- Changing `/render-gif`.
- A combined "PNG → GIF in one call" endpoint (the user explicitly wants two separate endpoints).
- Modifying the device-side skills' SKILL.md in this spec — that follows once the interface is fixed (a separate small change to `sugar-painting-flow` Step 2).
- Re-implementing the CV pipeline — `image_to_trajectory.py` is reused as-is, with a thin callable wrapper.

## Architecture

```
device (zero-dep, urllib)                desktop gif_service (PIL/numpy/opencv)
   │
   │  POST /trace  multipart: image=PNG
   ├────────────────────────────────────► │  1. save PNG to temp
   │                                       │  2. image_to_trajectory.py CV (auto, defaults) → ±240 strokes
   │                                       │  3. trajectory_prepare.finalize_plan() → stick-anchor + dedup + validate
   │                                       │  4. json + optional svg
   │  ◄─────────────────────────────────────┤  200 application/json
   │
   │  POST /render-gif  json: ±240 plan
   ├────────────────────────────────────► │  trajectory_gif.render_gif (PIL)
   │  ◄─────────────────────────────────────┤  200 image/gif
```

## Endpoints

### `POST /trace`
- **Request:** `multipart/form-data`, field `image` = PNG file. Optional query param `mode=auto|lineart|photo` (default `auto`).
- **Response 200 `application/json`:**
  ```json
  {
    "description": "auto (14 strokes)",
    "strokes": [{"points": [[0, 84], [10, 80]]}],
    "svg": "<svg ...>...</svg>"
  }
  ```
  Coordinates are ±240 integers, Y-up, stick-adhered. `svg` is the trajectory preview (same string `trajectory_prepare.render_svg` produces) so the device gets the preview without a second call.
- **Response 400:** PNG unreadable, or CV produced zero strokes.
- **Response 500:** Unexpected CV/Python error.

### `POST /render-gif`
- Unchanged: JSON body (the ±240 plan) → `200 image/gif`, `400` on bad JSON.

### `GET /healthz`
- Unchanged: `200 ok`.

## Key Architecture Point: Reusing the Guardian Core

**The mismatch:** `trajectory_prepare.parse_and_map` expects **normalized [0,1]** input and internally maps to ±240 via `map_point`. But `/trace`'s CV (`image_to_trajectory.py`) produces **±240 directly**. Feeding ±240 into `parse_and_map` would treat the values as normalized and remap them into garbage.

**The fix — refactor `trajectory_prepare.py` to expose the guardian as a reusable function on ±240 input:**
- Add `finalize_plan(plan: dict, stick_tol=STICK_TOL) -> dict`: runs `dedup_points` per stroke + `enforce_stick_adhesion` + validates each stroke ≥2 points. **No coordinate mapping.** Works on an already-±240 plan.
- `parse_and_map` (normalized → ±240) keeps its `map_point` mapping and then calls `finalize_plan` internally — so both paths share one guardian core (DRY).
- `render_svg` is already ±240-native; `/trace` reuses it for the `svg` field.

`/trace` internal flow:
```
image_to_trajectory.py(png, mode) → ±240 strokes
  → plan = {"description": ..., "strokes": strokes}
  → trajectory_prepare.finalize_plan(plan)     # stick-anchor + dedup + validate, NO mapping
  → {"description":..., "strokes":..., "svg": render_svg(plan)}
```

## Callable Wrapper for `image_to_trajectory.py`

`image_to_trajectory.py` is importable (functions `load_and_resize`, `binarize_lineart`, `skeletonize`, `extract_all_paths`, `scale_to_canvas`, `enforce_connectivity`, `optimize_stroke_order`, `build_plan`, `main`, etc.), but `main(image_path, output_path, ...)` **writes files** (`write_outputs`). There is no entry that returns a plan dict without writing.

Add a thin wrapper in `image_to_trajectory.py`:
```python
def image_to_trajectory(image_path, mode="auto", max_dim=None, smooth_sigma=None,
                        simplify_eps=None, resample_n=None, threshold=None,
                        min_contour_area=50, prune=15) -> dict:
    """Run the CV pipeline and return a plan dict ({description, strokes}) without writing files."""
    # mirrors main()'s pipeline up to build_plan, skips write_outputs
```
`main()` is refactored to call `image_to_trajectory(...)` + `write_outputs(...)` so the CLI behavior is unchanged (DRY — no duplicated pipeline logic).

## Device-Side Multipart (urllib, pure stdlib)

The device has no `requests`/`curl`. A multipart POST is ~20 lines of stdlib:
```python
import urllib.request, uuid

def post_png(url, png_bytes):
    boundary = uuid.uuid4().hex
    body = b"--" + boundary.encode() + b"\r\n" \
        + b'Content-Disposition: form-data; name="image"; filename="sugar.png"\r\n' \
        + b"Content-Type: image/png\r\n\r\n" \
        + png_bytes + b"\r\n" \
        + b"--" + boundary.encode() + b"--\r\n"
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()  # the JSON response
```

## Files

- **`gif_service.py`** (extend): `handle_trace(image_bytes, mode) -> dict` (saves PNG to temp, calls `image_to_trajectory()`, `finalize_plan()`, `render_svg()`); `Handler.do_POST` routes on path (`/trace` vs `/render-gif`); multipart parsing (stdlib — `email.parser` or manual boundary split, not `cgi` which is deprecated in 3.13+).
- **`trajectory_prepare.py`** (small refactor): add `finalize_plan(plan)`; `parse_and_map` calls it after mapping; `render_svg` unchanged.
- **`image_to_trajectory.py`** (small refactor): add `image_to_trajectory(...) -> dict` wrapper; `main()` calls it + `write_outputs`.
- **Tests:** `tests/test_gif_service.py` (extend with `handle_trace` + multipart tests); `tests/test_trajectory_prepare.py` (extend with `finalize_plan` tests).

## Testing

- `handle_trace`: feed a synthetic black-bg/white-line PNG → returns ±240 JSON, ≥1 stroke, at least one stroke touches x≈0, `svg` field is well-formed `<svg>...`.
- `finalize_plan`: dedup + stick adhesion on an already-±240 plan (no mapping); a plan already touching x=0 is a no-op; a plan with no x=0 stroke gets an anchor.
- multipart parsing: a hand-built multipart body yields the PNG bytes.
- End-to-end (manual/optional): a real sugar-gen PNG → `/trace` → `/render-gif` → GIF.

## Out of Scope

- Updating `sugar-painting-flow` SKILL.md Step 2 to call `/trace` instead of LLM-tracing — a separate follow-up after the interface is fixed.
- The leftover working-tree housekeeping (deletion of `image_to_trajectory_v2.py`, untracked `skills/` files) — predates this work.
- Cloud deployment / auth — the service is LAN-only for now; the host is already a swappable constant in the skill docs.
