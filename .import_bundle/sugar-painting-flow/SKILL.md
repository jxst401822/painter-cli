---
name: sugar-painting-flow
description: "One-shot sugar-painting flow: text prompt → sugar-painting PNG (dayin.la) → agent vision-traces the PNG into a trajectory JSON → ±240 strokes + SVG preview → animated GIF. All on-device, zero-dependency (system Python 3). Stops at the GIF preview."
metadata: {"nanobot":{"emoji":"🍭","requires":{"bins":["python3"]}}}
---

# Sugar Painting Flow (糖画全流程)

End-to-end sugar-painting preview, from a text prompt to an animated GIF:
generate a sugar-painting image, trace it into a drawing trajectory, render a
preview SVG, then produce an animated GIF of the drawing process.

This skill **orchestrates** two existing skills and one service — it contains
no scripts of its own:

- `sugar-painting-gen` — generates the PNG from a text prompt (dayin.la, no auth).
- `image-to-trajectory` — the agent visually traces the PNG into a trajectory;
  `trajectory_prepare.py` maps it to the machine's ±240 space + SVG preview.
- `gif_service` (desktop/cloud HTTP) — turns the ±240 trajectory JSON into a GIF.

The device (m310) has no PIL/numpy/opencv and no `curl`. Everything here runs
on system Python 3 with the standard library only.

## When to Use

- User gives a text prompt and wants a sugar painting made ("画条龙", "戴墨镜的猫").
- User wants to see the whole chain from words to a shareable animated preview.
- User says "糖画全流程" / "生成糖画并预览绘制过程".

## Prerequisites

**Python environment:** System Python 3 (`/usr/bin/python3`). Zero dependencies —
no pip, no numpy, no PIL, no opencv.

**Script paths:**

```
SUGAR_SCRIPTS=/root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts
TRAJ_SCRIPTS=/root/update_0508/_quantum-bot/workspace/skills/image-to-trajectory/scripts
```

**GIF service:**

```
GIF_SERVICE=http://192.168.0.113:8765
```

## Pipeline

```
text prompt ("龙")
      │
      ▼
① sugar-painting-gen  →  /tmp/sugar.png        (dayin.la, pure stdlib)
      │
      ▼
② agent vision-traces PNG  →  /tmp/trace_norm.json   (normalized [0,1])
      │
      ▼
③ trajectory_prepare.py  →  /tmp/trace.json + /tmp/trace.svg   (±240, stick-anchor)
      │
      ▼
④ POST GIF service  →  /tmp/trace.gif          (urllib, no curl)
      │
      ▼
   report PNG + SVG + GIF to the user
```

## Step 1: Generate the sugar-painting PNG

Use the dayin.la engine (default, no auth, no deps). Pick a short prompt
(≤40 chars for dayin.la): an animal, character, or simple object.

```bash
python3 $SUGAR_SCRIPTS/sugar_painting_gen.py \
  --prompt "龙" --engine dayinla --output /tmp/sugar.png
```

Output: `/tmp/sugar.png` (600×600, black background, amber lines). The ARK
engine requires PIL/numpy/yaml and `~/.ark-helper/config.yaml` — not
available on this device, so always use `--engine dayinla` (the default).

Note: dayin.la rate-limits (cooldown doubles each use). For batch work, add
delays. See the `sugar-painting-gen` skill for full prompt tips and the
dayin.la API reference.

## Step 2: Vision-trace the PNG into a normalized trajectory JSON

Look at `/tmp/sugar.png`. Trace each visible amber line as a stroke, in the
order a person would draw it. Output **normalized coordinates** in `[0, 1]`
where `(0,0)` is the image top-left and `(1,1)` is the bottom-right. Emit
this exact shape and save it to `/tmp/trace_norm.json`:

```json
{
  "description": "<subject> (<N> strokes)",
  "strokes": [
    { "points": [[0.1, 0.5], [0.4, 0.2], [0.6, 0.2], [0.9, 0.5]] }
  ]
}
```

