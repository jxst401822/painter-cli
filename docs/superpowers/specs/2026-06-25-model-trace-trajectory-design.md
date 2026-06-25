# Model-Traced Trajectory — Device-Thin Rework

**Date:** 2026-06-25
**Status:** Approved (pending spec review)
**Scope:** Rework the `image-to-trajectory` skill and lightly fix `sugar-painting-gen` for the quantum-bot device (m310, 2× Cortex-A55, BogoMIPS 48) so that the trajectory JSON is produced by an LLM visually tracing the generated sugar-painting PNG, instead of running `image_to_trajectory.py` (numpy/opencv) on the device.

## Background & Motivation

The quantum-bot device is a 2-core Cortex-A55 SoC with BogoMIPS 48 and ~448 KiB total cache — router/NAS class. Running OpenCV + numpy skeletonization (what `image_to_trajectory.py` does on a 600² image) is infeasible there. A prior attempt to bootstrap pip + numpy/Pillow/opencv on the device's stripped system Python 3.12 stalled on missing C extensions (`mmap`), and even if installed, the workload would be far too slow. The correct fix is to move the heavy work to the LLM (vision tracing) and keep the device running only zero-dependency stdlib code.

Two findings made this pivot clean:

1. **`sugar-painting-gen` can run on the device with zero deps.** `PIL`/`numpy` are imported at module top but are used *only* by `postprocess_sugar_style()` (ARK engine + `--postprocess`). The default **dayinla** path uses only `urllib`/`json`/`time`/`os`. `yaml` is already lazily imported. Making the PIL/numpy imports lazy lets the default path run on the device with no pip, no numpy, no opencv.

2. **`image_to_trajectory.py` is the real bottleneck.** Zhang-Suen thinning + DFS path tracing over a skeleton graph + connectivity union-find + nearest-neighbor TSP — all numpy/cv2. It produces a JSON with a strict contract that the LLM must reproduce.

## Goals

- Device stays **zero-dependency**: no pip, no numpy, no PIL, no opencv. Only system Python 3 stdlib.
- Sugar-painting PNG generation works on device (dayinla, HTTP).
- Trajectory JSON is produced by the **LLM visually tracing** the generated PNG.
- The JSON contract that the physical servo machine consumes is **enforced by a pure-stdlib script**, not by trusting the model's raw output.
- A GIF preview of the drawing process is produced by a **desktop HTTP micro-service** reusing the existing `trajectory_gif.py`, callable from the device over `urllib` (same mechanism as dayin.la).
- The same trajectory JSON feeds both the physical servo machine (`servo/json_loader.py`) and the GIF service (`trajectory_gif.py`) — one contract.

## Non-Goals

- Pixel-perfect trajectory fidelity. This is *approximate* vision-tracing, accepted by the user. `image_to_trajectory.py` is retained on the desktop as the high-fidelity reference path, not integrated into the device agent flow.
- MCP integration. The GIF service is plain HTTP, not MCP. MCP requires quantum-bot to be an MCP client (unconfirmed) and is overkill for a single render-gif call.
- A pure-stdlib GIF encoder on the device. A fixed-palette + LZW encoder is feasible in ~200 lines but a 600² × ~80-frame GIF in pure Python on a BogoMIPS-48 core takes minutes per GIF — too slow. Ruled out.
- Bootstrapping pip/deps/venv on the device. Abandoned — no longer needed once the heavy scripts move off-device.

## Architecture

```
Device (no PIL/numpy)                      Desktop (has PIL)
┌─────────────────────────────┐          ┌──────────────────────┐
│ sugar-painting-gen           │          │ GIF HTTP micro-service│
│  dayinla engine (stdlib)    │          │  reuses               │
│  → sugar PNG                │──PNG─────│  trajectory_gif.py     │
│                              │          │  POST /render-gif     │
│ image-to-trajectory (redone)│          │  → image/gif          │
│  LLM vision-traces PNG →    │          └──────────────────────┘
│    normalized [0,1] JSON    │                   ↑
│  trajectory_prepare.py      │                   │ urllib
│   (stdlib: validate + map   │                   │
│    to ±240 + stick-anchor + │──±240 JSON──POST──┘
│    dedup + SVG preview)     │
└──────────────┬───────────────┘
               │ ±240 JSON
               ↓
          painter-cli servo draw → physical machine (Modbus)
```

### Components

