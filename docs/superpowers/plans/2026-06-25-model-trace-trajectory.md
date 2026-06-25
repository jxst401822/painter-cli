# Model-Traced Trajectory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move trajectory JSON generation off the BogoMIPS-48 device onto the LLM (vision-trace), make `sugar-painting-gen` run zero-dependency on the device via lazy imports, and add a desktop HTTP GIF micro-service reusing `trajectory_gif.py`.

**Architecture:** Three components. (A) `sugar_painting_gen.py`: move PIL/numpy imports from module-top into the functions that use them, so the dayinla default path is pure stdlib. (B) `image-to-trajectory` skill: a new `trajectory_prepare.py` (pure stdlib) is the contract guardian — it validates the LLM's normalized `[0,1]` JSON, maps to ±240, enforces stick adhesion, dedups, renders SVG; `SKILL.md` is rewritten as an LLM vision-tracing procedure. (C) Desktop `gif_service.py`: a tiny `http.server` wrapper exposing `POST /render-gif` over the existing `trajectory_gif.py`.

**Tech Stack:** Python 3.12+ (device) / 3.14 (desktop dev), pytest 9, stdlib only on device (`json`/`re`/`math`/`os`/`sys`/`urllib`), PIL only on desktop.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-06-25-model-trace-trajectory-design.md`:

- Device stays **zero-dependency**: no pip, no numpy, no PIL, no opencv. System Python 3.12 stdlib only. No 3.14-only stdlib features — keep `trajectory_prepare.py` to `json`/`re`/`math`/`os`/`sys` (stable since 3.0+).
- JSON contract: `{"description": str, "strokes": [{"points": [[x,y],...]}]}`, coordinates clamped to `[-240, 240]`, Y positive = up, X=0 is the bamboo-stick axis, each stroke ≥2 valid points, markdown code fences tolerated.
- LLM emits **normalized `[0,1]`** coordinates; the script maps `x = round(nx*480-240)` and `y = round((1-ny)*480-240)`, both clamped to `[-240,240]`.
- Stick adhesion: if no stroke crosses `|x| <= STICK_TOL` (≈2–4), prepend `[0, y]` anchor to the nearest stroke's start.
- GIF micro-service endpoint is **configurable** (local LAN now, cloud later) — never hard-code a host. GIF is best-effort: unreachable service degrades gracefully to JSON + SVG.
- Device deliverables go to `.import_bundle/` (manual web import); desktop-only scripts stay at repo root / `skills/`.
- Frontmatter for device skills: nanobot convention `metadata: {"nanobot":{"emoji":"...","requires":{"bins":["python3"]}}}`.

---

## File Structure

**Device deliverables (`.import_bundle/`):**
- `.import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py` — lazy-import zero-dep version (modified copy of `skills/...`).
- `.import_bundle/sugar-painting-gen/SKILL.md` — updated to note ARK needs deps, dayinla is device-default.
- `.import_bundle/image-to-trajectory/SKILL.md` — rewritten as LLM vision-tracing procedure.
- `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py` — NEW, pure stdlib contract guardian.
- `.import_bundle/image-to-trajectory/scripts/trajectory_gif.py` — NOT bundled on device (PIL); referenced as the desktop service backend.

**Desktop:**
- `gif_service.py` — NEW, repo root, `http.server` wrapper reusing `trajectory_gif.py`.
- `trajectory_gif.py` — unchanged (already at repo root).

**Tests (local, 3.14/pytest):**
- `tests/test_trajectory_prepare.py` — NEW.

---

### Task 1: `sugar_painting_gen.py` lazy imports

**Files:**
- Modify: `skills/sugar-painting-gen/scripts/sugar_painting_gen.py` (source)
- Modify: `.import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py` (device copy — synced in Task 6, but edited here for the source of truth)

**Interfaces:**
- Produces: module importable with no PIL/numpy installed (dayinla path). Public API unchanged: `generate(prompt, output, engine="dayinla", size="2048x2048", postprocess=False)`, `dayinla_generate`, `dayinla_get_prompts`, `main`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sugar_gen_lazy_imports.py`:

```python
"""sugar_painting_gen must import with PIL/numpy unavailable (device has neither)."""
import importlib
import sys


def test_module_imports_without_pil_numpy(monkeypatch):
    # Block PIL and numpy as if absent on the device.
    for mod in ("PIL", "numpy", "yaml"):
        monkeypatch.setitem(sys.modules, mod, None)
    # Drop any cached import.
    sys.modules.pop("sugar_painting_gen", None)
    mod = importlib.import_module("sugar_painting_gen")
    # dayinla path uses only stdlib; these must exist without deps.
    assert hasattr(mod, "dayinla_generate")
    assert hasattr(mod, "dayinla_get_prompts")
    assert hasattr(mod, "generate")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sugar_gen_lazy_imports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'PIL'` raised at import (top-level import), or the test can't import the module because of the blocked imports.