Rules:
- `nx, ny` are floats in `[0, 1]`.
- Each stroke has **≥ 2 points**.
- Trace **continuous lines**; break at junctions. Eyes/holes are separate closed strokes.
- Order strokes as you'd draw them; start near the bamboo-stick axis (image left-center) if visible.
- Approximate is fine — `trajectory_prepare.py` enforces the contract.
- Aim for 5–25 strokes; >30 is usually too many.

See the `image-to-trajectory` skill for the full tracing rule and JSON contract.

## Step 3: Prepare the trajectory (validate + map to ±240 + SVG)

Run the stdlib guardian. It validates the normalized JSON, maps to ±240
(Y flipped: image y-down → machine y-up), enforces stick adhesion (anchors
to x=0), dedups, and writes an SVG preview:

```bash
python3 $TRAJ_SCRIPTS/trajectory_prepare.py \
  /tmp/trace_norm.json /tmp/trace.json --svg /tmp/trace.svg
```

`/tmp/trace.json` now contains machine-ready ±240 strokes. Open `/tmp/trace.svg`
in any browser to verify it looks right before proceeding.

## Step 4: Generate the animated GIF

The device has **no `curl`**. Call the GIF service over `urllib` (pure stdlib,
same pattern `sugar-painting-gen` uses for dayin.la):

```python
import urllib.request

GIF_SERVICE = "http://192.168.0.113:8765"   # LAN now; swap for a cloud URL later
plan = open("/tmp/trace.json", "rb").read()
req = urllib.request.Request(
    f"{GIF_SERVICE}/render-gif",
    data=plan,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        open("/tmp/trace.gif", "wb").write(resp.read())
    print("GIF saved: /tmp/trace.gif")
except urllib.error.URLError as e:
    print(f"GIF service unreachable, skipping: {e}")
```

`GIF_SERVICE` is a single constant — swap it for a cloud URL later without
touching anything else. If the service is unreachable, Step 4 is skipped;
`/tmp/trace.json` + `/tmp/trace.svg` are still delivered.

## Delivering to the user

Report the artifact paths:

- `/tmp/sugar.png` — the generated sugar painting (PNG).
- `/tmp/trace.svg` — trajectory vector preview (SVG).
- `/tmp/trace.gif` — animated drawing process (GIF).

**WeChat / Weixin:** GIFs embedded as markdown `![desc](MEDIA:/tmp/trace.gif)`
do **not** animate — they arrive as a static image. To deliver an animated GIF,
send it as its own media message:

```python
send_message(action="send", message="MEDIA:/tmp/trace.gif", target="weixin")
```

Static PNG/SVG can be referenced inline, but always send the GIF as a separate
media message.

## Error handling

- **dayin.la down / no PNG:** Step 1 fails → stop, tell the user generation failed, retry later.
- **Bad trajectory JSON:** `trajectory_prepare.py` raises `TrajectoryError` → re-trace (Step 2) with more/fewer strokes.
- **GIF service unreachable:** Step 4 is skipped (caught above). Still deliver `/tmp/sugar.png` + `/tmp/trace.svg`.

## End-to-end example ("龙")

```bash
# 1. Generate PNG
python3 /root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
  --prompt "龙" --engine dayinla --output /tmp/sugar.png

# 2. (agent) vision-trace /tmp/sugar.png → /tmp/trace_norm.json

# 3. Prepare trajectory + SVG
python3 /root/update_0508/_quantum-bot/workspace/skills/image-to-trajectory/scripts/trajectory_prepare.py \
  /tmp/trace_norm.json /tmp/trace.json --svg /tmp/trace.svg

# 4. (agent) POST /tmp/trace.json to http://192.168.0.113:8765/render-gif → /tmp/trace.gif
```

Artifacts: `/tmp/sugar.png`, `/tmp/trace.svg`, `/tmp/trace.gif`.
