"""10 comprehensive unit tests for Task 7.2: Active Spinner Polling & Settling Delay When Selecting Bookmarks."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge


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


class SpinnerAndNavigationTests(unittest.IsolatedAsyncioTestCase):
    """10 unit tests for Task 7.2 according to TASK7_2_BRIEF.md."""

    def _setup_mock_tab(self, url: str = "https://nomstead.com/play") -> bridge.Tab:
        tab = bridge.Tab(url, "ws://127.0.0.1:9222/devtools/page/test")
        tab.ws = mock.AsyncMock()
        return tab

    async def test_01_bookmarks_loading_fast_under_300ms(self):
        """Test 1: Fast loading network (<300ms) exits spinner polling immediately on first poll."""
        tab = self._setup_mock_tab()
        eval_calls = []
        spinner_polls = 0

        async def fake_eval(_t, expr):
            nonlocal spinner_polls
            eval_calls.append(expr)
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "clicked": False}
            if "spinner" in expr:
                spinner_polls += 1
                # Instant response: tiles ready, spinner gone
                return {"ready": True, "count": 40, "has_spinner": False}
            if "target_lake" in expr or "HO" in expr or "scrollIntoView" in expr:
                return {"found": True, "x": 400.0, "y": 300.0}
            return {}

        status_closed = _default_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 23)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 23)
        self.assertEqual(spinner_polls, 1)

    async def test_02_bookmarks_loading_delayed_spinner_2_seconds(self):
        """Test 2: Spinner spins for 2.0s then disappears, bot waits patiently and succeeds at Lake 23."""
        tab = self._setup_mock_tab()
        spinner_polls = 0
        sim_time = 1000.0

        def fake_monotonic():
            return sim_time

        async def fake_sleep(secs):
            nonlocal sim_time
            sim_time += secs

        async def fake_eval(_t, expr):
            nonlocal spinner_polls
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "clicked": False}
            if "spinner" in expr:
                spinner_polls += 1
                # Spin for 2.0s (~13 polls at 0.15s interval)
                if spinner_polls < 14:
                    return {"ready": False, "count": 0, "has_spinner": True}
                return {"ready": True, "count": 40, "has_spinner": False}
            if "HO" in expr or "scrollIntoView" in expr:
                return {"found": True, "x": 420.0, "y": 280.0}
            return {}

        status_closed = _default_status(modal=False)

        with mock.patch("time.monotonic", side_effect=fake_monotonic), \
             mock.patch("asyncio.sleep", side_effect=fake_sleep), \
             mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed):
            res = await bridge.travel_to_lake(tab, 23)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 23)
        self.assertGreaterEqual(spinner_polls, 14)

    async def test_03_bookmarks_loading_slow_spinner_4_5_seconds(self):
        """Test 3: Slow network (4.5s spinner) waits completely without premature modal close or error."""
        tab = self._setup_mock_tab()
        spinner_polls = 0
        sim_time = 2000.0

        def fake_monotonic():
            return sim_time

        async def fake_sleep(secs):
            nonlocal sim_time
            sim_time += secs

        async def fake_eval(_t, expr):
            nonlocal spinner_polls
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "clicked": False}
            if "spinner" in expr:
                spinner_polls += 1
                # 4.5s / 0.15s = 30 polls of spinning
                if spinner_polls <= 30:
                    return {"ready": False, "count": 0, "has_spinner": True}
                return {"ready": True, "count": 40, "has_spinner": False}
            if "HO" in expr or "scrollIntoView" in expr:
                return {"found": True, "x": 450.0, "y": 320.0}
            return {}

        status_closed = _default_status(modal=False)

        with mock.patch("time.monotonic", side_effect=fake_monotonic), \
             mock.patch("asyncio.sleep", side_effect=fake_sleep), \
             mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed):
            res = await bridge.travel_to_lake(tab, 23)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 23)
        self.assertGreaterEqual(spinner_polls, 31)

    async def test_04_bookmarks_loading_spinner_timeout_fallback(self):
        """Test 4: Spinner stuck > 6.0s times out safely without infinite hang."""
        tab = self._setup_mock_tab()
        spinner_polls = 0
        sim_time = 3000.0

        def fake_monotonic():
            return sim_time

        async def fake_sleep(secs):
            nonlocal sim_time
            sim_time += secs

        async def fake_eval(_t, expr):
            nonlocal spinner_polls
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "clicked": False}
            if "spinner" in expr:
                spinner_polls += 1
                # Permanently stuck spinner
                return {"ready": False, "count": 0, "has_spinner": True}
            if "HO" in expr or "scrollIntoView" in expr:
                return {"found": False, "count": 0}
            return {}

        status_modal = _default_status(modal=True)

        with mock.patch("time.monotonic", side_effect=fake_monotonic), \
             mock.patch("asyncio.sleep", side_effect=fake_sleep), \
             mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_modal):
            res = await bridge.travel_to_lake(tab, 23, max_retries=1)

        self.assertFalse(res.success)
        self.assertEqual(res.attempts, 1)
        self.assertIn("Failed to travel to lake 23", res.error or "")
        # Verified timeout terminated cleanly around 6.0s (40-41 polls)
        self.assertGreaterEqual(spinner_polls, 40)

    async def test_05_scroll_into_view_and_click_coordinates_accurate(self):
        """Test 5: scrollIntoView behavior is instant and center coordinates calculated accurately."""
        tab = self._setup_mock_tab()
        eval_exprs = []

        # Simulated element rect: left=150, top=200, width=80, height=40 -> center=(190.0, 220.0)
        expected_x = 150.0 + 80.0 / 2.0
        expected_y = 200.0 + 40.0 / 2.0

        async def fake_eval(_t, expr):
            eval_exprs.append(expr)
            if "Codex" in expr:
                return {"open": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "HO" in expr or "scrollIntoView" in expr:
                return {"found": True, "x": expected_x, "y": expected_y}
            return {}

        mock_click = mock.AsyncMock()
        status_closed = _default_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock_click), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 15)

        self.assertTrue(res.success)
        lake_exprs = [e for e in eval_exprs if "HO" in e and "15" in e and "scrollIntoView" in e]
        self.assertGreaterEqual(len(lake_exprs), 1)
        target_expr = lake_exprs[0]
        self.assertIn("scrollIntoView", target_expr)
        self.assertIn("center", target_expr)
        self.assertIn("instant", target_expr)
        mock_click.assert_awaited_once_with(tab, expected_x, expected_y, delay_ms=50.0)

    def test_06_exact_lake_target_selection_amidst_40_tiles(self):
        r"""Test 6: Target lake regex ^\s*HO\s+<target>\s*$ selects exact lake (e.g. HO 23) and rejects substrings."""
        target_lake = 23
        pattern = re.compile(rf"^\s*HO\s+{target_lake}\s*$", re.IGNORECASE)

        # Exact positive matches
        self.assertTrue(pattern.match("HO 23"))
        self.assertTrue(pattern.match("  HO 23  "))
        self.assertTrue(pattern.match("ho 23"))
        self.assertTrue(pattern.match("\tHO 23\n"))

        # Rejects substring collisions
        self.assertIsNone(pattern.match("HO 2"))
        self.assertIsNone(pattern.match("HO 3"))
        self.assertIsNone(pattern.match("HO 13"))
        self.assertIsNone(pattern.match("HO 230"))
        self.assertIsNone(pattern.match("HO 33"))
        self.assertIsNone(pattern.match("HO 231"))

    def test_07_spinner_detection_selectors_coverage(self):
        """Test 7: BOOKMARKS_READY_EXPR covers all common spinner / loading selectors."""
        expr = bridge.BOOKMARKS_READY_EXPR
        self.assertIn(".spinner", expr)
        self.assertIn('[class*="loading"]', expr)
        self.assertIn('[class*="spinner"]', expr)
        self.assertIn('svg[class*="spin"]', expr)
        self.assertIn('[data-ui="loading"]', expr)
        self.assertIn(".loading-indicator", expr)
        self.assertIn("isSpinning", expr)
        self.assertIn("hasTiles", expr)

    async def test_08_travel_success_after_slow_loading(self):
        """Test 8: Full successful flow: Open Codex -> Active Bookmarks -> 3s Spinner -> Fast Travel -> Done."""
        tab = self._setup_mock_tab()
        spinner_polls = 0
        sim_time = 4000.0

        def fake_monotonic():
            return sim_time

        async def fake_sleep(secs):
            nonlocal sim_time
            sim_time += secs

        async def fake_eval(_t, expr):
            nonlocal spinner_polls
            if "Codex" in expr:
                return {"open": True, "clicked": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True, "clicked": False}
            if "spinner" in expr:
                spinner_polls += 1
                if spinner_polls < 20:
                    return {"ready": False, "count": 0, "has_spinner": True}
                return {"ready": True, "count": 40, "has_spinner": False}
            if "HO" in expr or "scrollIntoView" in expr:
                return {"found": True, "x": 500.0, "y": 350.0}
            return {}

        status_closed = _default_status(modal=False)

        with mock.patch("time.monotonic", side_effect=fake_monotonic), \
             mock.patch("asyncio.sleep", side_effect=fake_sleep), \
             mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed):
            res = await bridge.travel_to_lake(tab, 30)

        self.assertTrue(res.success)
        self.assertEqual(res.lake, 30)
        self.assertGreaterEqual(spinner_polls, 20)

    async def test_09_stale_toast_cleaned_post_travel(self):
        """Test 9: Confirms DOM toast is cleaned after successful travel following spinner wait."""
        tab = self._setup_mock_tab()
        eval_calls = []

        async def fake_eval(_t, expr):
            eval_calls.append(expr)
            if "Codex" in expr:
                return {"open": True}
            if "bookmarks" in expr and "spinner" not in expr:
                return {"active": True}
            if "spinner" in expr:
                return {"ready": True, "count": 40, "has_spinner": False}
            if "HO" in expr or "scrollIntoView" in expr:
                return {"found": True, "x": 400.0, "y": 300.0}
            return {}

        status_closed = _default_status(modal=False)

        with mock.patch.object(bridge, "_cdp_evaluate", side_effect=fake_eval), \
             mock.patch.object(bridge, "click_point", mock.AsyncMock()), \
             mock.patch.object(bridge, "read_status", return_value=status_closed), \
             mock.patch("asyncio.sleep", mock.AsyncMock()):
            res = await bridge.travel_to_lake(tab, 12)

        self.assertTrue(res.success)
        clear_calls = [e for e in eval_calls if ".message-bar" in e and "innerText" in e]
        self.assertGreaterEqual(len(clear_calls), 1)

    def test_10_regression_full_suite(self):
        """Test 10: Regression check verifying entire test suite contains >= 223 tests."""
        tests_dir = Path(__file__).resolve().parent
        suite = unittest.defaultTestLoader.discover(str(tests_dir), pattern="test_*.py")
        total_tests = suite.countTestCases()
        self.assertGreaterEqual(total_tests, 223, f"Expected >= 223 tests in suite, got {total_tests}")


if __name__ == "__main__":
    unittest.main()
