---
name: sugar-painting-flow
description: "One-shot sugar-painting flow: text prompt → sugar-painting PNG (dayin.la) → POST /trace (deterministic CV) turns the PNG into a trajectory JSON → ±240 strokes + SVG preview → animated GIF. All on-device, zero-dependency (system Python 3). Stops at the GIF preview."
metadata: {"nanobot":{"emoji":"🍭","requires":{"bins":["python3"]}}}
---

# Sugar Painting Flow (糖画全流程)

End-to-end sugar-painting preview, from a text prompt to an animated GIF:
generate a sugar-painting image, trace it into a drawing trajectory, render a
preview SVG, then produce an animated GIF of the drawing process.

This skill **orchestrates** one existing skill and one service — it contains
no scripts of its own:

- `sugar-painting-gen` — generates the PNG from a text prompt (dayin.la, no auth).
- `gif_service` (desktop/cloud HTTP, same host) — `POST /trace` runs the CV
  pipeline on the PNG and returns a ±240 trajectory JSON + SVG preview;
  `POST /render-gif` turns the ±240 trajectory JSON into a GIF.

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
```

**Trace + GIF service (same host):**

```
TRACE_SERVICE=http://192.168.0.113:8765
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
② POST /trace  →  /tmp/trace.json + /tmp/trace.svg   (±240, stick-anchor, +svg)
      │
      ▼
③ POST /render-gif  →  /tmp/trace.gif          (urllib, no curl)
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

## Step 3: Prepare the trajectory (was: run trajectory_prepare.py)

Now done server-side by `/trace` — the service validates, maps to ±240
(Y flipped: image y-down → machine y-up), enforces stick adhesion, dedups, and
returns the SVG preview in the `svg` field. Skip this step; `/tmp/trace.json`
and `/tmp/trace.svg` from Step 2 are already machine-ready.

## Step 3: Generate the animated GIF

The device has **no `curl`**. Call the GIF service over `urllib` (pure stdlib,
same pattern `sugar-painting-gen` uses for dayin.la):

```python
import urllib.request

GIF_SERVICE = "http://192.168.0.113:8765"   # same host as /trace; swap for a cloud URL later
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
touching anything else. If the service is unreachable, Step 3 is skipped;
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
- **/trace fails (bad PNG / CV error):** the service returns an error → retry Step 1 with a simpler prompt, or re-run Step 2 once the service is healthy.
- **GIF service unreachable:** Step 3 is skipped (caught above). Still deliver `/tmp/sugar.png` + `/tmp/trace.svg`.

## End-to-end example ("龙")

```bash
# 1. Generate PNG
python3 /root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
  --prompt "龙" --engine dayinla --output /tmp/sugar.png

# 2. POST /tmp/sugar.png to http://192.168.0.113:8765/trace → /tmp/trace.json + /tmp/trace.svg
#    (urllib multipart upload — see Step 2)

# 3. POST /tmp/trace.json to http://192.168.0.113:8765/render-gif → /tmp/trace.gif
#    (urllib JSON body — see Step 3)
```

Artifacts: `/tmp/sugar.png`, `/tmp/trace.svg`, `/tmp/trace.gif`.
