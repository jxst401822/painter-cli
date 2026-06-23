# JSON Modbus Servo Painter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-version CLI path that reads stroke JSON, maps XY coordinates, generates pen-up/pen-down/XY motion actions, and sends them one at a time to the PLC via the new Modbus command handshake.

**Architecture:** Add a new `painter_cli.servo` package alongside the existing `drawing` and `modbus` packages so the current HMI register writer remains intact. The servo path uses strict JSON validation, explicit coordinate mapping, an action program builder, a command-oriented PLC client, and a blocking runner that waits for accepted/done status before sending the next action.

**Tech Stack:** Python 3.11+, click, pymodbus, pytest, existing `painter-cli` package layout.

## Global Constraints

- Keep the existing `painter_cli.drawing` and legacy `painter_cli.modbus.client.ModbusClient.write_position()` behavior working.
- Add the new PLC command protocol under `painter_cli.servo` instead of replacing the legacy HMI drawing protocol.
- Use Holding Register addresses from the design: command at 40001, sequence_id at 40002, control_word at 40003, status_word at 40004, active_command at 40005, done_sequence_id at 40006, error_code at 40007, heartbeat at 40008, target/motion REAL values at 40021 onward.
- Treat Modbus library addresses as zero-based: Modbus 40001 maps to address 0.
- REAL values use two 16-bit registers; first implementation uses big-endian byte order and big-endian word order, with the encoder isolated so it can be swapped after PLC verification.
- First version uses point-to-point blocking execution only.
- First version uses Z-axis pen control only: `PEN_UP` moves Z to `pen_up_z`; `PEN_DOWN` moves Z to `pen_down_z`.
- First version does not implement PLC-side point queues, trajectory blending, path optimization, service/API mode, or natural-language execution directly against PLC.
- The project at `C:\Users\se\projects\painter-cli` is not currently a git repository, so commit steps are omitted until the user initializes git.

---

## File Structure

Create these files:

- `painter_cli/servo/__init__.py` — exports the new servo package API.
- `painter_cli/servo/models.py` — command enums, points, bounds, motion config, actions, status bits.
- `painter_cli/servo/json_loader.py` — strict JSON stroke parser for servo workflow.
- `painter_cli/servo/mapper.py` — JSON coordinate to machine coordinate mapping and bounds validation.
- `painter_cli/servo/program.py` — stroke plan to action sequence conversion.
- `painter_cli/servo/registers.py` — register map, status bit helpers, REAL encoder.
- `painter_cli/servo/plc_client.py` — command-oriented Modbus TCP client.
- `painter_cli/servo/runner.py` — blocking action runner with accepted/done polling.
- `tests/test_servo_json_loader.py` — strict JSON parser tests.
- `tests/test_servo_mapper.py` — coordinate mapping and bounds tests.
- `tests/test_servo_program.py` — action sequence tests.
- `tests/test_servo_registers.py` — register/REAL/status tests.
- `tests/test_servo_runner.py` — runner handshake tests with fake PLC client.

Modify these files:

- `painter_cli/cli.py` — add `servo-draw`, `servo-ping`, and `servo-command` commands.
- `painter_cli/config.py` — add servo defaults for bounds, mapping, motion, and command timeouts.
- `.env.example` — document new `PAINTER_SERVO_*` variables if the file exists.

---

### Task 1: Servo Domain Models

**Files:**
- Create: `painter_cli/servo/__init__.py`
- Create: `painter_cli/servo/models.py`
- Test: `tests/test_servo_models.py`

**Interfaces:**
- Produces: `ServoCommand`, `JsonPoint`, `MachinePoint`, `Stroke`, `StrokePlan`, `MachineBounds`, `MappingConfig`, `MotionConfig`, `ServoAction`, `ServoStatus`, `ServoProtocolError`.
- Consumes: No new project-local interfaces.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_models.py`:

```python
from painter_cli.servo.models import (
    MachineBounds,
    MachinePoint,
    MotionConfig,
    ServoAction,
    ServoCommand,
    ServoStatus,
)


def test_servo_command_codes_match_protocol():
    assert ServoCommand.NOP.value == 0
    assert ServoCommand.POWER_ON.value == 1
    assert ServoCommand.RESET.value == 2
    assert ServoCommand.STOP.value == 3
    assert ServoCommand.PEN_UP.value == 10
    assert ServoCommand.PEN_DOWN.value == 11
    assert ServoCommand.MOVE_XY.value == 20
    assert ServoCommand.MOVE_XYZ.value == 21
    assert ServoCommand.READ_STATUS.value == 90


def test_machine_bounds_accepts_inside_point():
    bounds = MachineBounds(min_x=0, max_x=100, min_y=-50, max_y=50, min_z=0, max_z=20)
    bounds.validate_point(MachinePoint(x=50, y=0, z=10))


def test_machine_bounds_rejects_outside_point():
    bounds = MachineBounds(min_x=0, max_x=100, min_y=-50, max_y=50, min_z=0, max_z=20)
    try:
        bounds.validate_point(MachinePoint(x=101, y=0, z=10))
    except ValueError as exc:
        assert "x=101" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_motion_config_validates_positive_values():
    config = MotionConfig(velocity=50, acceleration=100, deceleration=100)
    assert config.velocity == 50


def test_motion_config_rejects_non_positive_values():
    try:
        MotionConfig(velocity=0, acceleration=100, deceleration=100)
    except ValueError as exc:
        assert "velocity" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_servo_status_bit_helpers():
    status = ServoStatus.from_word((1 << 0) | (1 << 3) | (1 << 8))
    assert status.ready is True
    assert status.busy is True
    assert status.accepted is True
    assert status.error is False


