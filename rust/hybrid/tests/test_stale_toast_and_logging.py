"""10 comprehensive unit tests for Task 7.1: Stale Toast Guard, Regex Classification & Stream Logging."""

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


def _default_status(
    w: float = 800.0,
    h: float = 600.0,
    energy: int | None = 70,
    xp: int | None = 100,
    toast: str = "",
    modal: bool = False,
) -> bridge.Status:
    return bridge.Status(
        url="https://nomstead.com/play",
        width=w,
        height=h,
        dpr=1.25,
        energy=energy,
        xp=xp,
        toast=toast,
        sequence_available=False,
        sequence=0,
        modal=modal,
    )


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


class StaleToastAndLoggingTests(unittest.IsolatedAsyncioTestCase):
    """10 unit tests for Task 7.1 according to TASK7_1_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    async def test_01_stale_toast_guard_ignores_inherited_toast_from_previous_lake(self):
        """Test 1: Stale Toast Guard ignores toast inherited from previous lake and does NOT return EMPTY."""
        tab = self._setup_mock_tab()
        stale_msg = "There is nothing left in this pond. Come back later!"
        status_stale = _default_status(toast=stale_msg)
        water_frame = _make_water_frame(800, 600, status_stale)
        alert_idle = _make_alert_frame(hit=False, status=status_stale)

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_idle

        # Both pre_status and immediate_status have the same stale toast
        with mock.patch.object(bridge, "read_status", return_value=status_stale), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(tab, max_alert_wait_sec=0.05)

        # Guard must prevent returning EMPTY because toast is identical to initial_toast
        self.assertNotEqual(outcome.kind, "EMPTY")
        self.assertEqual(outcome.kind, "TIMEOUT")

    async def test_02_fresh_empty_toast_triggers_fast_exit(self):
        """Test 2: Fresh empty toast appearing after cast triggers fast exit (<0.5s) with kind=EMPTY."""
        tab = self._setup_mock_tab()
        status_initial = _default_status(toast="")
        empty_msg = "There is nothing left in this pond. Come back later!"
        status_empty = _default_status(toast=empty_msg)
        water_frame = _make_water_frame(800, 600, status_initial)

        call_count = 0

        async def fake_read_status(_t):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return status_initial
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

    async def test_03_travel_to_lake_clears_dom_toast(self):
        """Test 3: travel_to_lake executes script clearing innerText of DOM toast after travel success."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr:
                return {"active": True, "clicked": False}
            if "tiles" in expr:
                return {"found": True, "x": 400.0, "y": 300.0}
            return {}

        status_closed = _default_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 5)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 5)
        # Verify clear DOM toast script was executed
        clear_calls = [e for e in eval_calls if ".message-bar" in e and "innerText" in e]
        self.assertGreaterEqual(len(clear_calls), 1)

    async def test_04_modal_active_not_classified_as_empty(self):
        """Test 4: post_status.modal == True is classified as MODAL_ACTIVE, NEVER as EMPTY."""
        tab = self._setup_mock_tab()
        status_pre = _default_status(toast="", modal=False)
        status_modal = _default_status(toast="", modal=True)
        water_frame = _make_water_frame(800, 600, status_pre)
        alert_hit_frame = _make_alert_frame(hit=True, status=status_pre)

        status_calls = [status_pre, status_pre, status_modal]

        async def fake_read_status(_t):
            if status_calls:
                return status_calls.pop(0)
            return status_modal

        async def fake_capture(_t, kind):
            if kind == "SCREEN_FULL":
                return water_frame
            return alert_hit_frame

        with mock.patch.object(bridge, "read_status", side_effect=fake_read_status), \
             mock.patch.object(bridge, "capture", side_effect=fake_capture), \
             mock.patch.object(bridge, "click_cast", mock.AsyncMock()), \
             mock.patch.object(bridge, "click_strike", mock.AsyncMock()), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            outcome = await bridge.run_one_cast(tab, max_alert_wait_sec=5.0, reel_wait_sec=0.01)

        self.assertNotEqual(outcome.kind, "EMPTY")
        self.assertEqual(outcome.kind, "MODAL_ACTIVE")

    def test_05_classify_toast_avoids_substring_false_positives(self):
        """Test 5: classify_toast avoids substring pitfalls: 'normal fish' is CATCH, not EMPTY."""
        # "normal fish" has "no" inside "normal" and "fish" -> Must NOT match EMPTY!
        self.assertEqual(bridge.classify_toast("You caught a normal fish!"), "CATCH")
        self.assertNotEqual(bridge.classify_toast("You caught a normal fish!"), "EMPTY")

        # "now fishing in nomstead" -> Neither EMPTY nor TRASH nor CATCH
        self.assertIsNone(bridge.classify_toast("now fishing in nomstead"))

    def test_06_classify_toast_matches_all_empty_patterns(self):
        """Test 6: classify_toast matches all variations of empty pond notifications."""
        empty_samples = [
            "There is nothing left in this pond. Come back later!",
            "Nothing left to catch here right now...",
            "no more fish",
            "needs time to restock",
            "There is no fish here",
            "Hồ này đã hết cá rồi",
            "Hồ cạn rồi",
            "This lake is empty",
            "Please come back later",
        ]
        for s in empty_samples:
            self.assertEqual(bridge.classify_toast(s), "EMPTY", f"Failed on empty pattern: {s}")

    def test_07_classify_toast_matches_all_trash_patterns(self):
        """Test 7: classify_toast matches all variations of trash notifications."""
        trash_samples = [
            "You pulled up some trash. The pond needs time to restock.",
            "I pulled up some trash.",
            "rusty can",
            "old boot",
            "You caught an old boot (trash).",
            "Câu phải rác rồi!",
            "an old can (lon)",
            "just some trash",
        ]
        for s in trash_samples:
            self.assertEqual(bridge.classify_toast(s), "TRASH", f"Failed on trash pattern: {s}")

    async def test_08_stream_log_format_verified_catch(self):
        """Test 8: Captures 1-line stream log format for verified CATCH."""
        tab = self._setup_mock_tab()
        status_ok = _default_status(energy=75)
        stop_event = asyncio.Event()

        catch_outcome = bridge.Outcome(
            kind="CATCH",
            toast="and I got a Rainbow Trout!",
            pre_energy=75,
            post_energy=74,
            pre_xp=100,
            post_xp=110,
            reaction_ms=15.2,
        )

        async def fake_cast(_t, **_kw):
            stop_event.set()
            return catch_outcome

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=1, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast), \
                 contextlib.redirect_stdout(output):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_event)

        log = output.getvalue()
        self.assertIn("🐟 CÂU THÀNH CÔNG! Đã bắt được cá tại HO 1", log)
        self.assertIn("[HỒ 01/40]", log)

    async def test_09_stream_log_format_empty_and_trash(self):
        """Test 9: Captures 1-line stream log format for EMPTY and TRASH."""
        tab = self._setup_mock_tab()
        status_ok = _default_status(energy=60)
        mock_travel = mock.AsyncMock(return_value=bridge.TravelResult(success=True, lake=2, attempts=1, duration_sec=0.5))

        # 1. EMPTY log
        stop_empty = asyncio.Event()

        async def fake_cast_empty(_t, **_kw):
            stop_empty.set()
            return bridge.Outcome(kind="EMPTY", toast="nothing left")

        out_empty = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=1, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_empty), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 contextlib.redirect_stdout(out_empty):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_empty)

        log_empty = out_empty.getvalue()
        self.assertIn("⚠️ Hồ đã hết cá", log_empty)
        self.assertIn("[HỒ 01/40]", log_empty)

        # 2. TRASH log
        stop_trash = asyncio.Event()

        async def fake_cast_trash(_t, **_kw):
            stop_trash.set()
            return bridge.Outcome(kind="TRASH", toast="some trash")

        out_trash = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = os.path.join(tmp_dir, "session_state.json")
            config = bridge.AutoSessionConfig(start_lake=1, state_file=state_file, initial_travel=False)
            with mock.patch.object(bridge, "read_status", return_value=status_ok), \
                 mock.patch.object(bridge, "run_one_cast", side_effect=fake_cast_trash), \
                 mock.patch.object(bridge, "travel_to_lake", mock_travel), \
                 contextlib.redirect_stdout(out_trash):
                await bridge.run_auto_session(tab, config=config, stop_event=stop_trash)

        log_trash = out_trash.getvalue()
        self.assertIn("🗑️ Câu phải rác", log_trash)
        self.assertIn("[HỒ 01/40]", log_trash)

    def test_10_regression_full_suite(self):
        """Test 10: Regression check verifying entire test suite contains >= 223 tests."""
        tests_dir = Path(__file__).resolve().parent
        suite = unittest.defaultTestLoader.discover(str(tests_dir), pattern="test_*.py")
        total_tests = suite.countTestCases()
        self.assertGreaterEqual(total_tests, 223, f"Expected >= 223 tests in suite, got {total_tests}")


if __name__ == "__main__":
    unittest.main()
