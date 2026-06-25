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