def test_servo_action_factory_methods():
    up = ServoAction.pen_up(z=20, velocity=40, acceleration=100, deceleration=100)
    assert up.command is ServoCommand.PEN_UP
    assert up.target.z == 20

    move = ServoAction.move_xy(x=10, y=20, z=20, velocity=40, acceleration=100, deceleration=100)
    assert move.command is ServoCommand.MOVE_XY
    assert move.target.x == 10
    assert move.target.y == 20
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'painter_cli.servo'`.

- [ ] **Step 3: Add the servo package and models**

Create `painter_cli/servo/__init__.py`:

```python
"""Servo command protocol for PLC-controlled painter motion."""
```

Create `painter_cli/servo/models.py`:

```python
"""Domain models for command-based servo painting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ServoProtocolError(Exception):
    """Raised when the PLC command protocol reports an error."""


class ServoCommand(IntEnum):
    NOP = 0
    POWER_ON = 1
    RESET = 2
    STOP = 3
    PEN_UP = 10
    PEN_DOWN = 11
    MOVE_XY = 20
    MOVE_XYZ = 21
    READ_STATUS = 90


@dataclass(frozen=True)
class JsonPoint:
    x: float
    y: float


@dataclass(frozen=True)
class MachinePoint:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Stroke:
    points: tuple[JsonPoint, ...]

    @property
    def start(self) -> JsonPoint:
        return self.points[0]

    @property
    def end(self) -> JsonPoint:
        return self.points[-1]

    def __len__(self) -> int:
        return len(self.points)


@dataclass(frozen=True)
class StrokePlan:
    strokes: tuple[Stroke, ...]
    description: str

    @property
    def total_points(self) -> int:
        return sum(len(stroke) for stroke in self.strokes)

    def __len__(self) -> int:
        return len(self.strokes)


@dataclass(frozen=True)
class MachineBounds:
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    def validate_point(self, point: MachinePoint) -> None:
        if not self.min_x <= point.x <= self.max_x:
            raise ValueError(f"x={point.x:g} outside [{self.min_x:g}, {self.max_x:g}]")
        if not self.min_y <= point.y <= self.max_y:
            raise ValueError(f"y={point.y:g} outside [{self.min_y:g}, {self.max_y:g}]")
        if not self.min_z <= point.z <= self.max_z:
            raise ValueError(f"z={point.z:g} outside [{self.min_z:g}, {self.max_z:g}]")


@dataclass(frozen=True)
class MappingConfig:
    scale_x: float
    scale_y: float
    offset_x: float
    offset_y: float
    pen_up_z: float
    pen_down_z: float
    bounds: MachineBounds

    def validate(self) -> None:
        if self.pen_up_z <= self.pen_down_z:
            raise ValueError("pen_up_z must be greater than pen_down_z")
        self.bounds.validate_point(MachinePoint(0, 0, self.pen_up_z))
        self.bounds.validate_point(MachinePoint(0, 0, self.pen_down_z))


@dataclass(frozen=True)
class MotionConfig:
    velocity: float
    acceleration: float
    deceleration: float

    def __post_init__(self) -> None:
        if self.velocity <= 0:
            raise ValueError("velocity must be positive")
        if self.acceleration <= 0:
            raise ValueError("acceleration must be positive")
        if self.deceleration <= 0:
            raise ValueError("deceleration must be positive")


@dataclass(frozen=True)
class ServoAction:
    command: ServoCommand
    target: MachinePoint
    velocity: float
    acceleration: float
    deceleration: float

    @classmethod
    def pen_up(cls, z: float, velocity: float, acceleration: float, deceleration: float) -> ServoAction:
        return cls(ServoCommand.PEN_UP, MachinePoint(0, 0, z), velocity, acceleration, deceleration)

    @classmethod
    def pen_down(cls, z: float, velocity: float, acceleration: float, deceleration: float) -> ServoAction:
        return cls(ServoCommand.PEN_DOWN, MachinePoint(0, 0, z), velocity, acceleration, deceleration)

    @classmethod
    def move_xy(
        cls,
        x: float,
        y: float,
        z: float,
        velocity: float,
        acceleration: float,
        deceleration: float,
    ) -> ServoAction:
        return cls(ServoCommand.MOVE_XY, MachinePoint(x, y, z), velocity, acceleration, deceleration)

    @classmethod
    def simple(cls, command: ServoCommand) -> ServoAction:
        return cls(command, MachinePoint(0, 0, 0), 1, 1, 1)


@dataclass(frozen=True)
class ServoStatus:
    word: int
    ready: bool
    power_on: bool
    group_enabled: bool
    busy: bool
    done: bool
    error: bool
    stopped: bool
    heartbeat_ok: bool
    accepted: bool
    rejected: bool

    @classmethod
    def from_word(cls, word: int) -> ServoStatus:
        return cls(
            word=word,
            ready=bool(word & (1 << 0)),
            power_on=bool(word & (1 << 1)),
            group_enabled=bool(word & (1 << 2)),
            busy=bool(word & (1 << 3)),
            done=bool(word & (1 << 4)),
            error=bool(word & (1 << 5)),
            stopped=bool(word & (1 << 6)),
            heartbeat_ok=bool(word & (1 << 7)),
            accepted=bool(word & (1 << 8)),
            rejected=bool(word & (1 << 9)),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_models.py -v
```

Expected: PASS.

---

### Task 2: Strict Servo JSON Loader

**Files:**
- Create: `painter_cli/servo/json_loader.py`
- Test: `tests/test_servo_json_loader.py`

**Interfaces:**
- Consumes: `JsonPoint`, `Stroke`, `StrokePlan` from `painter_cli.servo.models`.
- Produces: `parse_servo_plan(raw: str) -> StrokePlan` and `ServoJsonError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_json_loader.py`:

```python
import json

import pytest

from painter_cli.servo.json_loader import ServoJsonError, parse_servo_plan
from painter_cli.servo.models import JsonPoint


def test_parse_valid_plan():
    raw = json.dumps(
        {
            "description": "rabbit",
            "strokes": [
                {"points": [[-1, 2], [3.5, 4.25]]},
                {"points": [[5, 6], [7, 8]]},
            ],
        }
    )

    plan = parse_servo_plan(raw)

    assert plan.description == "rabbit"
    assert len(plan.strokes) == 2
    assert plan.total_points == 4
    assert plan.strokes[0].points[1] == JsonPoint(3.5, 4.25)


def test_rejects_missing_strokes():
    with pytest.raises(ServoJsonError, match="strokes"):
        parse_servo_plan('{"description": "bad"}')


def test_rejects_empty_stroke():
    raw = json.dumps({"strokes": [{"points": []}]})
    with pytest.raises(ServoJsonError, match="stroke 0"):
        parse_servo_plan(raw)


def test_rejects_bad_point_shape():
    raw = json.dumps({"strokes": [{"points": [[1, 2], [3, 4, 5]]}]})
    with pytest.raises(ServoJsonError, match="stroke 0 point 1"):
        parse_servo_plan(raw)


def test_rejects_non_numeric_point():
    raw = json.dumps({"strokes": [{"points": [[1, 2], ["x", 4]]}]})
    with pytest.raises(ServoJsonError, match="stroke 0 point 1"):
        parse_servo_plan(raw)


def test_strips_markdown_json_fence():
    raw = """```json
{"description":"ok","strokes":[{"points":[[0,0],[1,1]]}]}
```"""
    plan = parse_servo_plan(raw)
    assert plan.description == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_json_loader.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `painter_cli.servo.json_loader`.

- [ ] **Step 3: Implement the strict JSON loader**

Create `painter_cli/servo/json_loader.py`:

```python
"""Strict JSON loader for servo painting stroke files."""

from __future__ import annotations

import json
import re
from typing import Any

from painter_cli.servo.models import JsonPoint, Stroke, StrokePlan


class ServoJsonError(Exception):
    """Raised when a servo stroke JSON file is invalid."""


def parse_servo_plan(raw: str) -> StrokePlan:
    cleaned = _strip_code_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ServoJsonError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ServoJsonError(f"expected JSON object, got {type(data).__name__}")

    description = data.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    raw_strokes = data.get("strokes")
    if not isinstance(raw_strokes, list) or not raw_strokes:
        raise ServoJsonError("missing or empty strokes array")

    strokes = tuple(_parse_stroke(raw_stroke, stroke_idx) for stroke_idx, raw_stroke in enumerate(raw_strokes))
    return StrokePlan(strokes=strokes, description=description)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)\n?\s*```$", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def _parse_stroke(raw_stroke: Any, stroke_idx: int) -> Stroke:
    if not isinstance(raw_stroke, dict):
        raise ServoJsonError(f"stroke {stroke_idx} must be an object")

    raw_points = raw_stroke.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise ServoJsonError(f"stroke {stroke_idx} must contain a non-empty points array")

    points = tuple(_parse_point(raw_point, stroke_idx, point_idx) for point_idx, raw_point in enumerate(raw_points))
    return Stroke(points=points)


def _parse_point(raw_point: Any, stroke_idx: int, point_idx: int) -> JsonPoint:
    if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
        raise ServoJsonError(f"stroke {stroke_idx} point {point_idx} must be [x, y]")

    try:
        x = float(raw_point[0])
        y = float(raw_point[1])
    except (TypeError, ValueError) as exc:
        raise ServoJsonError(f"stroke {stroke_idx} point {point_idx} must contain numeric x/y") from exc

    return JsonPoint(x=x, y=y)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_json_loader.py -v
```

Expected: PASS.

---

### Task 3: Coordinate Mapper and Bounds Validation

**Files:**
- Create: `painter_cli/servo/mapper.py`
- Test: `tests/test_servo_mapper.py`

**Interfaces:**
- Consumes: `StrokePlan`, `MappingConfig`, `MachinePoint` from `painter_cli.servo.models`.
- Produces: `MappedStroke`, `MappedPlan`, `map_plan(plan: StrokePlan, config: MappingConfig) -> MappedPlan`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_mapper.py`:

```python
import pytest

from painter_cli.servo.mapper import map_plan
from painter_cli.servo.models import JsonPoint, MachineBounds, MappingConfig, Stroke, StrokePlan


def config() -> MappingConfig:
    return MappingConfig(
        scale_x=0.5,
        scale_y=-0.5,
        offset_x=300,
        offset_y=200,
        pen_up_z=20,
        pen_down_z=0,
        bounds=MachineBounds(min_x=0, max_x=600, min_y=0, max_y=400, min_z=0, max_z=50),
    )


def test_map_plan_applies_scale_and_offset():
    plan = StrokePlan(strokes=(Stroke(points=(JsonPoint(-100, -50), JsonPoint(100, 50))),), description="line")

    mapped = map_plan(plan, config())

    assert mapped.description == "line"
    assert mapped.strokes[0].points[0].x == 250
    assert mapped.strokes[0].points[0].y == 225
    assert mapped.strokes[0].points[0].z == 20
    assert mapped.strokes[0].points[1].x == 350
    assert mapped.strokes[0].points[1].y == 175


def test_rejects_mapped_point_outside_bounds():
    plan = StrokePlan(strokes=(Stroke(points=(JsonPoint(1000, 0),)),), description="bad")

    with pytest.raises(ValueError, match="stroke 0 point 0"):
        map_plan(plan, config())


def test_rejects_pen_up_not_above_pen_down():
    bad_config = MappingConfig(
        scale_x=1,
        scale_y=1,
        offset_x=0,
        offset_y=0,
        pen_up_z=0,
        pen_down_z=0,
        bounds=MachineBounds(min_x=-10, max_x=10, min_y=-10, max_y=10, min_z=0, max_z=50),
    )
    plan = StrokePlan(strokes=(Stroke(points=(JsonPoint(0, 0),)),), description="bad")

    with pytest.raises(ValueError, match="pen_up_z"):
        map_plan(plan, bad_config)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_mapper.py -v
```

Expected: FAIL with missing `painter_cli.servo.mapper`.

- [ ] **Step 3: Implement the mapper**

Create `painter_cli/servo/mapper.py`:

```python
"""Coordinate mapping from JSON drawing space to machine space."""

from __future__ import annotations

from dataclasses import dataclass

from painter_cli.servo.models import MachinePoint, MappingConfig, StrokePlan


@dataclass(frozen=True)
class MappedStroke:
    points: tuple[MachinePoint, ...]

    @property
    def start(self) -> MachinePoint:
        return self.points[0]

    @property
    def end(self) -> MachinePoint:
        return self.points[-1]

    def __len__(self) -> int:
        return len(self.points)


@dataclass(frozen=True)
class MappedPlan:
    strokes: tuple[MappedStroke, ...]
    description: str

    @property
    def total_points(self) -> int:
        return sum(len(stroke) for stroke in self.strokes)

    def __len__(self) -> int:
        return len(self.strokes)


def map_plan(plan: StrokePlan, config: MappingConfig) -> MappedPlan:
    config.validate()
    mapped_strokes: list[MappedStroke] = []

    for stroke_idx, stroke in enumerate(plan.strokes):
        mapped_points: list[MachinePoint] = []
        for point_idx, point in enumerate(stroke.points):
            mapped = MachinePoint(
                x=point.x * config.scale_x + config.offset_x,
                y=point.y * config.scale_y + config.offset_y,
                z=config.pen_up_z,
            )
            try:
                config.bounds.validate_point(mapped)
            except ValueError as exc:
                raise ValueError(f"stroke {stroke_idx} point {point_idx}: {exc}") from exc
            mapped_points.append(mapped)
        mapped_strokes.append(MappedStroke(points=tuple(mapped_points)))

    return MappedPlan(strokes=tuple(mapped_strokes), description=plan.description)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_mapper.py -v
```

Expected: PASS.

---

### Task 4: Motion Program Builder

**Files:**
- Create: `painter_cli/servo/program.py`
- Test: `tests/test_servo_program.py`

**Interfaces:**
- Consumes: `MappedPlan` from `painter_cli.servo.mapper`, `MappingConfig`, `MotionConfig`, `ServoAction`, `ServoCommand` from `painter_cli.servo.models`.
- Produces: `build_actions(mapped_plan: MappedPlan, mapping: MappingConfig, motion: MotionConfig, include_power_on: bool = True, include_reset: bool = True) -> list[ServoAction]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_program.py`:

```python
from painter_cli.servo.mapper import MappedPlan, MappedStroke
from painter_cli.servo.models import (
    MachineBounds,
    MachinePoint,
    MappingConfig,
    MotionConfig,
    ServoCommand,
)
from painter_cli.servo.program import build_actions


def mapping() -> MappingConfig:
    return MappingConfig(
        scale_x=1,
        scale_y=1,
        offset_x=0,
        offset_y=0,
        pen_up_z=20,
        pen_down_z=0,
        bounds=MachineBounds(min_x=-100, max_x=100, min_y=-100, max_y=100, min_z=0, max_z=50),
    )


def motion() -> MotionConfig:
    return MotionConfig(velocity=50, acceleration=100, deceleration=100)


def test_build_actions_for_single_stroke():
    mapped = MappedPlan(
        description="line",
        strokes=(MappedStroke(points=(MachinePoint(1, 2, 20), MachinePoint(3, 4, 20))),),
    )

    actions = build_actions(mapped, mapping(), motion())

    assert [action.command for action in actions] == [
        ServoCommand.POWER_ON,
        ServoCommand.RESET,
        ServoCommand.PEN_UP,
        ServoCommand.MOVE_XY,
        ServoCommand.PEN_DOWN,
        ServoCommand.MOVE_XY,
        ServoCommand.PEN_UP,
    ]
    assert actions[3].target.x == 1
    assert actions[3].target.y == 2
    assert actions[4].target.z == 0
    assert actions[5].target.x == 3
    assert actions[5].target.y == 4


def test_build_actions_can_skip_power_and_reset():
    mapped = MappedPlan(
        description="line",
        strokes=(MappedStroke(points=(MachinePoint(1, 2, 20),)),),
    )

    actions = build_actions(mapped, mapping(), motion(), include_power_on=False, include_reset=False)

    assert actions[0].command is ServoCommand.PEN_UP


def test_build_actions_pen_up_between_strokes():
    mapped = MappedPlan(
        description="two",
        strokes=(
            MappedStroke(points=(MachinePoint(1, 1, 20), MachinePoint(2, 2, 20))),
            MappedStroke(points=(MachinePoint(10, 10, 20), MachinePoint(11, 11, 20))),
        ),
    )

    actions = build_actions(mapped, mapping(), motion(), include_power_on=False, include_reset=False)
    commands = [action.command for action in actions]

    assert commands == [
        ServoCommand.PEN_UP,
        ServoCommand.MOVE_XY,
        ServoCommand.PEN_DOWN,
        ServoCommand.MOVE_XY,
        ServoCommand.PEN_UP,
        ServoCommand.PEN_UP,
        ServoCommand.MOVE_XY,
        ServoCommand.PEN_DOWN,
        ServoCommand.MOVE_XY,
        ServoCommand.PEN_UP,
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_program.py -v
```

Expected: FAIL with missing `painter_cli.servo.program`.

- [ ] **Step 3: Implement the action builder**

Create `painter_cli/servo/program.py`:

```python
"""Build blocking servo action programs from mapped stroke plans."""

from __future__ import annotations

from painter_cli.servo.mapper import MappedPlan
from painter_cli.servo.models import MappingConfig, MotionConfig, ServoAction, ServoCommand


def build_actions(
    mapped_plan: MappedPlan,
    mapping: MappingConfig,
    motion: MotionConfig,
    include_power_on: bool = True,
    include_reset: bool = True,
) -> list[ServoAction]:
    actions: list[ServoAction] = []

    if include_power_on:
        actions.append(ServoAction.simple(ServoCommand.POWER_ON))
    if include_reset:
        actions.append(ServoAction.simple(ServoCommand.RESET))

    actions.append(
        ServoAction.pen_up(
            z=mapping.pen_up_z,
            velocity=motion.velocity,
            acceleration=motion.acceleration,
            deceleration=motion.deceleration,
        )
    )

    for stroke in mapped_plan.strokes:
        actions.append(
            ServoAction.move_xy(
                x=stroke.start.x,
                y=stroke.start.y,
                z=mapping.pen_up_z,
                velocity=motion.velocity,
                acceleration=motion.acceleration,
                deceleration=motion.deceleration,
            )
        )
        actions.append(
            ServoAction.pen_down(
                z=mapping.pen_down_z,
                velocity=motion.velocity,
                acceleration=motion.acceleration,
                deceleration=motion.deceleration,
            )
        )
        for point in stroke.points[1:]:
            actions.append(
                ServoAction.move_xy(
                    x=point.x,
                    y=point.y,
                    z=mapping.pen_down_z,
                    velocity=motion.velocity,
                    acceleration=motion.acceleration,
                    deceleration=motion.deceleration,
                )
            )
        actions.append(
            ServoAction.pen_up(
                z=mapping.pen_up_z,
                velocity=motion.velocity,
                acceleration=motion.acceleration,
                deceleration=motion.deceleration,
            )
        )

    return actions
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_program.py -v
```

Expected: PASS.

---

### Task 5: Register Map and REAL Encoding

**Files:**
- Create: `painter_cli/servo/registers.py`
- Test: `tests/test_servo_registers.py`

**Interfaces:**
- Consumes: `ServoStatus` from `painter_cli.servo.models`.
- Produces: `RegisterMap`, `EXECUTE_MASK`, `encode_real(value: float) -> list[int]`, `decode_status(word: int) -> ServoStatus`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_registers.py`:

```python
import struct

from painter_cli.servo.models import ServoStatus
from painter_cli.servo.registers import EXECUTE_MASK, RegisterMap, decode_status, encode_real


def test_register_map_uses_zero_based_modbus_addresses():
    regs = RegisterMap()
    assert regs.command == 0
    assert regs.sequence_id == 1
    assert regs.control_word == 2
    assert regs.status_word == 3
    assert regs.target_x == 20
    assert regs.target_y == 22
    assert regs.target_z == 24


def test_execute_mask_is_bit_15():
    assert EXECUTE_MASK == 0x8000


def test_encode_real_big_endian_word_order():
    encoded = encode_real(1.0)
    packed = struct.pack(">f", 1.0)
    expected = [int.from_bytes(packed[0:2], "big"), int.from_bytes(packed[2:4], "big")]
    assert encoded == expected


def test_decode_status_returns_status_model():
    status = decode_status((1 << 0) | (1 << 4))
    assert isinstance(status, ServoStatus)
    assert status.ready is True
    assert status.done is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_registers.py -v
```

Expected: FAIL with missing `painter_cli.servo.registers`.

- [ ] **Step 3: Implement registers and REAL encoder**

Create `painter_cli/servo/registers.py`:

```python
"""Modbus register definitions for the PLC servo command protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from painter_cli.servo.models import ServoStatus

