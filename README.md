# painter-cli

CLI tool that draws coordinate plans on a Schneider HMI screen via Modbus TCP.

Designed to be called by external agents (openclaw, Claude, etc.) — you generate the coordinate plan, this tool executes it on the hardware.

## How It Works

```
Agent generates coordinate plan (JSON)
  ↓
painter-cli draw '{ "strokes": [...] }'
  ↓
Modbus TCP → PLC (10.10.20.244) → HMI pulls registers → physical pen draws
```

### Register Map

| Register | Address | Purpose | Range |
|----------|---------|---------|-------|
| `%MW0` | 0 | Pen control | `0` = up, `1` = down |
| `%MW1` | 1 | X-axis | `-240` to `240` |
| `%MW2` | 2 | Y-axis | `-240` to `240` |

### Coordinate System

4-quadrant Cartesian, origin `(0,0)`, range `[-240, 240]` on both axes. Values are written directly as signed integers.

## Setup

```bash
pip install -e .           # install
pip install -e ".[dev]"    # with dev deps
cp .env.example .env       # configure PLC address
```

## Usage

```bash
# Draw from JSON string
painter-cli draw '{"description":"circle","strokes":[{"points":[[120,0],[117,19],...]}]}'

# Draw from file
painter-cli draw plan.json

# Draw from stdin
cat plan.json | painter-cli draw

# Dry run (validate only)
painter-cli draw --dry-run plan.json

# Other commands
painter-cli status     # Test PLC connectivity
painter-cli center     # Pen up, move to (0,0)
painter-cli config     # Show settings
```

### JSON Plan Format

```json
{
  "description": "What you're drawing",
  "strokes": [
    {
      "points": [[x1, y1], [x2, y2], ...]
    }
  ]
}
```

See [SKILL.md](SKILL.md) for the full schema, rules, and examples.

## Project Structure

```
painter-cli/
├── SKILL.md                      # Agent integration guide
├── pyproject.toml
├── .env.example
├── painter_cli/
│   ├── cli.py                    # Click CLI (draw, status, center, config)
│   ├── config.py                 # Settings via pydantic-settings
│   ├── drawing/
│   │   ├── models.py             # Point, Stroke, StrokePlan
│   │   ├── parser.py             # JSON → StrokePlan parser
│   │   └── executor.py           # StrokePlan → Modbus writes
│   ├── modbus/
│   │   ├── client.py             # ModbusTcpClient wrapper
│   │   └── encoder.py            # [-240,240] → [0,480] encoding
│   └── ui/
│       └── console.py            # Rich console helpers
└── tests/
    ├── test_encoder.py
    ├── test_parser.py
    └── test_executor.py
```

## Development

```bash
pytest tests/ -v
ruff check painter_cli/ tests/
```

## License

MIT
