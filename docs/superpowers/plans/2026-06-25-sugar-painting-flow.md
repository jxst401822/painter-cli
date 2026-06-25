# Sugar Painting Flow — Orchestration Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one new orchestration skill `sugar-painting-flow` (a single `SKILL.md`, no scripts) that wires `sugar-painting-gen` + `image-to-trajectory` + the GIF micro-service into one text-prompt → GIF-preview flow on the device.

**Architecture:** Pure documentation. The new SKILL.md is four copy-paste-runnable steps: (1) run `sugar_painting_gen.py` for the PNG, (2) the agent vision-traces the PNG into a normalized JSON, (3) run `trajectory_prepare.py` for the ±240 JSON + SVG, (4) urllib-POST to the GIF service for the GIF. Every underlying script/service is reused unchanged.

**Tech Stack:** Python 3.12+ (device) / 3.14 (desktop), stdlib only on device (`urllib`/`json`), nanobot skill frontmatter.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-06-25-sugar-painting-flow-design.md`:

- **One file only:** `.import_bundle/sugar-painting-flow/SKILL.md`. No `scripts/` dir, no new `.py`.
- **Zero-dependency on device:** no pip/numpy/PIL/opencv. All commands run on system Python 3 (`/usr/bin/python3`).
- **Device path convention:** `/root/update_0508/_quantum-bot/workspace/skills/<name>/scripts`. No `/home/se/`, no `~/.hermes/`.
- **Frontmatter:** nanobot convention `metadata: {"nanobot":{"emoji":"🍭","requires":{"bins":["python3"]}}}`. No Hermes fields.
- **GIF service:** `http://192.168.0.113:8765/render-gif` via `urllib` (device has no `curl`). Host is a single constant, swappable for cloud later.
- **Flow stops at GIF preview** — no `painter-cli servo draw` / physical machine in this skill.
- **Self-contained but not duplicated:** each step gives runnable commands; the verbose tracing rule is restated in essentials + points at `image-to-trajectory` for the full version.

---

## File Structure

**Single new file:**
- `.import_bundle/sugar-painting-flow/SKILL.md` — the orchestration document (frontmatter + 4 steps + delivering + error handling + end-to-end example).

**Reused, unchanged (referenced by path, not modified):**
- `.import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py`
- `.import_bundle/image-to-trajectory/scripts/trajectory_prepare.py`
- `gif_service` at `http://192.168.0.113:8765`

**No tests directory** — this is a documentation deliverable. Verification is structural (frontmatter, paths, no residual local/Hermes refs, internal consistency) + a runnable end-to-end check, not a pytest suite.

---

### Task 1: Create `sugar-painting-flow/SKILL.md`

**Files:**
- Create: `.import_bundle/sugar-painting-flow/SKILL.md`

**Interfaces:**
- Consumes: `sugar_painting_gen.py --prompt <p> --output <png>` (sugar-painting-gen); the agent's vision (image-to-trajectory Step 1 tracing rule); `trajectory_prepare.py <norm.json> <out.json> --svg <svg>` (image-to-trajectory); `POST http://192.168.0.113:8765/render-gif` (gif_service).
- Produces: an importable skill that, given a text prompt, yields `/tmp/sugar.png`, `/tmp/trace_norm.json`, `/tmp/trace.json`, `/tmp/trace.svg`, `/tmp/trace.gif`.

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p .import_bundle/sugar-painting-flow
```

- [ ] **Step 2: Write the SKILL.md**

Create `.import_bundle/sugar-painting-flow/SKILL.md` with exactly this content:

```markdown
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
  "description": "龙 (3 strokes)",
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
```

- [ ] **Step 3: Verify frontmatter + paths**

Run:

```bash
head -6 .import_bundle/sugar-painting-flow/SKILL.md
grep -c "/root/update_0508/_quantum-bot/workspace/skills" .import_bundle/sugar-painting-flow/SKILL.md
grep -nE "/home/se|\.hermes|venv/bin|category: creative|version: 1|Hermes Agent" .import_bundle/sugar-painting-flow/SKILL.md || echo "no residual local/hermes paths: OK"
```

Expected: frontmatter shows `name`, `description`, `metadata: {"nanobot":...}`; path count ≥ 2 (both SUGAR_SCRIPTS and TRAJ_SCRIPTS, plus the end-to-end example); "no residual local/hermes paths: OK".

- [ ] **Step 4: Verify internal consistency (JSON shape across steps)**

The normalized JSON shape in Step 2 must match what `trajectory_prepare.py` consumes. Confirm the field names line up:

```bash
echo "--- Step 2 JSON shape (in new SKILL.md) ---"
grep -A4 '"description": "龙' .import_bundle/sugar-painting-flow/SKILL.md | head -5
echo "--- trajectory_prepare.py expected shape (description + strokes[].points) ---"
grep -nE 'data.get\("description|raw_strokes|\.get\("points"|map_point' .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py | head
```

Expected: Step 2 emits `{"description": ..., "strokes": [{"points": [[nx,ny]...]}]}`; `trajectory_prepare.py` reads `data.get("description")`, `data.get("strokes")`, per-stroke `.get("points")` and calls `map_point(nx,ny)`. The shapes match.

- [ ] **Step 5: Verify the four commands are runnable (dry structure check)**

Confirm each step's command references an existing script (don't execute on device here — just confirm the referenced files exist in the bundle):

```bash
test -f .import_bundle/sugar-painting-gen/scripts/sugar_painting_gen.py && echo "sugar_painting_gen.py: present"
test -f .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py && echo "trajectory_prepare.py: present"
grep -q "192.168.0.113:8765" .import_bundle/sugar-painting-flow/SKILL.md && echo "GIF service URL: present"
grep -q "render-gif" .import_bundle/sugar-painting-flow/SKILL.md && echo "GIF endpoint: present"
```

Expected: all four lines print present/present/present/present.

- [ ] **Step 6: Commit**

```bash
git add .import_bundle/sugar-painting-flow/SKILL.md
git commit -m "feat(sugar-painting-flow): orchestration skill (prompt→PNG→trajectory→SVG→GIF)"
```

---

### Task 2: End-to-end runnable verification (desktop, no device)

**Files:**
- None created; verifies the chain the new skill documents actually holds.

**Interfaces:**
- Consumes: the new SKILL.md's Step 1 + Step 3 + Step 4 commands; the local `gif_service` + `trajectory_prepare.py`.

- [ ] **Step 1: Confirm the GIF service is reachable**

```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://192.168.0.113:8765/healthz', timeout=5).read().decode())"
```
Expected: `ok`. If this fails, the GIF service is not running — start it (`python gif_service.py --port 8765` in a separate terminal) before continuing, or mark Step 4 of the flow as unverified (the SKILL.md itself is still correct; only the live check is skipped).

- [ ] **Step 2: Run the chain locally (Step 1 + Step 3 + Step 4), skipping Step 2's vision**

Step 2 (agent vision-trace) can't be automated, so use a pre-made normalized JSON to exercise Steps 1/3/4:

```bash
cat > /tmp/spf_norm.json <<'EOF'
{"description":"flow-check (2 strokes)","strokes":[
  {"points":[[0.1,0.5],[0.4,0.2],[0.6,0.2],[0.9,0.5]]},
  {"points":[[0.2,0.7],[0.5,0.9],[0.8,0.7]]}
]}
EOF
python .import_bundle/image-to-trajectory/scripts/trajectory_prepare.py /tmp/spf_norm.json /tmp/spf_trace.json --svg /tmp/spf_trace.svg
PLAN="$(cygpath -w /tmp/spf_trace.json 2>/dev/null || echo /tmp/spf_trace.json)"
python -c "
import urllib.request
plan = open(r'$PLAN','rb').read()
req = urllib.request.Request('http://192.168.0.113:8765/render-gif', data=plan, headers={'Content-Type':'application/json'}, method='POST')
with urllib.request.urlopen(req, timeout=120) as r:
    gif = r.read()