EXECUTE_MASK = 0x8000


@dataclass(frozen=True)
class RegisterMap:
    command: int = 0
    sequence_id: int = 1
    control_word: int = 2
    status_word: int = 3
    active_command: int = 4
    done_sequence_id: int = 5
    error_code: int = 6
    heartbeat: int = 7
    target_x: int = 20
    target_y: int = 22
    target_z: int = 24
    velocity: int = 26
    acceleration: int = 28
    deceleration: int = 30
    actual_x: int = 40
    actual_y: int = 42
    actual_z: int = 44


def encode_real(value: float) -> list[int]:
    raw = struct.pack(">f", float(value))
    return [int.from_bytes(raw[0:2], "big"), int.from_bytes(raw[2:4], "big")]


def decode_status(word: int) -> ServoStatus:
    return ServoStatus.from_word(word)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_registers.py -v
```

Expected: PASS.

---

### Task 6: Blocking Runner with Fake PLC Client

**Files:**
- Create: `painter_cli/servo/runner.py`
- Test: `tests/test_servo_runner.py`

**Interfaces:**
- Consumes: `ServoAction`, `ServoCommand`, `ServoStatus`, `ServoProtocolError` from `painter_cli.servo.models`.
- Produces: `ServoRunner(client: ServoCommandClient, accepted_timeout_s: float, done_timeout_s: float, poll_interval_s: float)` and `ServoRunner.run(actions: list[ServoAction]) -> None`.
- Required client protocol methods: `send_action(action: ServoAction) -> int`, `read_status() -> ServoStatus`, `read_done_sequence_id() -> int`, `read_error_code() -> int`, `clear_execute() -> None`, `stop() -> None`, `pen_up() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_runner.py`:

```python
import pytest

