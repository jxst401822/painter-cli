---
name: image-to-trajectory
description: Convert images (photos, illustrations, line art) to sugar painting trajectory JSON + animated GIF. Analyzes image edges, extracts skeleton paths, and outputs drawing trajectories with connectivity enforcement and stick adhesion.
category: creative
---

# Image to Trajectory (图片转轨迹)

Convert any image into a sugar painting trajectory: a JSON file of coordinate strokes, a PNG preview, an SVG vector, and an animated GIF showing the drawing process.

## When to Use

- User provides an image and wants a trajectory / sugar painting path from it
- User asks to "convert this picture to a drawing path"
- User wants to see how something would be drawn step by step (GIF animation)
- User wants to generate a plan for the physical sugar painting machine

## Prerequisites

**Python environment:** Use the Hermes venv (has numpy, PIL, opencv-python-headless):

```
PY=/home/se/.hermes/hermes-agent/venv/bin/python
```

**Project location:**

```
PROJECT=/home/se/projects/painter-cli
```

**Dependencies:** numpy, Pillow, opencv-python-headless (all installed in Hermes venv).

## Pipeline Overview

```
Image → image_to_trajectory.py → JSON + PNG + SVG
                                   ↓
                          trajectory_gif.py → GIF
                                   ↓
                          painter-cli draw   → Physical drawing (optional)
```

## Step 1: Image to Trajectory

```bash
$PY $PROJECT/image_to_trajectory.py <input_image> <output.json> [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mode` | `auto` | `auto`, `lineart`, or `photo` |
| `--max-dim` | mode-dependent | Max image dimension in pixels (higher = more detail) |
| `--sigma` | mode-dependent | Gaussian smoothing strength (higher = smoother) |
| `--eps` | mode-dependent | Douglas-Peucker simplification (higher = fewer points) |
| `--resample` | mode-dependent | Target points per stroke |
| `--prune` | `15` | Skeleton pruning iterations (higher = cleaner) |
| `--min-contour` | `50` | Min contour area to keep (photo mode, removes noise) |
| `--threshold` | None | Manual binary threshold (lineart mode only) |
| `--debug` | off | Save intermediate images (binary mask, skeleton) |
| `--compare` | off | Run both modes, generate side-by-side comparison |

### Mode Defaults

| Mode | sigma | eps | max_dim | resample |
|------|-------|-----|---------|----------|
| lineart | 4.0 | 1.5 | 200 | 100 |
| photo | 6.0 | 2.5 | 250 | 120 |

### Mode Selection

| Image Type | Mode | Example |
|------------|------|---------|
| Clean line art / illustrations / sketches | `lineart` | Anime, logos, icons |
| Photographs / real photos | `photo` | Portraits, objects |
| Uncertain | `auto` | Auto-detect via edge density + variance |

### Output Files

- `<output>.json` — Trajectory data (strokes with [x, y] points, range ±240)
- `<output>.png` — Visual preview (colored strokes on white canvas)
- `<output>.svg` — Vector version
- With `--debug`: `<output>_debug_binary.png` and `<output>_debug_skeleton.png`

## Step 2: Generate GIF Animation

```bash
$PY $PROJECT/trajectory_gif.py <trajectory.json> <output.gif> [options]
```

**IMPORTANT:** Always specify the output `.gif` path explicitly. Without it, the script derives the path but may fail due to CLI parsing.

### GIF Options

| Option | Default | Description |
|--------|---------|-------------|
| `--speed` | `15` | Milliseconds per point (lower = faster drawing) |
| `--size` | `600` | Canvas size in pixels (square) |

The GIF shows:
- Progressive stroke drawing with colored lines
- Red dot tracking the current drawing position
- X=0 stick reference line (gray)
- 300ms pause between strokes, 2s hold on final frame
- Infinite loop

## Parameter Tuning Guide

### Clean illustrations (best results)

```bash
$PY $PROJECT/image_to_trajectory.py input.jpg output.json \
  --mode lineart --max-dim 150 --sigma 6 --eps 1.2 --resample 80
```

