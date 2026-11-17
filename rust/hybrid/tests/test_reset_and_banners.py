"""Unit tests for Task 5.3: Fast Empty/Trash Banner Detection & Server Reset Scheduling."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge

SAFE_WATER = bytes([72, 90, 100])
DRY = bytes([200, 30, 5])


def _default_status(w: float = 800.0, h: float = 600.0) -> bridge.Status:
    return bridge.Status("https://nomstead.com/play", w, h, 1.25, 70, 123, "", False, 0, False)


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


class ResetAndBannerTests(unittest.IsolatedAsyncioTestCase):
    """Test suite covering Task 5.3 specifications according to TASK5_3_BRIEF.md."""

    def test_01_classify_toast_empty_variants(self):
        """Test 1: classify_toast accurately classifies all empty toast variants."""
        cases = [
            "There is nothing left in this pond. Come back later!",
            "Nothing left to catch here right now...",
            "This pond has no more fish.",
            "There is nothing left to catch",
            "This lake is empty",
            "Hồ này đã hết cá rồi",
            "Hồ cạn rồi",
            "no fish left",
            "please come back later to fish",
            "The pond needs time to restock",
        ]
        for text in cases:
            self.assertEqual(
                bridge.classify_toast(text),
                "EMPTY",
                f"Failed on text: {text}",
            )

    def test_02_classify_toast_trash_variants(self):
        """Test 2: classify_toast accurately classifies all trash toast variants."""
        cases = [
            "You pulled up some trash. The pond needs time to restock.",
            "I pulled up some trash. Looks like this pond is empty right now.",
            "You caught an old boot (trash).",
            "Câu phải rác rồi!",
            "You pulled up some trash",
            "pulled up trash",
            "found an old boot",
            "an old can (lon)",
            "just some trash",
        ]
        for text in cases:
            self.assertEqual(
                bridge.classify_toast(text),
                "TRASH",
                f"Failed on text: {text}",
            )

    def test_03_classify_toast_catch_variants(self):
        """Test 3: classify_toast accurately classifies catch toast variants."""
        cases = [
            "You caught a common carp!",
            "Fish caught!",
            "And I got a golden fish",
            "And 1 got a bass",
            "Collected 1 salmon",
            "Bắt được cá chép lớn!",
            "You caught a bass",
        ]
        for text in cases:
            self.assertEqual(
                bridge.classify_toast(text),
                "CATCH",
                f"Failed on text: {text}",
            )

    def test_04_classify_toast_empty_or_none(self):
        """Test 4: classify_toast returns None for empty, whitespace, None, or unrelated text."""
        cases = [
            "",
            None,
            "   ",
            "\n\t",
            "Welcome to NomStead!",
            "Game saved successfully.",
            "Random chat message from user123",
        ]
        for val in cases:
            self.assertIsNone(
                bridge.classify_toast(val),
                f"Expected None for: {val!r}",
            )

    def test_05_status_readonly_fallback_selectors(self):
        """Test 5: STATUS_READONLY prioritizes .message-bar then falls back to secondary selectors."""
        self.assertIn(".message-bar", bridge.STATUS_READONLY)
        self.assertIn(".toast", bridge.STATUS_READONLY)
        self.assertIn(".banner", bridge.STATUS_READONLY)
        self.assertIn("div[class*=\"message\"]", bridge.STATUS_READONLY)
        self.assertIn("div[class*=\"toast\"]", bridge.STATUS_READONLY)
        self.assertIn("div[class*=\"banner\"]", bridge.STATUS_READONLY)
        self.assertIn("div[class*=\"alert\"]", bridge.STATUS_READONLY)

    def test_06_is_reset_window(self):
        """Test 6: is_reset_window returns True only during first 15 mins of RESET_HOURS."""
        for hour in bridge.RESET_HOURS:
            # First 15 minutes -> True
            dt_start = datetime(2026, 11, 17, hour, 0, 0)
            dt_mid = datetime(2026, 11, 17, hour, 7, 30)
            dt_edge = datetime(2026, 11, 17, hour, 14, 59)
            self.assertTrue(bridge.is_reset_window(dt_start))
            self.assertTrue(bridge.is_reset_window(dt_mid))
            self.assertTrue(bridge.is_reset_window(dt_edge))

            # Minute 15+ -> False
            dt_after = datetime(2026, 11, 17, hour, 15, 0)
            dt_late = datetime(2026, 11, 17, hour, 45, 0)
            self.assertFalse(bridge.is_reset_window(dt_after))
            self.assertFalse(bridge.is_reset_window(dt_late))

        # Non-reset hours -> False
        non_reset_hours = [0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18, 20, 21, 23]
        for hour in non_reset_hours:
            dt = datetime(2026, 11, 17, hour, 5, 0)
            self.assertFalse(bridge.is_reset_window(dt))

    def test_07_check_server_reset_trigger_lake_gt_1(self):
        """Test 7: check_server_reset returns (True, hour) when lake > 1 in reset window."""
        dt = datetime(2026, 11, 17, 7, 5, 0)  # 07:05 (Hour 7 is in RESET_HOURS)
        should_reset, new_hour = bridge.check_server_reset(current_lake=25, last_reset_hour=None, dt=dt)
        self.assertTrue(should_reset)
        self.assertEqual(new_hour, 7)

        # Also works when last_reset_hour was a previous reset hour (e.g. 4)
        should_reset, new_hour = bridge.check_server_reset(current_lake=12, last_reset_hour=4, dt=dt)
        self.assertTrue(should_reset)
        self.assertEqual(new_hour, 7)

    def test_08_check_server_reset_already_at_lake_1(self):
        """Test 8: check_server_reset returns (False, hour) if already at Lake 1."""
        dt = datetime(2026, 11, 17, 10, 8, 0)  # 10:08 (Hour 10 is in RESET_HOURS)
        should_reset, new_hour = bridge.check_server_reset(current_lake=1, last_reset_hour=None, dt=dt)
        self.assertFalse(should_reset)
        self.assertEqual(new_hour, 10)

    def test_09_check_server_reset_no_double_trigger(self):
        """Test 9: check_server_reset does not trigger twice for the same reset hour."""
        dt = datetime(2026, 11, 17, 13, 10, 0)  # 13:10
        # Already processed hour 13
        should_reset, new_hour = bridge.check_server_reset(current_lake=5, last_reset_hour=13, dt=dt)
        self.assertFalse(should_reset)
        self.assertEqual(new_hour, 13)

    def test_10_get_next_reset_datetime(self):
        """Test 10: get_next_reset_datetime calculates the next upcoming reset time accurately."""
        # Middle of the day: 14:30 -> next reset is 16:00
        dt1 = datetime(2026, 11, 17, 14, 30, 0)
        next_dt1 = bridge.get_next_reset_datetime(dt1)
        self.assertEqual(next_dt1, datetime(2026, 11, 17, 16, 0, 0))

        # Late night: 22:30 -> next reset is 01:00 next day
        dt2 = datetime(2026, 11, 17, 22, 30, 0)
        next_dt2 = bridge.get_next_reset_datetime(dt2)
        self.assertEqual(next_dt2, datetime(2026, 11, 18, 1, 0, 0))

        # Early morning before first reset: 00:20 -> next reset is 01:00 same day
        dt3 = datetime(2026, 11, 17, 0, 20, 0)
        next_dt3 = bridge.get_next_reset_datetime(dt3)
        self.assertEqual(next_dt3, datetime(2026, 11, 17, 1, 0, 0))

    def test_11_session_state_last_reset_hour_persistence(self):
        """Test 11: SessionState correctly serializes and restores last_reset_hour."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "test_state.json")
            state = bridge.SessionState(
                current_lake=15,
                total_catches=20,
                last_reset_hour=19,
            )
            state.save(state_file)

            loaded = bridge.SessionState.load(state_file)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.current_lake, 15)
            self.assertEqual(loaded.last_reset_hour, 19)

    async def test_12_fast_exit_on_empty_toast_in_one_cast(self):
        """Test 12: run_one_cast exits immediately (<0.5s) when empty pond toast appears after cast."""
        tab = bridge.Tab("https://nomstead.com/play", "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()

        pre_status = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 70, 123, "", False, 0, False)
        empty_status = bridge.Status(
            "https://nomstead.com/play", 800.0, 600.0, 1.25, 70, 123,
            "There is nothing left in this pond. Come back later!",
            False, 0, False
        )
        water_frame = _make_water_frame(800, 600, pre_status)

        status_calls = [pre_status, empty_status]

        mock_cast = mock.AsyncMock()
        mock_strike = mock.AsyncMock()

        t0 = time.monotonic()
        with mock.patch.object(bridge, "read_status", side_effect=lambda _t: status_calls.pop(0)), \
             mock.patch.object(bridge, "capture", return_value=water_frame), \
             mock.patch.object(bridge, "click_cast", mock_cast), \
             mock.patch.object(bridge, "click_strike", mock_strike):
            outcome = await bridge.run_one_cast(tab, max_alert_wait_sec=11.0)
        duration = time.monotonic() - t0

        self.assertEqual(outcome.kind, "EMPTY")
        self.assertIn("nothing left", outcome.toast.lower())
        mock_cast.assert_awaited_once()
        mock_strike.assert_not_called()
        self.assertLess(duration, 0.5)

    async def test_13_active_toast_polling_detects_trash_after_strike(self):
        """Test 13: Active toast polling catches delayed trash toast and does NOT misclassify as catch."""
        tab = bridge.Tab("https://nomstead.com/play", "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()

        pre_status = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 70, 123, "", False, 0, False)
        # Immediate post-cast status (no toast)
        post_cast_status = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 70, 123, "", False, 0, False)
        # Immediate post-strike status (energy decreased, but toast not rendered yet!)
        reel_1_status = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 69, 123, "", False, 0, False)
        # Delayed post-strike status (trash toast appears!)
        reel_2_status = bridge.Status(
            "https://nomstead.com/play", 800.0, 600.0, 1.25, 69, 123,
            "You pulled up some trash. The pond needs time to restock.",
            False, 0, False
        )

        water_frame = _make_water_frame(800, 600, pre_status)
        alert_hit_frame = _make_alert_frame(hit=True, status=pre_status)

        status_calls = [pre_status, post_cast_status, reel_1_status, reel_2_status]

        async def fake_read_status(_t):
            if status_calls:
                return status_calls.pop(0)
            return reel_2_status

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_hit_frame

        mock_cast = mock.AsyncMock()
        mock_strike = mock.AsyncMock()

        with mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock_cast), \
             mock.patch.object(bridge, "click_strike", mock_strike):
            outcome = await bridge.run_one_cast(
                tab,
                max_alert_wait_sec=5.0,
                poll_interval_sec=0.001,
                baseline_delay_sec=0.001,
                obs_delay_sec=0.001,
                reel_wait_sec=0.5,
            )

        self.assertEqual(outcome.kind, "TRASH")
        self.assertIn("pulled up some trash", outcome.toast.lower())
        mock_cast.assert_awaited_once()
        mock_strike.assert_awaited_once()

    async def test_14_auto_session_server_reset_navigates_to_lake_1(self):
        """Test 14: run_auto_session detects reset window and navigates back to Lake 1."""
        tab = bridge.Tab("https://nomstead.com/play", "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        status_ok = bridge.Status("https://nomstead.com/play", 800.0, 600.0, 1.25, 50, 123, "", False, 0, False)

        stop_event = asyncio.Event()
        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=1, attempts=1, duration_sec=1.0))

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(
                start_lake=15,
                state_file=state_file,
                initial_travel=False,
            )

            calls = 0
            def fake_check_reset(lake, last_hour):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return True, 7
                stop_event.set()
                return False, 7

            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "check_server_reset", side_effect=fake_check_reset), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel):
                state = await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

            self.assertEqual(state.current_lake, 1)
            self.assertEqual(state.last_reset_hour, 7)
            mock_travel.assert_awaited_with(tab, 1)


if __name__ == "__main__":
    unittest.main()
