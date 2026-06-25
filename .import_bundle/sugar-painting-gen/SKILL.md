---
name: sugar-painting-gen
description: "Generate sugar painting (糖画) patterns from text prompts. Produces amber-on-black line art in the traditional Chinese sugar painting style. Uses dayin.la AI engine (no auth, no deps) with Volcengine ARK fallback (needs deps)."
metadata: {"nanobot":{"emoji":"🎨","requires":{"bins":["python3"]}}}
---

# Sugar Painting Pattern Generation (糖画图案生成)

Generate traditional Chinese sugar painting (糖画/Tanghua) patterns from text prompts.
The output mimics real sugar art: amber/orange continuous lines on a black background,
in a cute cartoon style suitable for sugar painting machines.

## When to Use

- User asks to generate sugar painting patterns (糖画图案)
- User wants to create tanghua/糖画 designs
- User mentions 糖画, 糖画图案, tanghua, or sugar painting art

## How It Works

### Visual Style of Sugar Painting Patterns

Sugar painting patterns have very specific visual characteristics:

1. **Black background** — mimics the dark stone slab used by street vendors
2. **Amber/orange lines** — mimics caramelized sugar syrup
3. **Continuous line style** — as if poured from a ladle in one flowing motion
4. **Slightly varying line thickness** — organic, not perfectly uniform
5. **Minimalist cartoon/kawaii style** — simple, cute, recognizable
6. **Outline-based** — minimal filling, mostly negative space
7. **No complex shading** — just lines and simple shapes

### Generation Engine

> **Device note (quantum-bot m310):** Only the **dayinla** engine runs here
> (pure stdlib, no pip/numpy/PIL). The **ark** engine requires PIL/numpy/yaml
> and `~/.ark-helper/config.yaml`; it is not available on this device. Always
> use `--engine dayinla` (the default).

The script has two engines:

1. **dayin.la API** (primary) — Calls the same AI engine used by ai.dayin.la
   - POST `https://ai.dayin.la/api/ai/image` with `{"msg": "prompt"}`
   - Poll GET `https://ai.dayin.la/api/ai/queue-info?id={task_id}` until status=2
   - Download the generated PNG image
   - No authentication required (open API)

2. **Volcengine ARK** (fallback) — Uses doubao-seedream-5.0-lite
   - Generates an image with a sugar-painting-style prompt
   - Post-processes with PIL: edge detection, color mapping to amber-on-black
   - Requires ark-helper config at ~/.ark-helper/config.yaml (not present by default on this device)

### Prompt Tips

Sugar painting prompts work best with:
- Simple, recognizable subjects (animals, characters, objects)
- Cute/cartoon style descriptions
- Short phrases (under 40 characters for dayin.la)
- Examples: "龙", "蝴蝶", "孙悟空", "戴着墨镜的猫", "骑自行车的兔子"

## Usage

### Command Line

```bash
# Basic usage — generates "龙" (dragon) pattern
python /root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
  --prompt "龙" --output ~/dragon_sugar.png

# Use dayin.la engine (default, produces authentic sugar painting style)
python /root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
  --prompt "戴墨镜的猫" --engine dayinla --output ~/cool_cat.png

# Use Volcengine ARK engine (requires Agent Plan subscription)
python /root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
  --prompt "独角兽" --engine ark --output ~/unicorn_sugar.png

# Use random prompt from dayin.la's vocabulary list
python /root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts/sugar_painting_gen.py \
  --random-prompt --output ~/surprise.png
```

### From execute_code

```python
import sys, os
sys.path.insert(0, os.path.expanduser(
    "/root/update_0508/_quantum-bot/workspace/skills/sugar-painting-gen/scripts"))
from sugar_painting_gen import generate

# Generate with dayin.la engine (default)
image_path = generate(
    prompt="龙",
    output="/root/dragon.png",
    engine="dayinla"
)

# Generate with Volcengine ARK engine
image_path = generate(
    prompt="独角兽",
    output="/root/unicorn.png",
    engine="ark"
)
```

### Batch generation (loop in Python)

The CLI script accepts a single `--prompt`. For batch generation, loop in Python:

```python
from sugar_painting_gen import generate
for p in ["龙", "凤凰", "蝴蝶"]:
    generate(prompt=p, output=f"/root/sugar_{p}.png", engine="dayinla")
    import time; time.sleep(3)  # respect rate limit
```

## Workflow

1. User provides a text prompt (e.g., "龙", "戴墨镜的猫")
2. Call `generate()` with the prompt
3. Script uses the specified engine (dayinla default, ark as alternative)
4. For ARK engine: generates image then post-processes to sugar painting style
5. Save the result PNG to the output path
6. Use `vision_analyze` to verify the result looks like a sugar painting
7. Report the file path to the user

## Pitfalls

See also: `references/dayinla-api.md` for full API endpoint documentation.

- **dayin.la API rate limiting**: The API has a cooldown that doubles with each use
  (2, 4, 8, 16, 32, 64, 128, 256 seconds). For batch generation, add delays.
- **dayin.la no auth**: The API currently works without authentication, but this may
  change. Always have the ARK fallback ready.
- **ARK engine post-processing**: The ARK engine's prompt already instructs the model
  to generate sugar painting style (black bg, amber lines). The `--postprocess` flag
  is OPTIONAL — it applies PIL edge detection + color remapping as a refinement.
  In testing, the ARK model alone (without postprocess) produced good sugar painting
  style because the prompt is detailed. Use `--postprocess` only if the raw output
  doesn't look right.
- **ARK engine requires ark-helper config**: The ARK engine reads its API key from
  `~/.ark-helper/config.yaml` (Volcengine ARK, `volcengine-agent-plan` api_key). This
  config is NOT present on this device by default — use the `dayinla` engine (default),
  which needs no credentials. To enable ARK, create `~/.ark-helper/config.yaml`.
- **ARK image is JPEG**: dayin.la returns PNG (small, ~10KB), ARK returns JPEG
  (large, ~200KB). The script saves with whatever extension you give to --output.
- **Prompt length**: dayin.la limits prompts to 40 characters. Keep it concise.
- **Image format**: Output is always PNG, even though dayin.la returns PNG and ARK
  returns JPEG. The script normalizes to PNG.
- **Black background is essential**: Sugar painting patterns MUST have a black
  background with amber lines. Do not generate with white background.
