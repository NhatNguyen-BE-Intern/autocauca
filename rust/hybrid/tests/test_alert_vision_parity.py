"""Independent parity unit tests for alert vision algorithm (NCC & Double Verification).

Verifies 1:1 algorithmic parity between Python SIMD implementation (cv2/NumPy)
and Rust std-only implementation in rust/hybrid/worker_vision.rs.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import (
    AlertHit,
    ProtocolError,
    RgbPayload,
    alert_point,
)

ALERT_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "assets" / "alert.rgb"
ALERT_TEMPLATE_BYTES = ALERT_TEMPLATE_PATH.read_bytes()
ALERT_TEMPLATE_ARR = np.frombuffer(ALERT_TEMPLATE_BYTES, dtype=np.uint8).reshape((35, 33, 3))


def _make_payload(width: int, height: int, pixels: bytes, timestamp: int = 0) -> bytes:
    stride = width * 3
    header = struct.pack("<IIIQ", width, height, stride, timestamp)
    return header + pixels


def _paint_alert(pixels: bytearray, width: int, x: int, y: int, patch: bytes = ALERT_TEMPLATE_BYTES) -> None:
    for py in range(35):
        for px in range(33):
            t_off = (py * 33 + px) * 3
            img_off = ((y + py) * width + (x + px)) * 3
            pixels[img_off : img_off + 3] = patch[t_off : t_off + 3]


class AlertVisionParityTests(unittest.TestCase):
    """Test suite verifying 1:1 parity with tests/worker_tests.rs alert vision."""

    def test_01_exact_template_match_on_flat_background(self) -> None:
        """Test 1: Exact alert template at (10, 20) on flat background returns score > 0.999."""
        width, height = 60, 60
        pixels = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels, width, 10, 20)
        payload = _make_payload(width, height, bytes(pixels))

        hit = alert_point(payload)
        self.assertIsNotNone(hit)
        self.assertEqual((hit.x, hit.y), (10, 20))
        self.assertGreater(hit.score, 0.999)

        # Direct RgbPayload object overload
        rgb_obj = RgbPayload(width, height, width * 3, 0, bytes(pixels))
        hit_obj = alert_point(rgb_obj)
        self.assertEqual(hit_obj, hit)

    def test_02_zero_variance_frame_returns_none(self) -> None:
        """Test 2: All black or all white frame returns None without division by zero."""
        for fill in (0, 255):
            pixels = bytes([fill] * (50 * 50 * 3))
            payload = _make_payload(50, 50, pixels)
            self.assertIsNone(alert_point(payload))

    def test_03_undersized_dimensions_rejected(self) -> None:
        """Test 3: Images smaller than template 33x35 return None."""
        for width, height in [(32, 35), (33, 34), (10, 10), (32, 32)]:
            pixels = bytes([128] * (width * height * 3))
            payload = _make_payload(width, height, pixels)
            self.assertIsNone(alert_point(payload))

    def test_04_high_confidence_returns_hit_regardless_of_baseline(self) -> None:
        """Test 4: High confidence (score >= 0.80) returns AlertHit with or without baseline."""
        width, height = 50, 50
        pixels = bytearray(b"\x40" * (width * height * 3))
        _paint_alert(pixels, width, 5, 5)
        payload = _make_payload(width, height, bytes(pixels))

        # Without baseline
        hit_no_base = alert_point(payload)
        self.assertIsNotNone(hit_no_base)
        self.assertEqual((hit_no_base.x, hit_no_base.y), (5, 5))
        self.assertGreaterEqual(hit_no_base.score, 0.80)

        # With baseline (even if identical, high confidence bypasses double verification)
        base_payload = _make_payload(width, height, bytes(pixels))
        hit_with_base = alert_point(payload, baseline=base_payload)
        self.assertIsNotNone(hit_with_base)
        self.assertEqual((hit_with_base.x, hit_with_base.y), (5, 5))

    def test_05_sub_threshold_returns_none(self) -> None:
        """Test 5: Sub-threshold (score < 0.60) returns None."""
        width, height = 40, 40
        # Background without alert template has score near 0 or < 0.60
        pixels = bytes([200] * (width * height * 3))
        payload = _make_payload(width, height, pixels)
        self.assertIsNone(alert_point(payload))

    def test_06_fallback_no_baseline_threshold_gate(self) -> None:
        """Test 6: In questionable range [0.60, 0.80) without baseline: score >= 0.74 accepted, < 0.74 rejected."""
        np.random.seed(42)
        noise = np.random.randint(0, 256, (35, 33, 3), dtype=np.uint8)

        # alpha=0.78 produces score ~0.764 (in [0.74, 0.80))
        patch_76 = cv2.addWeighted(ALERT_TEMPLATE_ARR, 0.78, noise, 0.22, 0)
        width, height = 50, 50
        pixels_76 = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels_76, width, 5, 5, patch_76.tobytes())
        payload_76 = _make_payload(width, height, bytes(pixels_76))

        hit_76 = alert_point(payload_76)
        self.assertIsNotNone(hit_76, "Score in [0.74, 0.80) without baseline must be accepted")
        self.assertEqual((hit_76.x, hit_76.y), (5, 5))
        self.assertGreaterEqual(hit_76.score, 0.74)
        self.assertLess(hit_76.score, 0.80)

        # Mismatched baseline dimensions also fall back to no-baseline logic
        mismatched_base = _make_payload(40, 50, b"\x00" * (40 * 50 * 3))
        hit_mismatched = alert_point(payload_76, baseline=mismatched_base)
        self.assertEqual(hit_mismatched, hit_76)

        # alpha=0.76 produces score ~0.727 (in [0.60, 0.74))
        patch_72 = cv2.addWeighted(ALERT_TEMPLATE_ARR, 0.76, noise, 0.24, 0)
        pixels_72 = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels_72, width, 5, 5, patch_72.tobytes())
        payload_72 = _make_payload(width, height, bytes(pixels_72))

        self.assertIsNone(alert_point(payload_72), "Score < 0.74 without baseline must be rejected")

    def test_07_double_verification_with_baseline(self) -> None:
        """Test 7: Score in [0.60, 0.74) verified against baseline: requires diff >= 18.0 and dark >= 0.05."""
        np.random.seed(42)
        noise = np.random.randint(0, 256, (35, 33, 3), dtype=np.uint8)

        dark_tpl = (ALERT_TEMPLATE_ARR[:, :, 0] < 45) & (ALERT_TEMPLATE_ARR[:, :, 1] < 45) & (ALERT_TEMPLATE_ARR[:, :, 2] < 45)
        # alpha=0.62 with restored dark pixels gives score ~0.688
        patch = cv2.addWeighted(ALERT_TEMPLATE_ARR, 0.62, noise, 0.38, 0)
        patch[dark_tpl] = ALERT_TEMPLATE_ARR[dark_tpl]

        width, height = 50, 50
        pixels = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels, width, 5, 5, patch.tobytes())
        payload = _make_payload(width, height, bytes(pixels))

        # Baseline: white background (200, 200, 200) -> diff ~116 >= 18.0 and dark_ratio ~0.17 >= 0.05
        base_pixels = bytes([200] * (width * height * 3))
        base_payload = _make_payload(width, height, base_pixels)

        hit = alert_point(payload, baseline=base_payload)
        self.assertIsNotNone(hit, "Valid baseline with diff >= 18.0 and dark >= 0.05 must be accepted")
        self.assertEqual((hit.x, hit.y), (5, 5))

        # Condition A failure: diff < 18.0 (baseline identical to image patch)
        self.assertIsNone(alert_point(payload, baseline=payload), "Diff < 18.0 must be rejected")

        # Condition B failure: dark_ratio < 0.05 (dark pixels brightened above 45)
        bright_patch = patch.copy()
        bright_dark = (bright_patch[:, :, 0] < 45) & (bright_patch[:, :, 1] < 45) & (bright_patch[:, :, 2] < 45)
        bright_patch[bright_dark] = 50
        pixels_bright = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels_bright, width, 5, 5, bright_patch.tobytes())
        payload_bright = _make_payload(width, height, bytes(pixels_bright))

        self.assertIsNone(alert_point(payload_bright, baseline=base_payload), "dark_ratio < 0.05 must be rejected")

    def test_08_row_major_tie_breaking_and_payload_protection(self) -> None:
        """Test 8: Row-major tie breaking and protocol error handling on malformed payloads."""
        width, height = 80, 100
        # Case A: Two identical alert templates at (5, 10) and (40, 55) -> (5, 10) chosen (earlier row)
        pixels_a = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels_a, width, 5, 10)
        _paint_alert(pixels_a, width, 40, 55)
        hit_a = alert_point(_make_payload(width, height, bytes(pixels_a)))
        self.assertIsNotNone(hit_a)
        self.assertEqual((hit_a.x, hit_a.y), (5, 10))

        # Case B: Two identical alert templates on same row at (5, 10) and (40, 10) -> (5, 10) chosen (smaller x)
        pixels_b = bytearray(b"\x80" * (width * height * 3))
        _paint_alert(pixels_b, width, 40, 10)
        _paint_alert(pixels_b, width, 5, 10)
        hit_b = alert_point(_make_payload(width, height, bytes(pixels_b)))
        self.assertIsNotNone(hit_b)
        self.assertEqual((hit_b.x, hit_b.y), (5, 10))

        # Protocol error protection
        valid_payload = _make_payload(40, 40, b"\x00" * (40 * 40 * 3))
        # Truncated headers (0..19 bytes)
        for length in range(20):
            with self.assertRaises(ProtocolError):
                alert_point(valid_payload[:length])

        # Dimension / stride errors
        for w, h, s in [(0, 40, 0), (40, 0, 120), (8193, 1, 24579), (40, 40, 119)]:
            header = struct.pack("<IIIQ", w, h, s, 0)
            with self.assertRaises(ProtocolError):
                alert_point(header)

        # Truncated body and trailing bytes
        with self.assertRaises(ProtocolError):
            alert_point(valid_payload[:-1])
        with self.assertRaises(ProtocolError):
            alert_point(valid_payload + b"\x00")

        # Invalid baseline type
        for bad_base in (12345, "string", [1, 2, 3]):
            with self.assertRaises(ProtocolError):
                alert_point(valid_payload, baseline=bad_base)  # type: ignore


if __name__ == "__main__":
    unittest.main()