open('/tmp/spf_trace.gif','wb').write(gif)
print('GIF bytes:', len(gif), 'magic:', gif[:6])
"
```

Expected: `trajectory_prepare.py` prints `Written` + `SVG`; the python snippet prints `GIF bytes: <N> magic: b'GIF89a'` and `/tmp/spf_trace.gif` exists. This proves the Step 3→Step 4 commands in the new SKILL.md are runnable and produce a real GIF.

- [ ] **Step 3: Verify the new skill is in the clean import bundle**

```bash
echo "--- bundle tree ---"
find .import_bundle -type f -name "*.md" -o -type f -name "*.py" | sort
echo "--- no stray scripts in sugar-painting-flow (should be SKILL.md only) ---"
find .import_bundle/sugar-painting-flow -type f | sort
```

Expected: `sugar-painting-flow/` contains **only** `SKILL.md` (no `scripts/` dir, no `.py`). The full bundle lists the two existing skills + the new one.

- [ ] **Step 4: Commit verification artifacts (if any changes)**

No code changes expected in this task (verification only):

```bash
git add -A && git commit -m "chore: verify sugar-painting-flow e2e chain" 2>&1 | tail -2 || echo "nothing to commit (clean)"
```

---

## Self-Review Notes

**Spec coverage:**
- Orchestration skill, one SKILL.md, no new scripts → Task 1. ✓
- Four-step chain (PNG → normalized JSON → ±240+SVG → GIF) → Task 1 Step 1–4 sections. ✓
- Agent vision produces trajectory JSON (not CV on device) → Task 1 Step 2 + non-goals. ✓
- Stops at GIF preview (no physical draw) → Task 1 frontmatter + non-goals + flow stops at GIF. ✓
- Zero-dep device, no curl, urllib GIF → Task 1 Step 4 + prerequisites. ✓
- Self-contained runnable steps + restated tracing rule + pointer to image-to-trajectory → Task 1 Step 2. ✓
- Delivering PNG+SVG+GIF, WeChat GIF-as-media-message → Task 1 Delivering section. ✓
- Error handling (dayin.la down / bad JSON / GIF unreachable) → Task 1 Error handling section. ✓
- End-to-end example → Task 1 End-to-end example section. ✓
- nanobot frontmatter + device paths, no Hermes/local residue → Task 1 Step 3. ✓
- Configurable GIF endpoint (single constant) → Task 1 Step 4 `GIF_SERVICE`. ✓

**Placeholder scan:** None — every command/snippet is complete; verification steps have exact commands + expected output.

**Type consistency:** JSON shape `{"description", "strokes":[{"points":[[nx,ny]...]}]}` is identical in Step 2 (new skill) and what `trajectory_prepare.py.parse_and_map` reads (verified in Task 1 Step 4). GIF endpoint `http://192.168.0.113:8765/render-gif` matches `gif_service.py`'s `do_POST` route. Device paths match the sister skills' `/root/update_0508/_quantum-bot/workspace/skills/<name>/scripts` convention. ✓