from painter_cli.servo.models import MachinePoint, ServoAction, ServoCommand, ServoProtocolError, ServoStatus
from painter_cli.servo.runner import ServoRunner


class FakeServoClient:
    def __init__(self):
        self.sent = []
        self.cleared = 0
        self.stopped = 0
        self.pen_up_calls = 0
        self.sequence = 0
        self.done_sequence = 0
        self.statuses = []
        self.error_code = 0

    def send_action(self, action):
        self.sequence += 1
        self.sent.append(action)
        self.done_sequence = self.sequence
        return self.sequence

    def read_status(self):
        if self.statuses:
            return self.statuses.pop(0)
        return ServoStatus.from_word((1 << 8) | (1 << 4))

    def read_done_sequence_id(self):
        return self.done_sequence

    def read_error_code(self):
        return self.error_code

    def clear_execute(self):
        self.cleared += 1

    def stop(self):
        self.stopped += 1

    def pen_up(self):
        self.pen_up_calls += 1


def action(command=ServoCommand.MOVE_XY):
    return ServoAction(command, MachinePoint(1, 2, 3), 10, 20, 30)


def test_runner_sends_actions_and_clears_execute():
    client = FakeServoClient()
    runner = ServoRunner(client, accepted_timeout_s=0.01, done_timeout_s=0.01, poll_interval_s=0)

    runner.run([action(), action(ServoCommand.PEN_UP)])

    assert [sent.command for sent in client.sent] == [ServoCommand.MOVE_XY, ServoCommand.PEN_UP]
    assert client.cleared == 2