Note: the test imports the module from repo root, so `skills/sugar-painting-gen/scripts` must be on the path. Add a `conftest.py` if not already resolvable — first check `pyproject.toml` for `pythonpath`/`testpaths` config; if the module isn't importable, add to `tests/conftest.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "sugar-painting-gen", "scripts"))
```

- [ ] **Step 3: Make imports lazy**

Edit `skills/sugar-painting-gen/scripts/sugar_painting_gen.py`. Remove the top-level PIL/numpy import lines (lines 29-30):

```python
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import numpy as np
```

Replace with a comment marker so the lazy imports are obvious:

```python
# PIL/numpy imported lazily inside postprocess_sugar_style() and ark_*() so the
# dayinla default path runs on devices without PIL/numpy (quantum-bot m310).
```

Then add the imports at the top of each function that uses them.

In `ark_get_api_key` — it already does `import yaml` inside; leave it.

In `ark_generate(prompt, size="2048x2048")` — it already does `import yaml` inside; leave it (no PIL/numpy used there).

In `postprocess_sugar_style(image_path, output_path, line_color=(255, 165, 0), bg_color=(0, 0, 0), threshold=128)` — add at the very top of the function body (after the docstring):

```python
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    import numpy as np
```

Verify no other function uses `Image`/`numpy` by searching:

```bash
grep -n "Image\.\|np\.\|numpy\|ImageFilter\|ImageEnhance\|ImageOps" skills/sugar-painting-gen/scripts/sugar_painting_gen.py
```

Every match must be inside `postprocess_sugar_style` (now with the local import) or removed. If `download_image` or others reference them, they don't — confirm `download_image` only uses `urllib`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sugar_gen_lazy_imports.py -v`
Expected: PASS.

Sanity-check the module still imports normally with PIL present:

```bash
python -c "import sys; sys.path.insert(0,'skills/sugar-painting-gen/scripts'); import sugar_painting_gen; print('ok', hasattr(sugar_painting_gen,'generate'))"
```
Expected: `ok True`

- [ ] **Step 5: Commit**

```bash
git add skills/sugar-painting-gen/scripts/sugar_painting_gen.py tests/test_sugar_gen_lazy_imports.py tests/conftest.py
git commit -m "feat(sugar-gen): lazy PIL/numpy imports so dayinla runs zero-dep on device"
```

---

### Task 2: `trajectory_prepare.py` — validation + normalized→±240 mapping

**Files:**
- Create: `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`
- Create: `tests/test_trajectory_prepare.py`

**Interfaces:**
- Consumes: the LLM's normalized JSON `{description, strokes:[{points:[[nx,ny]...]}]}` with `nx,ny ∈ [0,1]`.
- Produces: `parse_and_map(raw_json: str) -> dict` returning `{"description": str, "strokes": [{"points": [[x,y],...]}]}` with integer `x,y ∈ [-240,240]`, Y-flipped. Raises `TrajectoryError` on contract violation. Also produces `map_point(nx, ny) -> tuple[int,int]` and `dedup_points(points) -> list`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trajectory_prepare.py`:

```python
import json
import pytest

from trajectory_prepare import parse_and_map, map_point, TrajectoryError


def test_map_point_corners():
    # Normalized [0,1] -> ±240, Y flipped (image y-down -> machine y-up).
    assert map_point(0.0, 0.0) == (-240, 240)     # top-left image  -> bottom-left machine Y... see below
    assert map_point(1.0, 0.0) == (240, 240)      # top-right
    assert map_point(0.0, 1.0) == (-240, -240)    # bottom-left
    assert map_point(1.0, 1.0) == (240, -240)     # bottom-right
    assert map_point(0.5, 0.5) == (0, 0)          # center


def test_map_point_clamps():
    # Values outside [0,1] clamp to the edges.
    assert map_point(-0.5, 1.5) == (-240, -240)
    assert map_point(2.0, -1.0) == (240, 240)


def test_parse_and_map_strips_markdown_fence():
    raw = '```json\n{"description":"dragon","strokes":[{"points":[[0.1,0.2],[0.3,0.4]]}]}\n```'
    plan = parse_and_map(raw)
    assert plan["description"] == "dragon"
    pts = plan["strokes"][0]["points"]
    assert pts[0] == map_point(0.1, 0.2)
    assert pts[1] == map_point(0.3, 0.4)


def test_parse_and_map_requires_strokes():
    with pytest.raises(TrajectoryError):
        parse_and_map('{"description":"x","strokes":[]}')


def test_parse_and_map_requires_points():
    with pytest.raises(TrajectoryError):
        parse_and_map('{"description":"x","strokes":[{"points":[]}]}')


