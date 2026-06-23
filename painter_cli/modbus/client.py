"""Modbus TCP client wrapper for PLC communication."""

from __future__ import annotations

import logging
import time
from typing import Self

from pymodbus.client import ModbusTcpClient

logger = logging.getLogger(__name__)

# Register addresses (0-indexed, corresponding to %MW0, %MW1, %MW2)
REG_PEN = 0  # Pen control: 0=up, 1=down
REG_X = 1    # X-axis position (signed, written directly)
REG_Y = 2    # Y-axis position (signed, written directly)

UNIT_ID = 1


def _to_uint16(value: int) -> int:
    """Convert a signed integer to unsigned 16-bit two's complement.

    The PLC interprets the register value as a signed 16-bit integer.
    This conversion ensures pymodbus accepts the value while the PLC
    sees the correct signed number.

    Examples: 240 -> 240, -5 -> 65531, -240 -> 65296
    """
    return value & 0xFFFF


class ModbusError(Exception):
    """Raised on Modbus communication failures."""


class ModbusClient:
    """High-level Modbus TCP client for the drawing PLC.

    Provides connect/disconnect lifecycle, automatic reconnection,
    and a single `write_position` method that writes all three
    control registers in the correct order.

    Usage:
        with ModbusClient("10.10.20.244") as client:
            client.write_position(x=0, y=0, pen=False)
    """

    def __init__(
        self,
        host: str,
        port: int = 502,
        retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self._host = host
        self._port = port
        self._retries = retries
        self._retry_delay = retry_delay
        self._client = ModbusTcpClient(host=host, port=port, timeout=5)
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return f"{self._host}:{self._port}"

    def connect(self) -> None:
        """Establish connection to the PLC with retry logic."""
        for attempt in range(1, self._retries + 1):
            if self._client.connect():
                self._connected = True
                logger.info("Connected to PLC at %s", self.address)
                return
            logger.warning(
                "Connection attempt %d/%d failed, retrying in %.1fs...",
                attempt,
                self._retries,
                self._retry_delay,
            )
            time.sleep(self._retry_delay)
        raise ModbusError(
            f"Failed to connect to PLC at {self.address} after {self._retries} attempts"
        )

    def disconnect(self) -> None:
        """Close the Modbus connection."""
        self._client.close()
        self._connected = False
        logger.info("Disconnected from PLC at %s", self.address)

    def _ensure_connected(self) -> None:
        """Reconnect if the connection was lost."""
        if not self._client.connected:
            self._connected = False
            self.connect()

    def write_position(self, x: int, y: int, pen: bool) -> None:
        """Write pen state and X/Y coordinates to the PLC.

        Args:
            x: X coordinate in [-240, 240].
            y: Y coordinate in [-240, 240].
            pen: True to lower pen (draw), False to raise pen.

        Raises:
            ModbusError: If the write operation fails.
        """
        self._ensure_connected()
        pen_val = 1 if pen else 0

        # Write pen first (safety: pen up before moving)
        result = self._client.write_register(REG_PEN, pen_val, device_id=UNIT_ID)
        if result.isError():
            raise ModbusError(f"Failed to write pen register: {result}")

        result = self._client.write_register(REG_X, _to_uint16(x), device_id=UNIT_ID)
        if result.isError():
            raise ModbusError(f"Failed to write X register: {result}")

        result = self._client.write_register(REG_Y, _to_uint16(y), device_id=UNIT_ID)
        if result.isError():
            raise ModbusError(f"Failed to write Y register: {result}")

    def pen_up(self) -> None:
        """Raise the pen (emergency stop helper)."""
        try:
            self._ensure_connected()
            self._client.write_register(REG_PEN, 0, device_id=UNIT_ID)
        except Exception:
            logger.warning("Failed to raise pen during emergency stop")

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.pen_up()
        self.disconnect()
