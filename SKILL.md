# painter-cli

A CLI tool that draws coordinate paths on a physical HMI screen via Modbus TCP to a Schneider PLC. Used for **sugar painting (糖画)** — controlling a valve that dispenses sugar liquid onto a surface with a bamboo stick (木签) for pickup. You generate the coordinate plan; this tool executes it on the hardware.

## When to Use

Use this skill when the user asks you to **draw something on the HMI**, **make a sugar painting**, **draw on the PLC screen**, **paint a shape**, or any request involving controlling the physical drawing arm connected to the Schneider PLC at `10.10.20.208`.

## How It Works

You (the agent) are responsible for:
1. Understanding the user's drawing request
2. Generating a coordinate plan as JSON
3. Calling `painter-cli draw` with the plan

The tool handles:
- Connecting to the PLC via Modbus TCP
- Writing coordinates point-by-point at 150ms intervals
- Valve open/close (pen down = sugar flows, pen up = sugar stops) between strokes
- Progress display

## Coordinate System

**4-quadrant Cartesian system** with origin at center `(0, 0)`:

- **X range**: `-240` to `240` (positive = right)
- **Y range**: `-240` to `240` (positive = up)
- All coordinates must be **integers**

```
        Y=240
          |
          |
 X=-240 --+-- X=240
          |
          |
       Y=-240
```

## JSON Plan Schema

You must generate a JSON object matching this schema:

```json
{
  "description": "Brief description of the drawing",
  "strokes": [
    {
      "points": [[x1, y1], [x2, y2], ...]
    }
  ]
}
```

### Rules

- Each **stroke** is a continuous pen-down path. The pen lifts between strokes.
- Use **20-60 points** per stroke for smooth curves. Use **5-10** for straight lines.
- Keep ALL coordinates within `[-240, 240]` on both axes. Out-of-range values are clamped.
- For complex shapes, decompose into **3-10 strokes**.
- Start each stroke near where the previous one ended to minimize travel time.
- Each stroke needs at least **2 points**.
- Points are floats or ints — they will be rounded to integers.

## Sugar Painting Rules (糖画)

This system controls a **sugar painting machine**, not a pen plotter. Understanding the physical model is essential for generating valid plans.

### Physical Model

- **Pen down** (pen=True) = open valve → sugar liquid flows onto the surface
- **Pen up** (pen=False) = close valve → sugar flow stops
- **Bamboo stick (木签)** = the entire Y-axis (X=0). After the sugar cools and solidifies, the stick is used to lift the finished painting.

### Stick Adhesion Rule (Critical)

After the sugar cools, the painting must be physically attached to the bamboo stick so it can be lifted. This means:

- **Every stroke must include at least one point where X=0** (crossing the stick).
- A stroke that is entirely to the left or right of X=0 will **detach** after cooling — it has no anchor.
- For shapes drawn to the left or right of the stick, add a **root connection**: start or end the stroke at X=0.

```
  ✗ BAD: floating stroke         ✓ GOOD: stroke crosses stick

     X=80                              X=80
      |                                  |
  [stroke]                          ══[stroke]══
      |                                  |
  X=0 (stick) — no contact        X=0 ║ stick crossing
```

### Path Continuity

Sugar liquid flows continuously while the valve is open. Interruptions create weak points.

- Prefer **single continuous strokes** over multiple short ones. Fewer valve open/close cycles produce smoother sugar flow.
- When multi-stroke is necessary, **start each new stroke at X=0** (on the stick).
- Use the **"return to stick" pattern**: draw outward from X=0, trace the shape, then curve back to X=0 before ending the stroke.
- **Auto-interpolation**: The system automatically inserts intermediate points between your control points (default: max 5 coordinate units apart). This means you can provide **sparse control points** — the system densifies them for smooth sugar flow. Set `--step 0` to disable.

### Drawing Strategy