def test_parse_and_map_stroke_needs_two_points():
    with pytest.raises(TrajectoryError):
        parse_and_map('{"description":"x","strokes":[{"points":[[0.5,0.5]]}]}')


def test_parse_and_map_coords_are_ints_in_range():
    plan = parse_and_map('{"strokes":[{"points":[[0.0,0.0],[0.9,0.9]]}]}')
    for x, y in plan["strokes"][0]["points"]:
        assert isinstance(x, int) and isinstance(y, int)
        assert -240 <= x <= 240 and -240 <= y <= 240
```

Note on `map_point` corners: with `x = round(nx*480-240)` and `y = round((1-ny)*480-240)`:
- `(0,0)` → x=-240, y=round(480-240)=240
- `(1,0)` → x=240, y=240
- `(0,1)` → x=-240, y=round(0-240)=-240
- `(1,1)` → x=240, y=-240
- `(0.5,0.5)` → x=0, y=0. The test assertions above are correct.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trajectory_prepare.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'trajectory_prepare'`.

Add to `tests/conftest.py` (extend, don't overwrite):

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".import_bundle", "image-to-trajectory", "scripts"))
```

- [ ] **Step 3: Write minimal implementation**

Create `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`:

```python
#!/usr/bin/env python3
"""
trajectory_prepare.py — contract guardian for model-traced sugar-painting trajectories.

The LLM emits normalized [0,1] coordinates. This module validates that JSON,
maps to the machine's ±240 integer space (Y flipped: image y-down -> machine
y-up), and renders an SVG preview. Pure stdlib so it runs on the quantum-bot
device (no PIL/numpy).

Contract (matches painter_cli.servo.json_loader + painter_cli.drawing.parser):
    {"description": str, "strokes": [{"points": [[x,y], ...]}]}
with integer x,y in [-240, 240], each stroke >= 2 points.
"""
import json
import re
import math

CANVAS = 240          # half-extent; full range is ±240
STICK_TOL = 3         # |x| <= STICK_TOL counts as touching the X=0 stick axis


class TrajectoryError(Exception):
    """Raised when the model's trajectory JSON violates the contract."""


def _strip_code_fences(text):
    text = text.strip()
    m = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def map_point(nx, ny):
    """Map normalized [0,1] -> (x, y) integer in [-240, 240], Y flipped."""
    nx = min(1.0, max(0.0, float(nx)))
    ny = min(1.0, max(0.0, float(ny)))
    x = int(round(nx * (2 * CANVAS) - CANVAS))
    y = int(round((1.0 - ny) * (2 * CANVAS) - CANVAS))
    return x, y


def _parse_point(p):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise TrajectoryError(f"point must be [nx, ny], got {p!r}")
    try:
        return float(p[0]), float(p[1])
    except (TypeError, ValueError):
        raise TrajectoryError(f"point coordinates must be numeric, got {p!r}")


def dedup_points(points):
    """Drop consecutive duplicate points."""
    out = []
    for p in points:
        if not out or out[-1] != p:
            out.append(p)
    return out


