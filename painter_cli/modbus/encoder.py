"""Coordinate encoding for Modbus unsigned 16-bit registers.

The HMI uses a 4-quadrant coordinate system with origin (0,0) and
range [-240, 240] on both axes. Modbus holding registers are unsigned
16-bit integers, so we apply an offset of +240 to map the signed
coordinate space into [0, 480].
"""

from __future__ import annotations

OFFSET = 240
COORD_MIN = -240
COORD_MAX = 240


class CoordinateError(Exception):
    """Raised when a coordinate value is out of the valid range."""


def encode(value: int) -> int:
    """Map a signed coordinate [-240, 240] to an unsigned register value [0, 480].

    Args:
        value: Signed coordinate in the range [-240, 240].

    Returns:
        Unsigned integer suitable for writing to a Modbus holding register.

    Raises:
        CoordinateError: If value is outside [-240, 240].
    """
    if not (COORD_MIN <= value <= COORD_MAX):
        raise CoordinateError(
            f"Coordinate {value} out of range [{COORD_MIN}, {COORD_MAX}]"
        )
    return value + OFFSET


def decode(encoded: int) -> int:
    """Map an unsigned register value [0, 480] back to a signed coordinate [-240, 240].

    Args:
        encoded: Unsigned register value.

    Returns:
        Signed coordinate.
    """
    return encoded - OFFSET


def clamp(value: int) -> int:
    """Clamp a coordinate to the valid range [-240, 240].

    Args:
        value: Any integer coordinate.

    Returns:
        Value clamped to [-240, 240].
    """
    return max(COORD_MIN, min(COORD_MAX, value))