def test_runner_reject_raises_protocol_error_and_stops():
    client = FakeServoClient()
    client.error_code = 123
    client.statuses = [ServoStatus.from_word(1 << 9)]
    runner = ServoRunner(client, accepted_timeout_s=0.01, done_timeout_s=0.01, poll_interval_s=0)

    with pytest.raises(ServoProtocolError, match="rejected"):
        runner.run([action()])

    assert client.stopped == 1


def test_runner_plc_error_raises_protocol_error_and_stops():
    client = FakeServoClient()
    client.error_code = 456
    client.statuses = [ServoStatus.from_word(1 << 5)]
    runner = ServoRunner(client, accepted_timeout_s=0.01, done_timeout_s=0.01, poll_interval_s=0)

    with pytest.raises(ServoProtocolError, match="PLC error"):
        runner.run([action()])

    assert client.stopped == 1


def test_runner_ctrl_c_attempts_stop_and_pen_up():
    class InterruptingClient(FakeServoClient):
        def read_status(self):
            raise KeyboardInterrupt

    client = InterruptingClient()
    runner = ServoRunner(client, accepted_timeout_s=0.01, done_timeout_s=0.01, poll_interval_s=0)

    with pytest.raises(KeyboardInterrupt):
        runner.run([action()])

    assert client.stopped == 1
    assert client.pen_up_calls == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_runner.py -v
```

Expected: FAIL with missing `painter_cli.servo.runner`.

- [ ] **Step 3: Implement the runner**

Create `painter_cli/servo/runner.py`:

```python
"""Blocking executor for servo command actions."""

from __future__ import annotations

import time
from typing import Protocol

from painter_cli.servo.models import ServoAction, ServoProtocolError, ServoStatus


class ServoCommandClient(Protocol):
    def send_action(self, action: ServoAction) -> int: ...
    def read_status(self) -> ServoStatus: ...
    def read_done_sequence_id(self) -> int: ...
    def read_error_code(self) -> int: ...
    def clear_execute(self) -> None: ...
    def stop(self) -> None: ...
    def pen_up(self) -> None: ...


