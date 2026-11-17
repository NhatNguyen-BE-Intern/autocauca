"""Independent parity unit tests for water point vision algorithm.

Verifies 1:1 algorithmic parity between Python SIMD implementation and
Rust std-only implementation in rust/hybrid/worker_vision.rs.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import (
    ProtocolError,
    RgbPayload,
    water_point,
)

SAFE_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])
MEANS = (318229.0 / 4410.0, 397111.0 / 4410.0, 441422.0 / 4410.0)


def _make_payload(width: int, height: int, pixels: bytes, timestamp: int = 0) -> bytes:
    stride = width * 3
    header = struct.pack("<IIIQ", width, height, stride, timestamp)
    return header + pixels


def _paint_water_square(pixels: bytearray, width: int, cx: int, cy: int) -> None:
    for y in range(cy - 25, cy + 26):
        for x in range(cx - 25, cx + 26):
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = SAFE_WATER


def _direct_water_reference(width: int, height: int, pixels: bytes) -> Optional[Tuple[int, int]]:
    """Independent scalar reference without integral image."""
    if width < 60 or height < 60:
        return None
    y_start = max(height // 5, 25)
    y_end = min(height * 82 // 100, height - 25)
    x_start = max(width // 4, 25)
    x_end = min(width * 3 // 4, width - 25)

    for y in range(y_start, y_end, 4):
        for x in range(x_start, x_end, 4):
            safe = True
            for r in range(y - 25, y + 26):
                for c in range(x - 25, x + 26):
                    offset = (r * width + c) * 3
                    px = pixels[offset : offset + 3]
                    if not all(abs(px[ch] - MEANS[ch]) <= 14.0 for ch in range(3)):
                        safe = False
                        break
                if not safe:
                    break
            if safe:
                return (x, y)
    return None


class WaterVisionParityTests(unittest.TestCase):
    """Test suite verifying 1:1 parity with tests/worker_tests.rs."""

    def test_01_standard_frame_finds_first_safe_point(self) -> None:
        """Test 1: Standard water frame 70x70 finds exact first safe point coordinates."""
        for width, height, expected in [
            (70, 70, (25, 25)),
            (60, 60, (25, 25)),
            (100, 100, (25, 25)),
            (120, 100, (30, 25)),
        ]:
            pixels = SAFE_WATER * (width * height)
            payload = _make_payload(width, height, pixels)
            self.assertEqual(water_point(payload), expected)
            # Verify RgbPayload instance overload directly
            rgb_obj = RgbPayload(width, height, width * 3, 0, pixels)
            self.assertEqual(water_point(rgb_obj), expected)

        # Monotonic timestamp endpoints (0 and max uint64)
        for ts in [0, 0xFFFFFFFFFFFFFFFF]:
            payload = _make_payload(60, 60, SAFE_WATER * 3600, timestamp=ts)
            self.assertEqual(water_point(payload), (25, 25))

    def test_02_minimum_dimensions_rejects_sub_60(self) -> None:
        """Test 2: Dimensions < 60x60 return None."""
        for width, height in [(59, 60), (60, 59), (59, 59), (50, 50), (10, 100), (100, 10)]:
            pixels = SAFE_WATER * (width * height)
            payload = _make_payload(width, height, pixels)
            self.assertIsNone(water_point(payload))

        # All dry frame returns None
        dry_pixels = DRY * (100 * 100)
        self.assertIsNone(water_point(_make_payload(100, 100, dry_pixels)))

    def test_03_search_priority_is_row_major_y_first_then_x(self) -> None:
        """Test 3: Priority order is row-major (y first, then x), step 4."""
        # Case A: (124, 44) has lower y than (64, 104) -> (124, 44) chosen
        pixels_a = bytearray(DRY * (240 * 200))
        _paint_water_square(pixels_a, 240, 124, 44)
        _paint_water_square(pixels_a, 240, 64, 104)
        self.assertEqual(water_point(_make_payload(240, 200, bytes(pixels_a))), (124, 44))

        # Case B: (64, 44) and (124, 44) on same row -> (64, 44) chosen (smaller x)
        pixels_b = bytearray(DRY * (240 * 200))
        _paint_water_square(pixels_b, 240, 64, 44)
        _paint_water_square(pixels_b, 240, 124, 44)
        self.assertEqual(water_point(_make_payload(240, 200, bytes(pixels_b))), (64, 44))

        # Off-grid test: (74, 25) is not multiple of 4 from start x=25 -> not selected
        pixels_off = bytearray(DRY * (100 * 100))
        _paint_water_square(pixels_off, 100, 74, 25)
        self.assertIsNone(water_point(_make_payload(100, 100, bytes(pixels_off))))

    def test_04_center_pixel_defect_rejects_candidate(self) -> None:
        """Test 4: Single defective pixel at center of 51x51 square rejects candidate."""
        pixels = bytearray(DRY * (100 * 100))
        _paint_water_square(pixels, 100, 25, 25)
        self.assertEqual(water_point(_make_payload(100, 100, bytes(pixels))), (25, 25))

        # Defect at exact center (25, 25)
        offset = (25 * 100 + 25) * 3
        pixels[offset : offset + 3] = DRY
        self.assertIsNone(water_point(_make_payload(100, 100, bytes(pixels))))

        # Perimeter-only safety is insufficient: entire interior 1..50 made DRY
        pixels_perim = bytearray(DRY * (100 * 100))
        _paint_water_square(pixels_perim, 100, 25, 25)
        for y in range(1, 50):
            for x in range(1, 50):
                off = (y * 100 + x) * 3
                pixels_perim[off : off + 3] = DRY
        self.assertIsNone(water_point(_make_payload(100, 100, bytes(pixels_perim))))

    def test_05_corner_and_edge_defects_reject_candidate(self) -> None:
        """Test 5: Single defective pixel at corner or edge rejects candidate (requires full 2601)."""
        # Relative to center (25, 25) in 100x100: bounds are x in 0..50, y in 0..50
        corners_and_edges = [
            (0, 0),    # Top-left corner
            (50, 0),   # Top-right corner
            (0, 50),   # Bottom-left corner
            (50, 50),  # Bottom-right corner
            (25, 0),   # Top edge midpoint
            (50, 25),  # Right edge midpoint
            (25, 50),  # Bottom edge midpoint
            (0, 25),   # Left edge midpoint
        ]
        for cx, cy in corners_and_edges:
            pixels = bytearray(DRY * (100 * 100))
            _paint_water_square(pixels, 100, 25, 25)
            offset = (cy * 100 + cx) * 3
            pixels[offset : offset + 3] = DRY
            self.assertIsNone(
                water_point(_make_payload(100, 100, bytes(pixels))),
                f"Candidate should be rejected when ({cx}, {cy}) is defective",
            )

    def test_06_channel_thresholds_evaluated_independently(self) -> None:
        """Test 6: Channel thresholds Mean R, G, B +/- 14 evaluated separately."""
        # Mean R: 72.16 -> [58.16, 86.16] -> integer range [59, 86]
        # Mean G: 90.05 -> [76.05, 104.05] -> integer range [77, 104]
        # Mean B: 100.10 -> [86.10, 114.10] -> integer range [87, 114]
        channels = [
            (0, 59, 86),
            (1, 77, 104),
            (2, 87, 114),
        ]
        for ch, lower, upper in channels:
            for val, expected in [
                (lower, (25, 25)),
                (upper, (25, 25)),
                (lower - 1, None),
                (upper + 1, None),
            ]:
                color = bytearray(SAFE_WATER)
                color[ch] = val
                pixels = bytes(color) * 3600
                payload = _make_payload(60, 60, pixels)
                self.assertEqual(
                    water_point(payload),
                    expected,
                    f"Channel {ch} with value {val} failed expected {expected}",
                )

    def test_07_seeded_mixed_frames_match_direct_reference(self) -> None:
        """Test 7: Candidate arbitration on mixed water regions matches scalar reference."""
        dimensions = [(61, 63), (76, 84), (100, 100), (120, 100), (120, 200)]
        for width, height in dimensions:
            for seed in range(6):
                state = seed + 3103
                pixels = bytearray()
                for _ in range(width * height):
                    state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
                    pixels.extend(DRY if (state >> 30) == 0 else SAFE_WATER)

                x = max(width // 4, 25)
                y = max(height // 5, 25)
                if seed % 3 == 0:
                    _paint_water_square(pixels, width, x, y)
                elif seed % 3 == 1:
                    _paint_water_square(pixels, width, width // 2, height // 2)
                elif seed % 3 == 2:
                    _paint_water_square(pixels, width, x, y)
                    offset = (y * width + x) * 3
                    pixels[offset : offset + 3] = DRY

                expected = _direct_water_reference(width, height, bytes(pixels))
                actual = water_point(_make_payload(width, height, bytes(pixels)))
                self.assertEqual(
                    actual,
                    expected,
                    f"Mismatch on {width}x{height} seed {seed}: expected {expected}, got {actual}",
                )

    def test_08_malformed_rgb_header_and_payload_rejected(self) -> None:
        """Test 8: Malformed RGB headers and truncated payloads raise ProtocolError."""
        valid_payload = _make_payload(60, 60, SAFE_WATER * 3600)

        # Truncated headers (0..19 bytes)
        for length in range(20):
            with self.assertRaises(ProtocolError):
                water_point(valid_payload[:length])

        # Invalid dimensions and strides
        for width, height, stride in [
            (0, 60, 0),
            (60, 0, 180),
            (8193, 1, 24579),
            (1, 8193, 3),
            (60, 60, 179),
            (8192, 8192, 24576),
        ]:
            header = struct.pack("<IIIQ", width, height, stride, 0)
            with self.assertRaises(ProtocolError):
                water_point(header)

        # Truncated payload body by 1 byte
        with self.assertRaises(ProtocolError):
            water_point(valid_payload[:-1])

        # Trailing bytes
        with self.assertRaises(ProtocolError):
            water_point(valid_payload + b"\x00")

        # Non-bytes input
        for invalid in [None, 12345, "invalid", [1, 2, 3]]:
            with self.assertRaises(ProtocolError):
                water_point(invalid)  # type: ignore


if __name__ == "__main__":
    unittest.main()