1. **Start from the stick**: the first point of each stroke should be on or near X=0.
2. **Draw outward then return**: trace the shape, then come back to X=0 at the end.
3. **Connected structure**: all strokes must be physically connected to the stick line. No floating islands — every part of the drawing must be reachable from the stick through solid sugar paths.

```
  ✗ BAD: floating eye              ✓ GOOD: connected eye
                                      
       [eye]                              [eye]
        (gap)                               |
  [head outline]                     [head outline]
        |                                  |
  X=0 ║ stick                       X=0 ║ stick
```

### Sugar-Specific Tips

- Use **30-60 points** for curves to ensure smooth sugar flow. Sugar follows the coordinate path exactly.
- **Avoid sharp direction changes** — sugar liquid can't make tight corners well. Use gradual curves instead.
- **Wider contact areas** on the stick = better adhesion. A stroke that crosses X=0 over a wider Y-range holds better.
- **Keep total points reasonable** — sugar cools over time, so faster completion is better. Aim for under 200 total points.

## CLI Commands

### Draw a plan

```bash
# From a JSON string
painter-cli draw '{"description": "circle", "strokes": [{"points": [[120,0],[117,23],...]}]}'

# From a file
painter-cli draw plan.json

# From stdin
echo '{"strokes": [...]}' | painter-cli draw

# Dry run (validate only, no drawing)
painter-cli draw --dry-run plan.json

# Override PLC address
painter-cli draw --host 10.10.20.100 --port 502 plan.json

# Control interpolation density (max distance between points)
painter-cli draw --step 3 plan.json     # smoother (more points, slower)
painter-cli draw --step 0 plan.json     # disable interpolation
```

### Other commands

```bash
painter-cli status    # Test PLC connectivity
painter-cli center    # Pen up, move to origin (0, 0)
painter-cli config    # Show current settings
```

## Drawing Timing

For each stroke, the tool will:
1. Pen **up** → wait 0.5s
2. Move to stroke start → wait 2.0s (travel time)
3. Pen **down** → wait 0.5s
4. Write each point at **150ms** intervals
5. Pen **up** → wait 0.5s

A typical drawing with 100 points across 3 strokes takes approximately **30-40 seconds** to complete.

## Examples

### Circle (single stroke, ~40 points)

```json
{
  "description": "A circle centered at origin with radius 120",
  "strokes": [
    {
      "points": [
        [120, 0], [117, 19], [109, 37], [97, 54], [81, 68],
        [63, 79], [42, 87], [20, 92], [-3, 93], [-25, 91],
        [-46, 85], [-65, 76], [-82, 64], [-96, 49], [-106, 33],
        [-113, 15], [-117, -3], [-117, -22], [-113, -40], [-106, -56],
        [-96, -70], [-82, -82], [-65, -91], [-46, -97], [-25, -100],
        [-3, -100], [20, -97], [42, -91], [63, -82], [81, -70],
        [97, -56], [109, -40], [117, -22], [120, -3], [120, 0]
      ]
    }
  ]
}
```

### House (sugar painting, all strokes cross X=0)

```json
{
  "description": "A house — walls, roof, door, and window, all connected to the stick",
  "strokes": [
    {
      "points": [
        [0, -80], [-40, -80], [-60, -60], [-80, -40], [-100, 0],
        [-80, 40], [-60, 60], [-40, 80], [0, 80]
      ]
    },
    {
      "points": [
        [0, -25], [-50, -25], [-50, 25], [0, 25]
      ]
    },
    {
      "points": [
        [0, 40], [-50, 40], [-50, 65], [0, 65], [0, 40]
      ]
    }
  ]
}
```

### Smiley face (multi-stroke with curves)