class ServoRunner:
    def __init__(
        self,
        client: ServoCommandClient,
        accepted_timeout_s: float,
        done_timeout_s: float,
        poll_interval_s: float,
    ) -> None:
        self._client = client
        self._accepted_timeout_s = accepted_timeout_s
        self._done_timeout_s = done_timeout_s
        self._poll_interval_s = poll_interval_s

    def run(self, actions: list[ServoAction]) -> None:
        try:
            for action in actions:
                sequence_id = self._client.send_action(action)
                self._wait_accepted(action, sequence_id)
                self._wait_done(action, sequence_id)
                self._client.clear_execute()
        except KeyboardInterrupt:
            self._client.stop()
            self._client.pen_up()
            raise
        except Exception:
            self._client.stop()
            raise

    def _wait_accepted(self, action: ServoAction, sequence_id: int) -> None:
        deadline = time.monotonic() + self._accepted_timeout_s
        while time.monotonic() <= deadline:
            status = self._client.read_status()
            if status.error:
                error_code = self._client.read_error_code()
                raise ServoProtocolError(f"PLC error while accepting {action.command.name}: {error_code}")
            if status.rejected:
                error_code = self._client.read_error_code()
                raise ServoProtocolError(f"command {action.command.name} rejected: {error_code}")
            if status.accepted:
                return
            time.sleep(self._poll_interval_s)
        raise ServoProtocolError(f"accepted timeout for {action.command.name} sequence {sequence_id}")

    def _wait_done(self, action: ServoAction, sequence_id: int) -> None:
        deadline = time.monotonic() + self._done_timeout_s
        while time.monotonic() <= deadline:
            status = self._client.read_status()
            if status.error:
                error_code = self._client.read_error_code()
                raise ServoProtocolError(f"PLC error while running {action.command.name}: {error_code}")
            if self._client.read_done_sequence_id() == sequence_id and status.done:
                return
            time.sleep(self._poll_interval_s)
        raise ServoProtocolError(f"done timeout for {action.command.name} sequence {sequence_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_runner.py -v
```

Expected: PASS.

---

### Task 7: Command-Oriented PLC Modbus Client

**Files:**
- Create: `painter_cli/servo/plc_client.py`
- Test: `tests/test_servo_plc_client.py`

**Interfaces:**
- Consumes: `ServoAction`, `ServoCommand`, `ServoStatus` from `painter_cli.servo.models`; `RegisterMap`, `EXECUTE_MASK`, `encode_real`, `decode_status` from `painter_cli.servo.registers`.
- Produces: `ServoPlcClient` implementing `ServoCommandClient` from Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_plc_client.py`:

```python
from painter_cli.servo.models import MachinePoint, ServoAction, ServoCommand
from painter_cli.servo.plc_client import ServoPlcClient
from painter_cli.servo.registers import EXECUTE_MASK, RegisterMap, encode_real


class FakeModbusTcpClient:
    def __init__(self):
        self.connected = True
        self.writes = []
        self.reads = {}
        self.closed = False

    def connect(self):
        return True

    def close(self):
        self.closed = True

    def write_register(self, address, value, device_id=1):
        self.writes.append((address, value, device_id))
        return FakeResult()

    def write_registers(self, address, values, device_id=1):
        self.writes.append((address, tuple(values), device_id))
        return FakeResult()

    def read_holding_registers(self, address, count=1, device_id=1):
        return FakeReadResult([self.reads.get(address, 0) for _ in range(count)])


class FakeResult:
    def isError(self):
        return False


class FakeReadResult:
    def __init__(self, registers):
        self.registers = registers

    def isError(self):
        return False


def test_send_action_writes_parameters_then_command_sequence_execute():
    fake = FakeModbusTcpClient()
    regs = RegisterMap()
    client = ServoPlcClient(host="127.0.0.1", pymodbus_client=fake, registers=regs)
    action = ServoAction(ServoCommand.MOVE_XY, MachinePoint(10, 20, 30), 40, 50, 60)

    sequence = client.send_action(action)

    assert sequence == 1
    assert (regs.target_x, tuple(encode_real(10)), 1) in fake.writes
    assert (regs.target_y, tuple(encode_real(20)), 1) in fake.writes
    assert (regs.target_z, tuple(encode_real(30)), 1) in fake.writes
    assert (regs.velocity, tuple(encode_real(40)), 1) in fake.writes
    assert (regs.acceleration, tuple(encode_real(50)), 1) in fake.writes
    assert (regs.deceleration, tuple(encode_real(60)), 1) in fake.writes
    assert fake.writes[-3:] == [
        (regs.command, ServoCommand.MOVE_XY.value, 1),
        (regs.sequence_id, 1, 1),
        (regs.control_word, EXECUTE_MASK, 1),
    ]


def test_read_status_decodes_status_word():
    fake = FakeModbusTcpClient()
    regs = RegisterMap()
    fake.reads[regs.status_word] = (1 << 0) | (1 << 4)
    client = ServoPlcClient(host="127.0.0.1", pymodbus_client=fake, registers=regs)

    status = client.read_status()

    assert status.ready is True
    assert status.done is True


def test_clear_execute_writes_zero_control_word():
    fake = FakeModbusTcpClient()
    regs = RegisterMap()
    client = ServoPlcClient(host="127.0.0.1", pymodbus_client=fake, registers=regs)

    client.clear_execute()

    assert fake.writes[-1] == (regs.control_word, 0, 1)


def test_stop_sends_stop_command():
    fake = FakeModbusTcpClient()
    regs = RegisterMap()
    client = ServoPlcClient(host="127.0.0.1", pymodbus_client=fake, registers=regs)

    client.stop()

    assert any(write == (regs.command, ServoCommand.STOP.value, 1) for write in fake.writes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_plc_client.py -v
```

Expected: FAIL with missing `painter_cli.servo.plc_client`.

- [ ] **Step 3: Implement the PLC client**

Create `painter_cli/servo/plc_client.py`:

```python
"""Command-oriented Modbus client for PLC servo control."""

from __future__ import annotations

import logging
import time
from typing import Any, Self

from pymodbus.client import ModbusTcpClient

from painter_cli.modbus.client import ModbusError
from painter_cli.servo.models import MachinePoint, ServoAction, ServoCommand, ServoStatus
from painter_cli.servo.registers import EXECUTE_MASK, RegisterMap, decode_status, encode_real

logger = logging.getLogger(__name__)

UNIT_ID = 1


class ServoPlcClient:
    def __init__(
        self,
        host: str,
        port: int = 502,
        retries: int = 3,
        retry_delay: float = 2.0,
        pymodbus_client: Any | None = None,
        registers: RegisterMap | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._retries = retries
        self._retry_delay = retry_delay
        self._client = pymodbus_client or ModbusTcpClient(host=host, port=port, timeout=5)
        self._registers = registers or RegisterMap()
        self._sequence_id = 0
        self._connected = False

    @property
    def address(self) -> str:
        return f"{self._host}:{self._port}"

    def connect(self) -> None:
        for attempt in range(1, self._retries + 1):
            if self._client.connect():
                self._connected = True
                return
            logger.warning("servo PLC connection attempt %d/%d failed", attempt, self._retries)
            time.sleep(self._retry_delay)
        raise ModbusError(f"failed to connect to PLC at {self.address}")

    def disconnect(self) -> None:
        self._client.close()
        self._connected = False

    def send_action(self, action: ServoAction) -> int:
        self._write_real(self._registers.target_x, action.target.x)
        self._write_real(self._registers.target_y, action.target.y)
        self._write_real(self._registers.target_z, action.target.z)
        self._write_real(self._registers.velocity, action.velocity)
        self._write_real(self._registers.acceleration, action.acceleration)
        self._write_real(self._registers.deceleration, action.deceleration)

        self._sequence_id = (self._sequence_id + 1) & 0xFFFF
        if self._sequence_id == 0:
            self._sequence_id = 1

        self._write_register(self._registers.command, int(action.command))
        self._write_register(self._registers.sequence_id, self._sequence_id)
        self._write_register(self._registers.control_word, EXECUTE_MASK)
        return self._sequence_id

    def read_status(self) -> ServoStatus:
        return decode_status(self._read_register(self._registers.status_word))

    def read_done_sequence_id(self) -> int:
        return self._read_register(self._registers.done_sequence_id)

    def read_error_code(self) -> int:
        return self._read_register(self._registers.error_code)

    def clear_execute(self) -> None:
        self._write_register(self._registers.control_word, 0)

    def stop(self) -> None:
        self._write_register(self._registers.command, int(ServoCommand.STOP))
        self._sequence_id = (self._sequence_id + 1) & 0xFFFF or 1
        self._write_register(self._registers.sequence_id, self._sequence_id)
        self._write_register(self._registers.control_word, EXECUTE_MASK)

    def pen_up(self) -> None:
        self.send_action(ServoAction(ServoCommand.PEN_UP, MachinePoint(0, 0, 0), 1, 1, 1))

    def write_heartbeat(self, value: int) -> None:
        self._write_register(self._registers.heartbeat, value & 0xFFFF)

    def _write_real(self, address: int, value: float) -> None:
        result = self._client.write_registers(address, encode_real(value), device_id=UNIT_ID)
        if result.isError():
            raise ModbusError(f"failed to write REAL at register {address}: {result}")

    def _write_register(self, address: int, value: int) -> None:
        result = self._client.write_register(address, value & 0xFFFF, device_id=UNIT_ID)
        if result.isError():
            raise ModbusError(f"failed to write register {address}: {result}")

    def _read_register(self, address: int) -> int:
        result = self._client.read_holding_registers(address, count=1, device_id=UNIT_ID)
        if result.isError():
            raise ModbusError(f"failed to read register {address}: {result}")
        return int(result.registers[0])

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_plc_client.py -v
```

Expected: PASS.

---

### Task 8: Servo Settings

**Files:**
- Modify: `painter_cli/config.py`
- Modify: `.env.example`
- Test: `tests/test_servo_settings.py`

**Interfaces:**
- Consumes: existing `Settings` class.
- Produces: new Settings fields: `servo_scale_x`, `servo_scale_y`, `servo_offset_x`, `servo_offset_y`, `servo_min_x`, `servo_max_x`, `servo_min_y`, `servo_max_y`, `servo_min_z`, `servo_max_z`, `servo_pen_up_z`, `servo_pen_down_z`, `servo_velocity`, `servo_acceleration`, `servo_deceleration`, `servo_accepted_timeout_s`, `servo_done_timeout_s`, `servo_poll_interval_s`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_settings.py`:

```python
from painter_cli.config import Settings


def test_servo_defaults_are_available():
    settings = Settings()

    assert settings.servo_scale_x == 1.0
    assert settings.servo_scale_y == 1.0
    assert settings.servo_offset_x == 0.0
    assert settings.servo_offset_y == 0.0
    assert settings.servo_pen_up_z == 20.0
    assert settings.servo_pen_down_z == 0.0
    assert settings.servo_velocity > 0
    assert settings.servo_acceleration > 0
    assert settings.servo_deceleration > 0
    assert settings.servo_accepted_timeout_s > 0
    assert settings.servo_done_timeout_s > 0
    assert settings.servo_poll_interval_s >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_settings.py -v
```

Expected: FAIL with `AttributeError` for `servo_scale_x`.

- [ ] **Step 3: Add settings fields**

Modify `painter_cli/config.py` by adding these fields inside `class Settings` after `coord_range`:

```python
    # Servo command protocol defaults
    servo_scale_x: float = 1.0
    servo_scale_y: float = 1.0
    servo_offset_x: float = 0.0
    servo_offset_y: float = 0.0
    servo_min_x: float = -240.0
    servo_max_x: float = 240.0
    servo_min_y: float = -240.0
    servo_max_y: float = 240.0
    servo_min_z: float = 0.0
    servo_max_z: float = 50.0
    servo_pen_up_z: float = 20.0
    servo_pen_down_z: float = 0.0
    servo_velocity: float = 50.0
    servo_acceleration: float = 200.0
    servo_deceleration: float = 200.0
    servo_accepted_timeout_s: float = 5.0
    servo_done_timeout_s: float = 30.0
    servo_poll_interval_s: float = 0.05
```

If `.env.example` exists, append:

```text
PAINTER_SERVO_SCALE_X=1.0
PAINTER_SERVO_SCALE_Y=1.0
PAINTER_SERVO_OFFSET_X=0.0
PAINTER_SERVO_OFFSET_Y=0.0
PAINTER_SERVO_MIN_X=-240.0
PAINTER_SERVO_MAX_X=240.0
PAINTER_SERVO_MIN_Y=-240.0
PAINTER_SERVO_MAX_Y=240.0
PAINTER_SERVO_MIN_Z=0.0
PAINTER_SERVO_MAX_Z=50.0
PAINTER_SERVO_PEN_UP_Z=20.0
PAINTER_SERVO_PEN_DOWN_Z=0.0
PAINTER_SERVO_VELOCITY=50.0
PAINTER_SERVO_ACCELERATION=200.0
PAINTER_SERVO_DECELERATION=200.0
PAINTER_SERVO_ACCEPTED_TIMEOUT_S=5.0
PAINTER_SERVO_DONE_TIMEOUT_S=30.0
PAINTER_SERVO_POLL_INTERVAL_S=0.05
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_servo_settings.py -v
```

Expected: PASS.

---

### Task 9: CLI Integration for Dry Run, Ping, and Single Commands

**Files:**
- Modify: `painter_cli/cli.py`
- Test: `tests/test_servo_cli.py`

**Interfaces:**
- Consumes: `parse_servo_plan`, `map_plan`, `build_actions`, `ServoPlcClient`, `ServoRunner`, settings fields from Task 8.
- Produces: click commands `servo-draw`, `servo-ping`, and `servo-command`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_servo_cli.py`:

```python
import json

from click.testing import CliRunner

from painter_cli.cli import cli


def test_servo_draw_dry_run_outputs_action_summary(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({"description": "line", "strokes": [{"points": [[0, 0], [10, 10]]}]}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "servo-draw",
            str(plan_path),
            "--dry-run",
            "--min-x",
            "-100",
            "--max-x",
            "100",
            "--min-y",
            "-100",
            "--max-y",
            "100",
        ],
    )

    assert result.exit_code == 0
    assert "line" in result.output
    assert "Actions:" in result.output
    assert "PEN_UP" in result.output
    assert "MOVE_XY" in result.output


def test_servo_draw_dry_run_rejects_out_of_bounds(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({"strokes": [{"points": [[1000, 0]]}]}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["servo-draw", str(plan_path), "--dry-run", "--max-x", "100"])

    assert result.exit_code != 0
    assert "outside" in result.output


def test_servo_command_requires_plc_ip_for_live_command():
    result = CliRunner().invoke(cli, ["servo-command", "pen-up"])

    assert result.exit_code != 0
    assert "--plc-ip" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_servo_cli.py -v
```

Expected: FAIL because the CLI commands do not exist.

- [ ] **Step 3: Add CLI helper builders**

Modify imports in `painter_cli/cli.py` by adding:

```python
from painter_cli.servo.json_loader import ServoJsonError, parse_servo_plan
from painter_cli.servo.mapper import map_plan
from painter_cli.servo.models import (
    MachineBounds,
    MappingConfig,
    MotionConfig,
    ServoAction,
    ServoCommand,
    ServoProtocolError,
)
from painter_cli.servo.plc_client import ServoPlcClient
from painter_cli.servo.program import build_actions
from painter_cli.servo.runner import ServoRunner
```

Add these helper functions before `main()`:

```python
def _servo_mapping_from_options(
    settings: Settings,
    scale_x: float | None,
    scale_y: float | None,
    offset_x: float | None,
    offset_y: float | None,
    min_x: float | None,
    max_x: float | None,
    min_y: float | None,
    max_y: float | None,
    min_z: float | None,
    max_z: float | None,
    pen_up_z: float | None,
    pen_down_z: float | None,
) -> MappingConfig:
    bounds = MachineBounds(
        min_x=settings.servo_min_x if min_x is None else min_x,
        max_x=settings.servo_max_x if max_x is None else max_x,
        min_y=settings.servo_min_y if min_y is None else min_y,
        max_y=settings.servo_max_y if max_y is None else max_y,
        min_z=settings.servo_min_z if min_z is None else min_z,
        max_z=settings.servo_max_z if max_z is None else max_z,
    )
    return MappingConfig(
        scale_x=settings.servo_scale_x if scale_x is None else scale_x,
        scale_y=settings.servo_scale_y if scale_y is None else scale_y,
        offset_x=settings.servo_offset_x if offset_x is None else offset_x,
        offset_y=settings.servo_offset_y if offset_y is None else offset_y,
        pen_up_z=settings.servo_pen_up_z if pen_up_z is None else pen_up_z,
        pen_down_z=settings.servo_pen_down_z if pen_down_z is None else pen_down_z,
        bounds=bounds,
    )


def _servo_motion_from_options(
    settings: Settings,
    velocity: float | None,
    acceleration: float | None,
    deceleration: float | None,
) -> MotionConfig:
    return MotionConfig(
        velocity=settings.servo_velocity if velocity is None else velocity,
        acceleration=settings.servo_acceleration if acceleration is None else acceleration,
        deceleration=settings.servo_deceleration if deceleration is None else deceleration,
    )


def _print_servo_actions(description: str, total_points: int, actions: list[ServoAction]) -> None:
    console.print(f"Description: {description}")
    console.print(f"Points: {total_points}")
    console.print(f"Actions: {len(actions)}")
    for idx, action in enumerate(actions[:20], start=1):
        console.print(
            f"[{idx:03d}] {action.command.name} "
            f"x={action.target.x:g} y={action.target.y:g} z={action.target.z:g} "
            f"v={action.velocity:g}"
        )
    if len(actions) > 20:
        console.print(f"... {len(actions) - 20} more actions")
```

- [ ] **Step 4: Add `servo-draw` command**

Modify `painter_cli/cli.py` by adding this command before `config()`:

```python
@cli.command("servo-draw")
@click.argument("source", required=True)
@click.option("--plc-ip", default=None, help="PLC Modbus TCP host")
@click.option("--port", default=None, type=int, help="PLC Modbus TCP port")
@click.option("--dry-run", is_flag=True, help="Validate and print actions without connecting to PLC")
@click.option("--yes", is_flag=True, help="Run without confirmation")
@click.option("--scale-x", default=None, type=float)
@click.option("--scale-y", default=None, type=float)
@click.option("--offset-x", default=None, type=float)
@click.option("--offset-y", default=None, type=float)
@click.option("--min-x", default=None, type=float)
@click.option("--max-x", default=None, type=float)
@click.option("--min-y", default=None, type=float)
@click.option("--max-y", default=None, type=float)
@click.option("--min-z", default=None, type=float)
@click.option("--max-z", default=None, type=float)
@click.option("--pen-up-z", default=None, type=float)
@click.option("--pen-down-z", default=None, type=float)
@click.option("--velocity", default=None, type=float)
@click.option("--acceleration", default=None, type=float)
@click.option("--deceleration", default=None, type=float)
def servo_draw(
    source: str,
    plc_ip: str | None,
    port: int | None,
    dry_run: bool,
    yes: bool,
    scale_x: float | None,
    scale_y: float | None,
    offset_x: float | None,
    offset_y: float | None,
    min_x: float | None,
    max_x: float | None,
    min_y: float | None,
    max_y: float | None,
    min_z: float | None,
    max_z: float | None,
    pen_up_z: float | None,
    pen_down_z: float | None,
    velocity: float | None,
    acceleration: float | None,
    deceleration: float | None,
) -> None:
    """Execute a stroke JSON file through the servo Modbus command protocol."""
    settings = Settings()
    raw = _resolve_input(source)

    try:
        plan = parse_servo_plan(raw)
        mapping = _servo_mapping_from_options(
            settings,
            scale_x,
            scale_y,
            offset_x,
            offset_y,
            min_x,
            max_x,
            min_y,
            max_y,
            min_z,
            max_z,
            pen_up_z,
            pen_down_z,
        )
        motion = _servo_motion_from_options(settings, velocity, acceleration, deceleration)
        mapped = map_plan(plan, mapping)
        actions = build_actions(mapped, mapping, motion)
    except (ServoJsonError, ValueError) as exc:
        print_error(str(exc))
        sys.exit(1)

    _print_servo_actions(plan.description, plan.total_points, actions)

    if dry_run:
        print_success("Servo dry run complete.")
        return

    if not plc_ip:
        print_error("--plc-ip is required unless --dry-run is used")
        sys.exit(1)

    if not yes and not click.confirm("Continue and send commands to PLC?", default=False):
        print_warning("Aborted before connecting to PLC.")
        return

    client = ServoPlcClient(host=plc_ip, port=port or settings.plc_port)
    try:
        client.connect()
        runner = ServoRunner(
            client,
            accepted_timeout_s=settings.servo_accepted_timeout_s,
            done_timeout_s=settings.servo_done_timeout_s,
            poll_interval_s=settings.servo_poll_interval_s,
        )
        runner.run(actions)
        print_success("Servo drawing complete.")
    except (ModbusError, ServoProtocolError) as exc:
        print_error(str(exc))
        sys.exit(1)
    finally:
        client.disconnect()
```

- [ ] **Step 5: Add `servo-ping` and `servo-command` commands**

Add these commands after `servo_draw`:

```python
@cli.command("servo-ping")
@click.option("--plc-ip", required=True, help="PLC Modbus TCP host")
@click.option("--port", default=None, type=int, help="PLC Modbus TCP port")
def servo_ping(plc_ip: str, port: int | None) -> None:
    """Connect to PLC, read servo status, and write heartbeat."""
    settings = Settings()
    client = ServoPlcClient(host=plc_ip, port=port or settings.plc_port)
    try:
        client.connect()
        status = client.read_status()
        client.write_heartbeat(1)
        print_success(f"PLC: {client.address} — Connected")
        console.print(f"Status word: {status.word}")
    except ModbusError as exc:
        print_error(str(exc))
        sys.exit(1)
    finally:
        client.disconnect()


@cli.command("servo-command")
@click.argument("command", type=click.Choice(["pen-up", "pen-down", "stop", "reset", "power-on"]))
@click.option("--plc-ip", default=None, help="PLC Modbus TCP host")
@click.option("--port", default=None, type=int, help="PLC Modbus TCP port")
@click.option("--pen-up-z", default=None, type=float)
@click.option("--pen-down-z", default=None, type=float)
@click.option("--velocity", default=None, type=float)
@click.option("--acceleration", default=None, type=float)
@click.option("--deceleration", default=None, type=float)
def servo_command(
    command: str,
    plc_ip: str | None,
    port: int | None,
    pen_up_z: float | None,
    pen_down_z: float | None,
    velocity: float | None,
    acceleration: float | None,
    deceleration: float | None,
) -> None:
    """Send one servo command through the PLC command protocol."""
    if not plc_ip:
        print_error("--plc-ip is required")
        sys.exit(1)

    settings = Settings()
    motion = _servo_motion_from_options(settings, velocity, acceleration, deceleration)
    up_z = settings.servo_pen_up_z if pen_up_z is None else pen_up_z
    down_z = settings.servo_pen_down_z if pen_down_z is None else pen_down_z

    action_map = {
        "pen-up": ServoAction.pen_up(up_z, motion.velocity, motion.acceleration, motion.deceleration),
        "pen-down": ServoAction.pen_down(down_z, motion.velocity, motion.acceleration, motion.deceleration),
        "stop": ServoAction.simple(ServoCommand.STOP),
        "reset": ServoAction.simple(ServoCommand.RESET),
        "power-on": ServoAction.simple(ServoCommand.POWER_ON),
    }

    client = ServoPlcClient(host=plc_ip, port=port or settings.plc_port)
    try:
        client.connect()
        runner = ServoRunner(
            client,
            accepted_timeout_s=settings.servo_accepted_timeout_s,
            done_timeout_s=settings.servo_done_timeout_s,
            poll_interval_s=settings.servo_poll_interval_s,
        )
        runner.run([action_map[command]])
        print_success(f"Sent {command}.")
    except (ModbusError, ServoProtocolError) as exc:
        print_error(str(exc))
        sys.exit(1)
    finally:
        client.disconnect()
```

- [ ] **Step 6: Run CLI tests**

Run:

```bash
pytest tests/test_servo_cli.py -v
```

Expected: PASS.

---

### Task 10: Full Verification

**Files:**
- No code creation expected.
- Run all relevant tests and dry-run the actual rabbit file.

**Interfaces:**
- Consumes all prior tasks.
- Produces verified CLI commands ready for PLC-side integration testing.

- [ ] **Step 1: Run all test suites**

Run:

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run the rabbit dry run**

Run:

```bash
painter-cli servo-draw "C:/Users/se/projects/painter-cli/assets/rabbit_v2.json" --dry-run --scale-x 1 --scale-y 1 --offset-x 0 --offset-y 0 --min-x -300 --max-x 300 --min-y -300 --max-y 300 --min-z 0 --max-z 50 --pen-up-z 20 --pen-down-z 0 --velocity 50 --acceleration 200 --deceleration 200
```

Expected output includes:

```text
Description: lineart (6 strokes)
Points: 94
Actions:
PEN_UP
MOVE_XY
Servo dry run complete.
```

- [ ] **Step 3: Run module directly if console script is unavailable**

If `painter-cli` is not on PATH, run:

```bash
python -m painter_cli.cli servo-draw "C:/Users/se/projects/painter-cli/assets/rabbit_v2.json" --dry-run --scale-x 1 --scale-y 1 --offset-x 0 --offset-y 0 --min-x -300 --max-x 300 --min-y -300 --max-y 300 --min-z 0 --max-z 50 --pen-up-z 20 --pen-down-z 0 --velocity 50 --acceleration 200 --deceleration 200
```

Expected output is the same as Step 2.

- [ ] **Step 4: Document manual PLC smoke tests for the user**

Report these manual commands to the user after tests pass:

```bash
painter-cli servo-ping --plc-ip <PLC_IP>
painter-cli servo-command pen-up --plc-ip <PLC_IP>
painter-cli servo-command pen-down --plc-ip <PLC_IP>
painter-cli servo-draw "C:/Users/se/projects/painter-cli/assets/rabbit_v2.json" --plc-ip <PLC_IP> --scale-x 1 --scale-y 1 --offset-x 0 --offset-y 0 --min-x -300 --max-x 300 --min-y -300 --max-y 300 --min-z 0 --max-z 50 --pen-up-z 20 --pen-down-z 0 --velocity 20 --acceleration 100 --deceleration 100
```

Expected: the first command only reads/writes non-motion status/heartbeat, the next two move Z only, and the final command asks for confirmation before sending the full drawing program.

---

## Self-Review

- Spec coverage: The plan implements strict JSON parsing, coordinate mapping with configurable scale/offset, bounds validation, Z-axis pen-up/pen-down, point-to-point action generation, Modbus command registers, accepted/done handshake, dry run, ping, single commands, and full rabbit dry-run verification.
- Scope check: The plan does not implement natural language execution, queueing, blending, path optimization, service mode, or automatic return home, matching the version 1 exclusions.
- Placeholder scan: No task uses TBD/TODO/fill-in instructions. Each code-writing step includes concrete code.
- Type consistency: `ServoAction`, `ServoCommand`, `MappingConfig`, `MotionConfig`, `MappedPlan`, `ServoRunner`, and `ServoPlcClient` names are consistent across tasks.
- Repository note: `C:\Users\se\projects\painter-cli` is not currently a git repository, so this plan omits commit steps until git is initialized.
