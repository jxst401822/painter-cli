"""Tests for the Modbus coordinate encoder."""

import pytest

from painter_cli.modbus.encoder import (
    COORD_MAX,
    COORD_MIN,
    OFFSET,
    CoordinateError,
    clamp,
    decode,
    encode,
)


class TestEncode:
    def test_zero(self):
        assert encode(0) == OFFSET  # 240

    def test_positive_boundary(self):
        assert encode(240) == 480

    def test_negative_boundary(self):
        assert encode(-240) == 0

    def test_positive_value(self):
        assert encode(100) == 340

    def test_negative_value(self):
        assert encode(-100) == 140

    def test_out_of_range_positive(self):
        with pytest.raises(CoordinateError, match="out of range"):
            encode(241)

    def test_out_of_range_negative(self):
        with pytest.raises(CoordinateError, match="out of range"):
            encode(-241)

    def test_large_out_of_range(self):
        with pytest.raises(CoordinateError):
            encode(1000)


class TestDecode:
    def test_zero_encoded(self):
        assert decode(OFFSET) == 0

    def test_max_encoded(self):
        assert decode(480) == 240

    def test_min_encoded(self):
        assert decode(0) == -240

    def test_roundtrip(self):
        for v in range(COORD_MIN, COORD_MAX + 1, 10):
            assert decode(encode(v)) == v


class TestClamp:
    def test_within_range(self):
        assert clamp(0) == 0
        assert clamp(100) == 100
        assert clamp(-100) == -100

    def test_at_boundary(self):
        assert clamp(240) == 240
        assert clamp(-240) == -240

    def test_above_range(self):
        assert clamp(500) == 240

    def test_below_range(self):
        assert clamp(-500) == -240