def parse_and_map(raw_json):
    """Validate the model's normalized JSON and map to ±240 integer strokes."""
    cleaned = _strip_code_fences(raw_json)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise TrajectoryError(f"invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise TrajectoryError(f"expected JSON object, got {type(data).__name__}")

    description = data.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    raw_strokes = data.get("strokes")
    if not isinstance(raw_strokes, list) or not raw_strokes:
        raise TrajectoryError("missing or empty strokes array")

    strokes = []
    for i, rs in enumerate(raw_strokes):
        if not isinstance(rs, dict):
            raise TrajectoryError(f"stroke {i} must be an object")
        raw_points = rs.get("points")
        if not isinstance(raw_points, list) or not raw_points:
            raise TrajectoryError(f"stroke {i} must contain a non-empty points array")
        pts = [map_point(*_parse_point(p)) for p in raw_points]
        pts = dedup_points(pts)
        if len(pts) < 2:
            raise TrajectoryError(f"stroke {i} has fewer than 2 points after dedup")
        strokes.append({"points": pts})

    return {"description": description, "strokes": strokes}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_trajectory_prepare.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py tests/test_trajectory_prepare.py tests/conftest.py
git commit -m "feat(trajectory): stdlib trajectory_prepare — validate + map normalized->±240"
```

---

### Task 3: `trajectory_prepare.py` — stick adhesion

**Files:**
- Modify: `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`
- Modify: `tests/test_trajectory_prepare.py`

**Interfaces:**
- Produces: `enforce_stick_adhesion(plan: dict, stick_tol: int = STICK_TOL) -> dict` — mutates/returns the plan so at least one stroke crosses `|x| <= stick_tol`; if none does, prepends `[0, y]` to the nearest stroke. `parse_and_map` calls it before returning.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trajectory_prepare.py`:

```python
from trajectory_prepare import enforce_stick_adhesion, STICK_TOL


def _plan(strokes):
    return {"description": "", "strokes": [{"points": list(s)} for s in strokes]}


def test_stick_adhesion_noop_when_already_anchored():
    # First stroke already crosses x=0.
    plan = _plan([[[0, 10], [5, 20]], [[100, 0], [100, 50]]])
    out = enforce_stick_adhesion(plan)
    assert out["strokes"][0]["points"][0] == [0, 10]  # unchanged


def test_stick_adhesion_prepends_anchor_to_nearest_stroke():
    # No stroke crosses x=0; nearest stroke's first point is (10, 30).
    plan = _plan([[[10, 30], [50, 60]], [[20, -20], [80, -40]]])
    out = enforce_stick_adhesion(plan)
    # The anchor [0, y] is prepended to the stroke with the point closest to x=0.
    first = out["strokes"][0]["points"][0]
    assert first[0] == 0
    # Anchor y is the y of the closest point (here (10,30) -> y=30).
    assert first[1] == 30


def test_stick_adhesion_picks_truly_nearest_point():
    # Second stroke has a point at x=1, closer than first stroke's x=10.
    plan = _plan([[[10, 30], [50, 60]], [[1, -5], [80, -40]]])
    out = enforce_stick_adhesion(plan)
    anchored = out["strokes"][1]["points"][0]
    assert anchored[0] == 0
    assert anchored[1] == -5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trajectory_prepare.py -k stick_adhesion -v`
Expected: FAIL — `ImportError: cannot import name 'enforce_stick_adhesion'`.

- [ ] **Step 3: Implement enforce_stick_adhesion**

Add to `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py` (before `parse_and_map`):

```python
def enforce_stick_adhesion(plan, stick_tol=STICK_TOL):
    """Ensure at least one stroke touches the X=0 stick axis.

    If no stroke crosses |x| <= stick_tol, prepend [0, y] to whichever
    stroke contains the point closest to x=0 (using that point's y).
    """
    def crosses_stick(stroke):
        return any(abs(p[0]) <= stick_tol for p in stroke["points"])

    if any(crosses_stick(s) for s in plan["strokes"]):
        return plan

    best_stroke = 0
    best_point_idx = 0
    best_dist = float("inf")
    for si, st in enumerate(plan["strokes"]):
        for pi, p in enumerate(st["points"]):
            d = abs(p[0])
            if d < best_dist:
                best_dist = d
                best_stroke = si
                best_point_idx = pi

    anchor = [0, plan["strokes"][best_stroke]["points"][best_point_idx][1]]
    plan["strokes"][best_stroke]["points"] = [anchor] + plan["strokes"][best_stroke]["points"]
    return plan
```

Then call it at the end of `parse_and_map`, just before `return`:

```python
    plan = {"description": description, "strokes": strokes}
    plan = enforce_stick_adhesion(plan)
    return plan
```

(Replace the existing final `return {"description": ...}` with these two lines.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_trajectory_prepare.py -v`
Expected: PASS (all tests, including the 3 new ones).

- [ ] **Step 5: Commit**

```bash
git add .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py tests/test_trajectory_prepare.py
git commit -m "feat(trajectory): enforce stick adhesion (x=0 anchor) in trajectory_prepare"
```

---

### Task 4: `trajectory_prepare.py` — SVG preview + CLI

**Files:**
- Modify: `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`
- Modify: `tests/test_trajectory_prepare.py`

**Interfaces:**
- Produces: `render_svg(plan: dict, size: int = 600) -> str` (SVG string in ±240 space, Y-up) and a `main()` CLI: `python trajectory_prepare.py <input.json> <output.json> [--svg path.svg]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trajectory_prepare.py`:

```python
from trajectory_prepare import render_svg


def test_render_svg_contains_paths_and_coords():
    plan = _plan([[[0, 0], [100, 100]], [[0, 0], [-100, -100]]])
    svg = render_svg(plan, size=600)
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    # Two strokes -> two <path> elements.
    assert svg.count("<path") == 2


def test_render_svg_is_valid_xml():
    import xml.etree.ElementTree as ET
    plan = _plan([[[0, 0], [240, 240]]])
    svg = render_svg(plan)
    ET.fromstring(svg)  # raises if not well-formed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_trajectory_prepare.py -k render_svg -v`
Expected: FAIL — `ImportError: cannot import name 'render_svg'`.

- [ ] **Step 3: Implement render_svg + CLI**

Add to `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`:

```python
COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
    "#ffd8b1", "#000075", "#a9a9a9", "#fffac8", "#7cb342",
]


def render_svg(plan, size=600):
    """Render a plan (±240, Y-up) to an SVG string. Pure stdlib."""
    strokes = plan["strokes"]
    pad = 30
    draw = size - 2 * pad
    scale = draw / (2 * CANVAS)

    def tx(x):
        return round(pad + (x + CANVAS) * scale)

    def ty(y):
        return round(pad + (CANVAS - y) * scale)  # Y flip for SVG (y-down)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}">',
        f'<rect width="{size}" height="{size}" fill="#111"/>',
        # stick axis
        f'<line x1="{tx(0)}" y1="{pad}" x2="{tx(0)}" y2="{size - pad}" '
        f'stroke="#444" stroke-width="1"/>',
    ]
    for i, st in enumerate(strokes):
        c = COLORS[i % len(COLORS)]
        pts = st["points"]
        d = " ".join(
            f"{'M' if j == 0 else 'L'} {tx(p[0])} {ty(p[1])}"
            for j, p in enumerate(pts)
        )
        parts.append(
            f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)
```

Add a CLI at the bottom of the file:

```python
def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Validate + map a model-traced trajectory to ±240 and emit SVG.")
    ap.add_argument("input", help="Input JSON (normalized [0,1] or already ±240)")
    ap.add_argument("output", nargs="?", default=None, help="Output ±240 JSON path")
    ap.add_argument("--svg", default=None, help="Also write an SVG preview here")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw = f.read()
    plan = parse_and_map(raw)

    out_path = args.output or args.input.rsplit(".", 1)[0] + "_plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    print(f"Written: {out_path}")

    svg_path = args.svg or out_path.replace(".json", ".svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(render_svg(plan))
    print(f"SVG: {svg_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_trajectory_prepare.py -v`
Expected: PASS (all tests).

End-to-end CLI sanity check (uses a temp file, no network):

```bash
python -c "
import json, tempfile, os
from tests.conftest import *
" 2>/dev/null; cat > /tmp/_trace.json <<'EOF'
{"description":"dragon","strokes":[{"points":[[0.1,0.2],[0.5,0.8],[0.9,0.2]]},{"points":[[0.2,0.5],[0.8,0.5]]}]}
EOF
python .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py /tmp/_trace.json /tmp/_out.json --svg /tmp/_out.svg
echo "--- output json ---"; cat /tmp/_out.json
echo "--- svg head ---"; head -3 /tmp/_out.svg
```
Expected: prints `Written: /tmp/_out.json` and `SVG: /tmp/_out.svg`; JSON has integer ±240 coords with a `[0,...]` anchor prepended (stick adhesion); SVG head is `<svg ...>`.

- [ ] **Step 5: Commit**

```bash
git add .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py tests/test_trajectory_prepare.py
git commit -m "feat(trajectory): SVG preview + CLI in trajectory_prepare"
```

---

### Task 5: `image-to-trajectory` SKILL.md rewrite

**Files:**
- Modify: `.import_bundle/image-to-trajectory/SKILL.md` (full rewrite)

**Interfaces:**
- Consumes: the JSON contract (Global Constraints) and the `trajectory_prepare.py` CLI (Task 4).
- Produces: an importable skill document the agent follows to vision-trace a PNG into normalized JSON, then run `trajectory_prepare.py`.

- [ ] **Step 1: Read the current SKILL.md to preserve structure**

Run: `cat .import_bundle/image-to-trajectory/SKILL.md`
Note its section layout (When to Use, Prerequisites, Pipeline, etc.) — reuse the structure but replace the content.

- [ ] **Step 2: Rewrite SKILL.md**

Overwrite `.import_bundle/image-to-trajectory/SKILL.md` with:

```markdown
---
name: image-to-trajectory
description: "Convert a sugar-painting PNG into a drawing trajectory JSON by LLM vision-tracing. Emits ±240 integer strokes (stick-anchored) + SVG preview. No PIL/numpy needed — heavy work is done by the model, the device only runs a stdlib validator/mapper."
metadata: {"nanobot":{"emoji":"🖌️","requires":{"bins":["python3"]}}}
---

# Image to Trajectory (模型视觉描线)

Turn a generated sugar-painting PNG into a drawing trajectory: a JSON of
±240 integer strokes that drives the physical servo sugar-painting machine,
plus an SVG preview. The trajectory is produced by **the model visually
tracing the amber lines**, not by running image processing on the device
(the m310 device has no PIL/numpy and is too slow for CV).

## When to Use

- You have a sugar-painting PNG (from `sugar-painting-gen`) and need a trajectory.
- User asks to "make this drawable" / "convert to strokes" / "准备糖画轨迹".
- You need a trajectory JSON to send to `painter-cli servo draw`.

## Prerequisites

**Python environment:** System Python 3 (`/usr/bin/python3`). **No pip, no
numpy, no PIL required** — `trajectory_prepare.py` is pure stdlib.

**Scripts location:**

```
SCRIPTS=/root/update_0508/_quantum-bot/workspace/skills/image-to-trajectory/scripts
```

## Pipeline

```
sugar PNG → [LLM vision-traces lines] → normalized [0,1] JSON
                                              ↓
                            trajectory_prepare.py → ±240 JSON + SVG preview
                                              ↓
                          painter-cli servo draw → physical machine (Modbus)
                                              ↓ (optional, desktop only)
                         GIF micro-service → animated preview
```

## Step 1: Vision-trace the PNG into normalized JSON

Look at the sugar-painting PNG. Trace each visible amber line as a stroke,
in the order a person would draw it. Output **normalized coordinates** in
`[0, 1]` where `(0,0)` is the top-left of the image and `(1,1)` is the
bottom-right. Emit this exact JSON shape:

```json
{
  "description": "<subject> (<N> strokes)",
  "strokes": [
    { "points": [[nx, ny], [nx, ny], ...] }
  ]
}
```

Rules:
- `nx, ny` are floats in `[0, 1]`.
- Each stroke has **≥ 2 points**.
- Trace **continuous lines**; break at junctions. Eyes/holes are separate closed strokes.
- Order strokes as you'd draw them; start near the bamboo-stick axis (image left-center) if visible.
- It is fine to be approximate — `trajectory_prepare.py` enforces the contract.
- Aim for 5–25 strokes; >30 is usually too many.

## Step 2: Prepare the trajectory (validate + map to ±240)

Run the stdlib guardian. It maps normalized → ±240 (Y flipped: image y-down
becomes machine y-up), enforces stick adhesion (anchors to x=0), dedups, and
writes an SVG preview:

```bash
$SCRIPTS/trajectory_prepare.py /tmp/trace_norm.json /tmp/trace.json --svg /tmp/trace.svg
```

`/tmp/trace.json` now contains the machine-ready ±240 strokes. Verify it
looks right by opening `/tmp/trace.svg` (it renders in any browser).

## Step 3 (optional): Animated GIF preview

The GIF service runs on a desktop/cloud host (not the device). Call it over
HTTP the same way as dayin.la:

```bash
curl -s -X POST "$GIF_SERVICE_URL/render-gif" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/trace.json -o /tmp/trace.gif
```

`$GIF_SERVICE_URL` is configurable (local LAN now, cloud later). If the
service is unreachable, skip this step — JSON + SVG is enough to draw.

## JSON Format (machine input)

```json
{
  "description": "lineart (14 strokes)",
  "strokes": [
    {"points": [[0, 84], [10, 80]]}
  ]
}
```

- Coordinate range: X and Y both ±240 (integers).
- X=0 is the bamboo-stick axis (Y-axis).
- Y positive = up.
- At least one stroke touches X=0 (stick adhesion, enforced by trajectory_prepare.py).

## Integration with painter-cli

```bash
# Dry run (validate only)
painter-cli servo draw --dry-run /tmp/trace.json
# Draw on the machine
painter-cli servo draw /tmp/trace.json
```

## Tips

- The model estimates **relative** position well; that's why coordinates are normalized.
- If the SVG looks wrong, re-trace with more/fewer strokes — the model, not the script, decides fidelity.
- dayin.la PNGs are 600×600 square, so the normalized mapping is undistorted.
```

- [ ] **Step 3: Verify frontmatter + paths**

Run:

```bash
head -6 .import_bundle/image-to-trajectory/SKILL.md
grep -c "/root/update_0508/_quantum-bot/workspace/skills/image-to-trajectory" .import_bundle/image-to-trajectory/SKILL.md
grep -nE "/home/se|\.hermes|venv/bin|category: creative" .import_bundle/image-to-trajectory/SKILL.md || echo "no residual local/hermes paths: OK"
```
Expected: frontmatter has `name`, `description`, `metadata: {"nanobot":...}`; path count ≥ 1; "no residual local/hermes paths: OK".

- [ ] **Step 4: Commit**

```bash
git add .import_bundle/image-to-trajectory/SKILL.md
git commit -m "feat(image-to-trajectory): rewrite SKILL.md as LLM vision-trace procedure"
```

---

### Task 6: `sugar-painting-gen` SKILL.md + sync device bundle

**Files:**
- Modify: `.import_bundle/sugar-painting-gen/SKILL.md`
- Modify (copy): `.import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py` (sync from Task 1's source edit)

**Interfaces:**
- Produces: a `.import_bundle/sugar-painting-gen/` whose script matches the Task-1 lazy-import source, with SKILL.md noting ARK needs deps.

- [ ] **Step 1: Copy the lazy-import script into the bundle**

```bash
cp skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
   .import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py
```

Verify the copy has no top-level PIL/numpy import:

```bash
grep -nE "^from PIL|^import numpy" .import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py || echo "no top-level PIL/numpy import: OK"
```
Expected: `no top-level PIL/numpy import: OK`.

- [ ] **Step 2: Update SKILL.md for the device reality**

Overwrite `.import_bundle/sugar-painting-gen/SKILL.md` frontmatter + the ARK note. Read current first:

```bash
head -12 .import_bundle/sugar-painting-gen/SKILL.md
```

Ensure frontmatter is nanobot convention and the engine section reflects the device. The frontmatter (top block) must be:

```markdown
---
name: sugar-painting-gen
description: "Generate sugar painting (糖画) patterns from text prompts. Produces amber-on-black line art in the traditional Chinese sugar painting style. Uses dayin.la AI engine (no auth, no deps) with Volcengine ARK fallback (needs deps)."
metadata: {"nanobot":{"emoji":"🎨","requires":{"bins":["python3"]}}}
---
```

In the body, replace any `~/.hermes/skills/creative/sugar-painting-gen/scripts/` path with `/root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts`, and `/home/se/` with `/root/`. Add a note under "Generation Engine":

```markdown
> **Device note (quantum-bot m310):** Only the **dayinla** engine runs here
> (pure stdlib, no pip/numpy/PIL). The **ark** engine requires PIL/numpy/yaml
> and `~/.ark-helper/config.yaml`; it is not available on this device. Always
> use `--engine dayinla` (the default).
```

- [ ] **Step 3: Verify no residual local/hermes paths**

```bash
grep -rnE "/home/se|\.hermes|category: creative|version: 1|Hermes Agent" .import_bundle/sugar-painting-gen/ || echo "clean: OK"
```
Expected: `clean: OK`.

- [ ] **Step 4: Commit**

```bash
git add .import_bundle/sugar-painting-gen/
git commit -m "feat(sugar-gen): bundle device copy with lazy imports + device-engine note"
```

---

### Task 7: Desktop GIF HTTP micro-service

**Files:**
- Create: `gif_service.py` (repo root)
- Create: `tests/test_gif_service.py`

**Interfaces:**
- Consumes: `trajectory_gif.render_gif(json_path, gif_path=..., canvas_size=..., point_ms=...)` from the existing `trajectory_gif.py`.
- Produces: `handle_render_gif(body_bytes: bytes) -> bytes` returning GIF bytes (raises `GifServiceError` on bad input). An `http.server.BaseHTTPRequestHandler` subclass exposing `POST /render-gif`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gif_service.py`:

```python
import json
import pytest

from gif_service import handle_render_gif, GifServiceError, GIF_MAGIC

VALID_PLAN = {"description": "t", "strokes": [{"points": [[0, 0], [100, 100], [200, 0]]}]}


def test_render_returns_gif_bytes():
    gif = handle_render_gif(json.dumps(VALID_PLAN).encode())
    assert isinstance(gif, bytes)
    assert gif[:6] == GIF_MAGIC  # GIF89a or GIF87a


def test_render_rejects_bad_json():
    with pytest.raises(GifServiceError):
        handle_render_gif(b"not json at all")


def test_render_rejects_empty_strokes():
    with pytest.raises(GifServiceError):
        handle_render_gif(json.dumps({"strokes": []}).encode())


def test_render_rejects_short_stroke():
    with pytest.raises(GifServiceError):
        handle_render_gif(json.dumps({"strokes": [{"points": [[0, 0]]}]}).encode())
```

(`GIF_MAGIC = b"GIF8"` matches both GIF87a and GIF89a.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gif_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gif_service'`.

- [ ] **Step 3: Implement gif_service.py**

Create `gif_service.py` at repo root:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gif_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add gif_service.py tests/test_gif_service.py
git commit -m "feat(gif-service): HTTP micro-service reusing trajectory_gif.render_gif"
```

---

### Task 8: End-to-end smoke test + device bundle verification

**Files:**
- No new files; this task verifies the whole chain.

**Interfaces:**
- Verifies: dayinla-style JSON → `trajectory_prepare.py` → ±240 JSON → `gif_service` → GIF, and that `.import_bundle/` is clean.

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest tests/test_trajectory_prepare.py tests/test_gif_service.py tests/test_sugar_gen_lazy_imports.py -v
```
Expected: all PASS.

- [ ] **Step 2: End-to-end: normalized JSON → ±240 → GIF (local, no device)**

```bash
cat > /tmp/e2e_norm.json <<'EOF'
{"description":"dragon (3 strokes)","strokes":[
  {"points":[[0.1,0.5],[0.4,0.2],[0.6,0.2],[0.9,0.5]]},
  {"points":[[0.2,0.7],[0.5,0.9],[0.8,0.7]]},
  {"points":[[0.45,0.4],[0.55,0.4]]}
]}
EOF
python .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py /tmp/e2e_norm.json /tmp/e2e_plan.json --svg /tmp/e2e.svg
python -c "
import json
from gif_service import handle_render_gif
gif = handle_render_gif(open('/tmp/e2e_plan.json','rb').read())
open('/tmp/e2e.gif','wb').write(gif)
print('gif bytes:', len(gif), 'magic:', gif[:6])
"
```
Expected: `trajectory_prepare.py` prints `Written` + `SVG`; Python prints `gif bytes: <N> magic: b'GIF8'` and `/tmp/e2e.gif` exists.

Verify stick adhesion happened (the plan should have a `[0,...]` anchor since no stroke crosses x=0 in normalized→±240 space — check stroke 0):

```bash
python -c "import json; p=json.load(open('/tmp/e2e_plan.json')); print('first point:', p['strokes'][0]['points'][0])"
```
Expected: first point is `[0, <y>]` (anchored).

- [ ] **Step 3: Verify .import_bundle/ is clean and importable**

```bash
echo "--- tree ---"
find .import_bundle -type f | sort
echo "--- residual local/hermes paths (should be none) ---"
grep -rnE "/home/se|\.hermes|category: creative|version: 1|Hermes Agent|venv/bin" .import_bundle/ || echo "clean: OK"
echo "--- top-level PIL/numpy in bundled scripts (should be none) ---"
grep -rnE "^from PIL|^import numpy|^import cv2" .import_bundle/ || echo "no heavy top-level imports: OK"
```
Expected: tree shows both skills with SKILL.md + scripts; `clean: OK`; `no heavy top-level imports: OK`.

- [ ] **Step 4: (Manual) start the GIF service and confirm it serves**

This step is manual (needs a running server). Document it; do not block automation:

```bash
python gif_service.py --port 8765 &
sleep 1
curl -s -X POST http://127.0.0.1:8765/render-gif -H "Content-Type: application/json" --data-binary @/tmp/e2e_plan.json -o /tmp/e2e_via_http.gif
curl -s http://127.0.0.1:8765/healthz
kill %1
ls -la /tmp/e2e_via_http.gif
```
Expected: `/tmp/e2e_via_http.gif` is a non-empty GIF; `healthz` returns `ok`.

- [ ] **Step 5: Commit the verification artifacts reference**

No code changes in this task; if any fix surfaced, commit it:

```bash
git add -A && git commit -m "chore: e2e smoke + device bundle verification" 2>&1 | tail -2 || echo "nothing to commit (clean)"
```

- [ ] **Step 6: Update memory**

Update `C:\Users\se\.claude\projects\C--Users-se-projects-painter-cli\memory\quantum-bot-device.md` "Environment gaps" section: the skills no longer need numpy/PIL/opencv on the device — `trajectory_prepare.py` is pure stdlib and `sugar_painting_gen.py` (dayinla) is lazy-import zero-dep. GIF is served by a desktop/cloud HTTP micro-service. Then note the new architecture in `MEMORY.md`.

```bash
# After editing the memory file, no git commit (memory is outside the repo).
```

---

## Self-Review Notes

**Spec coverage:**
- Component A (lazy imports) → Task 1, 6. ✓
- Component B (image-to-trajectory rework: prepare script + SKILL.md) → Tasks 2, 3, 4, 5. ✓
- Component C (GIF HTTP service) → Task 7. ✓
- JSON contract (±240, ≥2 pts, fences, Y-up) → Task 2 tests + implementation. ✓
- Normalized→±240 mapping with Y flip → Task 2 `map_point`. ✓
- Stick adhesion → Task 3. ✓
- SVG preview → Task 4. ✓
- Configurable GIF endpoint (local/cloud) → SKILL.md uses `$GIF_SERVICE_URL` (Task 5); service binds `0.0.0.0` + configurable port (Task 7). ✓
- GIF best-effort (graceful degrade) → SKILL.md Step 3 says "skip if unreachable" (Task 5). ✓
- Device deliverables in `.import_bundle/` → Tasks 5, 6 + verified Task 8. ✓
- nanobot frontmatter → Tasks 5, 6 frontmatter. ✓

**Placeholder scan:** None — every code step has full code; every test has real assertions; commands have expected output.

**Type consistency:** `parse_and_map`, `map_point`, `enforce_stick_adhesion`, `render_svg`, `dedup_points`, `TrajectoryError`, `STICK_TOL`, `CANVAS` are used consistently across tasks. `handle_render_gif`/`GifServiceError`/`GIF_MAGIC` consistent between Task 7 tests and impl. ✓
