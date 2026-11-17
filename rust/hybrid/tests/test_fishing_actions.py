"""10 comprehensive unit tests for Task 6.2: 4-Step Fishing Cycle (Steps 5 -> 8)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

SAFE_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])


def _default_status(w: float = 800.0, h: float = 600.0, energy: int | None = 70, xp: int | None = 100, toast: str = "") -> bridge.Status:
    return bridge.Status("https://nomstead.com/play", w, h, 1.25, energy, xp, toast, False, 0, False)


def _make_water_frame(width: int = 800, height: int = 600, status: bridge.Status = None) -> bridge.CapturedFrame:
    if status is None:
        status = _default_status(float(width), float(height))
    full_pixels = bytearray(DRY * (width * height))
    for y in range(320 - 25, 320 + 26):
        for x in range(248 - 25, 248 + 26):
            off = (y * width + x) * 3
            full_pixels[off : off + 3] = SAFE_WATER
    img = bridge.RgbPayload(width, height, width * 3, 1000, bytes(full_pixels))
    return bridge.CapturedFrame(img, status, 0.0, 0.0, float(width), float(height))


def _make_alert_frame(hit: bool = False, status: bridge.Status = None) -> bridge.CapturedFrame:
    w, h = 240, 240
    if status is None:
        status = _default_status(float(w), float(h))
    if hit:
        template = bridge._get_alert_template().tobytes()
        pixels = bytearray(b"\x80" * (w * h * 3))
        for py in range(35):
            for px in range(33):
                t_off = (py * 33 + px) * 3
                off = ((50 + py) * w + (40 + px)) * 3
                pixels[off : off + 3] = template[t_off : t_off + 3]
        payload = bytes(pixels)
    else:
        payload = b"\x80" * (w * h * 3)
    img = bridge.RgbPayload(w, h, w * 3, 1000, payload)
    return bridge.CapturedFrame(img, status, 280.0, 120.0, float(w), float(h))


class FishingActionsTests(unittest.IsolatedAsyncioTestCase):
    """10 unit tests for Task 6.2 according to TASK6_2_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    async def test_01_water_detection_and_cast_coordinates(self):
        """Test 1: Detects water safe spot and dispatches click_cast with exact CSS coordinates (248.0, 320.0)."""
        tab = self._setup_mock_tab()
        status = _default_status(800.0, 600.0)
        water_frame = _make_water_frame(800, 600, status)

        mock_cast = mock.AsyncMock(return_value=bridge.ClickResult(248.0, 320.0, True, True, 100, 150, 50.0))

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return _make_alert_frame(hit=False, status=status)

        with mock.patch.object(bridge, "read_status", return_value=status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock_cast), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=0.05,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        self.assertEqual(outcome.cast_x, 248.0)
        self.assertEqual(outcome.cast_y, 320.0)
        mock_cast.assert_awaited_once_with(tab, 248.0, 320.0, status)

    async def test_02_alert_detection_and_instant_strike(self):
        """Test 2: Detects alert template and executes immediate click_strike with finite reaction_ms."""
        tab = self._setup_mock_tab()
        status = _default_status(800.0, 600.0)
        water_frame = _make_water_frame(800, 600, status)
        baseline_frame = _make_alert_frame(hit=False, status=status)
        alert_hit_frame = _make_alert_frame(hit=True, status=status)

        poll_count = 0

        async def fake_capture(_t, kind):
            nonlocal poll_count
            if kind == "SCREEN_FULL":
                return water_frame
            poll_count += 1
            if poll_count <= 2:
                return baseline_frame
            return alert_hit_frame

        mock_strike = mock.AsyncMock(return_value=bridge.ClickResult(248.0, 320.0, True, True, 200, 240, 40.0))

        with mock.patch.object(bridge, "read_status", return_value=status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock_strike), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=2.0,
                poll_interval_sec=0.001,
                reel_wait_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
            )

        mock_strike.assert_awaited_once()
        self.assertIsNotNone(outcome.reaction_ms)
        self.assertGreaterEqual(outcome.reaction_ms, 0.0)

    def test_03_verified_catch_with_and_i_got_banner(self):
        """Test 3: Confirms verified catch when toast contains 'and I got'."""
        outcome = bridge.Outcome(
            kind="CATCH",
            toast="and I got a Large Trout!",
            pre_energy=70,
            post_energy=69,
            pre_xp=100,
            post_xp=100,
        )
        self.assertTrue(bridge.is_verified_catch(outcome))
        self.assertEqual(outcome.kind, "CATCH")

    def test_04_verified_catch_with_caught_or_collected_banner(self):
        """Test 4: Confirms verified catch when toast contains 'caught' or 'collected'."""
        outcome1 = bridge.Outcome(
            kind="CATCH",
            toast="You caught a common carp!",
            pre_energy=70,
            post_energy=69,
        )
        self.assertTrue(bridge.is_verified_catch(outcome1))

        outcome2 = bridge.Outcome(
            kind="CATCH",
            toast="Collected 1 Salmon",
            pre_energy=70,
            post_energy=69,
        )
        self.assertTrue(bridge.is_verified_catch(outcome2))

    def test_05_verified_catch_with_xp_increase(self):
        """Test 5: Confirms verified catch when XP increases (pre: 1200 -> post: 1250) without toast."""
        outcome = bridge.Outcome(
            kind="CATCH",
            toast="",
            pre_xp=1200,
            post_xp=1250,
            pre_energy=70,
            post_energy=69,
        )
        self.assertTrue(bridge.is_verified_catch(outcome))

    def test_06_miss_outcome_when_no_catch_banner_and_no_xp(self):
        """Test 6: Classified as miss (is_verified_catch is False) when energy drops but no catch banner and no XP."""
        outcome = bridge.Outcome(
            kind="CATCH",
            toast="",
            pre_energy=70,
            post_energy=69,
            pre_xp=100,
            post_xp=100,
        )
        self.assertFalse(bridge.is_verified_catch(outcome))

    async def test_07_fast_empty_detection_under_one_second(self):
        """Test 7: Toast 'There is nothing left in this pond. Come back later!' exits immediately as EMPTY (<0.5s)."""
        tab = self._setup_mock_tab()
        status_empty = _default_status(800.0, 600.0, toast="There is nothing left in this pond. Come back later!")
        water_frame = _make_water_frame(800, 600, status_empty)

        # Status immediately returns empty toast after cast
        call_count = 0

        async def fake_read_status(_t):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _default_status(800.0, 600.0)
            return status_empty

        t0 = time.monotonic()
        with mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
             mock.patch.object(bridge, "capture", return_value=water_frame), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(tab, max_alert_wait_sec=11.0)
        t_elapsed = time.monotonic() - t0

        self.assertEqual(outcome.kind, "EMPTY")
        self.assertLess(t_elapsed, 0.5)

    async def test_08_fast_trash_detection_under_one_second(self):
        """Test 8: Toast 'You pulled up some trash. The pond needs time to restock.' exits as TRASH in <0.5s."""
        tab = self._setup_mock_tab()
        status_normal = _default_status(800.0, 600.0)
        status_trash = _default_status(800.0, 600.0, toast="You pulled up some trash. The pond needs time to restock.")
        water_frame = _make_water_frame(800, 600, status_normal)
        alert_hit_frame = _make_alert_frame(hit=True, status=status_normal)

        status_calls = [status_normal, status_normal, status_trash]

        async def fake_read_status(_t):
            if status_calls:
                return status_calls.pop(0)
            return status_trash

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_hit_frame

        t0 = time.monotonic()
        with mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(tab, max_alert_wait_sec=5.0, reel_wait_sec=0.01)
        t_elapsed = time.monotonic() - t0

        self.assertEqual(outcome.kind, "TRASH")
        self.assertLess(t_elapsed, 0.5)

    async def test_09_terminal_logging_format_catch_and_miss(self):
        """Test 9: Captures terminal logging for verified CATCH and MISS in run_auto_session."""
        tab = self._setup_mock_tab()
        status_ok = _default_status(800.0, 600.0, energy=50)

        # 1. Verified Catch
        verified_catch_outcome = bridge.Outcome(
            kind="CATCH",
            toast="and I got a Large Trout!",
            pre_energy=50,
            post_energy=49,
            pre_xp=100,
            post_xp=105,
            reaction_ms=18.5,
        )
        stop_event = asyncio.Event()

        async def fake_cast_catch(_t, **_kw):
            stop_event.set()
            return verified_catch_outcome

        output_catch = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=3, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_catch), \
                 contextlib.redirect_stdout(output_catch):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        log_catch = output_catch.getvalue()
        self.assertIn("🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO 3", log_catch)

        # 2. Miss (unverified catch without banner / XP)
        miss_outcome = bridge.Outcome(
            kind="CATCH",
            toast="",
            pre_energy=50,
            post_energy=49,
            pre_xp=100,
            post_xp=100,
            reaction_ms=22.0,
        )
        stop_event_miss = asyncio.Event()

        async def fake_cast_miss(_t, **_kw):
            stop_event_miss.set()
            return miss_outcome

        output_miss = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=3, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_miss), \
                 contextlib.redirect_stdout(output_miss):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event_miss)

        log_miss = output_miss.getvalue()
        self.assertIn("❌ Giật hụt cá (Miss) tại HO 3", log_miss)

    async def test_10_terminal_logging_format_empty_and_trash(self):
        """Test 10: Captures terminal logging for EMPTY and TRASH in run_auto_session."""
        tab = self._setup_mock_tab()
        status_ok = _default_status(800.0, 600.0, energy=50)

        # 1. EMPTY outcome
        empty_outcome = bridge.Outcome(kind="EMPTY")
        stop_event_empty = asyncio.Event()

        async def fake_cast_empty(_t, **_kw):
            stop_event_empty.set()
            return empty_outcome

        output_empty = io.StringIO()
        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=4, attempts=1, duration_sec=0.5))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=3, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_empty), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 contextlib.redirect_stdout(output_empty):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event_empty)

        log_empty = output_empty.getvalue()
        self.assertIn("Hồ đã hết cá (EMPTY) -> Đang chuyển sang HO 4...", log_empty)

        # 2. TRASH outcome
        trash_outcome = bridge.Outcome(kind="TRASH")
        stop_event_trash = asyncio.Event()

        async def fake_cast_trash(_t, **_kw):
            stop_event_trash.set()
            return trash_outcome

        output_trash = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=3, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_trash), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 contextlib.redirect_stdout(output_trash):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event_trash)

        log_trash = output_trash.getvalue()
        self.assertIn("Câu phải rác (TRASH) -> Đang chuyển sang HO 4...", log_trash)


if __name__ == "__main__":
    unittest.main()