**A. `sugar-painting-gen` (small fix)** — Make `PIL`/`numpy` imports lazy: move them from module top into `postprocess_sugar_style()` and the `ark_*` functions where they are actually used. The dayinla default path becomes pure stdlib and runs on the device. `yaml` is already lazy. SKILL.md notes that the ARK engine requires deps and is not available on the device by default (use dayinla).

**B. `image-to-trajectory` (rework — the core)** — `image_to_trajectory.py` is **not run on the device**. The skill becomes an "LLM vision-tracing procedure":

- `SKILL.md` is rewritten to describe the tracing procedure and the JSON contract.
- A new `trajectory_prepare.py` (pure stdlib) is the contract guardian: validates the model's normalized JSON, deterministically maps normalized `[0,1]` coordinates to ±240 integers (+clamp + Y flip), enforces stick adhesion (if no stroke crosses x≈0, prepend `[0, y]` anchor to the nearest stroke, reusing the original script's `STICK_TOL` convention of ≈2–4), dedups consecutive duplicate points, and renders an SVG preview in the final ±240 coordinate space. This is the "contract-execution tail" of the original CV pipeline, reimplemented in pure stdlib.

**C. Desktop GIF HTTP micro-service** — A tiny HTTP wrapper over the existing `trajectory_gif.py` (unchanged): `POST /render-gif` with trajectory JSON body → `image/gif` response. The device calls it via `urllib`, identical mechanism to dayin.la. The endpoint is written into the skill's SKILL.md and made configurable.

## Design Decision: Coordinate Space

The LLM emits **normalized `[0,1]` coordinates** (fraction of image width/height), and `trajectory_prepare.py` deterministically maps them to ±240:

- `x = round(nx * 480 - 240)`, clamped to `[-240, 240]`
- `y = round((1 - ny) * 480 - 240)` (Y flip: image Y-down → machine Y-up), clamped to `[-240, 240]`

Rationale: vision models estimate *relative* position well but absolute integer coordinates poorly. Normalized output raises model accuracy, and the ±240 contract — which the machine depends on — is enforced by the script, not by trusting the model's arithmetic. dayin.la images are 600×600 square, so the normalized mapping is undistorted.

## JSON Contract (the machine's input)

Defined by `servo/json_loader.py` and `drawing/parser.py` in the `json-modbus-servo-painter` worktree — both accept this same shape:

```json
{
  "description": "<string>",
  "strokes": [
    { "points": [[x, y], [x, y], ...] }
  ]
}
```

- `description`: string (optional, defaults to `""`).
- `strokes`: non-empty array.
- Each stroke: object with `points`: non-empty array (consumer requires ≥2 valid points; the script guarantees ≥2 after dedup).
- Each point: `[x, y]` numeric pair, clamped to `[-240, 240]`.
- Y positive = up. X=0 is the bamboo-stick axis.
- Markdown code fences (` ```json ... ``` `) are tolerated and stripped by the consumer.

`trajectory_prepare.py` guarantees the model's output is reshaped into this contract before it reaches the machine or the GIF service.

## Assumptions Requiring Verification Before Implementation

1. **quantum-bot agent has image vision capability.** Vision tracing is the premise of the whole design. If nanobot does not support vision analysis, "trace from PNG" is not viable and the design must fall back to "model natively generates" the trajectory (the rejected option). **Verify the agent's vision support first.**
2. **A desktop machine is available on the LAN** with a stable address the device can reach, running the GIF micro-service. GIF previews require it; if absent, the skill degrades to JSON + SVG preview only.

## Deliverables

- **Device `.import_bundle/`** (for manual web import):
  - `sugar-painting-gen/` — lazy-import zero-dep version.
  - `image-to-trajectory/` — new `SKILL.md` (tracing procedure + contract) + `trajectory_prepare.py`.
- **Desktop:**
  - `trajectory_gif.py` — retained unchanged.
  - `gif_service.py` — new tiny HTTP wrapper (`POST /render-gif`).

## Out of Scope / Deferred

- The physical `painter-cli servo draw` integration and Modbus PLC wiring live in the `json-modbus-servo-painter` worktree and are not changed by this spec; this spec only ensures the JSON it produces is compatible.
- Device cleanup of leftover state from the abandoned pip/bootstrap attempt (partial `/tmp/cpython.tar.gz`, added `colorsys.py`/`tomllib/`) — separate housekeeping task.
- The ARK engine path on device remains inert (needs deps); only dayinla is supported on device.