```json
{
  "description": "A smiley face",
  "strokes": [
    {
      "points": [
        [150,0],[146,24],[137,46],[123,67],[106,85],[85,100],[62,111],
        [38,118],[12,121],[-14,120],[-40,115],[-64,106],[-86,94],
        [-106,79],[-122,61],[-134,42],[-142,21],[-146,0],[-146,-21],
        [-142,-42],[-134,-61],[-122,-79],[-106,-94],[-86,-106],
        [-64,-115],[-40,-120],[-14,-121],[12,-121],[38,-118],[62,-111],
        [85,-100],[106,-85],[123,-67],[137,-46],[146,-24],[150,0]
      ]
    },
    {
      "points": [[-55,55],[-55,75],[-35,75],[-35,55],[-55,55]]
    },
    {
      "points": [[35,55],[35,75],[55,75],[55,55],[35,55]]
    },
    {
      "points": [
        [-80,-30],[-72,-45],[-60,-55],[-44,-62],[-25,-66],
        [-5,-68],[15,-66],[34,-62],[50,-55],[62,-45],[70,-30]
      ]
    }
  ]
}
```

### Sugar Painting: Flower (stick-crossing pattern)

```json
{
  "description": "A flower — demonstrates the return-to-stick pattern",
  "strokes": [
    {
      "points": [
        [0, 0], [20, 0], [40, 0], [60, 0], [80, 0], [100, 0],
        [130, 20], [150, 40], [160, 50], [170, 40], [175, 20],
        [180, 0], [175, -20], [170, -40], [160, -50], [150, -40],
        [130, -20], [100, 0], [120, 25], [130, 45], [140, 40],
        [145, 25], [140, 0], [145, -25], [140, -40], [130, -45],
        [120, -25], [100, 0], [80, 0], [60, 0], [40, 0], [20, 0], [0, 0]
      ]
    }
  ]
}
```

## Generating Paths — Tips

When generating coordinate paths for sugar paintings:

1. **Return to stick**: Every stroke should start at X=0, trace its shape, and end at X=0. No floating strokes.
2. **Parametric curves**: For circles/arcs, use `x = cx + r*cos(θ)`, `y = cy + r*sin(θ)` with 30-40 steps.
3. **Straight lines**: Interpolate linearly between endpoints with 5-10 intermediate points.
4. **Complex shapes**: Break into components, but ensure **each component connects to X=0**. A cat = body outline crossing X=0 + ears starting from X=0 + tail starting from X=0.
5. **Keep it inside bounds**: Always verify no point exceeds ±240 on either axis.
6. **Smooth transitions**: Avoid sharp direction changes. Use gradual curves — sugar liquid can't pivot sharply.
7. **Don't over-segment**: Aim for under 200 total points. Sugar cools over time, so faster completion is better. The system auto-interpolates, so sparse control points are fine.
8. **Verify stick crossings**: After generating, check that every stroke has at least one point with X=0.

## Image-to-Trajectory Conversion (图片转轨迹)

When the user provides an image (photo, illustration, line art, or sketch), you can convert it to a sugar painting trajectory automatically.

### When to Use

Use this feature when the user:
- Provides an image file and asks to generate a trajectory/sugar painting
- Wants to "draw this image" or "make a sugar painting from this picture"
- Uploads a photo, illustration, or drawing

### How It Works

The tool analyzes the image, extracts edges, converts them to a skeleton, traces paths, and outputs:
- JSON trajectory file (for the robot)
- PNG preview (visual trajectory with colored strokes)
- SVG vector version
- GIF animation (drawing process)

### CLI Commands

```bash
# Basic usage (auto-detects image type)
python image_to_trajectory.py input.jpg output.json

# Force specific mode
python image_to_trajectory.py input.jpg output.json --mode lineart  # for clean illustrations
python image_to_trajectory.py input.jpg output.json --mode photo    # for photographs

# Fine-tune parameters
python image_to_trajectory.py input.jpg output.json --max-dim 400 --eps 1.5 --prune 10

# Save debug images (binary mask, skeleton)
python image_to_trajectory.py input.jpg output.json --debug

# Compare both modes side-by-side
python image_to_trajectory.py input.jpg output.json --compare
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--mode` | `auto` | Processing mode: `auto`, `lineart`, or `photo` |
| `--max-dim` | mode-dependent | Max image dimension in pixels (higher = more detail, slower) |
| `--eps` | mode-dependent | Douglas-Peucker simplification (higher = simpler, fewer points) |
| `--sigma` | mode-dependent | Gaussian smoothing (higher = smoother curves) |
| `--prune` | `15` | Skeleton pruning iterations (higher = cleaner skeleton, may lose fine details) |
| `--min-contour` | `50` | Min contour area to keep in photo mode (removes noise) |
| `--resample` | mode-dependent | Target points per stroke |
| `--debug` | off | Save intermediate images (binary mask, skeleton) |
| `--compare` | off | Run both lineart and photo modes, generate comparison |

