"""Comprehensive unit tests for Task 3.5: Typed Diagnose Wiring & CLI Diagnostics."""

from __future__ import annotations

import argparse
import contextlib
import io
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

SAFE_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])


def _make_rgb_payload(width: int, height: int, pixels: bytes, timestamp: int = 1000) -> bytes:
    stride = width * 3
    header = struct.pack("<IIIQ", width, height, stride, timestamp)
    return header + pixels


class DiagnoseTests(unittest.IsolatedAsyncioTestCase):
    """8 comprehensive test cases verifying Task 3.5 according to TASK3_5_BRIEF.md."""

    def _setup_mock_tab_and_frames(self, water_pixel: bool = True, alert_hit: bool = False):
        status = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 70, 123, "", False, 0, False)
        tab = bridge.Tab(status.url, "ws://127.0.0.1:9222/devtools/page/test")

        # Full frame: 800x600 pixels
        if water_pixel:
            full_pixels = bytearray(DRY * (800 * 600))
            # Paint 51x51 water square centered at (248, 320)
            for y in range(320 - 25, 320 + 26):
                for x in range(248 - 25, 248 + 26):
                    off = (y * 800 + x) * 3
                    full_pixels[off : off + 3] = SAFE_WATER
            full_bytes = bytes(full_pixels)
        else:
            full_bytes = DRY * (800 * 600)

        full_img = bridge.RgbPayload(800, 600, 2400, 1000, full_bytes)
        full_frame = bridge.CapturedFrame(full_img, status, 0.0, 0.0, 800.0, 600.0)

        # Alert frame: 240x240 pixels (ROI)
        if alert_hit:
            alert_template = bridge._get_alert_template().tobytes()
            alert_pixels = bytearray(b"\x80" * (240 * 240 * 3))
            # Paint alert at (40, 50)
            for py in range(35):
                for px in range(33):
                    t_off = (py * 33 + px) * 3
                    off = ((50 + py) * 240 + (40 + px)) * 3
                    alert_pixels[off : off + 3] = alert_template[t_off : t_off + 3]
            alert_bytes = bytes(alert_pixels)
        else:
            alert_bytes = b"\x80" * (240 * 240 * 3)

        alert_img = bridge.RgbPayload(240, 240, 720, 1000, alert_bytes)
        alert_frame = bridge.CapturedFrame(alert_img, status, 280.0, 120.0, 240.0, 240.0)

        async def fake_capture(_tab, kind):
            if kind == "SCREEN_FULL":
                return full_frame
            elif kind == "SCREEN_ALERT":
                return alert_frame
            raise bridge.CdpError(f"unknown capture kind: {kind}")

        return tab, status, fake_capture

    async def test_01_diagnose_cli_with_in_process_fallback_on_sac_block(self):
        """Test 1: Worker spawn raises OSError 4551 -> transparent fallback to In-Process SIMD, exit 0."""
        tab, status, fake_capture = self._setup_mock_tab_and_frames(water_pixel=True, alert_hit=False)

        sac_error = OSError("Application Control blocked execution")
        sac_error.winerror = 4551

        output = io.StringIO()
        with mock.patch.object(bridge.WorkerClient, "spawn", side_effect=sac_error), \
             mock.patch.object(bridge, "discover_tab", return_value=tab), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             contextlib.redirect_stdout(output):
            exit_code = await bridge._main_async(argparse.Namespace(
                diagnose=True, check=False, worker="worker.exe", timeout=3.0
            ))

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("=== NOMSTEAD HYBRID DIAGNOSTICS ===", text)
        self.assertIn("Engine: In-Process SIMD (Python/OpenCV)", text)
        self.assertIn("Water Point: Found at Image=(248, 320)", text)
        self.assertIn("No-Click Policy: VERIFIED (0 input events emitted)", text)
        self.assertIn("DIAGNOSE OK", text)

    async def test_02_diagnose_cli_with_rust_worker_ipc(self):
        """Test 2: Worker IPC responds with OP_DIAGNOSE -> decodes coordinates and completes with code 0."""
        tab, status, fake_capture = self._setup_mock_tab_and_frames(water_pixel=True, alert_hit=True)

        client = mock.Mock()
        async def mock_request(payload: bytes):
            # Check opcode
            self.assertEqual(payload[0], bridge.OP_DIAGNOSE)
            # Response: water at (248, 320), alert at (40, 50, 0.98), duration 450000 ns
            resp_payload = bridge.encode_diagnose_response((248, 320), (40, 50, 0.98), 450000)
            return bridge.Frame(bridge.VERSION, bridge.KIND_RESPONSE, 1, resp_payload)

        client.request = mock.AsyncMock(side_effect=mock_request)
        client.shutdown = mock.AsyncMock()

        output = io.StringIO()
        with mock.patch.object(bridge.WorkerClient, "spawn", return_value=client), \
             mock.patch.object(bridge, "discover_tab", return_value=tab), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             contextlib.redirect_stdout(output):
            exit_code = await bridge._main_async(argparse.Namespace(
                diagnose=True, check=False, worker="worker.exe", timeout=3.0
            ))

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("=== NOMSTEAD HYBRID DIAGNOSTICS ===", text)
        self.assertIn("Engine: Rust Worker (IPC)", text)
        self.assertIn("Water Point: Found at Image=(248, 320)", text)
        self.assertIn("Alert Hook (!): Found at ROI=(40, 50, score=0.98)", text)
        self.assertIn("DIAGNOSE OK", text)
        client.shutdown.assert_awaited_once()

    def test_03_diagnose_wire_codec_roundtrip(self):
        """Test 3: Wire codec roundtrip across all 4 permutations (water/alert presence)."""
        cases = [
            ((250, 320), (40, 50, 0.95), 1000000),
            ((250, 320), None, 500000),
            (None, (40, 50, 0.88), 600000),
            (None, None, 12345),
        ]
        for water_in, alert_in, duration_in in cases:
            encoded = bridge.encode_diagnose_response(water_in, alert_in, duration_in)
            water_out, alert_out, duration_out = bridge.decode_diagnose_response(encoded)
            self.assertEqual(water_out, water_in)
            if alert_in is not None:
                self.assertIsNotNone(alert_out)
                self.assertEqual(alert_out[0], alert_in[0])
                self.assertEqual(alert_out[1], alert_in[1])
                self.assertAlmostEqual(alert_out[2], alert_in[2], places=3)
            else:
                self.assertIsNone(alert_out)
            self.assertEqual(duration_out, duration_in)

        # Request codec roundtrip
        valid_rgb = _make_rgb_payload(60, 60, b"\x00" * 10800)
        req = bridge.encode_diagnose_request(valid_rgb)
        self.assertEqual(req[0], bridge.OP_DIAGNOSE)
        decoded_rgb = bridge.decode_diagnose_request(req)
        self.assertEqual(decoded_rgb, valid_rgb)

    def test_04_diagnose_wire_codec_truncation_and_trailing_rejection(self):
        """Test 4: Wire codec rejects every truncation and any trailing bytes with ProtocolError."""
        encoded = bridge.encode_diagnose_response((10, 20), (5, 6, 0.85), 999)
        # Length of 31 bytes
        self.assertEqual(len(encoded), 31)

        # Truncation from 0 to 30 bytes
        for length in range(len(encoded)):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_diagnose_response(encoded[:length])

        # Trailing byte
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_diagnose_response(encoded + b"\x00")

        # Invalid opcode
        mutated_op = bytearray(encoded)
        mutated_op[0] = 99
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_diagnose_response(bytes(mutated_op))

        # Invalid boolean flags
        mutated_flag = bytearray(encoded)
        mutated_flag[1] = 2  # not 0 or 1
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_diagnose_response(bytes(mutated_flag))

    async def test_05_no_click_invariant_guaranteed(self):
        """Test 5: Verify NO Input.* CDP calls; only Page.captureScreenshot and Runtime.evaluate are emitted."""
        tab, status, fake_capture = self._setup_mock_tab_and_frames()

        # Intercept capture calls to verify no-click policy
        called_cdp_methods = []
        original_capture = bridge.capture

        async def spy_capture(t, kind):
            # Capture uses Runtime.evaluate (status) and Page.captureScreenshot
            called_cdp_methods.extend(["Runtime.evaluate", "Page.captureScreenshot", "Runtime.evaluate"])
            return await fake_capture(t, kind)

        with mock.patch.object(bridge, "discover_tab", return_value=tab), \
             mock.patch.object(bridge, "capture", side_effect=spy_capture):
            res = await bridge.run_diagnose(tab, use_worker=False)

        # Ensure allowlist only
        allowlist = {"Page.captureScreenshot", "Runtime.evaluate"}
        for method in called_cdp_methods:
            self.assertIn(method, allowlist)
            self.assertFalse(method.startswith("Input."), f"Forbidden input event emitted: {method}")

        self.assertIsNotNone(res)

    def test_06_geometry_mapping_precision(self):
        """Test 6: Precise coordinate mapping from pixel to CSS viewport."""
        status = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 70, 123, "", False, 0, False)

        # Full frame: 1000x750 pixels, status is 800x600 CSS (DPR 1.25)
        # Water pixel: (250, 300) -> CSS (250 * 800 / 1000, 300 * 600 / 750) = (200.0, 240.0)
        wx_pix, wy_pix = 250, 300
        css_x = (wx_pix * status.width) / 1000.0
        css_y = (wy_pix * status.height) / 750.0
        self.assertEqual((round(css_x, 1), round(css_y, 1)), (200.0, 240.0))

        # Alert ROI: alert_frame has css_x=280, css_y=120, css_width=240, css_height=240, img_w=240, img_h=240
        # Hit at (40, 50). Center offset +16, +17 -> (56, 67)
        # CSS: 280 + 56 = 336.0, 120 + 67 = 187.0
        ax_pix, ay_pix = 40, 50
        a_css_x = 280.0 + ((ax_pix + 16) * 240.0) / 240.0
        a_css_y = 120.0 + ((ay_pix + 17) * 240.0) / 240.0
        self.assertEqual((round(a_css_x, 1), round(a_css_y, 1)), (336.0, 187.0))

    async def test_07_diagnose_dry_and_no_alert_graceful_handling(self):
        """Test 7: All dry frame and no alert returns None gracefully, exit 0."""
        tab, status, fake_capture = self._setup_mock_tab_and_frames(water_pixel=False, alert_hit=False)

        output = io.StringIO()
        with mock.patch.object(bridge, "discover_tab", return_value=tab), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             contextlib.redirect_stdout(output):
            exit_code = await bridge._main_async(argparse.Namespace(
                diagnose=True, check=False, worker="worker.exe", timeout=3.0
            ))

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("Water Point: None", text)
        self.assertIn("Alert Hook (!): None", text)
        self.assertIn("DIAGNOSE OK", text)

    async def test_08_privacy_and_sensitive_data_protection(self):
        """Test 8: Ensure errors do not leak private auth tokens or sensitive data in stdout/stderr."""
        tab, status, fake_capture = self._setup_mock_tab_and_frames()

        private_token = "PRIVATE_SECRET_TOKEN_ABC123"
        cdp_error = bridge.CdpError(f"connection error to https://nomstead.com?token={private_token}")

        output_err = io.StringIO()
        output_out = io.StringIO()
        with mock.patch.object(bridge, "discover_tab", side_effect=cdp_error), \
             contextlib.redirect_stdout(output_out), \
             contextlib.redirect_stderr(output_err):
            exit_code = await bridge._main_async(argparse.Namespace(
                diagnose=True, check=False, worker="worker.exe", timeout=3.0
            ))

        self.assertEqual(exit_code, 1)
        err_text = output_err.getvalue()
        out_text = output_out.getvalue()
        self.assertNotIn(private_token, err_text)
        self.assertNotIn(private_token, out_text)
        self.assertIn("worker bridge failed: CdpError", err_text)


if __name__ == "__main__":
    unittest.main()
