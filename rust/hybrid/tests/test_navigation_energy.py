"""Comprehensive unit tests for Task 5.1: Bread Recovery & Lake Navigation Primitives.

Tests verify:
1. eat_bread success recovers energy (15 -> 40, recovered: 25).
2. eat_bread skips when energy is full (>= 75) without clicks.
3. eat_bread handles no bread found in ROI (0 clicks).
4. travel_to_lake success on first attempt (finds HO 12, clicks fast travel, modal closes, water verified).
5. travel_to_lake retries on initial failure and succeeds on attempt 2.
6. travel_to_lake rejects out-of-bounds lake numbers (0, 41) with ValueError.
7. travel_to_lake cleans up stuck modal after max retries.
8. Origin safety gate rejects untrusted URLs with ActionPreconditionError (0 clicks).
9. Wire codecs for OP_EAT_BREAD (5) and OP_TRAVEL_LAKE (6) with bounds and truncation rejection.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

SAFE_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])


def _make_frame_with_bread(width: int = 800, height: int = 600, status: bridge.Status = None) -> bridge.CapturedFrame:
    if status is None:
        status = bridge.Status("https://nomstead.com/play", float(width), float(height), 1.25, 15, 123, "", False, 0, False)
    pixels = bytearray(DRY * (width * height))
    bread_tmpl = bridge._get_bread_template().tobytes()
    # Paint bread template in bottom 30% ROI at (x=300, y=500)
    for py in range(33):
        for px in range(43):
            t_off = (py * 43 + px) * 3
            off = ((500 + py) * width + (300 + px)) * 3
            pixels[off : off + 3] = bread_tmpl[t_off : t_off + 3]
    img = bridge.RgbPayload(width, height, width * 3, 1000, bytes(pixels))
    return bridge.CapturedFrame(img, status, 0.0, 0.0, float(width), float(height))


def _make_frame_no_bread(width: int = 800, height: int = 600, status: bridge.Status = None) -> bridge.CapturedFrame:
    if status is None:
        status = bridge.Status("https://nomstead.com/play", float(width), float(height), 1.25, 15, 123, "", False, 0, False)
    img = bridge.RgbPayload(width, height, width * 3, 1000, DRY * (width * height))
    return bridge.CapturedFrame(img, status, 0.0, 0.0, float(width), float(height))


def _make_water_frame(width: int = 800, height: int = 600, status: bridge.Status = None) -> bridge.CapturedFrame:
    if status is None:
        status = bridge.Status("https://nomstead.com/play", float(width), float(height), 1.25, 70, 123, "", False, 0, False)
    pixels = bytearray(DRY * (width * height))
    for y in range(320 - 25, 320 + 26):
        for x in range(248 - 25, 248 + 26):
            off = (y * width + x) * 3
            pixels[off : off + 3] = SAFE_WATER
    img = bridge.RgbPayload(width, height, width * 3, 1000, bytes(pixels))
    return bridge.CapturedFrame(img, status, 0.0, 0.0, float(width), float(height))


class NavigationEnergyTests(unittest.IsolatedAsyncioTestCase):
    """9 comprehensive test cases for Task 5.1 according to TASK5_1_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    def _setup_status(
        self,
        energy: int | None = 15,
        modal: bool = False,
        toast: str = "",
        width: float = 800.0,
        height: float = 600.0,
    ) -> bridge.Status:
        return bridge.Status(
            url="https://nomstead.com/play",
            width=width,
            height=height,
            dpr=1.25,
            energy=energy,
            xp=123,
            toast=toast,
            sequence_available=False,
            sequence=0,
            modal=modal,
        )

    async def test_01_eat_bread_success_recovers_energy(self):
        """Test 1: Energy 15 recovers to 40 after eating bread (recovered: 25)."""
        tab = self._setup_mock_tab()
        pre_st = self._setup_status(energy=15)
        post_st = self._setup_status(energy=40)
        frame_bread = _make_frame_with_bread(800, 600, pre_st)

        status_calls = [pre_st, post_st]
        mock_click = mock.AsyncMock(return_value=bridge.ClickResult(321.5, 516.5, True, True, 100, 150, 50.0))

        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls.pop(0)), \
             mock.patch.object(bridge, "capture", return_value=frame_bread), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.eat_bread(tab)

        self.assertTrue(res.consumed)
        self.assertEqual(res.pre_energy, 15)
        self.assertEqual(res.post_energy, 40)
        self.assertEqual(res.recovered, 25)
        self.assertEqual(res.reason, "SUCCESS")
        mock_click.assert_awaited_once()

    async def test_02_eat_bread_skips_when_energy_full(self):
        """Test 2: Energy >= 75 skips eating without any clicks."""
        tab = self._setup_mock_tab()
        status_full = self._setup_status(energy=80)
        mock_click = mock.AsyncMock()

        with mock.patch.object(bridge, "read_status", return_value=status_full), \
             mock.patch.object(bridge, "click_point", mock_click):
            res = await bridge.eat_bread(tab, force=False)

        self.assertFalse(res.consumed)
        self.assertEqual(res.reason, "ENERGY_FULL")
        mock_click.assert_not_called()

    async def test_03_eat_bread_handles_no_bread_found(self):
        """Test 3: No bread in ROI and no quickslot returns NO_BREAD_FOUND with 0 clicks."""
        tab = self._setup_mock_tab()
        pre_st = self._setup_status(energy=20)
        frame_empty = _make_frame_no_bread(800, 600, pre_st)
        mock_click = mock.AsyncMock()

        with mock.patch.object(bridge, "read_status", return_value=pre_st), \
             mock.patch.object(bridge, "capture", return_value=frame_empty), \
             mock.patch.object(bridge, "click_point", mock_click):
            res = await bridge.eat_bread(tab, quickslot_pos=None)

        self.assertFalse(res.consumed)
        self.assertEqual(res.reason, "NO_BREAD_FOUND")
        mock_click.assert_not_called()

    async def test_04_travel_to_lake_success_first_attempt(self):
        """Test 4: Travel to lake 12 succeeds on first attempt."""
        tab = self._setup_mock_tab()
        status_closed = self._setup_status(modal=False)
        water_frame = _make_water_frame(800, 600, status_closed)

        async def fake_eval(_t, expr):
            if "tiles" in expr:
                return {"found": True, "x": 350.0, "y": 280.0, "url": "/play?lake=12"}
            return {"active": True}

        mock_click = mock.AsyncMock()

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch.object(bridge, "capture", return_value=water_frame), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 12)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 12)
        self.assertEqual(res.attempts, 1)
        self.assertIsNone(res.error)
        mock_click.assert_awaited_once()

    async def test_05_travel_to_lake_retries_on_initial_failure(self):
        """Test 5: Travel to lake 15 retries after initial lag and succeeds on attempt 2."""
        tab = self._setup_mock_tab()
        status_modal_open = self._setup_status(modal=True)
        status_modal_closed = self._setup_status(modal=False)
        water_frame = _make_water_frame(800, 600, status_modal_closed)

        attempt_counter = 0

        async def fake_eval(_t, expr):
            nonlocal attempt_counter
            if "tiles" in expr:
                attempt_counter += 1
                return {"found": True, "x": 350.0, "y": 280.0, "url": "/play?lake=15"}
            return {"active": True}

        status_calls = [status_modal_open, status_modal_closed]

        async def fake_status(_t):
            if status_calls:
                return status_calls.pop(0)
            return status_modal_closed

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", side_effect=fake_status), \
             mock.patch.object(bridge, "capture", return_value=water_frame), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 15, max_retries=3)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 15)
        self.assertEqual(res.attempts, 2)
        self.assertIsNone(res.error)

    async def test_06_travel_to_lake_rejects_out_of_bounds_lake_number(self):
        """Test 6: travel_to_lake rejects target_lake not in [1, 40] with ValueError."""
        tab = self._setup_mock_tab()

        for invalid_lake in (0, -5, 41, 100):
            with self.assertRaises(ValueError):
                await bridge.travel_to_lake(tab, invalid_lake)

        self.assertEqual(tab.ws.send.call_count, 0)

    async def test_07_travel_to_lake_cleans_up_stuck_modal_on_failure(self):
        """Test 7: After 3 failed attempts, cleans up stuck modal and returns failure."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "HO" in expr:
                return {"found": False}
            return {"active": True}

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 22, max_retries=3)

        self.assertFalse(res.success)
        self.assertEqual(res.lake, 22)
        self.assertEqual(res.attempts, 3)
        self.assertIn("Failed to travel to lake 22", res.error)
        # Verify close modal was called
        cleanup_evals = [e for e in eval_calls if ".modal .close" in e]
        self.assertGreaterEqual(len(cleanup_evals), 1)

    async def test_08_origin_safety_gate_rejects_untrusted_urls(self):
        """Test 8: Untrusted URLs are rejected by origin gate for both eat_bread and travel_to_lake."""
        bad_urls = [
            "https://fake.nomstead.com/play",
            "http://nomstead.com/play",
            "https://attacker.com/",
            "https://nomstead.com.evil.com/",
        ]

        for bad_url in bad_urls:
            tab = bridge.Tab(bad_url, "ws://127.0.0.1:9222/devtools/page/test")
            tab.ws = mock.AsyncMock()

            with self.assertRaises(bridge.ActionPreconditionError):
                await bridge.eat_bread(tab)

            with self.assertRaises(bridge.ActionPreconditionError):
                await bridge.travel_to_lake(tab, 5)

            self.assertEqual(tab.ws.send.call_count, 0)

    def test_09_wire_codec_eat_bread_and_travel_lake(self):
        """Test 9: Wire codecs for OP_EAT_BREAD (5) and OP_TRAVEL_LAKE (6)."""
        # 1. Opcode 5: Eat bread request
        req5 = bridge.encode_eat_bread_request()
        self.assertEqual(req5, bytes([bridge.OP_EAT_BREAD]))
        self.assertEqual(bridge.decode_eat_bread_request(req5), bridge.OP_EAT_BREAD)

        # Truncation and invalid opcode
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_eat_bread_request(b"")
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_eat_bread_request(bytes([bridge.OP_EAT_BREAD, 0]))
        with self.assertRaises(bridge.ProtocolError):
            bridge.decode_eat_bread_request(bytes([99]))

        # Opcode 5: Eat bread response
        resp5 = bridge.encode_eat_bread_response(bridge.EAT_BREAD_OK, 25, 800)
        self.assertEqual(len(resp5), 10)
        dec_op, dec_st, dec_rec, dec_dur = bridge.decode_eat_bread_response(resp5)
        self.assertEqual(dec_op, bridge.OP_EAT_BREAD)
        self.assertEqual(dec_st, bridge.EAT_BREAD_OK)
        self.assertEqual(dec_rec, 25)
        self.assertEqual(dec_dur, 800)

        for l in range(len(resp5)):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_eat_bread_response(resp5[:l])

        # 2. Opcode 6: Travel lake request
        req6 = bridge.encode_travel_lake_request(12)
        self.assertEqual(len(req6), 2)
        self.assertEqual(bridge.decode_travel_lake_request(req6), 12)

        # Bounds checking for lake
        with self.assertRaises(bridge.ProtocolError):
            bridge.encode_travel_lake_request(0)
        with self.assertRaises(bridge.ProtocolError):
            bridge.encode_travel_lake_request(41)

        # Opcode 6: Travel lake response
        resp6 = bridge.encode_travel_lake_response(bridge.TRAVEL_LAKE_OK, 12, 1200)
        self.assertEqual(len(resp6), 7)
        dec_op6, dec_st6, dec_lake, dec_dur6 = bridge.decode_travel_lake_response(resp6)
        self.assertEqual(dec_op6, bridge.OP_TRAVEL_LAKE)
        self.assertEqual(dec_st6, bridge.TRAVEL_LAKE_OK)
        self.assertEqual(dec_lake, 12)
        self.assertEqual(dec_dur6, 1200)

        for l in range(len(resp6)):
            with self.assertRaises(bridge.ProtocolError):
                bridge.decode_travel_lake_response(resp6[:l])


if __name__ == "__main__":
    unittest.main()
