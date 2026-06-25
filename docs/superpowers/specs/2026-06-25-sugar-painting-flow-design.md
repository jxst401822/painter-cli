# Sugar Painting Flow — Orchestration Skill Design

**Date:** 2026-06-25
**Status:** Approved (pending spec review)
**Scope:** A new orchestration skill `sugar-painting-flow` that wires the existing `sugar-painting-gen` and `image-to-trajectory` skills (plus the GIF micro-service) into one end-to-end flow from a text prompt to a GIF preview. Pure documentation (a single `SKILL.md`), no new scripts.

## Background & Motivation

Two working skills + a service already exist and were verified end-to-end on the quantum-bot device (m310, BogoMIPS 48, zero-dep):

- `sugar-painting-gen` — generates a sugar-painting PNG from a text prompt via the dayin.la API (pure stdlib, lazy imports, runs on device).
- `image-to-trajectory` — the agent visually traces the PNG into a normalized `[0,1]` JSON; `trajectory_prepare.py` (pure stdlib) validates it, maps to ±240 (Y-flip), enforces stick adhesion, dedups, renders an SVG preview.
- `gif_service` (desktop/cloud HTTP, `192.168.0.113:8765`) — `POST /render-gif` with a trajectory JSON → returns an animated GIF.

These are individual pieces. There is no single entry point that takes a user's text prompt ("画条龙") and runs the whole chain to a shareable GIF preview. The new `sugar-painting-flow` skill is that entry point — a pure-orchestration document an agent follows top to bottom.

## Goals

- One skill that takes a **text prompt** and produces **PNG + SVG + GIF** previews, on the device, zero-dependency.
- The trajectory JSON is produced by **the agent's vision** tracing the generated PNG (not by running CV on the device) — confirmed: the agent has image-vision capability.
- Reuse every existing script/service unchanged. No new `.py`.
- Each step is **self-contained** (copy-paste-runnable commands/snippets), so the agent needs only this one skill to complete the flow.

## Non-Goals

- Physical drawing. The flow stops at the GIF preview. `painter-cli servo draw` is out of scope (left to the separate `image-to-trajectory` / painter-cli skills).
- New scripts. `sugar_painting_gen.py`, `trajectory_prepare.py`, and `gif_service.py` are reused as-is.
- Re-duplicating dayin.la API internals or the full tracing ruleset — the flow references the source skills for depth but restates enough to be runnable standalone.

## Architecture

```
user text prompt ("龙")
        │
        ▼
① sugar-painting-gen  →  /tmp/sugar.png          (dayin.la, pure stdlib, device)
        │
        ▼
② agent vision-traces PNG  →  /tmp/trace_norm.json  (normalized [0,1], image-to-trajectory Step 1)
        │
        ▼
③ trajectory_prepare.py  →  /tmp/trace.json + /tmp/trace.svg   (stdlib: map ±240, stick-anchor, dedup, SVG, device)
        │
        ▼
④ POST → GIF service (192.168.0.113:8765)  →  /tmp/trace.gif    (urllib, device)
        │
        ▼
   report PNG + SVG + GIF paths to the user
```

## Components

**One file:** `.import_bundle/sugar-painting-flow/SKILL.md` (and only that — no `scripts/` dir).

It depends on, and points at:
- `.import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py`
- `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`
- `gif_service` at `http://192.168.0.113:8765` (host is a single constant, swappable for a cloud URL later).

## SKILL.md Structure

- **Frontmatter** — nanobot convention: `name: sugar-painting-flow`, `description` (text prompt → sugar-painting PNG → trajectory JSON → GIF preview, all on-device zero-dep), `metadata: {"nanobot":{"emoji":"🍭","requires":{"bins":["python3"]}}}`.
- **When to Use** — user gives a text prompt and wants a sugar painting; "画条龙看看"; wants the full chain from words to a shareable animated preview.
- **Prerequisites** — System Python 3 (`/usr/bin/python3`), zero-dep. Lists the two script paths (`SUGAR_SCRIPTS`, `TRAJ_SCRIPTS`) and the GIF service URL constant.
- **Pipeline** — the diagram above.
- **Step 1: Generate the PNG** — exact `python3 $SUGAR_SCRIPTS/sugar_painting_gen.py --prompt "龙" --output /tmp/sugar.png` command (dayinla default). Note dayin.la rate-limiting + that ARK needs deps (unavailable on device).
- **Step 2: Vision-trace the PNG → normalized JSON** — restated essentials of the tracing rule (emit `{description, strokes:[{points:[[nx,ny]...]}]}` with `nx,ny ∈ [0,1]`, ≥2 points/stroke, continuous lines broken at junctions, 5–25 strokes, start near the stick axis), saved to `/tmp/trace_norm.json`. References `image-to-trajectory` for the full rule.
- **Step 3: Prepare trajectory (±240 + SVG)** — `python3 $TRAJ_SCRIPTS/trajectory_prepare.py /tmp/trace_norm.json /tmp/trace.json --svg /tmp/trace.svg`. Note it enforces the ±240 contract + stick adhesion.
- **Step 4: Animated GIF** — the verified urllib POST snippet to `192.168.0.113:8765/render-gif`, writing `/tmp/trace.gif`, with `URLError` graceful-skip.
- **Delivering to the user** — report the three artifact paths (PNG/SVG/GIF). WeChat note: GIFs must be sent as a separate media message (`send_message` with `message: "MEDIA:/tmp/trace.gif"`, target weixin), since inline markdown `![](...)` does not animate in WeChat.
- **Error handling** — dayin.la down → no PNG, stop and tell user; trajectory JSON invalid → `trajectory_prepare.py` raises `TrajectoryError`, re-trace; GIF service unreachable → skip Step 4, still deliver PNG + SVG.
- **End-to-end example** — "龙": the four commands/outputs from prompt to the three artifact paths.

## Design Decision: Self-Contained vs Pure Cross-Reference

The orchestration skill's value is being a single runnable document. Each step gives copy-paste-runnable commands/snippets. The verbose tracing rule (Step 2) is restated in essentials **and** points at `image-to-trajectory` for the full version — enough to run, not a wall of duplication.

## Deliverables

- `.import_bundle/sugar-painting-flow/SKILL.md` (new, for web import).

## Out of Scope

- Physical drawing (`painter-cli servo draw`).
- New scripts or changes to `sugar_painting_gen.py` / `trajectory_prepare.py` / `gif_service.py`.
- The leftover working-tree housekeeping (deletion of `image_to_trajectory_v2.py`, untracked `skills/` files) — predates this work.