### Mode Selection Guide

| Image Type | Recommended Mode | Example |
|------------|-----------------|--------|
| Clean line art / illustrations | `lineart` | Anime drawings, logos, icons, simple sketches |
| Photographs / real photos | `photo` | Portraits, landscapes, real objects |
| Uncertain | `auto` | Let the tool decide (default) |

### Parameter Tuning Tips

**For detailed images with fine features (like horn stripes, facial details):**
```bash
python image_to_trajectory.py input.jpg output.json --max-dim 400 --prune 5 --eps 1.0
```
- Higher `max-dim` preserves small details
- Lower `prune` keeps short internal features
- Lower `eps` retains more points

**For noisy/blurry photos:**
```bash
python image_to_trajectory.py input.jpg output.json --mode photo --min-contour 100 --prune 20
```
- Higher `min-contour` removes noise
- Higher `prune` cleans up skeleton fragmentation

**For simple, clean sugar paintings:**
```bash
python image_to_trajectory.py input.jpg output.json --max-dim 200 --eps 2.5 --prune 15
```
- Lower `max-dim` for faster processing
- Higher `eps` for fewer points
- Standard pruning

### Generating the GIF

After generating the trajectory JSON, create an animated GIF:

```bash
python trajectory_gif.py output.json
```

This generates `output.gif` showing the drawing process. The GIF uses:
- 150ms per point drawing speed
- 500ms pause between strokes
- 600x600 canvas size

### Complete Workflow Example

```bash
# 1. Convert image to trajectory
python image_to_trajectory.py cute_drawing.png drawing_trace.json --mode lineart --max-dim 400 --prune 5

# 2. Generate animated GIF
python trajectory_gif.py drawing_trace.json

# 3. Send to PLC (draw on HMI)
painter-cli draw drawing_trace.json
```

### Output Files

After running `image_to_trajectory.py`:
- `output.json` - Trajectory data (strokes with points)
- `output.png` - Visual preview (colored strokes on white)
- `output.svg` - Vector version

After running `trajectory_gif.py`:
- `output.gif` - Animated drawing process

With `--debug`:
- `output_debug_binary.png` - Edge detection result
- `output_debug_skeleton.png` - Thinned skeleton

### Sugar Painting Validation

The tool automatically:
1. **Enforces connectivity** - All strokes are connected
2. **Adds bridges** - Connects disconnected components
3. **Validates stick adhesion** - Every stroke touches X=0 (the stick)

Check the output message for:
- `Stick adhesion: OK` - All strokes anchored to stick
- `All N strokes connected` - Drawing is one connected piece

## Configuration

Settings are loaded from environment variables or `.env` file (prefixed `PAINTER_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PAINTER_PLC_HOST` | `10.10.20.244` | PLC IP address |
| `PAINTER_PLC_PORT` | `502` | PLC Modbus port |
| `PAINTER_WRITE_INTERVAL_MS` | `150` | Interval between point writes |
| `PAINTER_MAX_STEP` | `5` | Max distance between consecutive points (0=off) |

## Error Handling

- If the PLC is unreachable, the `draw` command exits with code `1`.
- Invalid JSON input produces a clear error message and exits with code `1`.
- Out-of-range coordinates are silently clamped to `[-240, 240]`.
- Use `painter-cli status` to verify connectivity before sending plans.