Lower max-dim + higher sigma = fewer, smoother strokes.

### Detailed images with fine features

```bash
$PY $PROJECT/image_to_trajectory.py input.jpg output.json \
  --mode lineart --max-dim 400 --prune 5 --eps 1.0
```

Higher max-dim preserves small details. Lower prune keeps short features.

### Noisy/blurry photos

```bash
$PY $PROJECT/image_to_trajectory.py input.jpg output.json \
  --mode photo --min-contour 100 --prune 20
```

Higher min-contour removes noise. Higher prune cleans skeleton.

### Simple, clean sugar paintings (few strokes)

```bash
$PY $PROJECT/image_to_trajectory.py input.jpg output.json \
  --max-dim 200 --eps 2.5 --prune 15
```

Higher eps = fewer points. Lower max-dim = faster processing.

## Complete Workflow Examples

### Example 1: Clean illustration to GIF

```bash
PY=/home/se/.hermes/hermes-agent/venv/bin/python
PROJECT=/home/se/projects/painter-cli

# Step 1: Image → trajectory
$PY $PROJECT/image_to_trajectory.py cute_drawing.png /tmp/trace.json \
  --mode lineart --max-dim 150 --sigma 6 --eps 1.2 --resample 80

# Step 2: Trajectory → GIF
$PY $PROJECT/trajectory_gif.py /tmp/trace.json /tmp/trace.gif --speed 10 --size 600
```

### Example 2: Photo to trajectory with debug

```bash
$PY $PROJECT/image_to_trajectory.py portrait.jpg /tmp/portrait.json \
  --mode photo --max-dim 250 --debug

$PY $PROJECT/trajectory_gif.py /tmp/portrait.json /tmp/portrait.gif --speed 15
```

### Example 3: Auto mode with comparison

```bash
$PY $PROJECT/image_to_trajectory.py image.png /tmp/result.json --compare
# Generates result_lineart.json, result_photo.json, result_compare.png
```

## JSON Format

```json
{
  "description": "lineart (14 strokes)",
  "strokes": [
    {"points": [[0, 84], [10, 80], ...]},
    {"points": [[20, 18], [25, 15], ...]}
  ]
}
```

- Coordinate range: X and Y both ±240
- X=0 is the bamboo stick position (Y-axis)
- Y positive = up
- All strokes are physically connected (bridges auto-added)
- Every stroke touches X=0 (stick adhesion enforced)

## Integration with painter-cli

After generating the trajectory JSON, send it to the physical sugar painting machine:

```bash
# Dry run (validate only)
painter-cli draw --dry-run /tmp/trace.json

# Draw on the machine (PLC at 10.10.20.208:502)
painter-cli draw /tmp/trace.json
```

See the `painter-cli` skill for physical drawing details.

## Tips

- For best results, start with clean line art or illustrations rather than photos
- Sugar painting patterns (black background, amber lines) work well in lineart mode
- If the trajectory has too many strokes (>30), increase `--eps` or `--prune`
- If the trajectory is missing details, increase `--max-dim` or decrease `--prune`
- The `--compare` flag is useful for deciding which mode works better for a given image
- Generated GIFs can be large (100KB-1MB) for complex trajectories

## Delivering GIFs on WeChat/Weixin

GIFs embedded as markdown `![desc](MEDIA:/path/to.gif)` **do not animate** in WeChat — they arrive as static images. To deliver an animated GIF:

1. Use `send_message` with `message: "MEDIA:/path/to/file.gif"` and `target: "weixin"` to send it as a native media attachment.
2. Static PNG previews can still be sent via markdown `![desc](MEDIA:/path/to.png)` — only GIFs need the separate send_message call.

## Delivering GIFs on WeChat

GIFs embedded as markdown `![desc](MEDIA:/path.gif)` do **not** animate in WeChat — they appear as static images. To deliver a playable animated GIF:

```bash
# Send as a separate media file via send_message
send_message(action='send', message='MEDIA:/tmp/trace.gif', target='weixin')
```

Always send the GIF as its own media message, not inline with text.
